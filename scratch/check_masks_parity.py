"""Parity check for sims/masks's 6 sweep variants (2 parties x 3 focus
strategies) against their Phase 0 baselines (sims/masks/<variant>/baseline/).
Same column-renaming approach as check_otyugh_cr5_compare_parity.py.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from simharness.stats import compare

from dnd5e.cli import _build_system_and_runner
from dnd5e.loader import build_simulation, load_toml_file
from simharness import sweep as sweep_mod

RENAME = {
    "fighter": "champion_fighter", "ranger": "hunter_ranger", "rogue": "thief_rogue",
    "cleric": "life_cleric", "wizard": "evoker_wizard",
    "bruiser": "masked_bruiser", "hector_a": "masked_hector_1", "hector_b": "masked_hector_2",
    "poet_a": "masked_poet_1", "poet_b": "masked_poet_2",
}

# `[[sweep.axes]]` order in simulation.toml (overrides outer, environment.focus
# inner) matches this exactly — see network_value_report.py's own note.
BASELINE_DIRS = [
    "adventurers_natural", "adventurers_break_generator", "adventurers_break_mark",
    "beaumont_playtest_natural", "beaumont_playtest_break_generator", "beaumont_playtest_break_mark",
]


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


def check_variant(sim_dir: Path, ledger_rows: list[dict], baseline_subdir: str, console: Console) -> bool:
    baseline_rows = json.loads((sim_dir / baseline_subdir / "baseline" / "rows.json").read_text())
    baseline_rows = rename_columns(baseline_rows, RENAME)
    report = compare(baseline_rows, ledger_rows)

    table = Table(title=f"masks/{baseline_subdir} parity: {'PASS' if report.passed else 'FAIL'}")
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


def main(trials_override: int = None) -> int:
    sim_dir = Path(__file__).parent.parent / "sims" / "masks"
    cfg = load_toml_file(sim_dir / "simulation.toml")
    variants = sweep_mod.expand(cfg)

    console = Console()
    all_passed = True
    for (label, variant_cfg), baseline_subdir in zip(variants, BASELINE_DIRS):
        meta = json.loads((sim_dir / baseline_subdir / "baseline" / "meta.json").read_text())
        spec = build_simulation(variant_cfg, sim_dir=sim_dir, name_fallback=sim_dir.name)
        trials = trials_override if trials_override is not None else meta["trials"]
        runner, trials = _build_system_and_runner(spec, seed=meta["seed"], trials=trials)
        console.print(f"Running {baseline_subdir} ({trials} trials)...")
        ledger = runner.run(trials=trials)
        passed = check_variant(sim_dir, ledger.rows, baseline_subdir, console)
        all_passed = all_passed and passed

    return 0 if all_passed else 1


if __name__ == "__main__":
    override = int(sys.argv[1]) if len(sys.argv) > 1 else None
    raise SystemExit(main(override))
