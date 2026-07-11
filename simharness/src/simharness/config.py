"""TOML loading and small config-manipulation helpers shared by every game system.

Nothing here is D&D-specific: `deep_merge` is the override mechanism creature/
simulation files use (lifted from `dnd5e_combat.loader.deep_merge`); `get_path`/
`set_path` operate on dotted STRING paths (distinct from TOML's own dotted-key
syntax, which tomllib already resolves into nested dicts at parse time) and back
the sweep engine's `target = "overrides.otyugh.stats.hp"` axes; `require_keys`/
`closed_vocab` are the validation primitives every load-time schema check in a
game system's loader should use, so error messages are consistent.
"""

from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any, Iterable


def load_toml(path: str | Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def deep_merge(base: dict, override: dict) -> dict:
    """Merge `override` onto a deep copy of `base`. Nested tables merge
    recursively (so an override can tweak one field of one action); everything
    else — including lists — is replaced wholesale."""
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def get_path(d: dict, path: str) -> Any:
    """Look up a dotted string path (`"a.b.c"`) in a nested dict. Raises KeyError
    naming the exact segment that was missing, not just the whole path."""
    parts = path.split(".")
    cur: Any = d
    for i, part in enumerate(parts):
        if not isinstance(cur, dict) or part not in cur:
            seen = ".".join(parts[: i + 1])
            raise KeyError(f"path {path!r} not found (missing {seen!r})")
        cur = cur[part]
    return cur


def set_path(d: dict, path: str, value: Any) -> None:
    """Set a dotted string path (`"a.b.c"`) in a nested dict, creating
    intermediate tables as needed. Mutates `d` in place."""
    parts = path.split(".")
    cur = d
    for part in parts[:-1]:
        nxt = cur.setdefault(part, {})
        if not isinstance(nxt, dict):
            raise TypeError(
                f"cannot descend into {part!r} while setting {path!r}: "
                f"existing value is {type(nxt).__name__}, not a table"
            )
        cur = nxt
    cur[parts[-1]] = value


def require_keys(d: dict, keys: Iterable[str], where: str) -> None:
    """Raise ValueError listing every missing key at once, not just the first."""
    missing = [k for k in keys if k not in d]
    if missing:
        raise ValueError(f"{where}: missing required key(s) {missing}")


def closed_vocab(value: Any, allowed: Iterable[str], where: str) -> None:
    """Raise ValueError if `value` is not one of `allowed`, naming both the
    offending value and the full allowed set so a typo is obvious at load time."""
    allowed = tuple(allowed)
    if value not in allowed:
        raise ValueError(f"{where}: {value!r} is not one of {allowed}")
