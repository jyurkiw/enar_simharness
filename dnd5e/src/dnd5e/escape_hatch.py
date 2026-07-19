"""Resolves `behavior.custom = "python:module.Class"` handler strings into
instantiated `Behavior` handlers (design doc 04 section 5) — for behavior the
declarative `when`/`target_filter` language genuinely can't express. The CLI
adds the sim directory to `sys.path` (`cli.py`'s `main()`), so a sim-local
`behavior.py` (or `escape_hatch.py`, named whatever — this module has no
opinion) resolves the same as an installed package.
"""

from __future__ import annotations

import importlib
from typing import Optional, Protocol, runtime_checkable

from .creature import Creature
from .statblock import Ability


@runtime_checkable
class Behavior(Protocol):
    """A `behavior.custom` class implements this. Every hook may return
    `None` to fall through to the declarative rules — a hatch class
    typically overrides one hook, not all three (design doc 04 section 5's
    "20 lines, not a policy rewrite"). `view` is a `behavior.ConcreteScope`:
    the same queries the expression functions use, plus `view.eval(expr)`.
    `react` (reaction hooks) isn't part of this yet — Phase 5, no trigger bus."""

    def choose_multiattack(self, me: Creature, view) -> Optional[str]:
        """Return a `[multiattack.<name>]` key to force that option, or None
        to let the declarative selection algorithm (design doc 04 section 2)
        decide."""
        ...

    def choose_target(self, me: Creature, ability: Ability, pool: list, view) -> Optional[Creature]:
        """Return one creature from `pool` (already filtered/ordered by the
        declarative pipeline, design doc 04 section 3) to force it to the
        front, or None to keep the declarative order as-is."""
        ...

    def plan_movement(self, me: Creature, view) -> Optional[tuple]:
        """Return an explicit `(x, y)` destination cell to move toward this
        action (via `movement.move_to_cell`), or None to use the creature's
        named `behavior.tactic` as usual."""
        ...


# Handler instances are cached by their exact `"python:..."` string so every
# creature sharing one `behavior.custom` value (and every trial of a run)
# shares one instance — hatch classes are expected to be stateless (any
# per-creature state belongs on `Creature.trial_scratch`, not the handler).
_CACHE: dict[str, object] = {}


def resolve(handler: str) -> object:
    if handler in _CACHE:
        return _CACHE[handler]
    if not handler.startswith("python:"):
        raise ValueError(f"escape-hatch handler must start with 'python:', got {handler!r}")
    dotted = handler[len("python:"):]
    module_path, sep, class_name = dotted.rpartition(".")
    if not sep:
        raise ValueError(f"escape-hatch handler {handler!r}: expected 'module.ClassName'")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    instance = cls()
    _CACHE[handler] = instance
    return instance


def clear_cache() -> None:
    """Process-wide cache reset — call between test runs (or CLI
    invocations) that reuse a handler's dotted name for a differently
    behaved class, so a stale instance is never returned."""
    _CACHE.clear()
