"""TrialRunner: the game-agnostic Monte Carlo trial loop.

Reproduces the proven event shape of the old `dnd5e_combat.engine.build_engine`
(one `looper.Looper` pass = one actor's turn, `begin_round` / `take_turn` /
`advance` in that order) but generically, driving any `GameSystem`. A fresh
`Looper` is built per trial — cheap, and it removes an entire class of
state-bleed bugs the old engine's restart-in-place was prone to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Union, Mapping

from dieroller import Dice
from looper import Looper

from .ledger import Ledger
from .plugin import GameSystem, TrialContext


@dataclass
class _RunnerState:
    """Looper context for one trial. Distinct from the public `TrialContext`
    (which is all a `GameSystem` ever sees) so the exit flag and turn-cursor
    bookkeeping — pure runner internals — never leak into the game's view."""

    ctx: TrialContext
    turn_order: list[str] = field(default_factory=list)
    turn_index: int = 0
    trial_done: bool = False


class TrialRunner:
    def __init__(self, system: GameSystem, *, seed: int, max_rounds: int,
                 names: list[str], side_of: Union[Callable[[str], str], Mapping[str, str]],
                 on_trial_end: Optional[Callable[[TrialContext], None]] = None) -> None:
        self.system = system
        self.seed = seed
        self.max_rounds = max_rounds
        self.names = names
        self.side_of = side_of
        self.on_trial_end = on_trial_end

    def run(self, trials: int) -> Ledger:
        ledger = Ledger(names=self.names, side_of=self.side_of)
        # One master seed reproduces the whole run; each trial gets an
        # independent stream (numpy SeedSequence.spawn), so trial i is the
        # same regardless of how many trials are requested overall, and
        # extending `trials` never perturbs earlier trials.
        streams = Dice(seed=self.seed).spawn(trials)

        for trial_index in range(trials):
            ctx = TrialContext(
                dice=streams[trial_index],
                ledger=ledger,
                trial_index=trial_index,
                max_rounds=self.max_rounds,
            )
            self.system.setup_trial(ctx)
            state = _RunnerState(ctx=ctx)
            self._build_loop(state).run()
            if self.on_trial_end is not None:
                self.on_trial_end(ctx)

        return ledger

    # ---- looper wiring -------------------------------------------------

    def _build_loop(self, state: _RunnerState) -> Looper:
        loop: Looper = Looper(context=state, exit_value_name="trial_done")
        for name in ("begin_round", "take_turn", "advance"):
            loop.add_event(name, add_before=False, add_after=False)
        loop.register("begin_round", self._begin_round)
        loop.register("take_turn", self._take_turn)
        loop.register("advance", self._advance)
        return loop

    def _begin_round(self, event, dt, state: _RunnerState, **_) -> None:
        if state.turn_index != 0:
            return
        state.ctx.round_index += 1
        state.ctx.flags.clear()
        # Re-queried every round so games with dynamic initiative work.
        state.turn_order = list(self.system.turn_order(state.ctx))

    def _take_turn(self, event, dt, state: _RunnerState, **_) -> None:
        actor_id = state.turn_order[state.turn_index]
        self.system.take_turn(state.ctx, actor_id)

    def _advance(self, event, dt, state: _RunnerState, **_) -> None:
        state.turn_index += 1
        if self.system.is_over(state.ctx):
            self._finalize_trial(state)
            return
        if state.turn_index < len(state.turn_order):
            return
        state.turn_index = 0
        if state.ctx.round_index < self.max_rounds:
            return
        self._finalize_trial(state)

    def _finalize_trial(self, state: _RunnerState) -> None:
        outcome = self.system.finalize_trial(state.ctx)
        state.ctx.ledger.finalize_trial(outcome)
        state.trial_done = True
