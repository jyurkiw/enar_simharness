"""Difficulty report for the plaza guard squad — does the Southern Gate Guard
Cartel squad land where it was designed to, *between low and moderate* for five
level-6 adventurers?

Three things no generic ledger column answers on its own, and all three matter
for that question:

1. **Difficulty, in the terms the question is actually asked in** — party HP
   spent, how often anybody drops, how often anybody dies, TPK rate. The generic
   `survival` report gives per-combatant down/dead rates; this rolls them into
   the party-level numbers you'd compare against a difficulty band.

2. **Is the network doing its job?** The roster's whole design premise is that
   the Hound and Slinger undershoot their damage benchmarks on purpose and the
   Vise's club triples off the conditions they create. That payoff is
   invisible in `dealt_*` columns — it's split across the `vise_held` /
   `vise_restrained` / `finish_prone` damage *tags*. This script instruments
   `Ledger.record` to break damage out by tag, so "the control engine
   contributed N of the squad's M damage" is measurable.

3. **Where the dial sits.** The Vise is explicitly the plentiful, common guard
   type, so Vise count is the natural difficulty lever. The `--dial` mode runs
   2/3/4 Vises so the effect of one more body is a measured number rather than
   a guess.

    uv run --project ../../dnd5e python difficulty_report.py
    uv run --project ../../dnd5e python difficulty_report.py --dial
    uv run --project ../../dnd5e python difficulty_report.py --parties
    uv run --project ../../dnd5e python difficulty_report.py --trials 500
"""

from __future__ import annotations

import argparse
import copy
import statistics
from collections import Counter
from pathlib import Path

from rich.console import Console
from rich.table import Table
from simharness.ledger import Ledger
from simharness.runner import TrialRunner

from dnd5e.loader import build_simulation, load_toml_file
from dnd5e.system import Dnd5eSystem
from simharness import sweep

HERE = Path(__file__).parent
SIMULATION = HERE / "simulation.toml"

PARTY_SIDE = "party"

# Damage tags produced *because* the network landed a condition first — the
# Vise's two damage tiers above its base club, and the Hound's prone bonus.
# Everything the squad would deal with no conditions in play is excluded.
PAYOFF_TAGS = {"vise_held", "vise_restrained", "finish_prone"}


# ---- running ----------------------------------------------------------------


class TagCounter:
    """Wraps `Ledger.record` to accumulate damage per tag across a run. The
    ledger deliberately doesn't break `tag` out into columns (see its own
    docstring — nothing consumed it), and this is the one question that needs
    it, so it's instrumented here rather than by widening the ledger.

    Filtered to `side` because **ability names collide across sides**: the
    Champion Fighter also swings a `longsword`, so an unfiltered tag count
    credits the party's 100+ damage to the Constable and reports the squad
    dealing five times what it does."""

    def __init__(self, side_of: dict, side: str = "monsters") -> None:
        self.damage: Counter = Counter()
        self._side_of = side_of
        self._side = side

    def __enter__(self):
        self._orig = Ledger.record
        counter = self

        def record(ledger_self, source, target, tag, amount, kind=None):
            if amount > 0 and counter._side_of.get(source) == counter._side:
                counter.damage[tag] += amount
            return counter._orig(ledger_self, source, target, tag, amount, kind)

        Ledger.record = record
        return self

    def __exit__(self, *exc):
        Ledger.record = self._orig
        return False


def run(cfg: dict, *, trials: int | None = None) -> tuple[list[dict], Counter, dict]:
    spec = build_simulation(cfg, sim_dir=SIMULATION.parent, name_fallback="guard_cartel")
    system = Dnd5eSystem(board=spec.board, roster=spec.roster, max_rounds=spec.max_rounds,
                         hp_mode=spec.hp_mode, focus=spec.focus,
                         obscurement=spec.obscurement, light_plan=spec.light_plan,
                         grapple_escape=spec.grapple_escape)
    names = [slot.instance_name for slot in spec.roster]
    side_of = {slot.instance_name: slot.side for slot in spec.roster}
    runner = TrialRunner(system, seed=spec.seed, max_rounds=spec.max_rounds,
                         names=names, side_of=side_of)
    # Read the party's roster and max HP off the loaded spec rather than
    # hardcoding it — a `[[sweep.axes]]` variant swaps the whole party out, and
    # a stale HP table would silently misreport "HP spent" for the other one.
    party = {slot.instance_name: slot.statblock.stats.hp_average
             for slot in spec.roster if slot.side == PARTY_SIDE}
    with TagCounter(side_of) as tags:
        ledger = runner.run(trials=trials if trials is not None else spec.trials)
    return ledger.rows, tags.damage, party


# ---- metrics ----------------------------------------------------------------


def _mean(rows, key):
    return statistics.mean(r.get(key, 0) for r in rows)


def metrics(rows: list[dict], party: dict) -> dict:
    n = len(rows)
    names = list(party)
    party_hp = sum(party.values())
    hp_left = statistics.mean(sum(r.get(f"hp_remaining_{p}", 0) for p in names) for r in rows)
    return {
        "trials": n,
        "rounds": _mean(rows, "rounds"),
        "party_hp_spent_pct": 100 * (1 - hp_left / party_hp),
        "pcs_down": sum(_mean(rows, f"down_{p}") for p in names),
        "any_pc_down_pct": 100 * sum(1 for r in rows if any(r.get(f"down_{p}") for p in names)) / n,
        "pc_death_pct": 100 * _mean(rows, "any_dead_party"),
        "tpk_pct": 100 * _mean(rows, "wiped_party"),
        "squad_wiped_pct": 100 * _mean(rows, "wiped_monsters"),
        "squad_retreated_pct": 100 * _mean(rows, "squad_retreated"),
        "monster_dmg": _mean(rows, "side_dealt_monsters"),
        "party_dmg": _mean(rows, "side_dealt_party"),
    }


def print_headline(console: Console, m: dict, tags: Counter, *, title: str) -> None:
    table = Table(title=f"{title} — {m['trials']} trials")
    table.add_column("Measure")
    table.add_column("Value", justify="right")
    table.add_column("Reading")

    rows = [
        ("Rounds to resolve", f"{m['rounds']:.1f}", ""),
        ("Party HP spent", f"{m['party_hp_spent_pct']:.0f}%",
         "~20% reads low, ~40% reads moderate"),
        ("At least one PC down", f"{m['any_pc_down_pct']:.1f}%",
         "the headline difficulty number"),
        ("Mean PCs down at end", f"{m['pcs_down']:.2f}", ""),
        ("A PC actually dies", f"{m['pc_death_pct']:.1f}%", "3 failed death saves"),
        ("Total party wipe", f"{m['tpk_pct']:.1f}%",
         "note: the sim party never retreats — this tail is pessimistic"),
        ("", "", ""),
        ("Squad broken (Constable down -> retreat)", f"{m['squad_retreated_pct']:.1f}%", ""),
        ("Squad wiped to the last guard", f"{m['squad_wiped_pct']:.1f}%", ""),
        ("Damage dealt: squad / party", f"{m['monster_dmg']:.0f} / {m['party_dmg']:.0f}", ""),
    ]
    for row in rows:
        table.add_row(*row)
    console.print(table)

    # --- network contribution (tags are already monster-side only) ---
    squad_total = sum(tags.values())
    payoff = sum(v for k, v in tags.items() if k in PAYOFF_TAGS)
    net = Table(title="Is the control network paying off?")
    net.add_column("Damage tag")
    net.add_column("Per trial", justify="right")
    net.add_column("Share of squad damage", justify="right")
    for tag, total in sorted(tags.items(), key=lambda kv: -kv[1]):
        if total / m["trials"] < 0.01:
            continue
        marker = "  (payoff)" if tag in PAYOFF_TAGS else ""
        net.add_row(tag + marker, f"{total / m['trials']:.1f}", f"{100 * total / squad_total:.1f}%")
    net.add_row("[bold]condition payoff, total[/bold]", f"[bold]{payoff / m['trials']:.1f}[/bold]",
                f"[bold]{100 * payoff / squad_total:.1f}%[/bold]")
    console.print(net)


# ---- the difficulty dial ----------------------------------------------------


def dial(console: Console, cfg: dict, trials: int | None) -> None:
    table = Table(title="Difficulty dial — Vises in the squad")
    for col in ("Vises", "XP", "Rounds", "Party HP spent", ">=1 PC down",
                "PC death", "TPK", "Squad retreated"):
        table.add_column(col, justify="right" if col != "Vises" else "left")

    for count in (2, 3, 4):
        variant = copy.deepcopy(cfg)
        for entry in variant["combatants"]:
            if entry["creature"] == "cartel_vise":
                entry["count"] = count
        console.print(f"Running {count} Vises...")
        rows, _tags, party = run(variant, trials=trials)
        m = metrics(rows, party)
        xp = 450 * count + 700 + 450 + 1100
        table.add_row(
            f"{count}{'  (as specified)' if count == 3 else ''}", f"{xp:,}",
            f"{m['rounds']:.1f}", f"{m['party_hp_spent_pct']:.0f}%",
            f"{m['any_pc_down_pct']:.1f}%", f"{m['pc_death_pct']:.1f}%",
            f"{m['tpk_pct']:.1f}%", f"{m['squad_retreated_pct']:.1f}%",
        )
    console.print(table)
    console.print("[dim]2024 DMG XP budget, 5 PCs at level 6: low 3,000 / moderate 6,000 / "
                  "high 12,000.[/dim]")


# ---- party comparison -------------------------------------------------------

# `[[sweep.axes]] target = "combatants"` order in simulation.toml.
PARTY_LABELS = ["Standard (fighter/ranger/rogue/cleric/wizard)",
                "Vanguard (barbarian/paladin/monk/cleric/wizard)"]


def parties(console: Console, cfg: dict, trials: int | None) -> None:
    """Run both `[[sweep.axes]]` party variants with readable labels. The
    generic `dnd5e-sim sweep` table labels each variant by its raw swept value,
    which for a whole `combatants` list is an unreadable wall of dict repr —
    the same reason sims/masks ships its own report script."""
    variants = sweep.expand(cfg)
    if len(variants) != len(PARTY_LABELS):
        raise RuntimeError(f"expected {len(PARTY_LABELS)} sweep variants, got {len(variants)} — "
                           f"simulation.toml's [[sweep.axes]] changed; update PARTY_LABELS")

    table = Table(title="Does the answer hold across party shapes?")
    for col in ("Party", "Rounds", "Party HP spent", ">=1 PC down", "PC death", "TPK",
                "Squad retreated"):
        table.add_column(col, justify="left" if col == "Party" else "right")

    for label, (_, variant_cfg) in zip(PARTY_LABELS, variants):
        console.print(f"Running {label}...")
        rows, _tags, party = run(variant_cfg, trials=trials)
        m = metrics(rows, party)
        table.add_row(label, f"{m['rounds']:.1f}", f"{m['party_hp_spent_pct']:.0f}%",
                      f"{m['any_pc_down_pct']:.1f}%", f"{m['pc_death_pct']:.1f}%",
                      f"{m['tpk_pct']:.1f}%", f"{m['squad_retreated_pct']:.1f}%")
    console.print(table)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=None,
                    help="override simulation.toml's trial count")
    ap.add_argument("--dial", action="store_true",
                    help="sweep Vise count (2/3/4) instead of reporting the base encounter")
    ap.add_argument("--parties", action="store_true",
                    help="run both [[sweep.axes]] party compositions, with readable labels")
    args = ap.parse_args()

    console = Console()
    cfg = load_toml_file(SIMULATION)
    if args.dial:
        dial(console, cfg, args.trials)
        return
    if args.parties:
        parties(console, cfg, args.trials)
        return
    rows, tags, party = run(cfg, trials=args.trials)
    print_headline(console, metrics(rows, party), tags,
                   title="Plaza guard squad vs 5 level-6 adventurers")


if __name__ == "__main__":
    main()
