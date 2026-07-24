"""Exposure-per-round curve for the opera-house fight.

The written scene has a built-in clock: the guards flee roughly one round after
Véronique leaves (≤ start of round 4), so the party's guard-fighting window is
only ~5 rounds — not the 10-18 a raw run wanders into. This report doesn't pick
a single cutoff; it runs the fight capped at each round 3..9 and shows the
party's state *if the guards left at that round*, so you can size the stage
subplot (Nico vs Guy) and the coming fire clock against a real exposure curve.

Columns per cutoff round N:
  party HP spent   — % of the party's combined max HP gone
  >=1 down / dead / TPK — the survival tail (TPK = whole party wiped)
  init down        — of the 18 opening guards, how many are down (mean)
  reinf engaged    — damage the pit reinforcement waves have dealt by round N
                     (the geography tell: ~0 means they never reached the fight)

    uv run --project ../../dnd5e python timeline_report.py
    uv run --project ../../dnd5e python timeline_report.py --trials 1000
"""

from __future__ import annotations

import argparse
import statistics
from pathlib import Path

from rich.console import Console
from rich.table import Table
from simharness.runner import TrialRunner

from dnd5e.loader import build_simulation, load_toml_file
from dnd5e.system import Dnd5eSystem

HERE = Path(__file__).parent
SIMULATION = HERE / "simulation.toml"


def build(cfg: dict):
    spec = build_simulation(cfg, sim_dir=SIMULATION.parent, name_fallback="opera_house")
    names = [s.instance_name for s in spec.roster]
    side_of = {s.instance_name: s.side for s in spec.roster}
    for _r, slots in spec.reinforcements:
        for s in slots:
            names.append(s.instance_name)
            side_of[s.instance_name] = s.side
    party = {s.instance_name: s.statblock.stats.hp_average for s in spec.roster if s.side == "party"}
    initial = [s.instance_name for s in spec.roster
               if s.side == "monsters"]                      # the 18 openers (roster, not waves)
    reinf = [n for n in names if "_r2_" in n or "_r4_" in n]  # the pit waves
    return spec, names, side_of, party, initial, reinf


def run_to(cfg, spec, names, side_of, *, max_rounds: int, trials: int) -> list[dict]:
    system = Dnd5eSystem(board=spec.board, roster=spec.roster, max_rounds=max_rounds,
                         hp_mode=spec.hp_mode, focus=spec.focus, obscurement=spec.obscurement,
                         light_plan=spec.light_plan, reinforcements=spec.reinforcements,
                         extraction=spec.extraction, grapple_escape=spec.grapple_escape,
                         objective=spec.objective, subduing_side=spec.subduing_side)
    runner = TrialRunner(system, seed=spec.seed, max_rounds=max_rounds, names=names, side_of=side_of)
    return runner.run(trials=trials).rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=300)
    args = ap.parse_args()

    console = Console()
    cfg = load_toml_file(SIMULATION)
    spec, names, side_of, party, initial, reinf = build(cfg)
    party_hp = sum(party.values())

    table = Table(title=f"Opera house — party exposure if the guards leave at round N "
                        f"({args.trials} trials, {len(initial)} openers + {len(reinf)} in waves)")
    for col in ("cutoff N", "party HP spent", ">=1 PC down", ">=1 PC dead", "TPK",
                "init down /18", "reinf dmg dealt"):
        table.add_column(col, justify="left" if col == "cutoff N" else "right")

    for n in range(3, 10):
        rows = run_to(cfg, spec, names, side_of, max_rounds=n, trials=args.trials)
        m = lambda k: statistics.mean(r.get(k, 0) for r in rows)
        hp_left = statistics.mean(sum(r.get(f"hp_remaining_{p}", 0) for p in party) for r in rows)
        any_down = 100 * sum(1 for r in rows if any(r.get(f"down_{p}") for p in party)) / len(rows)
        init_down = statistics.mean(sum(r.get(f"down_{g}", 0) for g in initial) for r in rows)
        reinf_dmg = statistics.mean(sum(r.get(f"dealt_{g}", 0) for g in reinf) for r in rows)
        table.add_row(
            f"round {n}",
            f"{100 * (1 - hp_left / party_hp):.0f}%",
            f"{any_down:.1f}%",
            f"{100 * m('any_dead_party'):.1f}%",
            f"{100 * m('wiped_party'):.1f}%",
            f"{init_down:.1f}",
            f"{reinf_dmg:.0f}",
        )
    console.print(table)
    console.print("[dim]TPK = whole party wiped (the failure state). 'reinf dmg dealt' ~0 means "
                  "the pit waves never reached the melee within N rounds.[/dim]")


if __name__ == "__main__":
    main()
