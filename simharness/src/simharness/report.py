"""Rich-table report sections and matplotlib chart kinds, both name-registered.

`simharness` ships only the sections/charts that need nothing but the generic
`dealt_<name>`/`taken_<name>`/`side_dealt_<side>` columns every `Ledger`
always has: `totals`, `by_combatant`, and three chart kinds. Anything that
reads game-specific outcome columns (e.g. a `survival` section reading
`wiped_*`/`dead_*`) is registered by the game system itself at import time via
`register_section`/`register_chart` — see design doc 02 §6. Lifted from
`dnd5e_combat/report.py`, split into independently-selectable sections instead
of one fixed table.
"""

from __future__ import annotations

import statistics
from pathlib import Path
from types import ModuleType
from typing import Callable, Optional

from rich.console import Console
from rich.table import Table

from .ledger import Ledger

SectionFn = Callable[[Ledger, str, Console], None]
ChartFn = Callable[[Ledger, str, Path], str]

_SECTIONS: dict[str, SectionFn] = {}
_CHARTS: dict[str, ChartFn] = {}


def register_section(name: str, fn: SectionFn) -> None:
    _SECTIONS[name] = fn


def register_chart(name: str, fn: ChartFn) -> None:
    _CHARTS[name] = fn


def _sides(ledger: Ledger) -> list[str]:
    return sorted({ledger.side_of(n) for n in ledger.names})


def _add_stat_row(table: Table, rows: list[dict], label: str, key: str) -> None:
    values = [r.get(key, 0) for r in rows]
    table.add_row(label, f"{statistics.mean(values):.1f}", f"{statistics.median(values):.1f}",
                  str(min(values)), str(max(values)))


def _section_totals(ledger: Ledger, title: str, console: Console) -> None:
    rows = ledger.rows
    table = Table(title=f"{title} - totals ({len(rows)} trials)")
    for col, justify in (("Metric", "left"), ("Mean", "right"), ("Median", "right"),
                         ("Min", "right"), ("Max", "right")):
        table.add_column(col, justify=justify)
    for side in _sides(ledger):
        _add_stat_row(table, rows, f"Total dealt by {side}", f"side_dealt_{side}")
    console.print(table)


def _section_by_combatant(ledger: Ledger, title: str, console: Console) -> None:
    rows = ledger.rows
    table = Table(title=f"{title} - by combatant ({len(rows)} trials)")
    for col, justify in (("Metric", "left"), ("Mean", "right"), ("Median", "right"),
                         ("Min", "right"), ("Max", "right")):
        table.add_column(col, justify=justify)
    for side in _sides(ledger):
        for name in ledger.combatants_on(side):
            _add_stat_row(table, rows, f"  dealt by {name}", f"dealt_{name}")
    for side in _sides(ledger):
        for name in ledger.combatants_on(side):
            _add_stat_row(table, rows, f"  taken by {name}", f"taken_{name}")
    console.print(table)


register_section("totals", _section_totals)
register_section("by_combatant", _section_by_combatant)


def print_report(ledger: Ledger, *, title: str,
                  sections: tuple[str, ...] = ("totals", "by_combatant"),
                  console: Optional[Console] = None) -> None:
    if not ledger.rows:
        raise ValueError("cannot report on a ledger with no finalized trials")
    console = console or Console()
    for name in sections:
        if name not in _SECTIONS:
            raise KeyError(f"no report section registered as {name!r}; "
                           f"registered: {sorted(_SECTIONS)}")
        _SECTIONS[name](ledger, title, console)


_MATPLOTLIB_READY = False


def _ensure_matplotlib_agg() -> ModuleType:
    global _MATPLOTLIB_READY
    import matplotlib
    if not _MATPLOTLIB_READY:
        matplotlib.use("Agg")
        _MATPLOTLIB_READY = True
    import matplotlib.pyplot as plt
    return plt


def _chart_totals_hist(ledger: Ledger, prefix: str, out_dir: Path) -> str:
    plt = _ensure_matplotlib_agg()
    rows = ledger.rows
    fig, ax = plt.subplots(figsize=(10, 5))
    for side in _sides(ledger):
        ax.hist([r.get(f"side_dealt_{side}", 0) for r in rows], bins=20, alpha=0.6, label=side)
    ax.set_title("Total dealt per trial, by side")
    ax.set_xlabel("Amount")
    ax.set_ylabel("Trials")
    ax.legend()
    fig.tight_layout()
    path = str(out_dir / f"{prefix}_totals_hist.png")
    fig.savefig(path)
    plt.close(fig)
    return path


def _bar_chart_by_combatant(ledger: Ledger, prefix: str, out_dir: Path, *,
                             metric: str, color: str) -> str:
    plt = _ensure_matplotlib_agg()
    rows = ledger.rows
    names = list(ledger.names)
    means = [statistics.mean(r.get(f"{metric}_{n}", 0) for r in rows) for n in names]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(names, means, color=color)
    ax.set_title(f"Average {metric} per combatant")
    ax.set_ylabel("Average per trial")
    ax.tick_params(axis="x", rotation=30)
    fig.tight_layout()
    path = str(out_dir / f"{prefix}_{metric}_by_combatant.png")
    fig.savefig(path)
    plt.close(fig)
    return path


register_chart("totals_hist", _chart_totals_hist)
register_chart("dealt_by_combatant", lambda l, p, o: _bar_chart_by_combatant(l, p, o, metric="dealt", color="darkorange"))
register_chart("taken_by_combatant", lambda l, p, o: _bar_chart_by_combatant(l, p, o, metric="taken", color="slategray"))


def save_charts(ledger: Ledger, *, prefix: str,
                 kinds: tuple[str, ...] = ("totals_hist", "dealt_by_combatant", "taken_by_combatant"),
                 out_dir: str | Path = ".") -> list[str]:
    if not ledger.rows:
        raise ValueError("cannot chart a ledger with no finalized trials")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    for kind in kinds:
        if kind not in _CHARTS:
            raise KeyError(f"no chart kind registered as {kind!r}; registered: {sorted(_CHARTS)}")
        saved.append(_CHARTS[kind](ledger, prefix, out_dir))
    return saved
