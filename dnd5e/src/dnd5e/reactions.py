"""The reaction trigger bus (design doc 04 section 4): a publish point offers
an event to a pool of candidate creatures, in initiative order, and fires the
first eligible `[reactions.*]` entry whose `trigger` matches, gated by
`when` -> reaction/bonus-action economy -> `costs`. Only ONE reaction fires
per `offer()` call (an attack is intercepted by at most one guardian).

Publish points live where the event actually happens — `actions.py`'s
`attack()` is the only one wired so far (`ally_targeted_by_attack`/`self_
targeted_by_attack`, before any roll — design doc 04 section 4's ordering
invariant) plus `system.py`'s turn-start hook (`turn_start`, the Masked
Bruiser's Sleight of Crowd). The rest of the trigger catalog
(`conditions.REACTION_TRIGGERS`) is registered but nothing publishes it yet.
"""

from __future__ import annotations

from typing import Optional

from . import expressions
from .behavior import BehaviorContext, ConcreteScope
from .creature import Creature
from .effects import EffectScope, apply_effects


def offer(trigger: str, event: dict, *, candidates: list, behavior_ctx: BehaviorContext,
         combat_ctx) -> Optional[dict]:
    """Offer `event` to each of `candidates` (already filtered to who's
    eligible to react at all — e.g. allies of an attack's target), in
    initiative order, applying the first reaction whose `trigger` matches,
    `when` passes (evaluated with `event.*` bindings), and reaction/bonus-
    action economy is available. Returns `{"reactor": Creature, "reaction":
    name}` for the reaction that fired, or None."""
    order = {name: i for i, name in enumerate(behavior_ctx.turn_order)}
    ordered = sorted(candidates, key=lambda c: order.get(c.instance_name, 1 << 30))
    for creature in ordered:
        if creature.is_down:
            continue
        fired = _try_creature(trigger, event, creature, behavior_ctx=behavior_ctx, combat_ctx=combat_ctx)
        if fired is not None:
            return fired
    return None


def _try_creature(trigger: str, event: dict, creature: Creature, *,
                  behavior_ctx: BehaviorContext, combat_ctx) -> Optional[dict]:
    candidates = sorted(
        (r for r in creature.statblock.reactions.values() if r.trigger == trigger),
        key=lambda r: -r.priority,
    )
    for reaction in candidates:
        if reaction.uses_reaction and creature.round_scratch.get("reaction_used"):
            continue
        if reaction.uses_bonus_action and creature.turn_scratch.get("bonus_action_used"):
            continue
        scope = ConcreteScope(behavior_ctx, creature, event=event)
        if reaction.when is not None and not expressions.evaluate(reaction.when, scope):
            continue
        if reaction.uses_reaction:
            creature.round_scratch["reaction_used"] = True
        if reaction.uses_bonus_action:
            creature.turn_scratch["bonus_action_used"] = True
        effect_scope = EffectScope(ctx=combat_ctx, source=creature,
                                   target=event.get("target", creature), event=event)
        apply_effects(reaction.effects, effect_scope)
        return {"reactor": creature, "reaction": reaction.name}
    return None
