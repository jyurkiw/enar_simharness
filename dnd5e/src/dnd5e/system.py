"""`Dnd5eSystem`: implements `simharness.GameSystem`, wiring `Creature`,
`Battlefield`, and `actions.CombatContext` into the trial/round/turn pipeline
`simharness.TrialRunner` drives (design doc 03 section 2).

Phase 4 turn pipeline (design doc 04 section 2, `behavior.py` does the actual
selection logic — this module just calls it each turn):
    1. incapacity gates: down -> death save and stop; any SKIPS_TURN
       condition (stunned et al.) -> stop
    2. multiattack selection: `behavior.select_multiattack` (when-gated,
       highest eligible priority wins, no-eligible-option fallback + warning)
    3. per action in the chosen option: `behavior.select_targets` resolves
       that action's own target pool (targets/target_filter/[[behavior.
       targeting]]/ordering — doc04 section 3) independently of any other
       action in the same option; movement via the creature's `behavior.
       tactic` toward the first resolved target (a no-op if already in
       range/reach — see movement.py), then `resolve_ability` against the
       full target list

Phase 4 also adds an environment-sync step, run once per round (in
`turn_order`, alongside the flag clear — both fire exactly once at a round's
start): `battlefield.refresh_auras` re-centers any combatant-bound obscurement
regions, then `_sync_obscurement` blinds/unblinds standing-in-the-dark
creatures (source-tagged `conditions.OBSCUREMENT_SOURCE` so it never touches a
Blinded some other effect applied). `light_plan`'s scripted "someone lights a
torch" moment is checked in `take_turn`, after the incapacity gates and before
normal action resolution — see `_maybe_produce_light`.

Phase 4 also adds the Python escape hatch (design doc 04 section 5,
`behavior.custom`): `take_turn`'s `plan_movement` check resolves the handler
(`escape_hatch.resolve`, cached) and calls it directly, since movement is
system.py's own concern — `behavior.py`'s `select_multiattack`/`select_targets`
call the same resolver for their own hooks (`choose_multiattack`/
`choose_target`) internally.

Phase 5 adds condition clocks and the `turn_start` reaction trigger, both
ticking at fixed points in `take_turn` (mirroring `dnd5e_combat.engine.
Engine._take_turn`'s exact ordering): `_tick_start_of_turn` fires *before*
the incapacity gates (a `start_of_source_next_turn` expiry — e.g. Stunned —
must lift before checking whether the actor is stunned this turn); the whole
turn body runs in a `try`/`finally` so `_tick_end_of_turn` always fires, even
on an incapacitated actor's early return (matching the old engine calling
`_end_of_turn` on every exit path). `turn_start` reactions (the Masked
Bruiser's Sleight of Crowd) are offered right after the incapacity/light_plan
gates, before multiattack selection — the same point the old policy's
`take_turn` called it as its literal first line. `round_scratch` (reaction-
per-round economy) is cleared for every creature in `turn_order` (the
begin-round hook), alongside the flag clear.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from dnd_board import ObscurementField, Region
from simharness.plugin import TrialContext

from . import conditions, escape_hatch, movement, reactions
from .actions import CombatContext, resolve_ability
from .battlefield import Aura, Battlefield
from .behavior import BehaviorContext, ConcreteScope, select_multiattack, select_targets
from .creature import ConditionInstance, Creature
from .dice import Resolver
from .effects import EffectScope, apply_effects
from .flags import FlagBag
from .statblock import Statblock


@dataclass(frozen=True)
class RosterSlot:
    """One creature to place on the board, with its spawn point already
    resolved (round-robin/explicit-start resolution is the simulation
    loader's job, task 36 — by the time a `RosterSlot` reaches here, `start`
    is a concrete cell)."""

    statblock: Statblock
    instance_name: str
    side: str
    start: tuple[int, int]
    tags: tuple[str, ...] = ()


@dataclass
class GameState:
    combat_ctx: CombatContext
    battlefield: Battlefield
    creatures: dict            # instance_name -> Creature
    turn_order: list           # instance_name, in initiative order
    flags: FlagBag = field(default_factory=FlagBag)
    light_produced: bool = False   # `light_plan` fires at most once per trial


class Dnd5eSystem:
    def __init__(self, *, board, roster: list, max_rounds: int, hp_mode: str = "average",
                 focus: Optional[dict] = None, obscurement: tuple = (),
                 light_plan: Optional[object] = None) -> None:
        self.board = board
        self.roster = roster
        self.max_rounds = max_rounds
        self.hp_mode = hp_mode
        self.focus = dict(focus or {})
        # `obscurement`/`light_plan`: tuple[loader.ObscurementSpec, ...] /
        # Optional[loader.LightPlanSpec] — duck-typed here (not imported) so
        # this module doesn't import loader.py, which imports RosterSlot from
        # here.
        self.obscurement = obscurement
        self.light_plan = light_plan
        # Workspace-wide condition-definition registry (design doc 03 section
        # 3): built once (the roster is static across every trial of a run),
        # from every roster member's `[conditions.*]` — a condition may be
        # *attached* to a creature whose own file never defines it (the
        # Bruiser's Mark, attached to party members), so this can't be looked
        # up per-creature.
        self.condition_defs: dict = {}
        for slot in self.roster:
            self.condition_defs.update(slot.statblock.conditions)

    # ---- GameSystem protocol --------------------------------------------------

    def setup_trial(self, ctx: TrialContext) -> None:
        creatures = [
            Creature(statblock=slot.statblock, instance_name=slot.instance_name,
                     side=slot.side, tags=slot.tags)
            for slot in self.roster
        ]
        for creature, slot in zip(creatures, self.roster):
            creature.place(*slot.start)

        obscurement_field, auras = self._build_obscurement()
        battlefield = Battlefield(creatures, board=self.board, obscurement=obscurement_field, auras=auras)
        battlefield.focus.update(self.focus)

        resolver = Resolver(ctx.dice)
        flags = FlagBag()
        combat_ctx = CombatContext(resolver, battlefield, ctx.ledger, flags=flags,
                                   condition_defs=self.condition_defs)

        for creature in creatures:
            creature.roll_hp(resolver, mode=self.hp_mode)

        # Passive traits (design doc 03's `emit_light`/`limited_darkvision`/
        # `darkvision_immunity` — all marked "(trait)") apply once here, at
        # trial setup, not per-hit.
        for creature in creatures:
            for trait in creature.statblock.traits.values():
                apply_effects(trait.effects, EffectScope(ctx=combat_ctx, source=creature, target=creature))

        # Initiative: 1d20 + bonus, ties keep roster order (Python's sort is
        # stable, and `rolled` is built in roster order, so a `reverse=True`
        # sort by value alone preserves that order among equal rolls).
        rolled = [(c.instance_name, resolver.roll("1d20") + c.statblock.stats.initiative_bonus)
                 for c in creatures]
        rolled.sort(key=lambda pair: pair[1], reverse=True)
        turn_order = [name for name, _ in rolled]

        ctx.game = GameState(
            combat_ctx=combat_ctx, battlefield=battlefield,
            creatures={c.instance_name: c for c in creatures}, turn_order=turn_order,
            flags=flags,
        )

    def turn_order(self, ctx: TrialContext) -> list:
        # Called exactly once per round, at its start (runner.py's
        # `_begin_round`) — clear round-scoped flags, refresh combatant-bound
        # obscurement auras onto their sources' current cells, and re-derive
        # who's blinded by standing in heavy obscurement, all before anyone
        # acts this round.
        game: GameState = ctx.game
        game.flags.clear_round()
        for c in game.creatures.values():
            c.round_scratch.clear()
        game.battlefield.refresh_auras(ctx.round_index)
        self._sync_obscurement(game)
        return game.turn_order

    def take_turn(self, ctx: TrialContext, actor_id: str) -> None:
        game: GameState = ctx.game
        actor = game.creatures[actor_id]
        game.combat_ctx.round_index = ctx.round_index
        game.combat_ctx.turn_order = game.turn_order

        self._tick_start_of_turn(actor, game)
        actor.turn_scratch.clear()
        try:
            self._take_turn_body(ctx, actor, game)
        finally:
            self._tick_end_of_turn(actor, game, ctx.round_index)

    def _take_turn_body(self, ctx: TrialContext, actor: Creature, game: GameState) -> None:
        if actor.is_down:
            self._roll_death_save(actor, game.combat_ctx)
            return
        if any(actor.has_condition(name) for name in conditions.SKIPS_TURN):
            return
        if self._maybe_produce_light(actor, game, ctx):
            return  # producing light cost this creature its action

        self._offer_turn_start_reactions(actor, game, ctx)

        behavior_ctx = BehaviorContext(battlefield=game.battlefield, round_index=ctx.round_index,
                                       turn_order=game.turn_order, flags=game.flags,
                                       resolver=game.combat_ctx.resolver)
        option = select_multiattack(actor, behavior_ctx)
        if option is None:
            return

        custom = actor.statblock.behavior.custom
        for action_name in option.actions:
            ability = actor.statblock.abilities[action_name]
            targets = select_targets(actor, ability, behavior_ctx)
            if not targets:
                continue
            dest = None
            if custom is not None:
                scope = ConcreteScope(behavior_ctx, actor)
                dest = escape_hatch.resolve(custom).plan_movement(actor, scope)
            before = actor.coord
            if dest is not None:
                movement.move_to_cell(actor, dest, game.battlefield)
            else:
                movement.apply_tactic(actor.statblock.behavior.tactic, actor, targets[0], game.battlefield,
                                      max_range_ft=ability.range_normal)
            self._offer_opportunity_attacks(actor, before, actor.coord, game, ctx)
            resolve_ability(game.combat_ctx, actor, ability, targets)

    def is_over(self, ctx: TrialContext) -> bool:
        game: GameState = ctx.game
        if game.combat_ctx.trial_ending:
            return True
        sides = {c.side for c in game.creatures.values()}
        return any(
            members and all(m.is_down for m in members)
            for members in (game.battlefield.members(side) for side in sides)
        )

    def finalize_trial(self, ctx: TrialContext) -> dict:
        game: GameState = ctx.game
        outcome = {}
        sides = {c.side for c in game.creatures.values()}
        for c in game.creatures.values():
            outcome[f"down_{c.instance_name}"] = int(c.is_down)
            outcome[f"dead_{c.instance_name}"] = int(c.is_dead)
            outcome[f"hp_remaining_{c.instance_name}"] = c.hp_remaining
            # Real (not placeholder) — attach_condition can apply "poisoned"
            # today, matching the old engine's outcome columns even though
            # no Phase 3 creature happens to inflict it yet.
            outcome[f"poisoned_{c.instance_name}"] = int(c.has_condition(conditions.POISONED))
        for side in sides:
            members = game.battlefield.members(side)
            outcome[f"wiped_{side}"] = int(bool(members) and all(m.is_down for m in members))
            outcome[f"any_dead_{side}"] = int(any(m.is_dead for m in members))
            outcome[f"any_poisoned_{side}"] = int(any(m.has_condition(conditions.POISONED) for m in members))
        # `end_trial`'s optional `outcome` dict (design doc 03 section 4)
        # merges last, so a retreat/flee sim can add its own columns
        # (e.g. `retreated`) on top of the standard ones above.
        outcome.update(game.combat_ctx.trial_outcome)
        return outcome

    # ---- internals --------------------------------------------------------------

    def _build_obscurement(self):
        """Fresh `ObscurementField` + `Aura` list for one trial, from this
        sim's static `[[environment.obscurement]]` specs (`loader.
        ObscurementSpec`) — `follows` entries become auras (re-centered every
        round by `Battlefield.refresh_auras`); `center` entries are static
        regions, present from round 1 on."""
        if not self.obscurement:
            return None, []
        cell_feet = self.board.meta.get("cell_feet", 5)
        static_regions = [
            Region(center=spec.center, radius_ft=spec.radius_ft, kind=spec.kind)
            for spec in self.obscurement if spec.follows is None
        ]
        auras = [
            Aura(source=spec.follows, kind=spec.kind, radius_ft=spec.radius_ft, start_round=spec.start_round)
            for spec in self.obscurement if spec.follows is not None
        ]
        return ObscurementField(cell_feet=cell_feet, regions=static_regions), auras

    def _sync_obscurement(self, game: GameState) -> None:
        """Blind (source-tagged `conditions.OBSCUREMENT_SOURCE`) whoever's
        standing in heavy obscurement and isn't immune; unblind whoever no
        longer is, but only a Blinded we tagged ourselves. Port of
        `dnd5e_combat.engine.Engine._sync_obscurement`."""
        bf = game.battlefield
        if bf.obscurement is None:
            return
        immune = bf.not_blinded_by_obscurement()
        for c in game.creatures.values():
            if c.coord is None or c.instance_name in immune:
                continue
            existing = c.condition(conditions.BLINDED)
            if bf.obscurement.is_heavily_obscured(*c.coord):
                if existing is None:
                    c.add_condition(ConditionInstance(name=conditions.BLINDED,
                                                       source=conditions.OBSCUREMENT_SOURCE))
            elif existing is not None and existing.source == conditions.OBSCUREMENT_SOURCE:
                c.remove_condition(conditions.BLINDED)

    def _tick_start_of_turn(self, actor: Creature, game: GameState) -> None:
        """`start_of_source_next_turn` clocks (design doc 03 section 3):
        expire on whichever creature holds an instance sourced from `actor`,
        checked *before* the incapacity gates so a lifted Stunned still lets
        its bearer act this turn."""
        for creature in game.creatures.values():
            for instance in list(creature.conditions):
                if instance.expires == "start_of_source_next_turn" and instance.source == actor.instance_name:
                    self._expire_condition(creature, instance)

    def _tick_end_of_turn(self, actor: Creature, game: GameState, round_index: int) -> None:
        """`end_of_bearer_turn`/`end_of_bearer_next_turn` (treated identically
        — a documented Phase 5 simplification, see conditions.py) tick when
        `actor` is the bearer; `end_of_source_next_turn` ticks when `actor` is
        the source. Runs from `take_turn`'s `finally`, so it always fires even
        on an incapacitated actor's early return (matching the old engine's
        `_end_of_turn` being called on every exit path)."""
        for creature in game.creatures.values():
            for instance in list(creature.conditions):
                bearer_clock = (instance.expires in ("end_of_bearer_turn", "end_of_bearer_next_turn")
                                and creature is actor)
                source_clock = (instance.expires == "end_of_source_next_turn"
                                and instance.source == actor.instance_name)
                if bearer_clock or source_clock:
                    self._expire_condition(creature, instance)

    def _expire_condition(self, creature: Creature, instance: ConditionInstance) -> None:
        if instance.unless is not None and self._unless_predicate_holds(instance.unless, creature):
            return
        creature.remove_condition(instance.name)

    def _unless_predicate_holds(self, name: str, creature: Creature) -> bool:
        # v1's sole predicate (design doc 03 section 3): the Bruiser Mark's
        # keep-alive rule — the marked creature attacked someone other than
        # the Bruiser this turn, so the mark survives its own expiry tick.
        if name == "attacked_other_than_source_this_turn":
            return bool(creature.turn_scratch.get("attacked_other_than_source"))
        raise ValueError(f"unknown unless predicate {name!r}")  # pragma: no cover (validated at load)

    def _offer_opportunity_attacks(self, actor: Creature, before, after,
                                   game: GameState, ctx: TrialContext) -> None:
        """Publish `enemy_left_reach` (design doc 04 section 4's trigger, wired
        as of design doc 07) to every enemy whose reach `actor` just walked out
        of — the Opportunity Attack. This is what the shadow sims'
        `killed_on_retreat` column measures: parting shots on a fleeing monster.
        Reach is evaluated against the board cells directly (not `in_reach`)
        because the actor has already moved by the time this runs. A no-op for
        enemies that declare no reactions, so sims without an OA reaction draw
        exactly the dice they did before."""
        if before is None or after is None or before == after:
            return
        bf = game.battlefield
        board = bf.board
        behavior_ctx = BehaviorContext(battlefield=bf, round_index=ctx.round_index,
                                       turn_order=game.turn_order, flags=game.flags,
                                       resolver=game.combat_ctx.resolver)
        for enemy in bf.enemies_of(actor):
            if enemy.coord is None or not enemy.statblock.reactions:
                continue
            was_in_reach = board.distance_ft(enemy.coord, before) <= enemy.reach_ft
            still_in_reach = board.distance_ft(enemy.coord, after) <= enemy.reach_ft
            if was_in_reach and not still_in_reach:
                reactions.offer("enemy_left_reach",
                                {"attacker": enemy, "target": actor, "mover": actor},
                                candidates=[enemy], behavior_ctx=behavior_ctx,
                                combat_ctx=game.combat_ctx)

    def _offer_turn_start_reactions(self, actor: Creature, game: GameState, ctx: TrialContext) -> None:
        """The Masked Bruiser's Sleight of Crowd fires here — the same point
        the old policy's `take_turn` called it as its literal first line
        (after the incapacity/light_plan gates, before multiattack
        selection). Broadcast to every creature, like any other trigger-bus
        publish point; a `when = "self == event.actor"` clause is how a
        reaction restricts itself to its own turn starting."""
        behavior_ctx = BehaviorContext(battlefield=game.battlefield, round_index=ctx.round_index,
                                       turn_order=game.turn_order, flags=game.flags,
                                       resolver=game.combat_ctx.resolver)
        reactions.offer("turn_start", {"actor": actor}, candidates=list(game.creatures.values()),
                        behavior_ctx=behavior_ctx, combat_ctx=game.combat_ctx)

    def _maybe_produce_light(self, actor: Creature, game: GameState, ctx: TrialContext) -> bool:
        """If `actor` is `light_plan`'s configured source and its round has
        arrived: clear the party's obscurement-Blinded, mark `actor` the
        light source, and report whether that cost its action. Fires at most
        once per trial. Port of `dnd5e_combat.engine.Engine._produce_light`."""
        lp = self.light_plan
        if lp is None or game.light_produced:
            return False
        if actor.instance_name != lp.source or ctx.round_index < lp.round:
            return False
        game.light_produced = True
        for ally in game.battlefield.members(actor.side):
            existing = ally.condition(conditions.BLINDED)
            if existing is not None and existing.source == conditions.OBSCUREMENT_SOURCE:
                ally.remove_condition(conditions.BLINDED)
        actor.add_condition(ConditionInstance(name=conditions.LIGHT_SOURCE, source=actor.instance_name))
        return bool(lp.costs_action)

    def _roll_death_save(self, actor: Creature, combat_ctx: CombatContext) -> None:
        if actor.is_dead or actor.is_stabilized:
            return
        roll = combat_ctx.resolver.roll("1d20")
        if roll == 20:
            combat_ctx.revive_to_one_hp(actor)
            return
        if roll == 1:
            actor.death_save_failures += 2
        elif roll >= 10:
            actor.death_save_successes += 1
        else:
            actor.death_save_failures += 1
        actor.death_save_failures = min(actor.death_save_failures, 3)
        actor.death_save_successes = min(actor.death_save_successes, 3)
