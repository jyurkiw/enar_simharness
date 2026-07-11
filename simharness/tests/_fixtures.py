"""Shared test fixtures. Not a test module itself (doesn't match test_*.py),
so pytest won't try to collect it.
"""

from simharness.plugin import TrialContext


class CoinFlipSystem:
    """Two players flip a coin each round; a "heads" result (p=0.5) deals 1
    damage to the opponent. That's the whole game — the reference GameSystem
    every acceptance test (and every future real GameSystem) is measured
    against."""

    def setup_trial(self, ctx: TrialContext) -> None:
        ctx.game = {"players": ("heads", "tails")}

    def turn_order(self, ctx: TrialContext) -> list[str]:
        return list(ctx.game["players"])

    def take_turn(self, ctx: TrialContext, actor_id: str) -> None:
        opponent = "tails" if actor_id == "heads" else "heads"
        if ctx.dice.roll("1d2") == 2:
            ctx.ledger.record(actor_id, opponent, "flip", 1)

    def is_over(self, ctx: TrialContext) -> bool:
        return False

    def finalize_trial(self, ctx: TrialContext) -> dict:
        return {}
