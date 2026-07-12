"""`Dnd5eSystem`: implements `simharness.GameSystem`, wiring `Creature`,
`Battlefield`, and `actions.CombatContext` into the trial/round/turn pipeline
`simharness.TrialRunner` drives (design doc 03 section 2).

Phase 3 turn pipeline (simplified from the full design — see this module's
methods for exactly what's cut):
    1. incapacity gates: down -> death save and stop; any SKIPS_TURN
       condition (stunned et al.) -> stop
    2. multiattack selection: no `when` yet, so every option is always
       eligible — highest `priority` wins (ties are a load-time error, see
       loader.py); no `[multiattack]` at all falls back to one execution of
       `behavior.action_priority[0]`
    3. one target for the whole option (`battlefield.preferred_target`,
       fetched once, matching the old engine's fighter/ranger/rogue policies
       — see design doc 05's Otyugh fidelity note for why this simplifies
       the Otyugh specifically)
    4. movement via the creature's `behavior.tactic`, then resolve each
       action in the option against that target

Not yet wired (later phases): expression-driven multiattack/targeting
(Phase 4), reactions (Phase 5), condition clocks/expiry (Phase 4/5),
environment obscurement/light (Phase 4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from simharness.plugin import TrialContext

from . import conditions, movement
from .actions import CombatContext, resolve_ability
from .battlefield import Battlefield
from .creature import Creature
from .dice import Resolver
from .statblock import MultiattackOption, Statblock


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


class Dnd5eSystem:
    def __init__(self, *, board, roster: list, max_rounds: int, hp_mode: str = "average",
                 focus: Optional[dict] = None) -> None:
        self.board = board
        self.roster = roster
        self.max_rounds = max_rounds
        self.hp_mode = hp_mode
        self.focus = dict(focus or {})

    # ---- GameSystem protocol --------------------------------------------------

    def setup_trial(self, ctx: TrialContext) -> None:
        creatures = [
            Creature(statblock=slot.statblock, instance_name=slot.instance_name,
                     side=slot.side, tags=slot.tags)
            for slot in self.roster
        ]
        for creature, slot in zip(creatures, self.roster):
            creature.place(*slot.start)

        battlefield = Battlefield(creatures, board=self.board)
        battlefield.focus.update(self.focus)

        resolver = Resolver(ctx.dice)
        combat_ctx = CombatContext(resolver, battlefield, ctx.ledger)

        for creature in creatures:
            creature.roll_hp(resolver, mode=self.hp_mode)

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
        )

    def turn_order(self, ctx: TrialContext) -> list:
        return ctx.game.turn_order

    def take_turn(self, ctx: TrialContext, actor_id: str) -> None:
        game: GameState = ctx.game
        actor = game.creatures[actor_id]
        actor.turn_scratch.clear()

        if actor.is_down:
            self._roll_death_save(actor, game.combat_ctx)
            return
        if any(actor.has_condition(name) for name in conditions.SKIPS_TURN):
            return

        option = self._select_multiattack(actor)
        if option is None:
            return

        target = game.battlefield.preferred_target(actor)
        if target is None:
            return

        first_ability = actor.statblock.abilities[option.actions[0]]
        movement.apply_tactic(actor.statblock.behavior.tactic, actor, target, game.battlefield,
                              max_range_ft=first_ability.range_normal)

        for action_name in option.actions:
            ability = actor.statblock.abilities[action_name]
            resolve_ability(game.combat_ctx, actor, ability, [target])

    def is_over(self, ctx: TrialContext) -> bool:
        game: GameState = ctx.game
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
        return outcome

    # ---- internals --------------------------------------------------------------

    def _select_multiattack(self, actor: Creature) -> Optional[MultiattackOption]:
        options = actor.statblock.multiattack
        if options:
            # No `when` in Phase 3, so every option is always eligible;
            # highest priority wins. Duplicate priorities are rejected at
            # load time (loader.py), so max() here is unambiguous.
            return max(options.values(), key=lambda o: o.priority)
        priority = actor.statblock.behavior.action_priority
        if priority:
            # No [multiattack] at all: one execution of the first listed
            # action. The old `attacks_per_turn` repeat-count concept is
            # gone — a creature that wants more than one attack must define
            # an explicit [multiattack] table (design doc 01 section 1.5).
            return MultiattackOption(name="_implicit", actions=(priority[0],), priority=0)
        return None

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
