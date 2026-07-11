from simharness.plugin import TrialContext
from simharness.runner import TrialRunner


class DiceRollSystem:
    """Two actors roll 1d6 against each other every round for `rounds` rounds.
    No early termination. Exercises the full round/turn/ledger pipeline."""

    def __init__(self, names=("a", "b")):
        self.names = list(names)
        self.take_turn_log: list[tuple[int, str]] = []

    def setup_trial(self, ctx: TrialContext) -> None:
        ctx.game = {"reversed_rounds": False}
        self.take_turn_log = []

    def turn_order(self, ctx: TrialContext) -> list[str]:
        order = list(self.names)
        if ctx.round_index % 2 == 0:  # even rounds (2, 4, ...) reversed
            order.reverse()
        return order

    def take_turn(self, ctx: TrialContext, actor_id: str) -> None:
        self.take_turn_log.append((ctx.round_index, actor_id))
        other = self.names[1] if actor_id == self.names[0] else self.names[0]
        ctx.ledger.record(actor_id, other, "roll", ctx.dice.roll("1d6"))

    def is_over(self, ctx: TrialContext) -> bool:
        return False

    def finalize_trial(self, ctx: TrialContext) -> dict:
        return {"rounds_played": ctx.round_index}


def make_runner(system=None, *, seed=1, max_rounds=3, names=("a", "b")):
    system = system or DiceRollSystem(names)
    return TrialRunner(system, seed=seed, max_rounds=max_rounds, names=list(names),
                       side_of={n: "side" for n in names}), system


def test_runs_correct_number_of_rounds_and_turns():
    runner, system = make_runner(max_rounds=3, names=("a", "b"))
    ledger = runner.run(trials=1)
    assert len(system.take_turn_log) == 3 * 2  # 3 rounds x 2 actors
    assert ledger.rows[0]["rounds_played"] == 3


def test_turn_order_requeried_each_round():
    runner, system = make_runner(max_rounds=4, names=("a", "b"))
    runner.run(trials=1)
    rounds = {}
    for round_index, actor in system.take_turn_log:
        rounds.setdefault(round_index, []).append(actor)
    assert rounds[1] == ["a", "b"]   # odd round: forward
    assert rounds[2] == ["b", "a"]   # even round: reversed
    assert rounds[3] == ["a", "b"]
    assert rounds[4] == ["b", "a"]


def test_is_over_ends_trial_early():
    class EndsAfterTwoTurns(DiceRollSystem):
        def is_over(self, ctx):
            return len(self.take_turn_log) >= 2

    runner, system = make_runner(EndsAfterTwoTurns(), max_rounds=10)
    ledger = runner.run(trials=1)
    assert len(system.take_turn_log) == 2
    assert ledger.rows[0]["rounds_played"] == 1  # never reached round 2


def test_ledger_accumulates_one_row_per_trial():
    runner, _ = make_runner(max_rounds=2)
    ledger = runner.run(trials=5)
    assert len(ledger.rows) == 5


def test_finalize_trial_outcome_merged_into_row():
    runner, _ = make_runner(max_rounds=1)
    ledger = runner.run(trials=1)
    assert "rounds_played" in ledger.rows[0]


def test_flags_cleared_each_round():
    class FlagSystem(DiceRollSystem):
        def take_turn(self, ctx, actor_id):
            super().take_turn(ctx, actor_id)
            if ctx.round_index == 1:
                ctx.flags["seen"] = True
            elif ctx.round_index == 2 and actor_id == self.names[0]:
                # begin_round should have cleared flags before round 2 started
                assert "seen" not in ctx.flags

    runner, _ = make_runner(FlagSystem(), max_rounds=2)
    runner.run(trials=1)  # assertion happens inside take_turn; no exception = pass


def test_determinism_same_seed_produces_identical_rows():
    runner1, _ = make_runner(seed=42, max_rounds=3)
    runner2, _ = make_runner(seed=42, max_rounds=3)
    rows1 = runner1.run(trials=20).rows
    rows2 = runner2.run(trials=20).rows
    assert rows1 == rows2


def test_different_seeds_produce_different_rows():
    runner1, _ = make_runner(seed=1, max_rounds=3)
    runner2, _ = make_runner(seed=2, max_rounds=3)
    rows1 = runner1.run(trials=20).rows
    rows2 = runner2.run(trials=20).rows
    assert rows1 != rows2


def test_trial_i_identical_regardless_of_total_trial_count():
    runner_small, _ = make_runner(seed=99, max_rounds=3)
    runner_big, _ = make_runner(seed=99, max_rounds=3)
    rows_small = runner_small.run(trials=3).rows
    rows_big = runner_big.run(trials=50).rows
    assert rows_small == rows_big[:3]


def test_on_trial_end_hook_called_once_per_trial():
    seen = []
    runner, _ = make_runner(max_rounds=2)
    runner.on_trial_end = lambda ctx: seen.append(ctx.trial_index)
    runner.run(trials=4)
    assert seen == [0, 1, 2, 3]


def test_round_index_starts_at_zero_before_first_round():
    observed = []

    class ObservesFirstRound(DiceRollSystem):
        def setup_trial(self, ctx):
            super().setup_trial(ctx)
            observed.append(ctx.round_index)

    runner, _ = make_runner(ObservesFirstRound(), max_rounds=1)
    runner.run(trials=1)
    assert observed == [0]
