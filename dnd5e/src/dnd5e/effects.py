"""The effect-primitive registry (design doc 03 section 4) — closed vocabulary,
validated at load time, dispatched at resolution time.

**Phase 3 scope is intentionally a small subset** of doc 03's full 17-primitive
table: only what board_demo's creatures and a Phase-3-simplified Otyugh
actually use — `attach_condition`, `remove_condition`, `require_save`. Every
one of them is an "action"-context effect (legal inside an ability's
`on_hit`/`on_fail`/`on_crit`/`on_all_saved` list). "Grant"-context effects
(`grant_advantage_against`, `impose_disadvantage_except_source`, ...), which
only make sense inside a custom condition's `grants` list, have no members
yet because custom conditions (`[conditions.*]`) are Phase 5. Growing this
registry is a deliberate change: add the primitive, its dispatch function,
and a test — never call an unregistered name silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from .statblock import EffectCall

if TYPE_CHECKING:
    from .creature import Creature

ACTION_EFFECTS = frozenset({"attach_condition", "remove_condition", "require_save"})
# Grant-context effects only apply inside a condition's `grants` list or a
# trait's `effects` — none exist until Phase 5's custom conditions.
GRANT_EFFECTS: frozenset = frozenset()

ALL_EFFECTS = ACTION_EFFECTS | GRANT_EFFECTS


@dataclass
class EffectScope:
    """What an effect function needs to act: the resolution API (duck-typed
    here as `Any` to avoid a circular import with actions.py, which is the
    only real implementation) plus the source and target creatures."""

    ctx: Any
    source: "Creature"
    target: "Creature"


def validate_effect_name(name: str, *, where: str) -> None:
    if name not in ALL_EFFECTS:
        raise ValueError(f"{where}: unknown effect {name!r}; known effects: {sorted(ALL_EFFECTS)}")


def apply_effect(call: EffectCall, scope: EffectScope) -> None:
    fn = _DISPATCH.get(call.effect)
    if fn is None:
        raise ValueError(f"unknown effect {call.effect!r} (not caught at load time?)")
    fn(call.args, scope)


def apply_effects(calls: tuple[EffectCall, ...], scope: EffectScope) -> None:
    for call in calls:
        apply_effect(call, scope)


def _attach_condition(args: dict, scope: EffectScope) -> None:
    scope.ctx.apply_condition(scope.target, args["condition"], source=scope.source,
                              escape_dc=args.get("escape_dc"))


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


_DISPATCH: dict[str, Callable[[dict, EffectScope], None]] = {
    "attach_condition": _attach_condition,
    "remove_condition": _remove_condition,
    "require_save": _require_save,
}
