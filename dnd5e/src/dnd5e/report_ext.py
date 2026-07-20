"""Game-specific report sections registered by the dnd5e engine (design doc 02
section 6: sections that read outcome columns only this game emits register from
the game side, not from the game-agnostic `simharness.report`).

`survival` is the one that answers "how did the fight actually go" — wipe rates,
casualties, and per-combatant down/dead rates — which the generic damage-totals
sections don't show. Imported for its side effect (registration) by `cli.py`.
"""

from __future__ import annotations

import statistics

from rich.console import Console
from rich.table import Table
from simharness.ledger import Ledger
from simharness.report import register_section


def _rate(rows: list[dict], key: str) -> float:
    return statistics.mean(r.get(key, 0) for r in rows) if rows else 0.0


def _section_survival(ledger: Ledger, title: str, console: Console) -> None:
    rows = ledger.rows
    sides = sorted({ledger.side_of(n) for n in ledger.names})
    table = Table(title=f"{title} - survival ({len(rows)} trials)")
    table.add_column("Outcome", justify="left")
    table.add_column("Rate", justify="right")
    for side in sides:
        table.add_row(f"{side}: whole side wiped", f"{_rate(rows, f'wiped_{side}'):.1%}")
        table.add_row(f"{side}: at least one death", f"{_rate(rows, f'any_dead_{side}'):.1%}")
        for name in ledger.combatants_on(side):
            table.add_row(f"    {name} — down / dead (trial end)",
                          f"{_rate(rows, f'down_{name}'):.1%} / {_rate(rows, f'dead_{name}'):.1%}")
    console.print(table)


register_section("survival", _section_survival)
