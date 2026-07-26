"""How fast must a Pyre Weird drain Hit Dice to become the real threat?

Consume has now failed to fire in three separate measurements at the statblock's
1 HD/round: a PC must be grappled by the same weird for three consecutive rounds
to hit 0 HD, which the party's damage output never allows. Two fixes were on the
table — move Consume's gate, or drain faster. This sweeps the DRAIN RATE.

Reports, per rate: how much of the party's Hit Dice pool is gone by the end,
whether Consume ever fires, and what it costs the party.

    uv run --project ../../dnd5e python drain_rate_report.py --trials 300
"""

from __future__ import annotations

import argparse
import copy
import statistics
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(Path(__file__).parent))
from escape_report import run, metrics                      # noqa: E402
from dnd5e.loader import load_toml_file                     # noqa: E402

SIMULATION = Path(__file__).parent / "simulation.toml"
# The party wakes having spent half its Hit Dice: 5 PCs x 3 HD = 15 in the pool.
POOL = 15


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=200)
    ap.add_argument("--rates", type=int, nargs="*", default=[1, 2, 3])
    args = ap.parse_args()

    console = Console()
    base = load_toml_file(SIMULATION)

    table = Table(title=f"Pyre Weird Hit-Dice drain rate ({args.trials} trials each; "
                        f"party pool = {POOL} HD)")
    for col in ("HD/round", "HD drained", "% of pool", "Consume dmg", "drain dmg",
                "mean PCs dead", "mean escaped", "any escapes", "rounds"):
        table.add_column(col, justify="left" if col == "HD/round" else "right")

    for rate in args.rates:
        cfg = copy.deepcopy(base)
        drain = cfg["overrides"]["pyre_weird"]["abilities"]["drain"]
        for key in ("on_fail", "on_success"):
            drain[key] = [{"effect": "drain_hit_die", "amount": rate}]
        console.print(f"Running drain = {rate} HD/round...")
        rows, ends, tags, party = run(cfg, trials=args.trials)
        m = metrics(rows, ends, party)
        hd_left = statistics.mean(e["hd_left"] for e in ends)
        drained = POOL - hd_left
        table.add_row(
            f"{rate}"+("  (statblock)" if rate == 1 else ""),
            f"{drained:.1f}", f"{100 * drained / POOL:.0f}%",
            f"{tags.damage.get('consume', 0) / m['trials']:.2f}",
            f"{tags.damage.get('drain', 0) / m['trials']:.1f}",
            f"{m['mean_dead']:.2f}", f"{m['mean_escaped']:.2f}/5",
            f"{m['any_escaped']:.0f}%", f"{m['rounds']:.1f}",
        )
    console.print(table)
    console.print("[dim]Consume unlocks only when a PC hits 0 Hit Dice while grappled. "
                  "'Consume dmg' > 0 means the finisher actually came online.[/dim]")


if __name__ == "__main__":
    main()
