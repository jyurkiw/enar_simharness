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


def _spend_costs(actor: Creature, ability) -> None:
    """Deduct an ability's `costs` resource once it has actually fired (a
    limited spell slot, a ki point). `behavior._costs_available` already gated
    the multiattack option on the resource being present, so this is the
    matching debit — the usage ceiling. No-op for the common costless ability."""
    costs = ability.costs
    if not costs:
        return
    name = costs.get("resource")
    if name and name in actor.resources:
        actor.resources[name] = max(0, actor.resources[name] - costs.get("amount", 1))


class HazardView:
    """What a hazard actor's driver gets to work with (design: the Pyre
    Elemental). Deliberately narrow — a bodiless force reads the board, damages
    creatures, drops hazards and spawns minions; it has no position, no HP, and
    no conditions of its own.

    `scratch` is per-trial driver state (legendary uses left, recharge status,
    how many minions are out), keyed off the GameState so it resets each trial
    without the driver holding any state itself (drivers are cached and shared,
    exactly like escape-hatch brains)."""

    def __init__(self, system, ctx, game, spec) -> None:
        self.system = system
        self.ctx = ctx
        self.game = game
        self.spec = spec
        self.battlefield = game.battlefield
        self.combat = game.combat_ctx
        self.resolver = game.combat_ctx.resolver
        self.round_index = ctx.round_index
        self.config = spec.config

    @property
    def scratch(self) -> dict:
        return self.game.hazard_scratch.setdefault(self.spec.name, {})

    def creatures(self, *, side: Optional[str] = None, alive_only: bool = True) -> list:
        out = [c for c in self.battlefield.creatures.values()
               if side is None or c.side == side]
        if alive_only:
            out = [c for c in out if not c.is_down and c.coord is not None]
        return out

    def add_hazard(self, center: tuple, radius_ft: float, damage: str, *,
                   damage_type: str = "fire", duration: Optional[int] = None,
                   tag: str = "fire") -> None:
        from .hazards import Hazard
        expires = None if duration is None else self.ctx.round_index + int(duration)
        self.battlefield.hazards.add(Hazard(center=center, radius_ft=radius_ft, damage=damage,
                                            damage_type=damage_type, expires_round=expires, tag=tag))

    def spawn(self, statblock, instance_name: str, side: str, coord: tuple):
        return self.system.spawn_creature(self.ctx, statblock, instance_name, side, coord)


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
    # Per-trial scratch for hazard-actor drivers (legendary uses, recharges,
    # minion counts) — drivers are cached and shared, so their state lives here.
    hazard_scratch: dict = field(default_factory=dict)
    # Names that have left the board via a `require_all` objective (out the
    # door). They stop acting, stop burning, and stop counting as "still here".
    escaped: set = field(default_factory=set)
    light_produced: bool = False   # `light_plan` fires at most once per trial
    retreat_started: Optional[int] = None   # round the party began its extraction retreat


class Dnd5eSystem:
    def __init__(self, *, board, roster: list, max_rounds: int, hp_mode: str = "average",
                 focus: Optional[dict] = None, obscurement: tuple = (),
                 light_plan: Optional[object] = None, reinforcements: tuple = (),
                 extraction: Optional[object] = None, grapple_escape: bool = False,
                 objective: Optional[object] = None, subduing_side: Optional[str] = None,
                 hit_dice_spent: int = 0, hazard_actors: tuple = (),
                 wake_up: Optional[object] = None, initial_hazards: tuple = ()) -> None:
        self.board = board
        self.roster = roster
        self.max_rounds = max_rounds
        self.hp_mode = hp_mode
        # `[simulation] grapple_escape` — see `_try_escape_grapple`. Off by
        # default so existing grapple sims keep their captured behavior.
        self.grapple_escape = grapple_escape
        # `[objective]` (loader.ObjectiveSpec, duck-typed): a reach-a-zone goal.
        # When set, `party_side` members advance toward `reach_y` (north) and the
        # trial ends when one arrives. None for an ordinary fight.
        self.objective = objective
        # `[simulation] subduing_side`: this side knocks foes out cold (stable)
        # instead of killing — see CombatContext. None for lethal combat.
        self.subduing_side = subduing_side
        # `[simulation] hit_dice_spent`: start every leveled creature this many
        # Hit Dice down — the opera-house phase 2 wakes its PCs after they've
        # "spent up to half their hit dice to heal", which shortens the Pyre
        # Weird's drain timer to Consume. 0 = everyone starts full.
        self.hit_dice_spent = hit_dice_spent
        # `[[hazard_actors]]` (loader.HazardActorSpec, duck-typed): bodiless
        # forces with an initiative slot — the Pyre Elemental. Never Creatures,
        # so they can't be targeted, killed, or counted for a side wipe.
        self.hazard_actors = tuple(hazard_actors)
        # `[wake_up]` (loader.WakeUpSpec): start a side beaten and bound — the
        # opera house's phase 2. None for an ordinary fight.
        self.wake_up = wake_up
        # `[[initial_hazards]]`: fires already burning when the trial opens.
        self.initial_hazards = tuple(initial_hazards)
        self.focus = dict(focus or {})
        # `[extraction]` (loader.ExtractionSpec, duck-typed): a smash-and-grab
        # objective + retreat. None for ordinary deathmatch sims.
        self.extraction = extraction
        # Reinforcement waves: tuple[(round_index, tuple[RosterSlot]), ...],
        # spawned at the start of their round by turn_order (design: the cathedral
        # guard waves arriving from the back). Pre-expanded by the loader.
        self.reinforcements = tuple(reinforcements)
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
        for _round, slots in self.reinforcements:
            for slot in slots:
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
        battlefield = Battlefield(creatures, board=self.board, obscurement=obscurement_field, auras=auras,
                                  condition_defs=self.condition_defs)
        battlefield.focus.update(self.focus)

        resolver = Resolver(ctx.dice)
        flags = FlagBag()
        combat_ctx = CombatContext(resolver, battlefield, ctx.ledger, flags=flags,
                                   condition_defs=self.condition_defs, subduing_side=self.subduing_side)

        for creature in creatures:
            self._prime(creature, combat_ctx, resolver)

        # Initiative: 1d20 + bonus, ties keep roster order (Python's sort is
        # stable, and `rolled` is built in roster order, so a `reverse=True`
        # sort by value alone preserves that order among equal rolls).
        rolled = [(c.instance_name, resolver.roll("1d20") + c.statblock.stats.initiative_bonus)
                 for c in creatures]
        # Hazard actors take an initiative slot like anything else, but they're
        # not creatures — `take_turn` dispatches them to their driver.
        rolled.extend((spec.name, spec.initiative) for spec in self.hazard_actors)
        rolled.sort(key=lambda pair: pair[1], reverse=True)
        turn_order = [name for name, _ in rolled]

        ctx.game = GameState(
            combat_ctx=combat_ctx, battlefield=battlefield,
            creatures={c.instance_name: c for c in creatures}, turn_order=turn_order,
            flags=flags,
        )
        self._seed_hazards(battlefield)
        self._apply_wake_up(ctx.game, resolver)

    def _seed_hazards(self, battlefield) -> None:
        """`[[initial_hazards]]`: the building is already alight when the trial
        opens. Permanent by default — this is a structure fire, not a spell."""
        from .hazards import Hazard
        for h in self.initial_hazards:
            battlefield.hazards.add(Hazard(
                center=tuple(h["center"]), radius_ft=h["radius"], damage=h["damage"],
                damage_type=h.get("damage_type", "fire"),
                expires_round=h.get("expires_round"), tag=h.get("name", "fire")))

    def _apply_wake_up(self, game: GameState, resolver) -> None:
        """`[wake_up]`: the side starts beaten — dropped to `hp`, having spent
        `heal_hit_dice` Hit Dice patching themselves up, with the first
        `bound_count` of them in irons. This is the opera house's phase-2 opening
        state, authored directly rather than simulated from phase 1."""
        spec = self.wake_up
        if spec is None:
            return
        for c in game.battlefield.members(spec.side):
            c.current_damage = max(0, c.hp - spec.hp)
            spend = min(spec.heal_hit_dice, c.hit_dice_remaining)
            for _ in range(spend):
                c.hit_dice_remaining -= 1
                healed = max(1, resolver.roll("1d8") + c.statblock.stats.modifier("constitution"))
                c.current_damage = max(0, c.current_damage - healed)
        if spec.bound_condition:
            for c in game.battlefield.members(spec.side)[:spec.bound_count]:
                game.combat_ctx.apply_condition(c, spec.bound_condition)

    def _prime(self, creature: Creature, combat_ctx, resolver) -> None:
        """Roll HP, seed resource pools, and apply passive traits — everything a
        freshly-built Creature needs before it acts. Shared by setup_trial and
        reinforcement spawning. (Resources must be seeded here because Creatures
        are built fresh per trial and reset_state is never called — a monk's ki
        gate was silently always-false before this.)"""
        creature.roll_hp(resolver, mode=self.hp_mode)
        # Hit Dice = character level (0 for monsters). The Pyre Weird's drain
        # timer; a sim may pre-spend some via `[hit_dice_spent]`.
        creature.hit_dice_remaining = max(
            0, int(creature.statblock.classification.get("level", 0)) - self.hit_dice_spent)
        for name, resource in creature.statblock.resources.items():
            creature.resources[name] = resource.uses
        for trait in creature.statblock.traits.values():
            apply_effects(trait.effects, EffectScope(ctx=combat_ctx, source=creature, target=creature))

    def _spawn_reinforcements(self, ctx: TrialContext) -> None:
        """Bring on any wave whose round is now (design doc: guard reinforcements
        arriving from the back). New arrivals join the battlefield and the end of
        the initiative order, acting from this round on."""
        game: GameState = ctx.game
        resolver = game.combat_ctx.resolver
        for wave_round, slots in self.reinforcements:
            if wave_round != ctx.round_index:
                continue
            for slot in slots:
                c = Creature(statblock=slot.statblock, instance_name=slot.instance_name,
                             side=slot.side, tags=slot.tags)
                c.place(*slot.start)
                game.battlefield.creatures[c.instance_name] = c
                game.creatures[c.instance_name] = c
                self._prime(c, game.combat_ctx, resolver)
                game.turn_order.append(c.instance_name)  # act at the tail this round

    def _check_extraction(self, ctx: TrialContext) -> None:
        """Drive the smash-and-grab: once the objective is broken, flag the party
        retreating (so movement flees to the exit and Shield's retreat trigger
        arms), then end the trial after `cover_rounds` — the "one round of cover
        fire, then you're gone" rule. finalize_trial scores `extracted`."""
        if self.extraction is None:
            return
        game: GameState = ctx.game
        obj = game.creatures.get(self.extraction.objective)
        if obj is None:
            return
        if game.retreat_started is None:
            if obj.is_down:                       # objective secured -> run for it
                game.retreat_started = ctx.round_index
                game.combat_ctx.set_flag("party_retreating", scope="trial")
        elif ctx.round_index >= game.retreat_started + self.extraction.cover_rounds:
            # Cover round(s) done — they're gone. finalize_trial scores it.
            game.combat_ctx.end_trial()

    def turn_order(self, ctx: TrialContext) -> list:
        # Called exactly once per round, at its start (runner.py's
        # `_begin_round`) — clear round-scoped flags, spawn any due reinforcement
        # wave, refresh combatant-bound obscurement auras onto their sources'
        # current cells, and re-derive who's blinded by standing in heavy
        # obscurement, all before anyone acts this round.
        game: GameState = ctx.game
        game.flags.clear_round()
        for c in game.creatures.values():
            c.round_scratch.clear()
        self._spawn_reinforcements(ctx)
        self._check_extraction(ctx)
        game.battlefield.refresh_auras(ctx.round_index)
        game.battlefield.hazards.prune(ctx.round_index)
        self._sync_obscurement(game)
        return game.turn_order

    def take_turn(self, ctx: TrialContext, actor_id: str) -> None:
        game: GameState = ctx.game
        game.combat_ctx.round_index = ctx.round_index
        game.combat_ctx.turn_order = game.turn_order

        spec = self._hazard_actor(actor_id)
        if spec is not None:
            self._take_hazard_turn(ctx, spec, game)
            return

        actor = game.creatures[actor_id]
        self._tick_start_of_turn(actor, game)
        self._tick_hazards(actor, game, ctx)
        actor.turn_scratch.clear()
        try:
            self._take_turn_body(ctx, actor, game)
        finally:
            self._tick_sustain(actor, game, ctx)
            self._tick_end_of_turn(actor, game, ctx.round_index)
            self._offer_legendary(ctx, game, after=actor)

    # ---- hazard actors (bodiless environmental forces) -------------------------

    def _hazard_actor(self, actor_id: str):
        return next((s for s in self.hazard_actors if s.name == actor_id), None)

    def _driver(self, spec):
        return escape_hatch.resolve(spec.handler)

    def _take_hazard_turn(self, ctx: TrialContext, spec, game: GameState) -> None:
        """A hazard actor's own turn. Its driver gets a view of the world and a
        handle back on this system (for spawning); it has no body, so none of
        the creature turn pipeline (conditions, movement, sustain) applies."""
        if ctx.round_index < spec.start_round:
            return
        self._driver(spec).take_turn(HazardView(self, ctx, game, spec))

    def _offer_legendary(self, ctx: TrialContext, game: GameState, *, after: Creature) -> None:
        """"Immediately after another creature's turn" — offer each awake hazard
        actor its legendary actions. A driver without a `legendary` hook is
        skipped, so this is free for ordinary hazard actors."""
        for spec in self.hazard_actors:
            if ctx.round_index < spec.start_round:
                continue
            driver = self._driver(spec)
            hook = getattr(driver, "legendary", None)
            if hook is not None:
                hook(HazardView(self, ctx, game, spec), after)

    def spawn_creature(self, ctx: TrialContext, statblock, instance_name: str, side: str,
                       coord: tuple, tags: tuple = ()) -> Optional[Creature]:
        """Mid-trial arrival, shared by reinforcement waves and a hazard actor's
        summon (the Pyre Elemental calling up a Weird). Joins the battlefield and
        the tail of the initiative order, acting from this round on."""
        game: GameState = ctx.game
        if instance_name in game.creatures:
            return None
        c = Creature(statblock=statblock, instance_name=instance_name, side=side, tags=tags)
        c.place(*coord)
        game.battlefield.creatures[instance_name] = c
        game.creatures[instance_name] = c
        self.condition_defs.update(statblock.conditions)
        self._prime(c, game.combat_ctx, game.combat_ctx.resolver)
        game.turn_order.append(instance_name)
        return c

    def _try_escape_grapple(self, actor: Creature, game: GameState) -> bool:
        """RAW 2024: escaping a grapple costs your **action** — a check against
        the grappler's escape DC, win or lose. Returns True when the turn was
        spent on it.

        Opt-in per simulation (`[simulation] grapple_escape = true`), because
        turning it on globally would rewrite every existing grapple sim's
        numbers: the otyugh sims were all captured with grapple as an inert
        marker, and the party spending actions to break free is a different
        fight. Sims that *are* about grapple — the Guard Cartel, whose Vise
        damage triples against a held target — need the action cost modeled or
        the first successful Catch is permanent.

        The check is d20 + the better of the Strength/Dexterity modifier +
        proficiency, standing in for Athletics/Acrobatics (an approximation:
        the engine has no skill-check primitive, and `[stats.skills]` is
        carried but unused).

        **The escape is a choice, not a reflex.** Trading a whole turn to shed
        a condition whose only RAW effect is Speed 0 is usually *wrong* for a
        melee combatant that's already standing where it wants to be — a
        creature that escapes unconditionally is modeling worse play than a
        competent table, not better. So it only spends the action when being
        held actually costs it something: another enemy has closed to within 10
        ft, which is the shape every grapple-payoff design takes (here, a Vise
        whose club triples against a held target). Held by a lone grappler with
        nothing else nearby, it shrugs and keeps swinging."""
        instance = actor.condition(conditions.GRAPPLED)
        if instance is None or instance.escape_dc is None:
            return False
        others = [e for e in game.battlefield.enemies_of(actor)
                  if e.instance_name != instance.source]
        if not any((game.battlefield.distance_ft(actor, e) or 999) <= 10 for e in others):
            return False
        stats = actor.statblock.stats
        bonus = max(stats.modifier("strength"), stats.modifier("dexterity")) + stats.proficiency
        if game.combat_ctx.resolver.roll("1d20") + bonus >= instance.escape_dc:
            game.combat_ctx.remove_condition(actor, conditions.GRAPPLED)
        return True

    def _take_turn_body(self, ctx: TrialContext, actor: Creature, game: GameState) -> None:
        if actor.instance_name in game.escaped:
            return                      # already outside; nothing left to do
        if actor.is_down:
            self._roll_death_save(actor, game.combat_ctx)
            return
        if any(actor.has_condition(name) for name in conditions.SKIPS_TURN):
            return
        if self.grapple_escape and self._try_escape_grapple(actor, game):
            return  # breaking free cost this creature its action
        if self._maybe_produce_light(actor, game, ctx):
            return  # producing light cost this creature its action

        # Stand up from Prone at the start of the turn (RAW: costs half your
        # movement; that fractional cost isn't modeled, but the important part
        # — that a knocked-down creature is Prone until *its* next turn, so the
        # pack gets advantage against it in between — is). The Wolf's bite is
        # what applies it.
        if actor.has_condition(conditions.PRONE):
            actor.remove_condition(conditions.PRONE)

        self._offer_turn_start_reactions(actor, game, ctx)

        behavior_ctx = BehaviorContext(battlefield=game.battlefield, round_index=ctx.round_index,
                                       turn_order=game.turn_order, flags=game.flags,
                                       resolver=game.combat_ctx.resolver)
        option = select_multiattack(actor, behavior_ctx)

        # A party member with a reach-a-zone `[objective]` pushes toward the
        # zone instead of running its normal tactic (see `_advance_to_stage`).
        # Getting out of your irons comes first — you can't run in manacles.
        if self.objective is not None and actor.side == self.objective.party_side:
            if self._try_break_bonds(actor, game):
                return
            self._advance_to_stage(ctx, actor, option, game, behavior_ctx)
            return

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
            # A retreating party member flees toward the exit (still firing
            # cover at whatever's in range) instead of engaging.
            retreat_dest = None
            if (self.extraction is not None and actor.side == self.extraction.party_side
                    and game.flags.has("party_retreating")):
                retreat_dest = self.extraction.exit
            if dest is not None:
                movement.move_to_cell(actor, dest, game.battlefield)
            elif retreat_dest is not None:
                movement.move_to_cell(actor, retreat_dest, game.battlefield)
            else:
                movement.apply_tactic(actor.statblock.behavior.tactic, actor, targets[0], game.battlefield,
                                      max_range_ft=ability.range_normal)
            self._offer_opportunity_attacks(actor, before, actor.coord, game, ctx)
            resolve_ability(game.combat_ctx, actor, ability, targets)
            _spend_costs(actor, ability)

    def _reached_objective(self, actor: Creature) -> bool:
        if self.objective is None or actor.coord is None:
            return False
        if self.objective.direction == "south":
            return actor.y >= self.objective.reach_y
        return actor.y <= self.objective.reach_y

    def _try_break_bonds(self, actor: Creature, game: GameState) -> bool:
        """A bound creature spends its ACTION on the irons — either its own, or
        (if it's free) an adjacent ally's. Returns True when the turn went on it.

        Two outs, matching the encounter's design: the party brought a manacle
        key (`has_key` — Martinique's advice), in which case unlocking is
        automatic; or a raw DC 20 Dexterity attempt, which is the near-impossible
        trap. A *free* member can always spend its action on a bound ally, which
        is the intended "someone frees the others" path."""
        spec = self.wake_up
        if spec is None or not spec.bound_condition or actor.side != spec.side:
            return False
        cond = spec.bound_condition

        if actor.has_condition(cond):
            if spec.has_key or self._bond_check(actor, game, spec):
                game.combat_ctx.remove_condition(actor, cond)
                actor.trial_scratch["freed_self"] = True
            return True

        # Free: unlock the nearest bound ally in reach (needs the key, or picks
        # the lock at the same DC).
        bound = [a for a in game.battlefield.members(spec.side)
                 if a is not actor and not a.is_down and a.has_condition(cond)
                 and (game.battlefield.distance_ft(actor, a) or 999) <= spec.free_ally_range]
        if not bound:
            return False
        ally = bound[0]
        if spec.has_key or self._bond_check(actor, game, spec):
            game.combat_ctx.remove_condition(ally, cond)
            ally.trial_scratch["freed_by_ally"] = True
        return True

    @staticmethod
    def _bond_check(actor: Creature, game: GameState, spec) -> bool:
        stats = actor.statblock.stats
        bonus = stats.modifier("dexterity") + stats.proficiency
        return game.combat_ctx.resolver.roll("1d20") + bonus >= spec.escape_dc

    def _advance_to_stage(self, ctx: TrialContext, actor: Creature, option, game: GameState,
                          behavior_ctx) -> None:
        """The reach-a-zone objective's turn (design: sims/opera_house). The
        actor spends its move heading straight north toward the stage
        (`move_to_cell` to (its x, reach_y) — pathing routes it around bodies and
        up the open aisle), provoking opportunity attacks on the way, and ends
        the trial the instant it arrives. It does NOT chase enemies: it then
        makes its option's attacks only against whatever its normal targeting
        finds *in reach after moving* (a melee swing at a blocker that stepped
        into the way; a ranged shot at anything in range) — a runner taking
        opportunistic swings, not a fighter picking a fight. Immobilised (Speed 0
        from a bolo or manacles) it simply can't advance; grappled-and-taxed it
        already spent the turn escaping upstream in `_take_turn_body`."""
        before = actor.coord
        if before is not None:
            movement.move_to_cell(actor, (actor.x, self.objective.reach_y), game.battlefield)
            self._offer_opportunity_attacks(actor, before, actor.coord, game, ctx)
        if self._reached_objective(actor):
            if self.objective.require_all:
                # Out the door: this one is safe and off the board. The trial
                # runs on until every survivor is out or down.
                game.escaped.add(actor.instance_name)
                actor.trial_scratch["escaped_round"] = ctx.round_index
                return
            game.combat_ctx.end_trial(outcome={"reached_stage": 1, "reach_round": ctx.round_index})
            return
        if option is None:
            return
        for action_name in option.actions:
            ability = actor.statblock.abilities[action_name]
            targets = select_targets(actor, ability, behavior_ctx)
            if not targets:
                continue
            resolve_ability(game.combat_ctx, actor, ability, targets)
            _spend_costs(actor, ability)

    def is_over(self, ctx: TrialContext) -> bool:
        game: GameState = ctx.game
        if game.combat_ctx.trial_ending:
            return True
        sides = {c.side for c in game.creatures.values()}
        return any(
            members and all(m.is_down or m.instance_name in game.escaped for m in members)
            for members in (game.battlefield.members(side) for side in sides)
        )

    def finalize_trial(self, ctx: TrialContext) -> dict:
        game: GameState = ctx.game
        # How long the fight actually took. Cheap, always available, and the
        # thing you reach for first when asking whether an encounter is the
        # right size — a squad that folds in three rounds is a different
        # encounter from one that grinds for ten, even at identical HP totals.
        outcome = {"rounds": ctx.round_index}
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
        # Extraction scoring (always present when `[extraction]` is configured,
        # whether the trial ended by escape, wipe, or round limit).
        if self.extraction is not None:
            obj = game.creatures.get(self.extraction.objective)
            secured = obj is not None and obj.is_down
            party = game.battlefield.members(self.extraction.party_side)
            nobody_down = bool(party) and not any(m.is_down for m in party)
            outcome["secured"] = int(secured)
            outcome["extracted"] = int(secured and nobody_down)
        # Reach-a-zone objective: default 0 so a trial that ended by wipe or the
        # round cap reads as "didn't reach"; the `end_trial` outcome below flips
        # it to 1 (and adds `reach_round`) when a runner broke through.
        if self.objective is not None:
            outcome["reached_stage"] = 0
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
        its bearer act this turn. Then `actor`'s own `save_ends_*` conditions
        get their saving throw, and any exhausted recharge resource its roll."""
        for creature in game.creatures.values():
            for instance in list(creature.conditions):
                if instance.expires == "start_of_source_next_turn" and instance.source == actor.instance_name:
                    self._expire_condition(creature, instance)
        self._tick_save_ends(actor, game)
        self._tick_recharges(actor, game)

    def _tick_hazards(self, actor: Creature, game: GameState, ctx: TrialContext) -> None:
        """Fire burns at the start of a turn: a creature standing in one or more
        active hazards takes each one's damage (environmental, so lethal — see
        `CombatContext.environmental_damage`). Skips the already-down (the
        burning-building design leaves the unconscious to wake, not burn) and
        stops once a fire drops the actor. Damage typing (fire immunity for the
        elementals) arrives in P1; for now every creature burns."""
        if actor.is_down or actor.coord is None or actor.instance_name in game.escaped:
            return
        immune = actor.statblock.stats.immunities
        for hazard in game.battlefield.hazards.covering(actor.coord, ctx.round_index):
            if hazard.damage_type in immune:
                continue   # fire-immune (the elementals) — don't even roll
            amount = game.combat_ctx.resolver.damage(hazard.damage)
            game.combat_ctx.environmental_damage(actor, amount, tag=hazard.tag,
                                                 damage_type=hazard.damage_type)
            if actor.is_down:
                break

    def _tick_sustain(self, actor: Creature, game: GameState, ctx: TrialContext) -> None:
        """Guttering (`[sustain]`): at the end of its turn a creature that needs
        a hazard to live must be standing in one — or have fed this turn
        (`drained_hit_die`) — or make its save or die. The Pyre Weird starves
        outside fire, which is what makes dragging a drained victim out of the
        flames a real counter-tactic (design doc's own emergent note)."""
        spec = actor.statblock.sustain
        if spec is None or actor.is_down:
            return
        if actor.turn_scratch.get("drained_hit_die"):
            return
        kind = spec["hazard_type"]
        if any(h.damage_type == kind
               for h in game.battlefield.hazards.covering(actor.coord, ctx.round_index)):
            return
        if game.combat_ctx.saving_throw(actor, spec["save_ability"], int(spec["save_dc"])):
            return
        actor.current_damage = max(actor.current_damage, actor.hp)   # guttered out
        actor.death_save_failures = 3

    def _tick_save_ends(self, actor: Creature, game: GameState) -> None:
        """"…or succeeds on a DC N <ability> saving throw at the start of each
        of its turns" — the Guard Cartel Slinger's bolos. Rolled here, before
        the turn body, so a shaken-off Speed-0 bolo frees this turn's movement."""
        for instance in list(actor.conditions):
            if instance.expires not in conditions.SAVE_ENDS_CLOCKS:
                continue
            if instance.save_ability is None or instance.save_dc is None:
                continue
            if game.combat_ctx.saving_throw(actor, instance.save_ability, instance.save_dc):
                actor.remove_condition(instance.name)

    def _tick_recharges(self, actor: Creature, game: GameState) -> None:
        """`recharge = "5-6"` on a `[resources.*]` pool: at the start of its
        owner's turn, an exhausted pool rolls a d6 and comes back on a hit
        (the Constable's Rally). Parsed since Phase 3 but never rolled until
        now — a recharge resource simply stayed spent for the rest of the
        fight."""
        for name, resource in actor.statblock.resources.items():
            if not resource.recharge or actor.resources.get(name, 0) > 0:
                continue
            low = int(str(resource.recharge).split("-")[0])
            if game.combat_ctx.resolver.roll("1d6") >= low:
                actor.resources[name] = resource.uses

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
