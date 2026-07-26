"""The effect-primitive registry (design doc 03 section 4) — closed vocabulary,
validated at load time, dispatched at resolution time.

**Phase 3 scope was intentionally a small subset** of doc 03's full
17-primitive table: `attach_condition`, `remove_condition`, `require_save`.
Phase 4 added `set_flag` (the round/trial signal bag — design doc 04's
`has_flag` function reads what this writes), `end_trial` (flee/retreat —
finalize immediately, optionally merging extra outcome keys; the
shadow-otyugh retreat's `force_trial_end` equivalent), and the three
obscurement/vision trait effects (`emit_light`, `limited_darkvision`,
`darkvision_immunity`).

Phase 5 adds `redirect_attack`/`swap_positions` (reaction-context: retarget
the pending attack / exchange board coordinates — design doc 04 section 4's
ordering invariant, that these complete *before* the roll, is enforced by
`actions.py`'s `attack`, not here) and `damage_rider` (extra dice on the
triggering hit — the Masked Hector's advantage/mark riders).

Bug-A follow-up (design doc 07) adds `reduce_damage` (reaction-context, the
`taking_damage` trigger: multiply the pending hit's damage by a factor —
the Thief Rogue's Uncanny Dodge, reusable for the Barbarian's Rage
resistance) and `mark_turn` (set a once-per-turn `turn_scratch` toggle read
back by the `turn_marked` predicate — the Thief Rogue's Sneak Attack
first-hit-per-turn gate). Every action
effect call may now carry a `when` (compiled at load time like any other,
evaluated here against the acting creature/target/event before dispatch —
design doc 01's masked_bruiser example gates several effects this way) and a
`target` override (`"self"` | `"target"` | `"event.<field>"`, resolved by
`_resolve_ref` — most calls implicitly target `scope.target`, but a reaction
effect often needs to address someone else, e.g. marking `event.attacker`).
"Grant"-context effects (`grant_advantage_to_attackers`, `impose_disadvantage_
except_source`, ...) are a *separate* registry, `conditions.GRANT_EFFECTS` —
they're never dispatched via `apply_effect` (they're data, folded by
`actions.attack`), only validated by loader.py against that registry.
Growing this registry is a deliberate change: add the primitive, its dispatch
function, and a test — never call an unregistered name silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Optional

from .statblock import EffectCall

if TYPE_CHECKING:
    from .creature import Creature

ACTION_EFFECTS = frozenset({
    "attach_condition", "remove_condition", "require_save", "set_flag", "end_trial",
    "emit_light", "limited_darkvision", "darkvision_immunity",
    "redirect_attack", "swap_positions", "damage_rider",
    "reduce_damage", "mark_turn", "make_attack", "spend_resource",
    "grant_temp_hp", "create_hazard", "drain_hit_die", "instant_death",
})

ALL_EFFECTS = ACTION_EFFECTS


@dataclass
class EffectScope:
    """What an effect function needs to act: the resolution API (duck-typed
    here as `Any` to avoid a circular import with actions.py, which is the
    only real implementation) plus the source and target creatures, and
    (Phase 5) the triggering event's bindings — populated for reaction
    effects (`event.attacker`/`event.target`/`event.ability`), empty
    otherwise."""

    ctx: Any
    source: "Creature"
    target: "Creature"
    event: dict = field(default_factory=dict)


def validate_effect_name(name: str, *, where: str) -> None:
    if name not in ALL_EFFECTS:
        raise ValueError(f"{where}: unknown effect {name!r}; known effects: {sorted(ALL_EFFECTS)}")


def _resolve_ref(ref, scope: EffectScope) -> "Creature":
    """Resolve an effect-call `target`/`to`/`with` reference: `"self"` (the
    effect's source — the acting/reacting creature), `"target"` (the effect's
    default target), `"event.<field>"` (a triggering-event binding, e.g.
    `event.attacker`), or a **compiled expression** — the `"expr:<expression>"`
    form, already parsed by `loader._compile_target_ref`, for references the
    fixed forms can't name (the Bruiser's Sleight of Crowd swaps with a *Poet
    ally*). An expression may legitimately resolve to `None` (nothing matched);
    callers must tolerate that."""
    if not isinstance(ref, str):
        from . import expressions
        return expressions.evaluate(ref, _effect_when_scope(scope))
    if ref == "self":
        return scope.source
    if ref == "target":
        return scope.target
    if ref.startswith("event."):
        return scope.event.get(ref[len("event."):])
    raise ValueError(f"cannot resolve effect reference {ref!r}")  # pragma: no cover (validated at load)


def _effect_when_scope(scope: EffectScope):
    """Build a full `expressions.Scope` for an effect call's `when` (design
    doc 01's masked_bruiser example gates several effects this way) — needs
    the full query vocabulary (`has_tag`, `distance`, ...), which `EffectScope`
    deliberately doesn't carry itself (it would need a circular import on
    `behavior.py`, which itself imports `escape_hatch`, `expressions`, etc.).
    Lazy import here instead; `behavior.py` never imports `effects.py`, so
    this is one-directional, not a cycle."""
    from .behavior import BehaviorContext, ConcreteScope
    ctx = scope.ctx
    behavior_ctx = BehaviorContext(battlefield=ctx.battlefield, round_index=ctx.round_index,
                                   turn_order=ctx.turn_order, flags=ctx.flags, resolver=ctx.resolver)
    return ConcreteScope(behavior_ctx, scope.source, target=scope.target, event=scope.event)


def apply_effect(call: EffectCall, scope: EffectScope) -> None:
    when = call.args.get("when")
    if when is not None:
        from . import expressions
        if not expressions.evaluate(when, _effect_when_scope(scope)):
            return
    fn = _DISPATCH.get(call.effect)
    if fn is None:
        raise ValueError(f"unknown effect {call.effect!r} (not caught at load time?)")
    if "target" in call.args:
        scope = EffectScope(ctx=scope.ctx, source=scope.source,
                            target=_resolve_ref(call.args["target"], scope), event=scope.event)
    fn(call.args, scope)


def apply_effects(calls: tuple[EffectCall, ...], scope: EffectScope) -> None:
    for call in calls:
        apply_effect(call, scope)


def _attach_condition(args: dict, scope: EffectScope) -> None:
    condition = args["condition"]
    cdef = scope.ctx.condition_defs.get(condition)
    # `exclusive = "per_source"` (design doc 03 section 3): attaching to a new
    # bearer detaches this *same source's* instance from whoever else holds
    # it — the Bruiser's Mark's RAW "only one creature marked at a time".
    # `"per_target"` needs no extra handling: `Creature.add_condition` already
    # no-ops a duplicate on the same target, which is all it RAW means (a
    # target can't be double-marked, but different targets each hold their
    # own instance independently).
    if cdef is not None and cdef.exclusive == "per_source":
        for other in scope.ctx.battlefield.creatures.values():
            if other is scope.target:
                continue
            existing = other.condition(condition)
            if existing is not None and existing.source == scope.source.instance_name:
                other.remove_condition(condition)
    scope.ctx.apply_condition(scope.target, condition, source=scope.source,
                              escape_dc=args.get("escape_dc"))
    # Clock/unless predicate come from the condition's *definition* (custom
    # conditions), OR from an explicit `expires` on the effect call itself — the
    # latter lets a RAW condition be attached with a duration (the Monk's
    # Stunning Strike attaches `stunned` with `expires =
    # "start_of_source_next_turn"`, which has no ConditionDef of its own). The
    # call's `expires` wins if both are present.
    expires = args.get("expires") or (cdef.expires if cdef is not None else None)
    unless = cdef.unless if cdef is not None else None
    if expires or unless:
        instance = scope.target.condition(condition)
        if instance is not None:
            instance.expires = expires
            instance.unless = unless
            # A `save_ends_*` clock needs its save parameters on the instance:
            # system.py's start-of-turn tick rolls them without re-looking up
            # the definition (same rationale as expires/unless above).
            if cdef is not None:
                instance.save_ability = cdef.save_ability
                instance.save_dc = cdef.save_dc


def _remove_condition(args: dict, scope: EffectScope) -> None:
    scope.ctx.remove_condition(scope.target, args["condition"])


def _require_save(args: dict, scope: EffectScope) -> None:
    """A nested save distinct from the ability's own resolution — e.g. the
    Otyugh's Bite forcing a secondary Constitution save on top of the initial
    attack roll. `on_fail`/`on_success` are raw effect-dict lists (mirroring
    an ability's own `on_hit`/`on_fail`), dispatched recursively."""
    saved = scope.ctx.saving_throw(scope.target, args["ability"], args["dc"])
    nested = args.get("on_success" if saved else "on_fail", [])
    for raw in nested:
        apply_effect(EffectCall.from_dict(raw), scope)


def _set_flag(args: dict, scope: EffectScope) -> None:
    scope.ctx.set_flag(args["flag"], scope=args.get("scope", "round"))


def _spend_resource(args: dict, scope: EffectScope) -> None:
    """Decrement a named resource on the effect's source (e.g. a reaction-cast
    Shield spending one of its charges). The matching debit for a `when` gated
    on `resource_available(...)`."""
    src = scope.source
    name, amount = args["resource"], int(args.get("amount", 1))
    if name in src.resources:
        src.resources[name] = max(0, src.resources[name] - amount)


def _end_trial(args: dict, scope: EffectScope) -> None:
    scope.ctx.end_trial(outcome=args.get("outcome"))


def _emit_light(args: dict, scope: EffectScope) -> None:
    """Register `scope.target` as a light-emitting aura source, following it
    around the board (design doc 03's effect table: "become a light source,
    clears local obscurement blindness" — the clearing itself happens every
    round via `system.py`'s obscurement sync once this aura is in place, not
    here)."""
    from .battlefield import Aura
    scope.ctx.battlefield.auras.append(
        Aura(source=scope.target.instance_name, kind="light",
             radius_ft=args["radius"], start_round=args.get("start_round", 1)))


def _limited_darkvision(args: dict, scope: EffectScope) -> None:
    from .battlefield import LIMITED_DARKVISION_RANGE_FT
    scope.target.trial_scratch["limited_darkvision_ft"] = args.get("range", LIMITED_DARKVISION_RANGE_FT)


def _darkvision_immunity(args: dict, scope: EffectScope) -> None:
    scope.target.trial_scratch["darkvision_immune"] = True


def _redirect_attack(args: dict, scope: EffectScope) -> None:
    """Reaction-only (design doc 04 section 4's ordering invariant):
    `actions.attack` calls the reaction bus *before* any roll, then reads
    `CombatContext`'s pending-redirect back — this just records the new
    target, it doesn't touch the roll itself."""
    to = _resolve_ref(args["to"], scope)
    if to is not None:
        scope.ctx.set_pending_redirect(to)


def _swap_positions(args: dict, scope: EffectScope) -> None:
    # An `expr:` reference can resolve to nothing (no matching ally) — then
    # there is simply no one to swap with.
    other = _resolve_ref(args["with"], scope)
    if other is not None:
        scope.ctx.swap_positions(scope.source, other)


def _damage_rider(args: dict, scope: EffectScope) -> None:
    """Extra dice on the triggering hit (the Masked Hector's advantage/mark
    riders, the Thief Rogue's Sneak Attack) — a second `deal()` call, not a
    mutation of the base hit's already-dealt damage; crit-doubled the same way
    the base hit was, via `scope.event["crit"]` (set by
    `actions._resolve_attack`)."""
    amount = scope.ctx.roll(args["damage"], crit=bool(scope.event.get("crit")))
    scope.ctx.deal(scope.source, scope.target, amount, args.get("name", "rider"), args.get("damage_type"))


def _make_attack(args: dict, scope: EffectScope) -> None:
    """Resolve an ability as an out-of-turn attack.

    Two shapes:

    * **No `actor`** — the effect's *source* swings its own named ability at
      `scope.target`. The Opportunity Attack (design doc 07): `enemy_left_reach`
      fires, and the reactor swings at whoever is leaving.
    * **`actor = <creature ref>`** — *someone else* attacks, picking its own
      target with its own declarative targeting. This is the Guard Cartel
      Constable's Commander's Strike ("that ally can use its reaction to make one
      weapon attack against a target within its range, adding an extra 1d8
      damage"): the ally, not the Constable, is the attacker, so its to-hit,
      damage, reach and range all apply.

    `uses_reaction = true` spends the attacker's reaction (the shared
    `round_scratch["reaction_used"]` economy `reactions.py` uses) and refuses to
    fire when it's already gone — RAW one Commander's Strike per ally per round.
    `bonus_damage` is dealt as a rider on a hit, crit-aware like any other.

    Lazily imports `actions`/`behavior` (which import this module) to keep the
    dependency one-directional at import time."""
    from .actions import _resolve_attack

    attacker = scope.source if "actor" not in args else _resolve_ref(args["actor"], scope)
    if attacker is None or attacker.is_down:
        return
    ability = attacker.statblock.abilities.get(args["ability"])
    if ability is None:
        return
    if args.get("uses_reaction"):
        if attacker.round_scratch.get("reaction_used"):
            return
        attacker.round_scratch["reaction_used"] = True

    if attacker is scope.source:
        target = scope.target
    else:
        # A commanded ally picks its own victim, through its own
        # `[[behavior.targeting]]` rules and the ability's own range gating.
        from .behavior import BehaviorContext, select_targets
        ctx = scope.ctx
        behavior_ctx = BehaviorContext(battlefield=ctx.battlefield, round_index=ctx.round_index,
                                       turn_order=ctx.turn_order, flags=ctx.flags, resolver=ctx.resolver)
        chosen = select_targets(attacker, ability, behavior_ctx)
        target = chosen[0] if chosen else None
    if target is None or target.is_down:
        return

    out = _resolve_attack(scope.ctx, attacker, ability, target)
    bonus = args.get("bonus_damage")
    if bonus and out.hit:
        amount = scope.ctx.roll(bonus, crit=out.crit)
        scope.ctx.deal(attacker, out.target or target, amount,
                       args.get("name", "commanded_strike"), ability.damage_type)


def _drain_hit_die(args: dict, scope: EffectScope) -> None:
    """Burn `amount` (default 1) Hit Dice off the target — the Pyre Weird's
    life-force drain. Hit Dice are the weird's *timer*, not damage: at 0 its
    Consume finisher unlocks (`hit_dice(target) == 0`). Floors at 0."""
    n = int(args.get("amount", 1))
    scope.target.hit_dice_remaining = max(0, scope.target.hit_dice_remaining - n)
    # Feeding satisfies the weird's Guttering check for this turn (system.
    # `_tick_sustain` reads this) — a drained victim is fuel, so it doesn't need
    # to be standing in fire.
    scope.source.turn_scratch["drained_hit_die"] = True


def _instant_death(args: dict, scope: EffectScope) -> None:
    """Kill outright — no death saves, no corpse (the Pyre Weird's Pyre's Due:
    "revivable only by True Resurrection or Wish"). Sets damage past 0 and
    stamps three death-save failures so `is_dead` is true and no later heal or
    stabilize can walk it back."""
    target = scope.target
    if target is None or target.is_dead:
        return
    target.current_damage = max(target.current_damage, target.hp)
    target.death_save_successes = 0
    target.death_save_failures = 3


def _create_hazard(args: dict, scope: EffectScope) -> None:
    """Drop a persistent fire region (the Pyre Elemental's Falling Debris) —
    a `radius`-ft sphere of `damage` centered on the effect's target (or the
    source if it has no target), lasting `duration` rounds (omit = permanent).
    Anyone starting a turn inside it burns (`system._tick_hazards`)."""
    from .hazards import Hazard
    ctx = scope.ctx
    center = None
    if scope.target is not None and scope.target.coord is not None:
        center = scope.target.coord
    elif scope.source is not None:
        center = scope.source.coord
    if center is None:
        return
    duration = args.get("duration")
    expires = None if duration is None else ctx.round_index + int(duration)
    ctx.battlefield.hazards.add(Hazard(
        center=center, radius_ft=args["radius"], damage=args["damage"],
        damage_type=args.get("damage_type", "fire"),
        expires_round=expires, tag=args.get("name", "fire")))


def _grant_temp_hp(args: dict, scope: EffectScope) -> None:
    """Temporary hit points (the Constable's Rally). RAW they never stack: a
    new grant only replaces the current pool if it's larger."""
    amount = scope.ctx.roll(args["amount"]) if isinstance(args["amount"], str) else int(args["amount"])
    if amount > scope.target.temp_hp:
        scope.target.temp_hp = amount


def _reduce_damage(args: dict, scope: EffectScope) -> None:
    """Reaction-only (design doc 04 section 4's `taking_damage` trigger):
    multiply the pending attack's damage by `factor` (0.5 = halve). Writes to
    a `CombatContext` side channel `actions._resolve_attack` reads back before
    dealing — the Thief Rogue's Uncanny Dodge, and (future) the Barbarian's
    Rage resistance, are both exactly this."""
    scope.ctx.reduce_pending_damage(args["factor"])


def _mark_turn(args: dict, scope: EffectScope) -> None:
    """Set a once-per-turn toggle on the acting creature's `turn_scratch`
    (cleared at the start of each of its turns by `system.take_turn`), read
    back by the `turn_marked(key)` expression predicate — the mechanism the
    Thief Rogue's Sneak Attack uses to fire on only its first hit each turn."""
    scope.source.turn_scratch[args["key"]] = True


_DISPATCH: dict[str, Callable[[dict, EffectScope], None]] = {
    "attach_condition": _attach_condition,
    "remove_condition": _remove_condition,
    "require_save": _require_save,
    "set_flag": _set_flag,
    "end_trial": _end_trial,
    "emit_light": _emit_light,
    "limited_darkvision": _limited_darkvision,
    "darkvision_immunity": _darkvision_immunity,
    "redirect_attack": _redirect_attack,
    "swap_positions": _swap_positions,
    "damage_rider": _damage_rider,
    "reduce_damage": _reduce_damage,
    "make_attack": _make_attack,
    "mark_turn": _mark_turn,
    "spend_resource": _spend_resource,
    "grant_temp_hp": _grant_temp_hp,
    "create_hazard": _create_hazard,
    "drain_hit_die": _drain_hit_die,
    "instant_death": _instant_death,
}
