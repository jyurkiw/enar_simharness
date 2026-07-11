from io import StringIO

import pytest
from rich.console import Console

from simharness.ledger import Ledger
from simharness.report import print_report, register_chart, register_section, save_charts


def make_ledger():
    ledger = Ledger(names=["fighter", "otyugh"], side_of={"fighter": "party", "otyugh": "monsters"})
    for dealt_fighter, dealt_otyugh in [(10, 5), (20, 0), (15, 8)]:
        ledger.record("fighter", "otyugh", "longsword", dealt_fighter)
        if dealt_otyugh:
            ledger.record("otyugh", "fighter", "bite", dealt_otyugh)
        ledger.finalize_trial()
    return ledger


def test_print_report_default_sections_produce_output():
    ledger = make_ledger()
    buf = StringIO()
    console = Console(file=buf, width=100)
    print_report(ledger, title="Test", console=console)
    output = buf.getvalue()
    assert "Test - totals" in output
    assert "Test - by combatant" in output
    assert "fighter" in output
    assert "otyugh" in output


def test_print_report_single_section():
    ledger = make_ledger()
    buf = StringIO()
    console = Console(file=buf, width=100)
    print_report(ledger, title="Test", sections=("totals",), console=console)
    output = buf.getvalue()
    assert "totals" in output
    assert "by combatant" not in output


def test_print_report_unknown_section_raises():
    ledger = make_ledger()
    with pytest.raises(KeyError):
        print_report(ledger, title="Test", sections=("nonexistent",))


def test_print_report_empty_ledger_raises():
    ledger = Ledger(names=["a"], side_of={"a": "side"})
    with pytest.raises(ValueError):
        print_report(ledger, title="Test")


def test_custom_section_can_be_registered():
    calls = []

    def my_section(ledger, title, console):
        calls.append((title, len(ledger.rows)))
        console.print("custom section rendered")

    register_section("custom_test_section", my_section)
    ledger = make_ledger()
    buf = StringIO()
    console = Console(file=buf, width=100)
    print_report(ledger, title="Test", sections=("custom_test_section",), console=console)
    assert calls == [("Test", 3)]
    assert "custom section rendered" in buf.getvalue()


def test_save_charts_writes_expected_files(tmp_path):
    from pathlib import Path

    ledger = make_ledger()
    paths = save_charts(ledger, prefix="test_sim", out_dir=tmp_path)
    assert len(paths) == 3
    for p in paths:
        assert Path(p).exists()


def test_save_charts_creates_out_dir(tmp_path):
    out_dir = tmp_path / "nested" / "out"
    ledger = make_ledger()
    save_charts(ledger, prefix="x", out_dir=out_dir)
    assert out_dir.exists()
    assert (out_dir / "x_totals_hist.png").exists()
    assert (out_dir / "x_dealt_by_combatant.png").exists()
    assert (out_dir / "x_taken_by_combatant.png").exists()


def test_save_charts_unknown_kind_raises(tmp_path):
    ledger = make_ledger()
    with pytest.raises(KeyError):
        save_charts(ledger, prefix="x", kinds=("nonexistent",), out_dir=tmp_path)


def test_save_charts_empty_ledger_raises(tmp_path):
    ledger = Ledger(names=["a"], side_of={"a": "side"})
    with pytest.raises(ValueError):
        save_charts(ledger, prefix="x", out_dir=tmp_path)


def test_custom_chart_can_be_registered(tmp_path):
    def my_chart(ledger, prefix, out_dir):
        path = out_dir / f"{prefix}_custom.png"
        path.write_text("fake png")
        return str(path)

    register_chart("custom_test_chart", my_chart)
    ledger = make_ledger()
    paths = save_charts(ledger, prefix="x", kinds=("custom_test_chart",), out_dir=tmp_path)
    assert len(paths) == 1
    assert (tmp_path / "x_custom.png").exists()
