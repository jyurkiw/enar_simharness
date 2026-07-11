"""The one contract between the harness and a game system.

`simharness` drives the trial/round/turn bookkeeping; a `GameSystem`
implementation resolves what actually happens each turn and reports the
results. The harness never inspects `TrialContext.game` — everything
game-specific (combatants, board, conditions, dice-notation rules) lives
behind that one opaque field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from dieroller import Dice

from .ledger import Ledger


@dataclass
class TrialContext:
    dice: Dice
    ledger: Ledger
    trial_index: int
    max_rounds: int
    round_index: int = 0
    flags: dict = field(default_factory=dict)
    # The game system's own state (combatants, board, whatever it needs).
    # None until `GameSystem.setup_trial` populates it — the harness never
    # reads or writes this field itself.
    game: Any = None


@runtime_checkable
class GameSystem(Protocol):
    def setup_trial(self, ctx: TrialContext) -> None:
        """Reset all game state for a fresh trial; roll initiative; place
        pieces. Responsible for populating `ctx.game`."""
        ...

    def turn_order(self, ctx: TrialContext) -> list[str]:
        """Actor ids in initiative order for the current round. Re-queried by
        the runner every round, so dynamic initiative is supported."""
        ...

    def take_turn(self, ctx: TrialContext, actor_id: str) -> None:
        """Resolve one actor's full turn, recording events into ctx.ledger."""
        ...

    def is_over(self, ctx: TrialContext) -> bool:
        """True when the trial should finalize early (a side wiped, a flee,
        ...). Checked by the runner after every turn."""
        ...

    def finalize_trial(self, ctx: TrialContext) -> dict:
        """Outcome columns for this trial's ledger row (wiped_*,
        hp_remaining_*, ...), merged over the ledger's own damage columns."""
        ...
