"""Aggregation over ledger rows: summaries, bootstrap confidence intervals, and
`compare()` — the statistical-equivalence tool the migration plan (design doc
05) uses to check a new-engine sim against its frozen old-engine baseline.
Percentiles use linear interpolation (numpy's default "linear" method) so
results are stable and don't depend on a particular Python version's
`statistics.quantiles` behavior.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Callable, Optional, Union


@dataclass(frozen=True)
class Summary:
    n: int
    mean: float
    stdev: float
    min: float
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    max: float


def _percentile(sorted_data: list[float], p: float) -> float:
    """Linear-interpolation percentile of already-sorted data. `p` in [0, 100]."""
    if not sorted_data:
        raise ValueError("cannot take a percentile of no data")
    if len(sorted_data) == 1:
        return sorted_data[0]
    k = (len(sorted_data) - 1) * (p / 100)
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    return sorted_data[f] * (c - k) + sorted_data[c] * (k - f)


def _column_values(rows: list[dict], column: str) -> list[float]:
    return [r.get(column, 0) for r in rows]


def summarize(rows: list[dict], column: str) -> Summary:
    """Summary statistics for one column across all rows. Rows missing the
    column contribute 0 (columns are conditionally present — e.g. poison
    tracking only exists for sims with a poison-capable monster — and a
    missing key means "didn't happen," not "unknown")."""
    if not rows:
        raise ValueError("cannot summarize an empty row set")
    values = _column_values(rows, column)
    ordered = sorted(values)
    return Summary(
        n=len(values),
        mean=statistics.mean(values),
        stdev=statistics.stdev(values) if len(values) >= 2 else 0.0,
        min=ordered[0],
        p10=_percentile(ordered, 10),
        p25=_percentile(ordered, 25),
        p50=_percentile(ordered, 50),
        p75=_percentile(ordered, 75),
        p90=_percentile(ordered, 90),
        max=ordered[-1],
    )


def summarize_all(rows: list[dict]) -> dict[str, Summary]:
    """Summarize every numeric column present in the first row. Assumes rows
    are uniform in shape (true of any Ledger.finalize_trial output)."""
    if not rows:
        raise ValueError("cannot summarize an empty row set")
    columns = [k for k, v in rows[0].items() if isinstance(v, (int, float))]
    return {col: summarize(rows, col) for col in columns}


def bootstrap_ci(rows: list[dict], column: str, *, stat: Union[str, Callable[[list[float]], float]] = "mean",
                  confidence: float = 0.95, n_resamples: int = 2000,
                  seed: Optional[int] = None) -> tuple[float, float]:
    """Percentile bootstrap confidence interval for `stat` of `column`. This is
    an exploratory-analysis tool, not part of a trial's own RNG stream, so it
    draws from `random`/an optional local seed rather than a game's `Dice`."""
    values = _column_values(rows, column)
    if len(values) < 2:
        raise ValueError("need at least 2 rows to bootstrap a confidence interval")
    stat_fn: Callable[[list[float]], float] = (
        statistics.mean if stat == "mean" else statistics.median if stat == "median" else stat
    )
    rng = random.Random(seed)
    resample_stats = [
        stat_fn([rng.choice(values) for _ in values])
        for _ in range(n_resamples)
    ]
    resample_stats.sort()
    alpha = (1 - confidence) / 2
    lo = _percentile(resample_stats, alpha * 100)
    hi = _percentile(resample_stats, (1 - alpha) * 100)
    return lo, hi


def _relative_delta(a: float, b: float) -> float:
    """Relative |b - a| / |a|, defined as 0.0 when both are exactly 0 (trivial
    match) and +inf when only one is 0 (any nonzero value is an infinite
    relative change from zero — a guaranteed tolerance failure, not a crash)."""
    if a == 0 and b == 0:
        return 0.0
    if a == 0:
        return math.inf
    return abs(b - a) / abs(a)


def _is_rate_column(rows_a: list[dict], rows_b: list[dict], column: str) -> bool:
    """A column is treated as a rate/binary column (e.g. `wiped_monsters`) when
    every value on both sides is 0 or 1 — detected from data, not from naming
    conventions, so this stays game-agnostic."""
    values = _column_values(rows_a, column) + _column_values(rows_b, column)
    return all(v in (0, 1) for v in values)


@dataclass(frozen=True)
class ColumnComparison:
    column: str
    is_rate: bool
    mean_a: float
    mean_b: float
    mean_delta: float          # relative delta for continuous columns, pp delta for rate columns
    p10_delta: Optional[float] = None
    p50_delta: Optional[float] = None
    p90_delta: Optional[float] = None
    passed: bool = True


@dataclass(frozen=True)
class CompareReport:
    columns: list[ColumnComparison]
    mean_tol: float
    pct_tol: float
    rate_pp_tol: float
    missing_in_a: list[str] = field(default_factory=list)
    missing_in_b: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.missing_in_a and not self.missing_in_b and all(c.passed for c in self.columns)


def compare(rows_a: list[dict], rows_b: list[dict], *, columns: Optional[list[str]] = None,
            mean_tol: float = 0.03, pct_tol: float = 0.05, rate_pp_tol: float = 0.02) -> CompareReport:
    """Statistical-equivalence check between two row sets (e.g. an old-engine
    baseline and a new-engine run of the same scenario/seed). Per design doc
    05: continuous columns pass when relative Δmean <= mean_tol and relative Δ
    at p10/p50/p90 <= pct_tol; rate/binary columns (every value 0 or 1, e.g.
    `wiped_monsters`) pass when the absolute percentage-point delta in the
    rate <= rate_pp_tol instead — a percentile of a 0/1 column isn't a
    meaningful comparison. Never RNG-identical by design; this is the
    tolerance-based substitute."""
    if not rows_a or not rows_b:
        raise ValueError("cannot compare against an empty row set")
    if columns is None:
        keys_a = {k for k, v in rows_a[0].items() if isinstance(v, (int, float))}
        keys_b = {k for k, v in rows_b[0].items() if isinstance(v, (int, float))}
        columns = sorted(keys_a & keys_b)
        missing_in_a = sorted(keys_b - keys_a)
        missing_in_b = sorted(keys_a - keys_b)
    else:
        missing_in_a = [c for c in columns if c not in rows_a[0]]
        missing_in_b = [c for c in columns if c not in rows_b[0]]

    results: list[ColumnComparison] = []
    for col in columns:
        if col in missing_in_a or col in missing_in_b:
            continue
        rate = _is_rate_column(rows_a, rows_b, col)
        sum_a, sum_b = summarize(rows_a, col), summarize(rows_b, col)
        if rate:
            pp_delta = abs(sum_b.mean - sum_a.mean)
            results.append(ColumnComparison(
                column=col, is_rate=True, mean_a=sum_a.mean, mean_b=sum_b.mean,
                mean_delta=pp_delta, passed=pp_delta <= rate_pp_tol,
            ))
            continue
        mean_delta = _relative_delta(sum_a.mean, sum_b.mean)
        p10_delta = _relative_delta(sum_a.p10, sum_b.p10)
        p50_delta = _relative_delta(sum_a.p50, sum_b.p50)
        p90_delta = _relative_delta(sum_a.p90, sum_b.p90)
        passed = (mean_delta <= mean_tol and p10_delta <= pct_tol
                  and p50_delta <= pct_tol and p90_delta <= pct_tol)
        results.append(ColumnComparison(
            column=col, is_rate=False, mean_a=sum_a.mean, mean_b=sum_b.mean,
            mean_delta=mean_delta, p10_delta=p10_delta, p50_delta=p50_delta,
            p90_delta=p90_delta, passed=passed,
        ))

    return CompareReport(columns=results, mean_tol=mean_tol, pct_tol=pct_tol,
                         rate_pp_tol=rate_pp_tol, missing_in_a=missing_in_a,
                         missing_in_b=missing_in_b)
