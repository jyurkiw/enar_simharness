"""Phase 1 acceptance test (design doc 02 section 7, item 3): a 2-axis sweep
over the coin-flip game produces the expected 6 variants and a comparison
table — the sweep machinery exercised end-to-end against a real GameSystem,
not just against bare dicts (see test_sweep.py for the unit-level tests).
"""

from io import StringIO

from rich.console import Console

from simharness.runner import TrialRunner
from simharness.sweep import comparison_table, expand, run

from _fixtures import CoinFlipSystem


def run_variant(cfg: dict):
    runner = TrialRunner(
        CoinFlipSystem(), seed=cfg["simulation"]["seed"], max_rounds=cfg["simulation"]["rounds"],
        names=["heads", "tails"], side_of={"heads": "heads", "tails": "tails"},
    )
    return runner.run(trials=cfg["simulation"]["trials"])


def test_two_axis_sweep_over_coinflip_produces_six_variants_and_a_comparison_table():
    cfg = {
        "simulation": {"seed": 1, "rounds": 10, "trials": 200},
        "sweep": {
            "axes": [
                {"target": "simulation.rounds", "values": [5, 10, 20]},
                {"target": "simulation.seed", "values": [1, 2]},
            ]
        },
    }
    variants = expand(cfg)
    assert len(variants) == 6  # 3 x 2

    ledgers = run(variants, run_variant)
    assert len(ledgers) == 6
    for label, ledger in ledgers.items():
        assert len(ledger.rows) == 200, label

    buf = StringIO()
    console = Console(file=buf, width=120)
    comparison_table(ledgers, ["dealt_heads", "dealt_tails"], console=console)
    output = buf.getvalue()
    for label in ledgers:
        assert label in output
    assert "dealt_heads" in output and "dealt_tails" in output
