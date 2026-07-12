"""`dnd5e-sim` console entry point (design doc 03 section 6).

Phase 3 scope: `run` and `validate` only. `sweep` (expand `[sweep]`, run
variants, comparison table/chart) is deferred — nothing in `[sweep]` is
consumed yet, so a simulation file that happens to have one just runs its
base configuration. The Python escape-hatch `sys.path` wiring described in
design doc 04 section 5 is Phase 4 (no creature can reference `behavior.custom`
yet — the loader rejects it), but is harmless to set up now.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from simharness.report import print_report, save_charts
from simharness.runner import TrialRunner
from simharness.stats import CompareReport, compare

from .loader import load_creature, load_simulation, load_toml_file
from .system import Dnd5eSystem


def _build_system_and_runner(spec, *, seed=None, trials=None):
    system = Dnd5eSystem(board=spec.board, roster=spec.roster, max_rounds=spec.max_rounds,
                         hp_mode=spec.hp_mode, focus=spec.focus)
    names = [slot.instance_name for slot in spec.roster]
    side_of = {slot.instance_name: slot.side for slot in spec.roster}
    runner = TrialRunner(system, seed=seed if seed is not None else spec.seed,
                         max_rounds=spec.max_rounds, names=names, side_of=side_of)
    return runner, (trials if trials is not None else spec.trials)


def _print_compare_report(report: CompareReport, console: Console) -> None:
    table = Table(title=f"Parity vs baseline: {'PASS' if report.passed else 'FAIL'}")
    # overflow="fold" instead of the rich default ("ellipsis", which renders a
    # Unicode "…" character): the legacy Windows console codepage can't
    # encode it and crashes the whole print (confirmed — same root cause as
    # the "Δ" crash this file used to have in its "Delta" column header).
    table.add_column("Column", justify="left", overflow="fold")
    table.add_column("Kind", justify="left")
    table.add_column("Baseline mean", justify="right")
    table.add_column("New mean", justify="right")
    table.add_column("Delta", justify="right")
    table.add_column("Result", justify="left")
    for col in report.columns:
        delta = f"{col.mean_delta:.1%}" if not col.is_rate else f"{col.mean_delta:.1%}pp"
        table.add_row(col.column, "rate" if col.is_rate else "continuous",
                      f"{col.mean_a:.1f}", f"{col.mean_b:.1f}", delta,
                      "[green]pass[/green]" if col.passed else "[red]FAIL[/red]")
    console.print(table)
    if report.missing_in_a:
        console.print(f"[red]Columns missing from baseline: {report.missing_in_a}[/red]")
    if report.missing_in_b:
        console.print(f"[red]Columns missing from new run: {report.missing_in_b}[/red]")


def _run(args: argparse.Namespace) -> int:
    console = Console()
    spec = load_simulation(args.path)
    runner, trials = _build_system_and_runner(spec, seed=args.seed, trials=args.trials)
    ledger = runner.run(trials=trials)

    sections = tuple(spec.output.get("report", ("totals", "by_combatant")))
    charts = tuple(spec.output.get("charts", ()))
    print_report(ledger, title=spec.name, sections=sections, console=console)
    if charts:
        out_dir = Path(args.out) if args.out else Path(args.path).parent / spec.output.get("dir", "out")
        paths = save_charts(ledger, prefix=spec.name, kinds=charts, out_dir=out_dir)
        for p in paths:
            console.print(f"chart: {p}")

    if args.baseline:
        baseline_rows = json.loads(Path(args.baseline).read_text())
        report = compare(baseline_rows, ledger.rows)
        _print_compare_report(report, console)
        return 0 if report.passed else 1

    return 0


def _classify_and_validate(path: Path) -> None:
    cfg = load_toml_file(path)
    if "map" in cfg:
        from dnd_board import load_board_toml
        load_board_toml(path)
    elif "simulation" in cfg or "combatants" in cfg:
        load_simulation(path)
    elif "stats" in cfg:
        load_creature(path)
    else:
        raise ValueError(
            f"{path}: cannot determine file type "
            f"(expected a top-level 'map' key, '[simulation]'/'[[combatants]]', or '[stats]')"
        )


def _validate(args: argparse.Namespace) -> int:
    path = Path(args.path)
    targets = [path] if path.is_file() else sorted(path.rglob("*.toml"))
    if not targets:
        print(f"no .toml files found under {path}", file=sys.stderr)
        return 1
    failures = 0
    for target in targets:
        try:
            _classify_and_validate(target)
            print(f"OK    {target}")
        except Exception as e:
            failures += 1
            print(f"FAIL  {target}: {e}")
    if failures:
        print(f"\n{failures} failure(s) of {len(targets)}", file=sys.stderr)
        return 1
    print(f"\nall {len(targets)} file(s) valid")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dnd5e-sim")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run a simulation and report results")
    run_p.add_argument("path", help="Path to a simulation.toml")
    run_p.add_argument("--seed", type=int, default=None, help="Override the scenario's seed")
    run_p.add_argument("--trials", type=int, default=None, help="Override the scenario's trial count")
    run_p.add_argument("--out", default=None, help="Override the output directory")
    run_p.add_argument("--baseline", default=None,
                       help="Path to a baseline rows.json; compares and exits nonzero on failure")
    run_p.set_defaults(func=_run)

    validate_p = sub.add_parser("validate", help="Load-time validation only (a file or a directory)")
    validate_p.add_argument("path", help="A creature/board/simulation TOML file, or a directory to scan")
    validate_p.set_defaults(func=_validate)

    return parser


def main(argv: list = None) -> int:
    # Escape-hatch resolution (design doc 04 section 5) isn't reachable yet —
    # no creature can declare behavior.custom until Phase 4 — but adding the
    # cwd is harmless now and saves a Phase 4 change here.
    sys.path.insert(0, str(Path.cwd()))
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
