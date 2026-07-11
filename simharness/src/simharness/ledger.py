"""Generic per-trial event ledger.

Lifted from `dnd5e_combat.ledger.DamageLedger` with the 5e-specific assumption
removed: instead of a fixed `sides: dict[str, str]`, a `Ledger` takes the
universe of participant `names` (so every trial's row has a uniform set of
`dealt_*`/`taken_*` columns even for a participant with zero events) plus a
`side_of` lookup (callable or mapping) used only to roll `dealt_*` up into
`side_dealt_<side>` totals. Column names and their meaning (damage? healing?
resource spend?) are entirely up to the game system — the ledger just sums
whatever `amount` is recorded per (source, target, tag) triple.

`dnd5e_combat.ledger.DamageLedger` also carried a cumulative `by_attack`
breakdown and an `attack_means()` method; grepping the old codebase shows
neither is read anywhere, so this rewrite drops that dead surface.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Mapping, Optional, Union


class Ledger:
    """Records every (source, target, tag) event so a report can slice by
    dealer, receiver, side, or event tag. Per-trial totals are snapshotted
    into `rows` (one dict per trial) via `finalize_trial`."""

    def __init__(self, names: list[str], side_of: Union[Callable[[str], str], Mapping[str, str]]) -> None:
        self.names = list(names)
        self.side_of: Callable[[str], str] = (
            side_of.__getitem__ if isinstance(side_of, Mapping) else side_of
        )
        self.rows: list[dict] = []
        self._trial: dict[tuple[str, str, str], float] = defaultdict(float)

    def record(self, source: str, target: str, tag: str, amount: float,
               kind: Optional[str] = None) -> None:
        """Record one quantity event (damage, healing, resource spend — the
        game decides what `tag`/`kind` mean). Non-positive amounts are no-ops,
        so callers don't need to guard a miss/zero-heal themselves. `kind` is
        accepted for the game system's own use (e.g. damage type) but is not
        broken out into separate columns in v1 — nothing downstream consumes
        it yet; add a breakdown here if and when something does."""
        if amount <= 0:
            return
        self._trial[(source, target, tag)] += amount

    def finalize_trial(self, outcome: Optional[dict] = None) -> None:
        """Snapshot this trial's accumulated events into one row and reset for
        the next trial. `outcome` carries per-trial facts the ledger can't
        derive from events alone (HP remaining, wiped/dead flags, ...) —
        supplied by the game system, merged into the row as-is, and allowed to
        overwrite a same-named ledger column (the game's own accounting wins)."""
        dealt: dict[str, float] = defaultdict(float)
        taken: dict[str, float] = defaultdict(float)
        # Seed every known side at 0 so a shut-out trial still emits a uniform row.
        side_dealt: dict[str, float] = {self.side_of(n): 0.0 for n in self.names}
        for (source, target, _tag), amount in self._trial.items():
            dealt[source] += amount
            taken[target] += amount
            side_dealt[self.side_of(source)] += amount

        row: dict = {}
        for name in self.names:
            row[f"dealt_{name}"] = dealt.get(name, 0)
            row[f"taken_{name}"] = taken.get(name, 0)
        for side, total in side_dealt.items():
            row[f"side_dealt_{side}"] = total
        if outcome:
            row.update(outcome)
        self.rows.append(row)
        self._trial.clear()

    def combatants_on(self, side: str) -> list[str]:
        return [name for name in self.names if self.side_of(name) == side]
