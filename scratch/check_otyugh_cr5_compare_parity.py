"""Parity check for sims/otyugh_cr5_compare's two sweep variants against
their respective Phase 0 baselines (standard/ and vanguard/ subdirs). Same
column-renaming approach as the dps/x2 scripts.
"""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console
from rich.table import Table
from simharness.stats import compare

from dnd5e.cli import _build_system_and_runner
from dnd5e.loader import build_simulation, load_toml_file
from simharness import sweep as sweep_mod

STANDARD_RENAME = {
    "fighter": "champion_fighter", "ranger": "hunter_ranger", "rogue": "thief_rogue",
    "cleric": "life_cleric", "wizard": "evoker_wizard",
}
VANGUARD_RENAME = {
    "barbarian": "berserker_barbarian", "paladin": "devotion_paladin", "monk": "martial_arts_monk",
    "cleric": "life_cleric", "wizard": "evoker_wizard",
}


def rename_columns(rows: list[dict], rename: dict) -> list[dict]:
    renamed = []
    for row in rows:
        new_row = {}
        for key, value in row.items():
            new_key = key
            for old, new in rename.items():
                if key.endswith(f"_{old}"):
                    new_key = key[: -len(old)] + new
                    break
            new_row[new_key] = value
        renamed.append(new_row)
    return renamed


def check_variant(sim_dir: Path, ledger_rows: list[dict], baseline_subdir: str, rename: dict,
                  console: Console) -> bool:
    baseline_rows = json.loads((sim_dir / baseline_subdir / "baseline" / "rows.json").read_text())
    baseline_rows = rename_columns(baseline_rows, rename)
    report = compare(baseline_rows, ledger_rows)

    table = Table(title=f"otyugh_cr5_compare/{baseline_subdir} parity: {'PASS' if report.passed else 'FAIL'}")
    table.add_column("Column", overflow="fold")
    table.add_column("Baseline mean", justify="right")
    table.add_column("New mean", justify="right")
    table.add_column("Mean delta", justify="right")
    table.add_column("Result")
    for col in sorted(report.columns, key=lambda c: c.column):
        delta = f"{col.mean_delta:.1%}" if not col.is_rate else f"{col.mean_delta:.1%}pp"
        table.add_row(col.column, f"{col.mean_a:.2f}", f"{col.mean_b:.2f}", delta,
                      "pass" if col.passed else "FAIL")
    console.print(table)
    return report.passed


def main() -> int:
    sim_dir = Path(__file__).parent.parent / "sims" / "otyugh_cr5_compare"
    cfg = load_toml_file(sim_dir / "simulation.toml")
    variants = sweep_mod.expand(cfg)

    console = Console()
    all_passed = True
    for (label, variant_cfg), baseline_subdir, rename in zip(
        variants, ("standard", "vanguard"), (STANDARD_RENAME, VANGUARD_RENAME)
    ):
        meta = json.loads((sim_dir / baseline_subdir / "baseline" / "meta.json").read_text())
        spec = build_simulation(variant_cfg, sim_dir=sim_dir, name_fallback=sim_dir.name)
        runner, trials = _build_system_and_runner(spec, seed=meta["seed"], trials=meta["trials"])
        ledger = runner.run(trials=trials)
        passed = check_variant(sim_dir, ledger.rows, baseline_subdir, rename, console)
        all_passed = all_passed and passed

    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
