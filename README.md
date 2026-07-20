# simharness v2

A data-driven Monte Carlo harness for tabletop combat simulation. You describe an
encounter in TOML — a board, some creatures, a party — and it runs it thousands of
times and tells you what actually happens: who deals what, who goes down, how often
the party wipes.

The point is **encounter balance**: answering "is this monster fair at CR 5?" or "does
this three-monster network fall apart if you kill the support first?" with numbers
instead of vibes.

```
$ uv run --project dnd5e dnd5e-sim run sims/otyugh_cr5_dps/simulation.toml --trials 1000

            otyugh_cr5_dps - totals (1000 trials)
+----------------------------------------------------------+
| Metric                  |  Mean | Median |   Min |   Max |
|-------------------------+-------+--------+-------+-------|
| Total dealt by monsters |  16.5 |   14.0 |   0.0 |  71.0 |
| Total dealt by party    | 110.4 |  109.0 | 104.0 | 141.0 |
+----------------------------------------------------------+
```

---

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.13+.

```bash
cd simharness_v2
uv sync --all-packages        # NOTE: --all-packages is required, see Gotchas
```

Verify:

```bash
uv run --project dnd5e pytest .                      # ~480 tests
uv run --project dnd5e dnd5e-sim --help
```

## Running simulations

Everything goes through one CLI, `dnd5e-sim`:

```bash
# Run a simulation and print a report
uv run --project dnd5e dnd5e-sim run sims/otyugh_cr5_dps/simulation.toml

# Fewer trials while iterating (overrides the file's own trials/seed)
uv run --project dnd5e dnd5e-sim run sims/masks/simulation.toml --trials 200 --seed 42

# Check a file parses and validates WITHOUT running it — fast authoring loop.
# Accepts a single file or a whole directory.
uv run --project dnd5e dnd5e-sim validate sims/masks/simulation.toml
uv run --project dnd5e dnd5e-sim validate dnd5e_data/src/dnd5e_data/

# Run every variant of a [sweep] block and print a comparison table
uv run --project dnd5e dnd5e-sim sweep sims/otyugh_cr5_compare/simulation.toml
```

`run` also takes `--out <dir>` (chart output) and `--baseline <rows.json>` (compare
against a captured run and exit nonzero if it drifts).

> **Tip:** `validate` is your fast feedback loop. Every expression, effect name, condition
> name and creature reference is checked at load time, so a typo fails immediately with a
> file-and-field error instead of surfacing halfway through 10,000 trials.

## Where things live

| Path | What it is |
|---|---|
| `sims/` | The simulations themselves — pure data. One directory per encounter. |
| `dnd5e_data/` | Shared creature/board library: `characters/`, `monsters/`, `boards/`. |
| `dnd5e/` | The 5e rules engine (turn pipeline, actions, conditions, reactions) + the CLI. |
| `simharness/` | Game-agnostic Monte Carlo core: trial runner, ledger, stats, sweeps, reports. |
| `dnd5e_behaviors/` | Python escape-hatch classes, for behavior TOML can't express. |
| `../dnd_board` | Grid/board package (out-of-tree workspace member): pathing, line of sight, cover. |
| `design/` | Design docs + the known-issues backlog. |

The layering is deliberate: `simharness` knows nothing about D&D, and `dnd5e` contains no
creature-specific code. A monster is data, not a Python class.

## Documentation

- **[SIMULATION.md](SIMULATION.md)** — build a simulation from scratch, author creatures,
  and hook in bespoke Python for new mechanics. **Start here.**
- [docs/creatures.md](docs/creatures.md) — creature TOML reference
- [docs/expressions.md](docs/expressions.md) — the `when` / `target_filter` language
- [docs/effects.md](docs/effects.md) — effects, conditions, and reactions
- [docs/python-hooks.md](docs/python-hooks.md) — escape hatches and new engine primitives
- [docs/boards.md](docs/boards.md) — board TOML
- [design/07-known-issues.md](design/07-known-issues.md) — current parity status and open items

## Interpreting results

Each trial emits a row of outcome columns; the report aggregates them:

| Column | Meaning |
|---|---|
| `dealt_<name>` / `taken_<name>` | Damage dealt / taken by one combatant |
| `side_dealt_<side>` | Total damage dealt by a whole side |
| `down_<name>` / `dead_<name>` | Was this combatant at 0 HP / dead at the end |
| `hp_remaining_<name>` | HP left at the end |
| `wiped_<side>` / `any_dead_<side>` | Whole side down / at least one death |

`[output].report` picks report sections (`totals`, `by_combatant`); `[output].charts`
writes PNGs (`totals_hist`, `dealt_by_combatant`, `taken_by_combatant`).

> **On comparing against old numbers:** the `sims/*/baseline/` files are captures from a
> retired engine, kept for history. They are **not** a correctness target — see the parity
> note at the top of [design/07-known-issues.md](design/07-known-issues.md).

## Determinism

A run is fully reproducible from its seed. The master seed spawns one independent RNG
stream per trial, so trial *i* is identical regardless of how many trials you ask for —
raising `trials` never perturbs earlier trials. Same seed + same data = same numbers.

## Gotchas

These bite people. Worth reading once.

- **`uv sync --all-packages`, always.** A bare `uv sync` at the workspace root syncs only
  the root project's (empty) dependencies and silently uninstalls every workspace member.
- **Pass pytest an explicit path.** Bare `pytest` from the root recurses from the current
  directory and picks up unrelated sibling trees.
- **TOML: top-level keys must come before the first `[table]` header.** Otherwise they get
  silently nested into that table. `tomllib` parsing successfully proves nothing about
  shape — this has bitten this project twice. `dnd5e-sim validate` catches it.
- **TOML inline tables must be on one line.** A `{ ... }` split across lines is a parse
  error. Effect lists get long; keep each entry on a single line.
- **Save files as UTF-8.** The loader reads strict UTF-8; a stray Windows-1252 character
  (a pasted em-dash) fails the file.
