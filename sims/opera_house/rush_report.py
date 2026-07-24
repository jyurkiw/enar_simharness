"""Rush-to-the-stage report for the opera house.

With the `[objective]` in place the party pushes north and the trial ends when a
PC reaches the stage (y<=13). This report answers the two questions that model
was built for:

  1. Do the runners break through — and how fast, and at what cost (TPK is still
     the only real failure)?
  2. Do the guards' CONTROL mechanics actually land on the runners, or do the PCs
     breeze past out of melee? Measures per-trial incidence of every guard
     condition (grapple/prone/restrain+manacle, the slinger bolos, stun) plus how
     often a guard reaches melee of a PC at all.

    uv run --project ../../dnd5e python rush_report.py
    uv run --project ../../dnd5e python rush_report.py --trials 400
"""

from __future__ import annotations

import argparse
import statistics
from collections import defaultdict
from pathlib import Path

from rich.console import Console
from rich.table import Table
from simharness.runner import TrialRunner

from dnd5e.loader import build_simulation, load_toml_file
from dnd5e.system import Dnd5eSystem

HERE = Path(__file__).parent
SIMULATION = HERE / "simulation.toml"

# Guard-applied conditions worth tracking on the PCs, label -> condition name.
CONTROL = [
    ("grappled (Hound)", "grappled"),
    ("prone (Hound)", "prone"),
    ("manacled/captured (Vise)", "manacled"),
    ("Speed 0 — Low Bolo", "low_bolo"),
    ("disadvantage — High Bolo", "high_bolo"),
    ("stunned (Stone)", "stunned"),
    ("frightened (Mage)", "frightened"),
]

REC: dict[int, dict] = defaultdict(lambda: {"cond": set(), "melee": False})


def install_probe(party_names, bf_melee_ft=5):
    original = Dnd5eSystem.take_turn

    def probed(self, ctx, actor_id):
        original(self, ctx, actor_id)
        d = REC[ctx.trial_index]
        game = ctx.game
        bf = game.battlefield
        pcs = [game.creatures[n] for n in party_names if n in game.creatures]
        for pc in pcs:
            for c in pc.conditions:
                d["cond"].add(c.name)
        if not d["melee"]:
            live_pcs = [p for p in pcs if not p.is_down and p.coord is not None]
            for e in bf.members("monsters"):
                if e.is_down or e.coord is None:
                    continue
                if any((bf.distance_ft(e, p) or 999) <= bf_melee_ft for p in live_pcs):
                    d["melee"] = True
                    break

    Dnd5eSystem.take_turn = probed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=200)
    args = ap.parse_args()

    console = Console()
    cfg = load_toml_file(SIMULATION)
    spec = build_simulation(cfg, sim_dir=SIMULATION.parent, name_fallback="opera_house")
    party = {s.instance_name: s.statblock.stats.hp_average for s in spec.roster if s.side == "party"}
    party_names = list(party)

    names = [s.instance_name for s in spec.roster]
    side_of = {s.instance_name: s.side for s in spec.roster}
    for _r, slots in spec.reinforcements:
        for s in slots:
            names.append(s.instance_name)
            side_of[s.instance_name] = s.side

    # End-state snapshot per trial: each PC is conscious (>0 HP, may be
    # manacled), down (0 HP, dying — effectively out), or dead (3 death-save
    # fails). "At least one conscious" is the party's survival line; "all
    # down-or-dead" is the effective TPK.
    END: dict[int, dict] = {}

    def snapshot(ctx):
        g = ctx.game
        pcs = [g.creatures[p] for p in party_names if p in g.creatures]
        END[ctx.trial_index] = {
            "conscious": sum(1 for p in pcs if not p.is_down),
            "ko_stable": sum(1 for p in pcs if p.is_down and p.is_stabilized and not p.is_dead),
            "dying": sum(1 for p in pcs if p.is_down and not p.is_stabilized and not p.is_dead),
            "dead": sum(1 for p in pcs if p.is_dead),
            "manacled": sum(1 for p in pcs if p.has_condition("manacled")),
        }

    install_probe(party_names)
    REC.clear()
    system = Dnd5eSystem(board=spec.board, roster=spec.roster, max_rounds=spec.max_rounds,
                         hp_mode=spec.hp_mode, focus=spec.focus, obscurement=spec.obscurement,
                         light_plan=spec.light_plan, reinforcements=spec.reinforcements,
                         extraction=spec.extraction, grapple_escape=spec.grapple_escape,
                         objective=spec.objective, subduing_side=spec.subduing_side)
    runner = TrialRunner(system, seed=spec.seed, max_rounds=spec.max_rounds, names=names,
                         side_of=side_of, on_trial_end=snapshot)
    rows = runner.run(trials=args.trials).rows
    probe = [REC[i] for i in range(args.trials)]
    ends = [END[i] for i in range(args.trials)]

    n = len(rows)
    def mean(k): return statistics.mean(r.get(k, 0) for r in rows)
    def epct(pred): return 100 * sum(1 for e in ends if pred(e)) / n
    hp_left = statistics.mean(sum(r.get(f"hp_remaining_{p}", 0) for p in party) for r in rows)
    reached = [r for r in rows if r.get("reached_stage")]

    t1 = Table(title=f"Rush to the stage ({n} trials)")
    t1.add_column("measure"); t1.add_column("value", justify="right")
    t1.add_row("reached the stage", f"{100 * len(reached) / n:.0f}%")
    if reached:
        t1.add_row("  ...in round (mean, when reached)", f"{statistics.mean(r['reach_round'] for r in reached):.1f}")
    t1.add_row("rounds to resolve (mean)", f"{mean('rounds'):.1f}")
    t1.add_row("party HP spent", f"{100 * (1 - hp_left / sum(party.values())):.0f}%")
    t1.add_row("a guard reaches melee of a PC", f"{100 * sum(1 for d in probe if d['melee']) / n:.0f}%")
    console.print(t1)

    t3 = Table(title="How the guard fight ends (the guards SUBDUE — a defeat is the phase-2 hand-off)")
    t3.add_column("outcome"); t3.add_column("of trials", justify="right")
    t3.add_row("ESCAPED — ≥1 PC reached the stage", f"{100 * len(reached) / n:.1f}%")
    t3.add_row("SUBDUED — party fully down, none conscious → phase 2", f"{epct(lambda e: e['conscious'] == 0):.1f}%")
    t3.add_row("  ...cleanly (every downed PC knocked out & stable)",
               f"{epct(lambda e: e['conscious'] == 0 and e['dead'] == 0 and e['dying'] == 0):.1f}%")
    t3.add_row("A PC actually DIED (the real failure — guards shouldn't)", f"{epct(lambda e: e['dead'] >= 1):.1f}%")
    t3.add_row("A PC left DYING on death saves (shouldn't happen)", f"{epct(lambda e: e['dying'] >= 1):.1f}%")
    t3.add_row("mean PCs knocked out & stable at end", f"{statistics.mean(e['ko_stable'] for e in ends):.2f}")
    t3.add_row("mean PCs manacled at end", f"{statistics.mean(e['manacled'] for e in ends):.2f}")
    t3.add_row("mean PCs dead at end", f"{statistics.mean(e['dead'] for e in ends):.2f}")
    console.print(t3)

    t2 = Table(title="Did the guards' control land on the runners? (≥1 PC affected, per trial)")
    t2.add_column("condition"); t2.add_column("of trials", justify="right")
    for label, cond in CONTROL:
        hit = 100 * sum(1 for d in probe if cond in d["cond"]) / n
        t2.add_row(label, f"{hit:.0f}%")
    console.print(t2)


if __name__ == "__main__":
    main()
