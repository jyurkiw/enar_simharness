"""The Phase 1 acceptance test (design doc 02 section 7, item 1): a GameSystem
with zero knowledge of D&D, small enough to read in one glance, proves the
harness is genuinely game-agnostic. Every future GameSystem implementation
(dnd5e included) should look structurally like this, just with more going on
inside take_turn().
"""

import pytest

from simharness.plugin import GameSystem
from simharness.runner import TrialRunner
from simharness.stats import summarize

from _fixtures import CoinFlipSystem

ROUNDS = 20
TRIALS = 5000


def make_runner(seed=20260711):
    return TrialRunner(
        CoinFlipSystem(), seed=seed, max_rounds=ROUNDS,
        names=["heads", "tails"], side_of={"heads": "heads", "tails": "tails"},
    )


def test_coinflip_system_satisfies_the_gamesystem_protocol():
    assert isinstance(CoinFlipSystem(), GameSystem)


def test_ledger_rows_have_the_expected_uniform_columns():
    ledger = make_runner().run(trials=10)
    expected = {"dealt_heads", "taken_heads", "dealt_tails", "taken_tails",
                "side_dealt_heads", "side_dealt_tails"}
    assert len(ledger.rows) == 10
    for row in ledger.rows:
        assert set(row.keys()) == expected


def test_summarize_matches_analytic_binomial_expectation():
    # Each of ROUNDS turns per side is an independent p=0.5 Bernoulli "hit",
    # so dealt_<player> ~ Binomial(ROUNDS, 0.5): mean ROUNDS/2, var ROUNDS/4.
    ledger = make_runner().run(trials=TRIALS)
    analytic_mean = ROUNDS / 2
    analytic_stdev = (ROUNDS * 0.25) ** 0.5
    standard_error = analytic_stdev / (TRIALS ** 0.5)

    heads_summary = summarize(ledger.rows, "dealt_heads")
    tails_summary = summarize(ledger.rows, "dealt_tails")

    # Generous tolerance (~10 standard errors) keeps this non-flaky while
    # still catching any real implementation bug in the roll/record pipeline.
    assert heads_summary.mean == pytest.approx(analytic_mean, abs=10 * standard_error)
    assert tails_summary.mean == pytest.approx(analytic_mean, abs=10 * standard_error)
    assert heads_summary.stdev == pytest.approx(analytic_stdev, rel=0.1)


def test_coinflip_1000_trials_matches_analytic_mean_within_3_standard_errors():
    # Literal Phase 1 DoD wording (design doc 06): 1000 trials, 3 standard errors.
    trials = 1000
    ledger = make_runner().run(trials=trials)
    analytic_mean = ROUNDS / 2
    analytic_stdev = (ROUNDS * 0.25) ** 0.5
    standard_error = analytic_stdev / (trials ** 0.5)
    heads_summary = summarize(ledger.rows, "dealt_heads")
    assert heads_summary.mean == pytest.approx(analytic_mean, abs=3 * standard_error)


def test_side_dealt_matches_dealt_for_single_member_sides():
    # With one combatant per side, side_dealt_<side> is exactly dealt_<name>.
    ledger = make_runner().run(trials=50)
    for row in ledger.rows:
        assert row["side_dealt_heads"] == row["dealt_heads"]
        assert row["side_dealt_tails"] == row["dealt_tails"]


def test_dealt_and_taken_are_consistent_between_the_two_players():
    ledger = make_runner().run(trials=50)
    for row in ledger.rows:
        assert row["dealt_heads"] == row["taken_tails"]
        assert row["dealt_tails"] == row["taken_heads"]
