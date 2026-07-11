import statistics as pystats

import pytest

from simharness.stats import (
    ColumnComparison,
    Summary,
    bootstrap_ci,
    compare,
    summarize,
    summarize_all,
)


def rows_of(**columns):
    """Build row list from column -> values (all same length)."""
    n = len(next(iter(columns.values())))
    return [{k: v[i] for k, v in columns.items()} for i in range(n)]


def test_summarize_basic_stats():
    rows = rows_of(dealt_fighter=[10, 20, 30, 40, 50])
    s = summarize(rows, "dealt_fighter")
    assert s.n == 5
    assert s.mean == pytest.approx(30)
    assert s.stdev == pytest.approx(pystats.stdev([10, 20, 30, 40, 50]))
    assert s.min == 10
    assert s.max == 50
    assert s.p50 == pytest.approx(30)


def test_summarize_missing_column_defaults_to_zero():
    rows = [{"a": 5}, {}, {"a": 10}]
    s = summarize(rows, "a")
    assert s.n == 3
    assert s.mean == pytest.approx(5)  # (5 + 0 + 10) / 3


def test_summarize_single_row_no_stdev_error():
    s = summarize([{"a": 7}], "a")
    assert s.n == 1
    assert s.stdev == 0.0
    assert s.mean == 7
    assert s.p50 == 7


def test_summarize_empty_rows_raises():
    with pytest.raises(ValueError):
        summarize([], "a")


def test_summarize_all_covers_every_numeric_column():
    rows = rows_of(dealt_fighter=[1, 2], taken_fighter=[3, 4])
    out = summarize_all(rows)
    assert set(out.keys()) == {"dealt_fighter", "taken_fighter"}
    assert isinstance(out["dealt_fighter"], Summary)


def test_summarize_all_skips_non_numeric_columns():
    rows = [{"a": 1, "label": "x"}, {"a": 2, "label": "y"}]
    out = summarize_all(rows)
    assert "label" not in out
    assert "a" in out


def test_bootstrap_ci_deterministic_with_seed():
    rows = rows_of(a=[10, 12, 11, 9, 13, 10, 11, 12, 10, 9])
    lo1, hi1 = bootstrap_ci(rows, "a", seed=42, n_resamples=200)
    lo2, hi2 = bootstrap_ci(rows, "a", seed=42, n_resamples=200)
    assert (lo1, hi1) == (lo2, hi2)


def test_bootstrap_ci_brackets_the_sample_mean_for_stable_data():
    rows = rows_of(a=[10] * 50)  # zero variance: CI should collapse to exactly 10
    lo, hi = bootstrap_ci(rows, "a", seed=1, n_resamples=500)
    assert lo == pytest.approx(10)
    assert hi == pytest.approx(10)


def test_bootstrap_ci_requires_at_least_two_rows():
    with pytest.raises(ValueError):
        bootstrap_ci([{"a": 1}], "a")


def test_compare_identical_rows_passes():
    rows = rows_of(dealt_fighter=[10, 20, 30, 40, 50] * 20)
    report = compare(rows, rows)
    assert report.passed
    assert all(c.mean_delta == 0 for c in report.columns)


def test_compare_identical_rows_passes_at_literal_zero_tolerance():
    # Phase 1 DoD (design doc 06): compare(rows, rows) passes at zero tolerance.
    rows = rows_of(dealt_fighter=[10, 20, 30, 40, 50] * 20, wiped_monsters=[1, 0, 1, 0, 1] * 20)
    report = compare(rows, rows, mean_tol=0.0, pct_tol=0.0, rate_pp_tol=0.0)
    assert report.passed


def test_compare_within_tolerance_passes():
    rows_a = rows_of(dealt_fighter=[100] * 100)
    rows_b = rows_of(dealt_fighter=[101] * 100)  # 1% off
    report = compare(rows_a, rows_b, mean_tol=0.03, pct_tol=0.05)
    assert report.passed


def test_compare_outside_tolerance_fails():
    rows_a = rows_of(dealt_fighter=[100] * 100)
    rows_b = rows_of(dealt_fighter=[150] * 100)  # 50% off
    report = compare(rows_a, rows_b, mean_tol=0.03, pct_tol=0.05)
    assert not report.passed
    col = next(c for c in report.columns if c.column == "dealt_fighter")
    assert not col.passed
    assert col.mean_delta == pytest.approx(0.5)


def test_compare_rate_column_uses_absolute_pp_tolerance():
    # 10% wipe rate vs 11% wipe rate: 1pp difference, well within rate_pp_tol
    rows_a = rows_of(wiped_monsters=[1] * 10 + [0] * 90)
    rows_b = rows_of(wiped_monsters=[1] * 11 + [0] * 89)
    report = compare(rows_a, rows_b, rate_pp_tol=0.02)
    col = next(c for c in report.columns if c.column == "wiped_monsters")
    assert col.is_rate
    assert col.passed
    assert col.mean_delta == pytest.approx(0.01, abs=1e-9)


def test_compare_rate_column_fails_outside_pp_tolerance():
    rows_a = rows_of(wiped_monsters=[1] * 10 + [0] * 90)   # 10%
    rows_b = rows_of(wiped_monsters=[1] * 50 + [0] * 50)   # 50%
    report = compare(rows_a, rows_b, rate_pp_tol=0.02)
    col = next(c for c in report.columns if c.column == "wiped_monsters")
    assert not col.passed


def test_compare_flags_columns_missing_from_one_side():
    rows_a = rows_of(dealt_fighter=[10] * 10, poisoned_otyugh=[0] * 10)
    rows_b = rows_of(dealt_fighter=[10] * 10)  # no poisoned_otyugh column
    report = compare(rows_a, rows_b)
    assert "poisoned_otyugh" in report.missing_in_b
    assert not report.passed  # missing columns are never silently ignored


def test_compare_explicit_columns_list_restricts_comparison():
    rows_a = rows_of(dealt_fighter=[10] * 10, dealt_rogue=[999] * 10)
    rows_b = rows_of(dealt_fighter=[10] * 10, dealt_rogue=[1] * 10)
    report = compare(rows_a, rows_b, columns=["dealt_fighter"])
    assert len(report.columns) == 1
    assert report.columns[0].column == "dealt_fighter"
    assert report.passed  # dealt_rogue's huge divergence is out of scope


def test_compare_both_zero_mean_passes_trivially():
    rows_a = rows_of(dealt_fighter=[0] * 10)
    rows_b = rows_of(dealt_fighter=[0] * 10)
    report = compare(rows_a, rows_b)
    col = report.columns[0]
    assert col.mean_delta == 0.0
    assert col.passed


def test_compare_one_sided_zero_mean_fails():
    rows_a = rows_of(dealt_fighter=[0] * 10)
    rows_b = rows_of(dealt_fighter=[5] * 10)
    report = compare(rows_a, rows_b)
    col = report.columns[0]
    assert col.mean_delta == float("inf")
    assert not col.passed


def test_compare_empty_rows_raises():
    with pytest.raises(ValueError):
        compare([], [{"a": 1}])
