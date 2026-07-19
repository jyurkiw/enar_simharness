"""Network-value report for the masks sim (Task #69): how much the masked-
guests network's synergy is worth, and how fast it collapses when the party
breaks it. Ported from dnd/masks/src/simulation.py's `print_network_value`/
`print_headline`, adapted to the new engine's `[sweep]`-expanded simulation.

The generic `dnd5e-sim sweep` comparison table (simharness.sweep.
comparison_table) labels each variant by its raw swept config value — fine
for otyugh's single-axis sweeps, unreadable here (this sim's party axis
swaps a whole `[overrides.*]` table, so the label is the dict's repr). This
script re-runs the same 6 variants `simulation.toml`'s `[[sweep.axes]]`
produces (party x strategy, in that same cartesian-product order — see the
zip with READABLE_LABELS below) and reports grouped, masks-specific metrics
(summed Hector/Poet/Bruiser damage, party HP taken, wipe/death rates) no
generic ledger column captures on its own.

    uv run --project ../../dnd5e python network_value_report.py
"""

from __future__ import annotations

import statistics
from pathlib import Path

from rich.console import Console
from rich.table import Table
from simharness.runner import TrialRunner

from dnd5e.loader import build_simulation, load_toml_file
from dnd5e.system import Dnd5eSystem
from simharness import sweep

HERE = Path(__file__).parent
SIMULATION = HERE / "simulation.toml"

HECTORS = ["masked_hector_1", "masked_hector_2"]
POETS = ["masked_poet_1", "masked_poet_2"]
BRUISER = ["masked_bruiser"]

# `[[sweep.axes]]` order in simulation.toml: overrides (adventurers,
# beaumont_playtest) outer, environment.focus (natural, break-generator,
# break-mark) inner — sweep.expand's itertools.product preserves that
# nesting, so this is exactly the 6-variant order `expand()` produces.
READABLE_LABELS = [
    ("Adventurers", "Natural (focus Hector)"),
    ("Adventurers", "Break generator (focus Poets)"),
    ("Adventurers", "Break mark (focus Bruiser)"),
    ("Beaumont playtest", "Natural (focus Hector)"),
    ("Beaumont playtest", "Break generator (focus Poets)"),
    ("Beaumont playtest", "Break mark (focus Bruiser)"),
]


def _mean(rows: list[dict], key: str) -> float:
    values = [r.get(key, 0) for r in rows]
    return statistics.mean(values) if values else 0.0


def _group_dealt(rows: list[dict], names: list[str]) -> float:
    return statistics.mean(sum(r.get(f"dealt_{n}", 0) for n in names) for r in rows) if rows else 0.0


def metrics(rows: list[dict]) -> dict:
    return {
        "hector_dmg": _group_dealt(rows, HECTORS),
        "poet_dmg": _group_dealt(rows, POETS),
        "bruiser_dmg": _group_dealt(rows, BRUISER),
        "monster_dmg": _mean(rows, "side_dealt_monsters"),   # = party HP taken
        "party_wipe": _mean(rows, "wiped_party") * 100,
        "any_pc_death": _mean(rows, "any_dead_party") * 100,
        "monster_wipe": _mean(rows, "wiped_monsters") * 100,
    }


def run_variant(cfg: dict, *, trials: int = None) -> list[dict]:
    spec = build_simulation(cfg, sim_dir=SIMULATION.parent, name_fallback="masks")
    system = Dnd5eSystem(board=spec.board, roster=spec.roster, max_rounds=spec.max_rounds,
                         hp_mode=spec.hp_mode, focus=spec.focus,
                         obscurement=spec.obscurement, light_plan=spec.light_plan)
    names = [slot.instance_name for slot in spec.roster]
    side_of = {slot.instance_name: slot.side for slot in spec.roster}
    runner = TrialRunner(system, seed=spec.seed, max_rounds=spec.max_rounds, names=names, side_of=side_of)
    ledger = runner.run(trials=trials if trials is not None else spec.trials)
    return ledger.rows


def main(trials: int = None) -> None:
    console = Console()
    cfg = load_toml_file(SIMULATION)
    variants = sweep.expand(cfg)
    if len(variants) != len(READABLE_LABELS):
        raise RuntimeError(
            f"expected {len(READABLE_LABELS)} sweep variants, got {len(variants)} — "
            f"simulation.toml's [[sweep.axes]] shape changed; update READABLE_LABELS to match"
        )

    table = Table(title="Masks network value (party x focus strategy)")
    for col in ("Party", "Strategy", "Hector dmg", "Poet dmg", "Bruiser dmg",
               "Party HP taken", "Party wipe", "any-PC death", "Monsters wiped"):
        table.add_column(col, justify="left" if col in ("Party", "Strategy") else "right")

    natural_hector = {}
    rows_by_label = {}
    for (party, strategy), (_, variant_cfg) in zip(READABLE_LABELS, variants):
        console.print(f"Running {party} vs full network, {strategy}...")
        rows = run_variant(variant_cfg, trials=trials)
        m = metrics(rows)
        rows_by_label[(party, strategy)] = m
        if strategy.startswith("Natural"):
            natural_hector[party] = m["hector_dmg"]

    for (party, strategy), m in rows_by_label.items():
        delta = ""
        base = natural_hector.get(party, 0)
        if not strategy.startswith("Natural") and base > 0:
            pct = 100 * (m["hector_dmg"] - base) / base
            delta = f" ({pct:+.0f}%)"
        table.add_row(
            party, strategy,
            f"{m['hector_dmg']:.1f}{delta}", f"{m['poet_dmg']:.1f}", f"{m['bruiser_dmg']:.1f}",
            f"{m['monster_dmg']:.1f}", f"{m['party_wipe']:.1f}%", f"{m['any_pc_death']:.1f}%",
            f"{m['monster_wipe']:.1f}%",
        )
    console.print(table)


if __name__ == "__main__":
    main()
