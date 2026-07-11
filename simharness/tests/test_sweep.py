from io import StringIO
from pathlib import Path

from rich.console import Console

from simharness.ledger import Ledger
from simharness.sweep import comparison_chart, comparison_table, expand, run


def test_expand_no_sweep_block_returns_single_base_variant():
    cfg = {"simulation": {"seed": 1, "trials": 100}}
    variants = expand(cfg)
    assert len(variants) == 1
    label, variant_cfg = variants[0]
    assert label == "base"
    assert variant_cfg == cfg
    assert variant_cfg is not cfg  # deep copy, not the same object


def test_expand_single_axis_produces_one_variant_per_value():
    cfg = {
        "simulation": {"seed": 1},
        "sweep": {"axes": [{"target": "simulation.seed", "values": [1, 2, 3]}]},
    }
    variants = expand(cfg)
    assert len(variants) == 3
    seeds = [v["simulation"]["seed"] for _, v in variants]
    assert seeds == [1, 2, 3]
    labels = [label for label, _ in variants]
    assert labels == ["simulation.seed=1", "simulation.seed=2", "simulation.seed=3"]


def test_expand_two_axes_produces_cartesian_product():
    cfg = {
        "sweep": {
            "axes": [
                {"target": "overrides.otyugh.to_hit", "values": [6, 7]},
                {"target": "simulation.seed", "values": [1, 2, 3]},
            ]
        }
    }
    variants = expand(cfg)
    assert len(variants) == 6  # 2 x 3, matches the design doc's acceptance test
    combos = {(v["overrides"]["otyugh"]["to_hit"], v["simulation"]["seed"]) for _, v in variants}
    assert combos == {(6, 1), (6, 2), (6, 3), (7, 1), (7, 2), (7, 3)}


def test_expand_does_not_mutate_original_cfg():
    cfg = {"sweep": {"axes": [{"target": "simulation.seed", "values": [1, 2]}]}}
    original = {"sweep": {"axes": [{"target": "simulation.seed", "values": [1, 2]}]}}
    expand(cfg)
    assert cfg == original


def test_run_executes_run_fn_per_variant_and_preserves_order():
    variants = [("a", {"n": 1}), ("b", {"n": 2}), ("c", {"n": 3})]
    calls = []

    def run_fn(cfg):
        calls.append(cfg["n"])
        ledger = Ledger(names=["x"], side_of={"x": "side"})
        ledger.record("x", "x", "tag", cfg["n"])
        ledger.finalize_trial()
        return ledger

    ledgers = run(variants, run_fn)
    assert calls == [1, 2, 3]
    assert list(ledgers.keys()) == ["a", "b", "c"]
    assert ledgers["b"].rows[0]["dealt_x"] == 2


def _ledger_with_dealt(value):
    ledger = Ledger(names=["x"], side_of={"x": "side"})
    ledger.record("x", "x", "tag", value)
    ledger.finalize_trial()
    return ledger


def test_comparison_table_renders_variant_rows():
    ledgers = {"variant_a": _ledger_with_dealt(10), "variant_b": _ledger_with_dealt(20)}
    buf = StringIO()
    console = Console(file=buf, width=100)
    comparison_table(ledgers, ["dealt_x"], console=console)
    output = buf.getvalue()
    assert "variant_a" in output
    assert "variant_b" in output
    assert "dealt_x" in output


def test_comparison_chart_writes_file(tmp_path):
    ledgers = {"a": _ledger_with_dealt(10), "b": _ledger_with_dealt(20)}
    out_path = tmp_path / "comparison.png"
    result = comparison_chart(ledgers, ["dealt_x"], path=out_path)
    assert Path(result).exists()


def test_comparison_chart_handles_empty_ledger_gracefully(tmp_path):
    empty = Ledger(names=["x"], side_of={"x": "side"})
    ledgers = {"a": _ledger_with_dealt(10), "empty": empty}
    out_path = tmp_path / "comparison.png"
    result = comparison_chart(ledgers, ["dealt_x"], path=out_path)
    assert Path(result).exists()
