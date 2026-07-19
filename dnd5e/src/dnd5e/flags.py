"""The round/trial signal bag behind `set_flag`/`has_flag` (design doc 03
section 4, design doc 04's function registry). A single small,
dependency-free class so `actions.py` (writes, via the `set_flag` effect),
`behavior.py` (reads, via `has_flag()` in expressions), and `system.py`
(owns the round/trial lifecycle that clears it) can all depend on it without
any of them depending on each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FlagBag:
    round_flags: set = field(default_factory=set)
    trial_flags: set = field(default_factory=set)

    def set(self, name: str, *, scope: str) -> None:
        if scope == "round":
            self.round_flags.add(name)
        elif scope == "trial":
            self.trial_flags.add(name)
        else:
            raise ValueError(f"unknown flag scope {scope!r} (must be 'round' or 'trial')")

    def has(self, name: str) -> bool:
        return name in self.round_flags or name in self.trial_flags

    def clear_round(self) -> None:
        self.round_flags.clear()

    def clear_all(self) -> None:
        self.round_flags.clear()
        self.trial_flags.clear()
