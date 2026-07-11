"""Parameter sweeps: expand a `[sweep]` config block into cartesian-product
variants, run each, and compare results. Replaces the copy-pasted sweep/
comparison scripts (`masks/scaling.py`, `otyugh_cr5_compare`,
`otyugh_cr5_monk`) with one generic mechanism — see design doc 02 §6.
"""

from __future__ import annotations

import copy
import itertools
import statistics
from pathlib import Path
from types import ModuleType
from typing import Callable

from rich.console import Console
from rich.table import Table

from .config import set_path
from .ledger import Ledger


def expand(cfg: dict) -> list[tuple[str, dict]]:
    """Cartesian product of `cfg["sweep"]["axes"]` (each `{target, values}`,
    `target` a dotted string path per `config.set_path`). No `[sweep]` block
    (or an empty `axes` list) yields the single unmodified config, labeled
    `"base"`, so callers can treat every simulation as a one-variant sweep."""
    axes = cfg.get("sweep", {}).get("axes", [])
    if not axes:
        return [("base", copy.deepcopy(cfg))]

    targets = [axis["target"] for axis in axes]
    value_lists = [axis["values"] for axis in axes]

    variants: list[tuple[str, dict]] = []
    for combo in itertools.product(*value_lists):
        variant_cfg = copy.deepcopy(cfg)
        parts = []
        for target, value in zip(targets, combo):
            set_path(variant_cfg, target, value)
            parts.append(f"{target}={value}")
        variants.append((", ".join(parts), variant_cfg))
    return variants


def run(variants: list[tuple[str, dict]], run_fn: Callable[[dict], Ledger]) -> dict[str, Ledger]:
    """Execute `run_fn(cfg)` for every sweep variant, keyed by label (insertion
    order preserved, so a caller iterating the result sees variants in the
    same order `expand()` produced them)."""
    return {label: run_fn(cfg) for label, cfg in variants}


def comparison_table(ledgers: dict[str, Ledger], columns: list[str], *,
                      title: str = "Sweep comparison", console: Console | None = None) -> None:
    """One row per variant, one column per requested metric, each cell the
    mean of that ledger column across the variant's trials."""
    console = console or Console()
    table = Table(title=title)
    table.add_column("Variant", justify="left")
    for col in columns:
        table.add_column(col, justify="right")
    for label, ledger in ledgers.items():
        row = [label]
        for col in columns:
            values = [r.get(col, 0) for r in ledger.rows]
            row.append(f"{statistics.mean(values):.1f}" if values else "-")
        table.add_row(*row)
    console.print(table)


_MATPLOTLIB_READY = False


def _agg_pyplot() -> ModuleType:
    global _MATPLOTLIB_READY
    import matplotlib
    if not _MATPLOTLIB_READY:
        matplotlib.use("Agg")
        _MATPLOTLIB_READY = True
    import matplotlib.pyplot as plt
    return plt


def comparison_chart(ledgers: dict[str, Ledger], columns: list[str], *, path: str | Path,
                      title: str = "Sweep comparison", ylabel: str = "Mean per trial") -> str:
    """Grouped bar chart: one group per variant, one bar per requested column."""
    plt = _agg_pyplot()
    labels = list(ledgers)
    n_cols = len(columns)
    width = 0.8 / max(n_cols, 1)
    x = range(len(labels))
    fig, ax = plt.subplots(figsize=(max(6, len(labels) * 1.5), 5))
    for i, col in enumerate(columns):
        means = []
        for label in labels:
            values = [r.get(col, 0) for r in ledgers[label].rows]
            means.append(statistics.mean(values) if values else 0)
        offset = (i - (n_cols - 1) / 2) * width
        ax.bar([xi + offset for xi in x], means, width, label=col)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend()
    fig.tight_layout()
    path = str(path)
    fig.savefig(path)
    plt.close(fig)
    return path
