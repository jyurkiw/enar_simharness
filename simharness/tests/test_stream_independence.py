"""Phase 1 DoD (design doc 06): trial streams spawned from one master seed must
be statistically independent, not merely different sequences. This underlies
`TrialRunner`'s seeding scheme (design doc 02 section 3) — if spawned streams
were correlated, "each trial is independently reproducible" would still hold,
but pooling trials for statistics would be subtly biased.
"""

import statistics

from dieroller import Dice


def _pearson_correlation(a: list[float], b: list[float]) -> float:
    mean_a, mean_b = statistics.mean(a), statistics.mean(b)
    cov = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b)) / len(a)
    std_a, std_b = statistics.pstdev(a), statistics.pstdev(b)
    return cov / (std_a * std_b)


def test_spawned_streams_are_pairwise_uncorrelated():
    master = Dice(seed=20260711)
    streams = master.spawn(5)
    n = 3000
    sequences = [[s.roll("1d1000000") for _ in range(n)] for s in streams]

    for i in range(len(sequences)):
        for j in range(i + 1, len(sequences)):
            corr = _pearson_correlation(sequences[i], sequences[j])
            assert abs(corr) < 0.05, f"stream {i} vs stream {j}: correlation {corr!r}"


def test_spawned_streams_are_not_merely_offset_copies_of_each_other():
    # A weaker implementation might spawn "streams" that are really the same
    # underlying sequence at different offsets (still "different", but
    # trivially correlated once shifted back into alignment). Guard against
    # that specifically: no small shift of stream 0 should align with stream 1.
    master = Dice(seed=7)
    s0, s1 = master.spawn(2)
    n = 500
    a = [s0.roll("1d6") for _ in range(n)]
    b = [s1.roll("1d6") for _ in range(n)]
    exact_matches = sum(1 for x, y in zip(a, b) if x == y)
    # Two independent d6 streams agree ~1/6 of the time by chance; a shifted
    # copy of itself would agree ~100% of the time.
    assert exact_matches < n * 0.3
