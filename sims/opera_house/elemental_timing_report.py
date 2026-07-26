"""When should the Pyre Elemental turn from scenery into a monster?

Sweeps `attack_round` — the round the fire stops merely burning and starts
dropping debris / using legendary actions — against the phase-1 guard fight.

The hypothesis being tested (Jeff's): **pushing the elemental back makes life
WORSE for the PCs**, because reaching the stage was already a 0% proposition and
the elemental is the only thing that hurts the guards. Delay it and the guards
get uninterrupted rounds to grind the party down; bring it in early and it
shreds the guard ranks too.

Reports, per attack_round: whether anyone reaches the stage, how the party ends
up (subdued cleanly / dying / dead), and — the crux — how many GUARDS the
elemental takes with it.

    uv run --project ../../dnd5e python elemental_timing_report.py
    uv run --project ../../dnd5e python elemental_timing_report.py --trials 300
"""

from __future__ import annotations

import argparse
import copy
import statistics
from pathlib import Path

from rich.console import Console
from rich.table import Table
from simharness.ledger import Ledger
from simharness.runner import TrialRunner

from dnd5e.loader import build_simulation, load_toml_file
from dnd5e.system import Dnd5eSystem

HERE = Path(__file__).parent
SIMULATION = HERE / "simulation.toml"
FIRE_TAGS = {"fire", "debris", "enflame"}


def run(cfg: dict, trials: int):
    spec = build_simulation(cfg, sim_dir=SIMULATION.parent, name_fallback="opera_house")
    party = {s.instance_name for s in spec.roster if s.side == "party"}
    names = [s.instance_name for s in spec.roster]
    side_of = {s.instance_name: s.side for s in spec.roster}
    for _r, slots in spec.reinforcements:
        for s in slots:
            names.append(s.instance_name)
            side_of[s.instance_name] = s.side

    system = Dnd5eSystem(board=spec.board, roster=spec.roster, max_rounds=spec.max_rounds,
                         hp_mode=spec.hp_mode, focus=spec.focus, obscurement=spec.obscurement,
                         light_plan=spec.light_plan, reinforcements=spec.reinforcements,
                         extraction=spec.extraction, grapple_escape=spec.grapple_escape,
                         objective=spec.objective, subduing_side=spec.subduing_side,
                         hazard_actors=spec.hazard_actors, hit_dice_spent=spec.hit_dice_spent,
                         wake_up=spec.wake_up, initial_hazards=spec.initial_hazards)

    tags: dict = {}
    orig = Ledger.record

    def record(self, source, target, tag, amount, kind=None):
        if amount > 0 and target in party:
            tags[tag] = tags.get(tag, 0) + amount
        return orig(self, source, target, tag, amount, kind)

    ends: list[dict] = []

    def snapshot(ctx):
        g = ctx.game
        pcs = [g.creatures[p] for p in party if p in g.creatures]
        guards = g.battlefield.members("monsters")
        ends.append({
            "conscious": sum(1 for p in pcs if not p.is_down),
            "stable": sum(1 for p in pcs if p.is_down and p.is_stabilized and not p.is_dead),
            "dying": sum(1 for p in pcs if p.is_down and not p.is_stabilized and not p.is_dead),
            "dead": sum(1 for p in pcs if p.is_dead),
            "guards_down": sum(1 for c in guards if c.is_down),
            "guards": len(guards),
            "min_y": min((p.y for p in pcs if p.coord is not None), default=99),
        })

    Ledger.record = record
    try:
        runner = TrialRunner(system, seed=spec.seed, max_rounds=spec.max_rounds,
                             names=names, side_of=side_of, on_trial_end=snapshot)
        rows = runner.run(trials=trials).rows
    finally:
        Ledger.record = orig
    return rows, ends, tags, party


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=150)
    ap.add_argument("--rounds", type=int, nargs="*",
                    default=[2, 4, 6, 8, 10, 99],
                    help="attack_round values to sweep (99 = never attacks)")
    args = ap.parse_args()

    console = Console()
    base = load_toml_file(SIMULATION)

    table = Table(title=f"When should the elemental start attacking? ({args.trials} trials each)")
    for col in ("attack_round", "rounds", "reached stage", "PC dies", "clean subdual",
                "mean PCs dead", "GUARDS down", "fire dmg to PCs", "closest PC to stage"):
        table.add_column(col, justify="left" if col == "attack_round" else "right")

    for ar in args.rounds:
        cfg = copy.deepcopy(base)
        cfg["hazard_actors"][0]["attack_round"] = ar
        label = "never" if ar >= 99 else f"round {ar}"
        console.print(f"Running attack_round = {label}...")
        rows, ends, tags, party = run(cfg, args.trials)
        n = len(rows)
        mean = lambda k: statistics.mean(r.get(k, 0) for r in rows)
        fire = sum(v for k, v in tags.items() if k in FIRE_TAGS) / n
        table.add_row(
            label,
            f"{mean('rounds'):.1f}",
            f"{100 * sum(1 for r in rows if r.get('reached_stage')) / n:.0f}%",
            f"{100 * sum(1 for e in ends if e['dead'] >= 1) / n:.0f}%",
            f"{100 * sum(1 for e in ends if e['conscious'] == 0 and e['dead'] == 0 and e['dying'] == 0) / n:.0f}%",
            f"{statistics.mean(e['dead'] for e in ends):.2f}",
            f"{statistics.mean(e['guards_down'] for e in ends):.1f}"
            f"/{statistics.mean(e['guards'] for e in ends):.0f}",
            f"{fire:.0f}",
            f"row {statistics.mean(e['min_y'] for e in ends):.0f}",
        )
    console.print(table)
    console.print("[dim]'reached stage' = a PC got to y<=13 (the stage step). "
                  "'closest PC to stage' is the northernmost any PC reached — lower is further in. "
                  "PCs enter at row ~73.[/dim]")


if __name__ == "__main__":
    main()
