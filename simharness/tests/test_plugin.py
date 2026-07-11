from dieroller import Dice

from simharness.ledger import Ledger
from simharness.plugin import GameSystem, TrialContext


def make_ctx():
    return TrialContext(
        dice=Dice(seed=1),
        ledger=Ledger(names=["a"], side_of={"a": "side"}),
        trial_index=0,
        max_rounds=5,
    )


def test_trial_context_defaults():
    ctx = make_ctx()
    assert ctx.round_index == 0
    assert ctx.flags == {}
    assert ctx.game is None


def test_trial_context_flags_default_is_not_shared_between_instances():
    ctx1 = make_ctx()
    ctx2 = make_ctx()
    ctx1.flags["x"] = 1
    assert ctx2.flags == {}


class CoinFlipSystem:
    """Minimal duck-typed GameSystem used only to check Protocol conformance."""

    def setup_trial(self, ctx: TrialContext) -> None:
        ctx.game = {}

    def turn_order(self, ctx: TrialContext) -> list[str]:
        return ["a", "b"]

    def take_turn(self, ctx: TrialContext, actor_id: str) -> None:
        pass

    def is_over(self, ctx: TrialContext) -> bool:
        return False

    def finalize_trial(self, ctx: TrialContext) -> dict:
        return {}


def test_duck_typed_system_satisfies_runtime_checkable_protocol():
    assert isinstance(CoinFlipSystem(), GameSystem)


def test_incomplete_system_does_not_satisfy_protocol():
    class Incomplete:
        def setup_trial(self, ctx):
            pass

    assert not isinstance(Incomplete(), GameSystem)
