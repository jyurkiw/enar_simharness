"""Phase-2 escape report — the deliverable for sims/opera_house PLAN P4.

Answers the question the whole burning-building branch exists for: **the party
lost the guard fight; can they get out?** And the design question underneath it:
**how much does bringing a manacle key matter** (Martinique's warning), and **is
Consume actually doing anything** (Jeff's "keep it in and measure it" call).

Sweeps the two dials that matter — the key, and how much of the party wakes
bound — and splits every death by cause, which the generic report can't do:
fire/debris (environmental), a weird's Constrict, or Pyre's Due/Consume.

    uv run --project ../../dnd5e python escape_report.py
    uv run --project ../../dnd5e python escape_report.py --trials 500
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

HERE = Path(__file__).parent
SIMULATION = HERE / "simulation.toml"

# Damage tags, split into what they mean for a cause-of-death read.
ENVIRONMENT = {"fire", "debris", "enflame"}
WEIRD = {"constrict", "drain", "consume"}


class TagCounter:
    """Per-tag damage totals (the ledger doesn't break `tag` out into columns).
    Also records, per trial, the tag of the last damage each PC took — the
    cause-of-death read."""

    def __init__(self, party: set) -> None:
        self.damage = Counter()
        self.last_hit: dict = {}
        self._party = party

    def __enter__(self):
        self._orig = Ledger.record
        counter = self

        def record(ledger_self, source, target, tag, amount, kind=None):
            if amount > 0:
                counter.damage[tag] += amount
                if target in counter._party:
                    counter.last_hit[target] = tag
            return counter._orig(ledger_self, source, target, tag, amount, kind)

        Ledger.record = record
        return self

    def __exit__(self, *exc):
        Ledger.record = self._orig
        return False


def run(cfg: dict, *, trials: int | None = None):
    spec = build_simulation(cfg, sim_dir=SIMULATION.parent, name_fallback="opera_house_escape")
    party = {s.instance_name for s in spec.roster if s.side == "party"}
    names = [s.instance_name for s in spec.roster]
    side_of = {s.instance_name: s.side for s in spec.roster}

    system = Dnd5eSystem(board=spec.board, roster=spec.roster, max_rounds=spec.max_rounds,
                         hp_mode=spec.hp_mode, focus=spec.focus, obscurement=spec.obscurement,
                         light_plan=spec.light_plan, reinforcements=spec.reinforcements,
                         extraction=spec.extraction, grapple_escape=spec.grapple_escape,
                         objective=spec.objective, subduing_side=spec.subduing_side,
                         hazard_actors=spec.hazard_actors, hit_dice_spent=spec.hit_dice_spent,
                         wake_up=spec.wake_up, initial_hazards=spec.initial_hazards)

    ends: list[dict] = []

    def snapshot(ctx):
        g = ctx.game
        pcs = [g.creatures[p] for p in party if p in g.creatures]
        # A trial ends when EITHER side is finished. If the party kills every
        # weird, the trial stops before they physically walk the remaining
        # aisle — but they are safe and the way out is clear, so a survivor
        # counts as escaped. Without this, wiping the weirds scores as 0%
        # escaped, which inverts the result.
        monsters_left = [c for c in g.battlefield.members("monsters") if not c.is_down]
        clear = not monsters_left
        ends.append({
            "escaped": sum(1 for p in pcs
                           if not p.is_down and (clear or system._reached_objective(p))),
            "alive": sum(1 for p in pcs if not p.is_down),
            "dead": sum(1 for p in pcs if p.is_dead),
            "still_bound": sum(1 for p in pcs if p.has_condition("manacled")),
            "hd_left": sum(p.hit_dice_remaining for p in pcs),
        })

    with TagCounter(party) as tags:
        runner = TrialRunner(system, seed=spec.seed, max_rounds=spec.max_rounds,
                             names=names, side_of=side_of, on_trial_end=snapshot)
        rows = runner.run(trials=trials if trials is not None else spec.trials).rows
    return rows, ends, tags, party


def metrics(rows, ends, party):
    n = len(rows)
    mean = lambda k: statistics.mean(r.get(k, 0) for r in rows)
    return {
        "trials": n,
        "rounds": mean("rounds"),
        "any_escaped": 100 * sum(1 for e in ends if e["escaped"] >= 1) / n,
        "all_escaped": 100 * sum(1 for e in ends if e["escaped"] == len(party)) / n,
        "mean_escaped": statistics.mean(e["escaped"] for e in ends),
        "mean_dead": statistics.mean(e["dead"] for e in ends),
        "all_dead": 100 * sum(1 for e in ends if e["dead"] == len(party)) / n,
        "any_dead": 100 * sum(1 for e in ends if e["dead"] >= 1) / n,
        "still_bound": statistics.mean(e["still_bound"] for e in ends),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=None)
    args = ap.parse_args()

    console = Console()
    base = load_toml_file(SIMULATION)

    # ---- the two dials -------------------------------------------------------
    table = Table(title="Phase 2 — escaping the burning opera house")
    for col in ("scenario", "any PC escapes", "ALL escape", "mean escaped",
                "mean PCs dead", "whole party dies", "rounds"):
        table.add_column(col, justify="left" if col == "scenario" else "right")

    variants = [
        ("no key, all 5 bound  (ignored the advice)", {"has_key": False, "bound_count": 5}),
        ("no key, 3 bound  (2 wake free)", {"has_key": False, "bound_count": 3}),
        ("MANACLE KEY, all 5 bound", {"has_key": True, "bound_count": 5}),
        ("manacle key, 3 bound", {"has_key": True, "bound_count": 3}),
    ]
    # There is no fire in this phase (narrative only — see simulation.toml), so
    # the difficulty dial is now the WEIRDS. `weirds` = how many start in the
    # aisle, on top of any the elemental summons.
    variants += [
        (f"manacle key, {n} weirds in the aisle", {"has_key": True, "bound_count": 5, "weirds": n})
        for n in (1, 3)
    ]

    detail = {}
    for label, patch in variants:
        cfg = copy.deepcopy(base)
        weirds = patch.pop("weirds", None)
        if weirds is not None:
            base_w = [c for c in cfg["combatants"] if c["creature"] == "pyre_weird"]
            others = [c for c in cfg["combatants"] if c["creature"] != "pyre_weird"]
            pool = list(base_w)
            while len(pool) < weirds:            # clone down the aisle
                extra = dict(base_w[len(pool) % len(base_w)])
                extra["name"] = f"weird_extra{len(pool)}"
                extra["start"] = [20, 30 + 12 * len(pool)]
                pool.append(extra)
            cfg["combatants"] = others + pool[:weirds]
        cfg["wake_up"].update(patch)
        console.print(f"Running {label}...")
        rows, ends, tags, party = run(cfg, trials=args.trials)
        m = metrics(rows, ends, party)
        detail[label] = (m, tags, party, ends)
        table.add_row(label, f"{m['any_escaped']:.0f}%", f"{m['all_escaped']:.0f}%",
                      f"{m['mean_escaped']:.2f}/5", f"{m['mean_dead']:.2f}",
                      f"{m['all_dead']:.0f}%", f"{m['rounds']:.1f}")
    console.print(table)

    # ---- cause of death, for the headline (key) variant ---------------------
    label = "MANACLE KEY, all 5 bound"
    m, tags, party, ends = detail[label]
    t2 = Table(title=f"What is actually killing them — {label}")
    t2.add_column("source"); t2.add_column("damage/trial", justify="right")
    total = sum(tags.damage.values()) or 1
    for tag, amount in sorted(tags.damage.items(), key=lambda kv: -kv[1]):
        if amount / m["trials"] < 0.05:
            continue
        bucket = ("environment" if tag in ENVIRONMENT
                  else "weird" if tag in WEIRD else "party")
        t2.add_row(f"{tag}  ({bucket})", f"{amount / m['trials']:.1f}")
    console.print(t2)

    t3 = Table(title="Consume / Pyre's Due — is the Hit-Dice timer doing anything?")
    t3.add_column("measure"); t3.add_column("value", justify="right")
    t3.add_row("Consume damage per trial", f"{tags.damage.get('consume', 0) / m['trials']:.2f}")
    t3.add_row("drain (HD timer) damage per trial", f"{tags.damage.get('drain', 0) / m['trials']:.2f}")
    t3.add_row("constrict damage per trial", f"{tags.damage.get('constrict', 0) / m['trials']:.2f}")
    t3.add_row("mean party Hit Dice left at end", f"{statistics.mean(e['hd_left'] for e in ends):.1f}")
    console.print(t3)


if __name__ == "__main__":
    main()
