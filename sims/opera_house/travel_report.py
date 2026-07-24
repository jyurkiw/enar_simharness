"""Movement-timing report for the opera house: how fast the two sides close.

Answers two questions the geography raised:
  * How long do the ENEMIES take to reach the PCs (first blood, and first melee
    contact — split into the southern openers vs. the pit reinforcements)?
  * How long do the PCS take to reach the STAGE (and if they don't, how close do
    they get)?

It snapshots creature positions after every turn (monkeypatching
`Dnd5eSystem.take_turn`), so it measures what actually happens with combat and
difficult terrain in play — not just a straight-line walk. A pure-travel
analytic baseline is printed alongside for reference.

    uv run --project ../../dnd5e python travel_report.py
    uv run --project ../../dnd5e python travel_report.py --trials 300 --max-rounds 12
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

STAGE_EDGE_Y = 13     # y <= 13 == at the stage step / on the stage
MELEE_FT = 5
SLINGER_FT = 40       # a reinforcement is "in range" of a PC once this close

REC: dict[int, dict] = defaultdict(dict)


def is_reinf(name: str) -> bool:
    return "_r2_" in name or "_r4_" in name


def install_probe(party_names: list[str]):
    original = Dnd5eSystem.take_turn

    def probed(self, ctx, actor_id):
        original(self, ctx, actor_id)
        r = ctx.round_index
        d = REC[ctx.trial_index]
        game = ctx.game
        bf = game.battlefield
        pcs = [game.creatures[n] for n in party_names
               if n in game.creatures and game.creatures[n].coord is not None]
        live_pcs = [p for p in pcs if not p.is_down]

        # --- PCs toward the stage ---
        for p in pcs:
            if "min_y" not in d or p.y < d["min_y"]:
                d["min_y"] = p.y
                d["min_y_round"] = r
            if p.y <= STAGE_EDGE_Y and "stage_round" not in d:
                d["stage_round"] = r

        # --- first blood (any enemy reached a PC) ---
        if "first_blood" not in d and any(game.creatures[n].current_damage > 0
                                          for n in party_names if n in game.creatures):
            d["first_blood"] = r

        # --- first melee contact by an opener / a reinforcement ---
        enemies = [c for c in bf.members("monsters") if not c.is_down and c.coord is not None]
        for e in enemies:
            near = [p for p in live_pcs if (bf.distance_ft(e, p) or 999) <= MELEE_FT]
            if near:
                key = "reinf_melee" if is_reinf(e.instance_name) else "opener_melee"
                d.setdefault(key, r)
        # --- first time ANY reinforcement is within slinger range of a PC ---
        for e in enemies:
            if is_reinf(e.instance_name):
                dist = min((bf.distance_ft(e, p) or 999) for p in live_pcs) if live_pcs else 999
                if "reinf_min_ft" not in d or dist < d["reinf_min_ft"]:
                    d["reinf_min_ft"] = dist
                if dist <= SLINGER_FT and "reinf_inrange" not in d:
                    d["reinf_inrange"] = r

    Dnd5eSystem.take_turn = probed
    return original


def pct(rows, key):
    got = [d for d in rows if key in d]
    return 100 * len(got) / len(rows), got


def summarize(rows, key, console_label):
    frac, got = pct(rows, key)
    if not got:
        return f"never", "—"
    vals = [d[key] for d in got]
    return f"{statistics.mean(vals):.1f}", f"{frac:.0f}%"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=150)
    ap.add_argument("--max-rounds", type=int, default=None)
    args = ap.parse_args()

    console = Console()
    cfg = load_toml_file(SIMULATION)
    spec = build_simulation(cfg, sim_dir=SIMULATION.parent, name_fallback="opera_house")
    party_names = [s.instance_name for s in spec.roster if s.side == "party"]
    max_rounds = args.max_rounds or spec.max_rounds

    names = [s.instance_name for s in spec.roster]
    side_of = {s.instance_name: s.side for s in spec.roster}
    for _r, slots in spec.reinforcements:
        for s in slots:
            names.append(s.instance_name)
            side_of[s.instance_name] = s.side

    install_probe(party_names)
    REC.clear()
    system = Dnd5eSystem(board=spec.board, roster=spec.roster, max_rounds=max_rounds,
                         hp_mode=spec.hp_mode, focus=spec.focus, obscurement=spec.obscurement,
                         light_plan=spec.light_plan, reinforcements=spec.reinforcements,
                         extraction=spec.extraction, grapple_escape=spec.grapple_escape,
                         objective=spec.objective, subduing_side=spec.subduing_side)
    runner = TrialRunner(system, seed=spec.seed, max_rounds=max_rounds, names=names, side_of=side_of)
    runner.run(trials=args.trials)
    rows = [REC[i] for i in range(args.trials)]

    # --- enemies reaching the PCs ---
    t1 = Table(title=f"Enemies reaching the PCs ({args.trials} trials, capped at {max_rounds} rounds)")
    for c in ("event", "mean round", "of trials"):
        t1.add_column(c, justify="left" if c == "event" else "right")
    for key, label in [("first_blood", "first blood (any PC damaged)"),
                       ("opener_melee", "an opener reaches melee of a PC"),
                       ("reinf_inrange", "a reinforcement gets within 40 ft of a PC"),
                       ("reinf_melee", "a reinforcement reaches melee of a PC")]:
        mean_r, frac = summarize(rows, key, label)
        t1.add_row(label, mean_r, frac)
    console.print(t1)

    reinf_min = [d.get("reinf_min_ft", 999) for d in rows]
    console.print(f"[dim]Closest any reinforcement ever got to a PC (mean over trials): "
                  f"{statistics.mean(reinf_min):.0f} ft.[/dim]\n")

    # --- PCs reaching the stage ---
    t2 = Table(title="PCs reaching the stage")
    for c in ("measure", "value"):
        t2.add_column(c, justify="left" if c == "measure" else "right")
    frac, got = pct(rows, "stage_round")
    t2.add_row("PCs reach the stage (y<=13) at all", f"{frac:.0f}% of trials")
    if got:
        t2.add_row("  ...in round (mean, when they do)", f"{statistics.mean([d['stage_round'] for d in got]):.1f}")
    min_ys = [d.get("min_y", 74) for d in rows]
    closest_row = statistics.mean(min_ys)
    t2.add_row("closest a PC got to the stage (mean min y)", f"row {closest_row:.0f}  ({closest_row - STAGE_EDGE_Y:.0f} rows short)")
    t2.add_row("  ...reached at round (mean)", f"{statistics.mean([d.get('min_y_round', 0) for d in rows]):.1f}")
    console.print(t2)

    # --- analytic pure-travel baseline ---
    console.print("\n[bold]Pure-travel baseline[/bold] (straight sprint, no fighting; "
                  "open = 6 cells/round, difficult = 3):")
    console.print("  PC entrance (y~73) -> stage edge (y=13): ~53 open + ~7 difficult (pit/step) "
                  "= ~67 move-cost / 6 ≈ [bold]~12 rounds[/bold].")
    console.print("  Openers (y~64) -> PCs (y~73): ~5-8 cells of chairs ≈ [bold]~1-2 rounds[/bold].")
    console.print("  Pit reinforcements (y~15) -> the fight (y~65): ~50 cells ≈ [bold]~9 rounds[/bold] "
                  "of travel on top of their round-2 / round-4 arrival.")


if __name__ == "__main__":
    main()
