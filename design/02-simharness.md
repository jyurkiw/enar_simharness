# 02 — simharness: the Game-Agnostic Harness

`simharness` owns everything a Monte Carlo tabletop simulation needs that isn't a game
rule: the trial loop, seeding, event-loop wiring, result collection, statistics,
reporting, and parameter sweeps. It must remain importable and useful with **zero**
knowledge of D&D — the acceptance test is a toy coin-flip game implemented against the
public protocol (§7).

```
simharness/src/simharness/
├── __init__.py       # public API re-exports
├── plugin.py         # GameSystem protocol + TrialContext
├── runner.py         # TrialRunner (looper wiring, trials loop, seeding)
├── ledger.py         # Ledger (per-event records + per-trial rows)
├── stats.py          # aggregation, percentiles, compare()
├── report.py         # rich tables + matplotlib chart registry
├── sweep.py          # sweep expansion + comparison runner
└── config.py         # load_toml, deep_merge, dotted-path set/get, schema helpers
```

Dependencies: `looper`, `py-die-roller`, `rich`, `matplotlib`, `numpy`. Never `dnd5e`,
never `dnd_board`.

## 1. The GameSystem protocol (`plugin.py`)

The single contract between harness and game. The harness drives; the game resolves.

```python
class GameSystem(Protocol):
    def setup_trial(self, ctx: TrialContext) -> None:
        """Reset all game state for a fresh trial; roll initiative; place pieces."""

    def turn_order(self, ctx: TrialContext) -> list[str]:
        """Actor ids in initiative order for the current round."""

    def take_turn(self, ctx: TrialContext, actor_id: str) -> None:
        """Resolve one actor's full turn, recording events into ctx.ledger."""

    def is_over(self, ctx: TrialContext) -> bool:
        """True when the trial should finalize early (a side wiped, a flee, ...)."""

    def finalize_trial(self, ctx: TrialContext) -> dict:
        """Outcome columns for this trial's ledger row (wiped_*, hp_remaining_*, ...)."""
```

```python
@dataclass
class TrialContext:
    dice: Dice                 # per-trial seeded stream (see §3)
    ledger: Ledger
    trial_index: int
    round_index: int           # maintained by the runner
    max_rounds: int
    flags: dict                # cross-actor signal bag, cleared per round by the runner
    game: Any                  # the game system's own state object (opaque to harness)
```

The harness never inspects `ctx.game`. Everything D&D-shaped (combatants, board,
conditions) lives behind it.

## 2. TrialRunner (`runner.py`)

Reproduces the proven event shape of the old engine (`dnd5e_combat.engine.build_engine`)
but generically:

```
for trial in range(trials):
    ctx = TrialContext(dice=trial_stream(trial), ...)
    system.setup_trial(ctx)
    looper pass (one pass = one actor's turn):
        begin_round  -> fires when the turn cursor is at 0: round_index += 1,
                        ctx.flags.clear(); stops the trial at max_rounds
        take_turn    -> system.take_turn(ctx, current_actor_id)
        advance      -> step the turn cursor; if system.is_over(ctx) or the
                        round budget is spent, exit the loop
    row = {**damage_columns, **system.finalize_trial(ctx)}
    ledger.finalize_trial(row)
```

Implementation notes:
- One `Looper(context=ctx, exit_value_name="trial_done")` per trial with the three events,
  bookends disabled (`add_before=False, add_after=False`) as today. Constructing a Looper
  is cheap; per-trial construction is simpler than the old engine's restart-in-place and
  removes an entire class of state-bleed bugs.
- `turn_order` is re-queried each round, so games with dynamic initiative work.
- The runner owns rounds/turn-cursor bookkeeping; the game owns everything else.
- A `on_trial_end(callback)` hook supports progress bars and streaming stats.

## 3. Seeding scheme

Reproducibility requirements: (a) one master seed reproduces an entire run; (b) each trial
is independently reproducible; (c) adding trials doesn't perturb earlier trials.

```python
master = Dice(seed=cfg.seed)
streams = master.spawn(trials)      # dieroller's independent-stream support
# trial i uses streams[i]; re-running with the same seed and trials >= i
# reproduces trial i exactly.
```

All game randomness must flow through `ctx.dice` — the game system receives no other
entropy source. (In `dnd5e`, the `Resolver` wraps `ctx.dice`.)

## 4. Ledger (`ledger.py`)

Lift of `dnd5e_combat/ledger.py` with the 5e assumptions removed:

- `record(source: str, target: str, tag: str, amount: float, kind: str | None)` — generic
  quantity events (damage, healing, resource spend — the game decides).
- `finalize_trial(row: dict)` — snapshots accumulated per-(source,target,tag) sums into
  the standard columns (`dealt_<name>`, `taken_<name>`, `side_dealt_<side>` — side mapping
  supplied by the game via a `side_of` callable at construction) merged with the game's
  outcome dict, then resets accumulators.
- `rows: list[dict]` — the full per-trial distribution, the input to stats and reports.
- Column names are whatever the game emits; the harness treats them as opaque numerics.

## 5. Statistics (`stats.py`)

- `summarize(rows, column) -> Summary` — n, mean, stdev, min, p10/p25/p50/p75/p90, max.
- `summarize_all(rows) -> dict[str, Summary]`.
- `bootstrap_ci(rows, column, stat="mean", confidence=0.95)`.
- **`compare(rows_a, rows_b, columns=None, mean_tol=0.03, pct_tol=0.05) -> CompareReport`**
  — the migration parity tool ([05](05-migration-plan.md)): per-column relative deltas of
  mean and p10/p50/p90, pass/fail against tolerances, formatted as a rich table. Also used
  post-migration for A/B balance questions ("did +1 to-hit matter?").

## 6. Reporting (`report.py`) and sweeps (`sweep.py`)

- `print_report(ledger, sections=[...])` — rich tables; section renderers are registered
  by name (`totals`, `by_combatant`, `survival`, ...). `simharness` ships the generic ones;
  `dnd5e` registers game-flavored sections (e.g. `survival` knows `wiped_*` columns) at
  import time via `report.register_section(name, fn)`.
- `save_charts(ledger, kinds=[...], prefix, out_dir)` — same registry pattern for
  matplotlib charts (`totals_hist`, `dealt_by_combatant`, `taken_by_combatant`).
- `sweep.expand(cfg) -> list[(label, cfg_variant)]` — cartesian product of `[sweep.axes]`
  (dotted-path targets set via `config.set_path`); `sweep.run(variants, run_fn)` executes
  each and returns labeled ledgers; `sweep.comparison_table(...)` /
  `sweep.comparison_chart(...)` render cross-variant summaries. This replaces
  `masks/scaling.py`, `otyugh_cr5_compare`, and `otyugh_cr5_monk`'s hand-rolled loops.

## 7. config.py and verification

- `load_toml(path)`, `deep_merge(base, override)` (dict-merge/list-replace — lifted from
  `dnd5e_combat.loader`), `get_path(d, "a.b.c")` / `set_path(d, "a.b.c", v)` for dotted
  overrides and sweep axes, and small validation helpers (`require_keys`,
  `closed_vocab(value, allowed, where)`) shared by game-system loaders.

Acceptance tests shipped with the package:
1. **Coin-flip game**: a 10-line `GameSystem` where two sides flip coins for "damage";
   asserts protocol shape, ledger columns, and that `summarize` matches analytic values.
2. **Determinism**: same seed → byte-identical `ledger.rows` across two runs; trial `i`
   identical whether `trials = i+1` or `trials = 1000`.
3. **Sweep**: a 2-axis sweep over the coin-flip game produces the expected 6 variants and
   a comparison table.
