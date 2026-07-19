"""Parity check for sims/otyugh_shadow_solo against its Phase 0 baseline.
Same column-renaming approach as the other otyugh parity scripts.
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table
from simharness.stats import compare

from dnd5e.cli import _build_system_and_runner
from dnd5e.loader import load_simulation

RENAME = {
    "fighter": "champion_fighter", "ranger": "hunter_ranger", "rogue": "thief_rogue",
    "cleric": "life_cleric", "wizard": "evoker_wizard",
}


def rename_columns(rows: list[dict]) -> list[dict]:
    renamed = []
    for row in rows:
        new_row = {}
        for key, value in row.items():
            new_key = key
            for old, new in RENAME.items():
                if key.endswith(f"_{old}"):
                    new_key = key[: -len(old)] + new
                    break
            new_row[new_key] = value
        renamed.append(new_row)
    return renamed


def main() -> int:
    sim_dir = Path(__file__).parent.parent / "sims" / "otyugh_shadow_solo"
    meta = json.loads((sim_dir / "baseline" / "meta.json").read_text())
    baseline_rows = json.loads((sim_dir / "baseline" / "rows.json").read_text())
    baseline_rows = rename_columns(baseline_rows)

    spec = load_simulation(sim_dir / "simulation.toml")
    runner, trials = _build_system_and_runner(spec, seed=meta["seed"], trials=meta["trials"])
    ledger = runner.run(trials=trials)

    report = compare(baseline_rows, ledger.rows)

    console = Console()
    table = Table(title=f"otyugh_shadow_solo parity vs baseline: {'PASS' if report.passed else 'FAIL'}")
    table.add_column("Column", overflow="fold")
    table.add_column("Kind")
    table.add_column("Baseline mean", justify="right")
    table.add_column("New mean", justify="right")
    table.add_column("Mean delta", justify="right")
    table.add_column("Result")
    for col in sorted(report.columns, key=lambda c: c.column):
        delta = f"{col.mean_delta:.1%}" if not col.is_rate else f"{col.mean_delta:.1%}pp"
        table.add_row(col.column, "rate" if col.is_rate else "continuous",
                      f"{col.mean_a:.2f}", f"{col.mean_b:.2f}", delta,
                      "pass" if col.passed else "FAIL")
    console.print(table)
    if report.missing_in_a:
        console.print(f"[red]Columns missing from baseline: {report.missing_in_a}[/red]")
    if report.missing_in_b:
        console.print(f"[red]Columns missing from new run: {report.missing_in_b}[/red]")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
