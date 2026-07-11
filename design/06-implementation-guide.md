# 06 — Implementation Guide (for the executing agent)

This document is the **operational companion** to [05-migration-plan.md](05-migration-plan.md).
Doc 05 says *what* each phase delivers; this doc says *exactly how to do it* — commands,
file skeletons, ordering, and gotchas. It assumes the executor has NOT read the old
codebase and will not re-derive design decisions.

> **Workspace root note (set during Phase 0):** the new workspace root is
> `E:\Repos\simulations\simharness_v2\` — a separate, already git-initialized directory
> sibling to the old `dnd/`, `dnd5e_combat/`, etc. (which remain at `E:\Repos\simulations\`).
> This doc and doc 05 were originally written assuming the bare repo root
> (`E:\Repos\simulations\`) would be the new root; wherever a path below reads like
> `pyproject.toml`, `sims/`, `dnd5e_data/`, etc. relative to "repo root," resolve it against
> `simharness_v2/` instead. Old-sim paths (`dnd/board_demo`, `dnd5e_combat/`, ...) are
> unaffected — they're still at the top-level `E:\Repos\simulations\`.

## How to use this guide

- Execute **one phase per work session**. Do not start a phase until the previous phase's
  "Definition of done" checklist is fully green.
- Before writing any code in a phase, read the design docs listed in that phase's
  "Read first" line. The design decisions are already made — **do not redesign**. If a
  needed detail is genuinely missing from docs 00–05, STOP and ask the user; do not invent
  schema keys, expression functions, or effect primitives (the vocabularies in
  [01](01-toml-schemas.md)/[03](03-dnd5e-engine.md)/[04](04-behavior-rules.md) are closed).
- Never modify anything under `dnd5e_combat/`, `dnd/`, or `sim_template/` before Phase 6,
  with one exception: the Phase 0 fix to `dnd/monsters/masks/masked_troubadour.toml`.

## Global gotchas (read before every phase)

1. **TOML**: inline tables `{ ... }` must fit on ONE line (TOML 1.0). Use
   `[[table.array]]` syntax for anything longer. Parse with `tomllib` — files open in
   **binary** mode (`open(path, "rb")`).
2. **looper API**: `Looper(context=obj, exit_value_name="attr")`;
   `loop.add_event(name, add_before=False, add_after=False)`;
   `loop.register(event, handler)`; handler signature is
   `handler(event: str, dt: int, context, **payload) -> None`. One `loop` pass runs every
   registered event once, in add order. Source lives in any sim venv at
   `.venv/Lib/site-packages/looper/_loop.py` if you need to check behavior.
3. **dieroller API**: `Dice(seed=...)`, `.roll("2d8+3") -> int`, `.spawn(n) -> list[Dice]`
   (independent streams). Source: `.venv/Lib/site-packages/dieroller/`.
4. **dnd_board coordinates**: public API is `(x, y)` = (col, row); the numpy layers are
   `(H, W)` indexed `[y, x]`. This is documented in `dnd_board/src/dnd_board/grid.py`.
   Getting this backwards produces transposed maps that still "work" on square boards.
5. **Windows**: this repo is on Windows. Use `pathlib.Path` everywhere; never hardcode
   `/` or `\\` separators; be careful that generated scripts run under PowerShell.
6. **uv**: run things inside a project's environment with
   `uv run --project <dir> python <script>`. After editing any `pyproject.toml`, run
   `uv sync` in that project. Workspace members share one lock file at the root.
7. **Determinism**: ALL randomness must flow through the per-trial `Dice` stream handed to
   the game system. If you ever reach for `random`, `numpy.random`, or a fresh `Dice()`,
   that is a bug.
7a. **Hidden nondeterminism via unordered `set` iteration (confirmed in Phase 0).** The
   OLD engine's `dnd5e_combat.battlefield.Battlefield._grapples` is a
   `dict[str, set[str]]`, and `grabbed_targets()` returns `list(self._grapples[grappler])`
   — a Python `set`'s iteration order depends on string hashes, which are randomized
   per-process (`PYTHONHASHSEED`) unless pinned. The Otyugh's policy consumes that order
   to decide *which* grappled target it bites/slams first, so two runs of the identical
   scenario + seed diverge (same total damage dealt, different per-target split) starting
   at whichever trial first involves a multi-target grapple — confirmed by bisecting a
   10k-trial baseline capture where trial 12 was the first divergence. Fix used for
   baseline capture: run with `PYTHONHASHSEED=0` (both `scratch/capture_baseline.py` and
   `scratch/capture_masks_baseline.py` now refuse to run without it set, and record it in
   `meta.json`). **This is a real hazard for the new `dnd5e` package**: nothing in
   `creature.py`/`battlefield.py`/`conditions.py` (grapple graph, condition lists,
   targeting pools, `enemies_grappled_by_self` set selector) may use a plain `set()` (or
   dict/set comprehension) for any collection whose iteration order can influence which
   ability fires, which target is picked, or the sequence of `ctx.dice.roll()` calls. Use
   a `list`, an insertion-ordered `dict` used as an ordered set, or explicitly `sorted()`
   the collection before iterating. Add a test in Phase 3 that runs a grapple-involving
   scenario twice **without** pinning `PYTHONHASHSEED` and asserts identical ledgers —
   this is the regression test for this exact class of bug.
8. **Lifting old code**: docs point at old files to "lift" (e.g. `dnd5e_combat/ledger.py`).
   Lift means: copy the logic, rename per the new design, strip 5e-specific assumptions
   where the doc says so, and write tests. Do not import from `dnd5e_combat` in new
   packages — ever.

---

## Phase 0 — Workspace + baselines

**Read first:** [05 §Baseline capture](05-migration-plan.md), this section.

### Step 0.1 — Fix the invalid TOML file

**Status: done.** `dnd/monsters/masks/masked_troubadour.toml` had its unquoted string
fixed on **line 37** (`name = Flowery Mark` → `name = "Flowery Mark"`) — one line earlier
than originally estimated; always re-locate by content, not line number. Verified with
`tomllib.load`.

### Step 0.2 — Workspace root pyproject

**Status: done**, at `simharness_v2\pyproject.toml` (not the bare repo root — see the
workspace root note above). One gotcha hit during Phase 0: **do not create/`uv sync` a
pyproject at the bare repo root** — there was already an unrelated `.venv` there (scratch
tooling, `sim-template-cli` etc.) with no `pyproject.toml` of its own; running `uv sync`
against a newly-created root pyproject with empty `members` silently uninstalled every
package from that pre-existing `.venv` to match the (empty) lockfile. Always run
`Get-ChildItem -Force` on a directory before writing a `pyproject.toml`/running `uv sync`
in it, and stop to ask if a `.venv` or other unexplained state is already there.

For reference, the pyproject content used:

```toml
[project]
name = "simulations-workspace"
version = "0.1.0"
requires-python = ">=3.13"

[tool.uv.workspace]
members = []    # simharness, dnd5e, dnd5e_data added in later phases
```

Do **not** add the old sims or `dnd5e_combat` as members — they keep their standalone
venvs until retirement. `dnd_board` becomes a member in Phase 2.

### Step 0.3 — Baseline capture

**Status: done.** The scripts and all 13 baseline rows exist at
`simharness_v2/scratch/capture_baseline.py`, `simharness_v2/scratch/capture_masks_baseline.py`,
and `simharness_v2/sims/*/baseline/{rows.json,meta.json}`. Read the scripts directly rather
than a skeleton here — they diverged from the original sketch in one important way
(below). If baselines ever need recapturing, reuse these scripts as-is.

**PYTHONHASHSEED is mandatory.** Both scripts refuse to run unless `PYTHONHASHSEED` is set
in the environment, and record its value in `meta.json`. This was not in the original
plan — it was discovered empirically during Phase 0 (see Global Gotcha 7a above): the old
engine's grapple bookkeeping uses a `set`, so without a pinned hash seed, two captures of
the same scenario/seed silently disagree starting at the first multi-target-grapple trial.
Always invoke as `PYTHONHASHSEED=0 uv run python scratch/capture_baseline.py ...`.

Each sim's `main()` was read before writing the scripts to confirm the exact cfg-mutation
pattern (`cfg["encounter"]["monster"] = apply_stats(cfg["encounter"]["monster"], cfg.get("stats", {}))`,
identical across every otyugh/board_demo sim) — do the same before reusing or extending
these scripts for any new sim.

Capture matrix — one baseline row per scenario variant (all captured):

| Run from | Scenario file | Label | --stats? |
|---|---|---|---|
| `dnd/board_demo` | `src/scenario.toml` | `board_demo` | no |
| `dnd/otyugh/otyugh_cr5_dps` | `src/scenario.toml` | `otyugh_cr5_dps` | yes |
| `dnd/otyugh/otyugh_cr5_x2` | `src/scenario.toml` | `otyugh_cr5_x2` | yes |
| `dnd/otyugh/otyugh_cr5_compare` | `src/scenario_standard.toml` | `otyugh_cr5_compare/standard` | yes |
| `dnd/otyugh/otyugh_cr5_compare` | `src/scenario_vanguard.toml` | `otyugh_cr5_compare/vanguard` | yes |
| `dnd/otyugh/otyugh_cr5_monk` | `src/scenario_standard_1x.toml` | `otyugh_cr5_monk/standard_1x` | yes |
| `dnd/otyugh/otyugh_cr5_monk` | `src/scenario_standard_2x.toml` | `otyugh_cr5_monk/standard_2x` | yes |
| `dnd/otyugh/otyugh_cr5_monk` | `src/scenario_monk_1x.toml` | `otyugh_cr5_monk/monk_1x` | yes |
| `dnd/otyugh/otyugh_cr5_monk` | `src/scenario_monk_2x.toml` | `otyugh_cr5_monk/monk_2x` | yes |
| `dnd/otyugh/otyugh_shadow_solo` | `src/scenario.toml` | `otyugh_shadow_solo` | yes |
| `dnd/otyugh/otyugh_shadow_pair` | `src/scenario.toml` | `otyugh_shadow_pair` | yes |
| `dnd/otyugh/otyugh_shadow_board` | `src/scenario.toml` | `otyugh_shadow_board` | yes |
| `dnd/masks` | see below | `masks/<party>_<strategy>` | yes |

**masks special case:** `dnd/masks/src/simulation.py` loops over party × strategy variants
mutating cfg between runs. Read that file, find the variant loop, and capture one baseline
per variant using the same mutation code (easiest: temporarily copy the loop into a
`capture_masks.py` beside it that dumps `ctx.ledger.rows` per variant instead of charts).
Do not modify `simulation.py` itself.

### Definition of done (Phase 0)
- [ ] `masked_troubadour.toml` parses.
- [ ] Root `pyproject.toml` exists; `uv sync` at root succeeds.
- [ ] `sims/<label>/baseline/rows.json` + `meta.json` exist for every row of the matrix.
- [ ] Running capture twice for one sim produces identical `rows.json` (determinism).
- [ ] Every old sim still runs unmodified (`uv run python src/simulation.py` in each dir).

---

## Phase 1 — `simharness`

**Read first:** [02-simharness.md](02-simharness.md) end to end.

Build order (each module + its tests before the next):
`config.py` → `ledger.py` → `stats.py` → `plugin.py` → `runner.py` → `report.py` → `sweep.py`.

Setup: `uv init --package simharness` (src layout), add to workspace members, deps:
`looper`, `py-die-roller` (both via `[tool.uv.sources]` git refs — copy the source lines
from `dnd5e_combat/pyproject.toml`), `rich`, `matplotlib`, `numpy`. Dev dep: `pytest`.

What to lift from where:
- `config.deep_merge` ← `dnd5e_combat/src/dnd5e_combat/loader.py` (`deep_merge`), plus new
  `get_path`/`set_path` for dotted keys.
- `ledger.Ledger` ← `dnd5e_combat/src/dnd5e_combat/ledger.py`; replace its hardcoded side
  handling with a `side_of: Callable[[str], str]` constructor arg.
- `report.py` ← `dnd5e_combat/src/dnd5e_combat/report.py`; split each table/chart into a
  registered section/chart function (registry = module-level dict + `register_*` helpers).
- `runner.TrialRunner` — new code per [02 §2](02-simharness.md); event names exactly
  `begin_round`, `take_turn`, `advance`.

The coin-flip acceptance game ([02 §7](02-simharness.md)) lives in
`simharness/tests/test_acceptance_coinflip.py` and is the template consumers follow —
write it carefully.

### Definition of done (Phase 1)
- [ ] `uv run --project simharness pytest` green.
- [ ] Coin-flip game runs 1000 trials; `summarize` matches analytic mean within 3σ.
- [ ] Determinism tests pass ([02 §7](02-simharness.md) items 2).
- [ ] Stream-independence check: correlation between trial-stream outputs ≈ 0
      ([05 §Risks](05-migration-plan.md)).
- [ ] `compare(rows, rows)` passes at zero tolerance.

---

## Phase 2 — Board TOML

**Read first:** [01 §2](01-toml-schemas.md); skim `dnd_board/src/dnd_board/fileio.py`
(`parse_ascii`) and `palette.py` (`load_palette`) — the new loader is a thin composition
of those two.

Steps:
1. Add `dnd_board` to workspace members (keep its own tests running).
2. New `dnd_board/src/dnd_board/loaders.py`: `load_board_toml(path) -> Board`. Read the
   TOML; build a `Palette` from `[meta]` + `[glyph.*]` (reuse `_cell_from_spec`; merge
   over `default_palette()` when glyphs are omitted); split the `map` string into lines
   (strip one leading/trailing blank line only); validate rectangularity; feed to
   `parse_ascii`.
3. Export from `__init__.py`.
4. Port `data/boards/arena.txt` → `dnd5e_data/boards/arena.toml` (create the
   `dnd5e_data` package now: `uv init --package dnd5e_data`, no code, package data only).
5. Author featureless-room boards for the abstract sims (see [05 §Baseline capture]
   guidance): a walled rectangle sized so melee closes in round 1 (party spawns ~25–30 ft
   from monster spawns) with `P`/`M` spawn glyphs. One shared
   `dnd5e_data/boards/plain_room.toml` is fine unless a sim's parity requires a variant.

### Definition of done (Phase 2)
- [ ] Round-trip test green: `load_board_toml(arena.toml)` equals the Board from
      `load_npz(arena.npz)` — compare all four numpy layers, `spawns`, `cell_feet`,
      `diagonal`.
- [ ] Ragged map, unknown glyph key, unknown terrain each raise a load error naming the
      file (tests).
- [ ] Existing `dnd_board` test suite untouched and green.

---

## Phase 3 — `dnd5e` core + board_demo

**Read first:** [03-dnd5e-engine.md](03-dnd5e-engine.md) fully; [01 §1](01-toml-schemas.md)
for the creature schema; [04 §2–3](04-behavior-rules.md) only for the *shape* of behavior
(expressions themselves are Phase 4 — in Phase 3 the only behavior is
`behavior.action_priority` + implicit single multiattack + `tactic`).

Build order: `dice.py` (lift `dnd5e_combat/dice.py`, wrap the ctx stream) →
`statblock.py` → `loader.py` (creature only) → `creature.py` → `battlefield.py` →
`vision.py` → `movement.py` (tactics: `engage`, `kite`, `hold` only) → `conditions.py`
(RAW only) → `actions.py` → `system.py` → `loader.py` (simulation files) → `cli.py`.

Semantics to preserve exactly (all currently in `dnd5e_combat/src/dnd5e_combat/engine.py`
— open it and read the named method before implementing each):
- attack advantage/disadvantage folding and cancellation (`attack`)
- ranged gating: reach → LOS → full cover auto-miss → cover AC bonus → range bands
  (`attack`, lines with `cover_bonus`)
- save-for-half (`simple_attack`), death saves (`_roll_death_save`), instant death on
  massive overkill, down/bloodied sync + grapple release (`_sync_hp_conditions`)
- initiative: `1d20 + bonus`, ties keep roster order (`_start_trial`)

Data conversion: create `dnd5e_data/characters/*.toml` for the 9 archetypes by
translating each `dnd5e_combat/src/dnd5e_combat/characters/<arch>/defaults.toml` into the
[01 §1] schema, and `dnd5e_data/monsters/otyugh.toml` from
[01 §1.11](01-toml-schemas.md) (already written — copy it). board_demo's three inline PCs
become `sims/board_demo/creatures/{fighter,barbarian,archer}.toml`.
Character features that were Python policy code (Savage Attacker, GWF reroll, sneak-attack
riders, monk flurry, cleric heal timing) translate to traits/effects **only where the v1
primitive table covers them** ([03 §4]); where it doesn't, note the gap in the creature
file as a `# TODO(phaseN)` comment and simplify — board_demo's PCs don't use any of them,
and the full character fidelity is only needed by the sims that use those archetypes
(check each sim's scenario before assuming).

Then: write `sims/board_demo/simulation.toml` per [01 §3], run
`dnd5e-sim validate`, `dnd5e-sim run --baseline sims/board_demo/baseline/rows.json`.

### Definition of done (Phase 3)
- [ ] Module unit tests green (attack math incl. cover/range-band cases, save halving,
      death-save table, grapple release on down, hp_mode average vs rolled).
- [ ] `dnd5e-sim validate` passes on every file in `dnd5e_data/` and `sims/board_demo/`.
- [ ] Load-time failure tests: unknown ability kind, unknown effect, multiattack
      referencing a missing ability, name/file-stem mismatch — each raises with path+table.
- [ ] board_demo parity: `compare` within tolerances of [05 §Parity].

---

## Phase 4 — Expressions + behavior + otyugh family

**Read first:** [04-behavior-rules.md](04-behavior-rules.md) fully (the grammar and both
registries are normative — implement exactly, add nothing).

Build order: `expressions.py` (lexer → parser → load-time validation → evaluator; test
each stage) → `behavior.py` (multiattack selection [04 §2], targeting [04 §3]) →
environment (`[[environment.obscurement]]` incl. `follows` auras, `light_plan`,
`emit_light`) → `set_flag`/`has_flag` → `end_trial` → escape-hatch loading ([04 §5]).

Old-code references for exact semantics: aura refresh + blinded sync ←
`dnd5e_combat/battlefield.py` (`refresh_auras`, `not_blinded_by_obscurement`) and
`engine.py` (`_sync_obscurement`, `_produce_light`); shadow-otyugh retreat ← its policy in
`dnd5e_combat/src/dnd5e_combat/monsters/shadow_otyugh/__init__.py` (the `force_trial_end`
path becomes the `end_trial` effect).

Migrate the 7 otyugh sims per the [05 checklist](05-migration-plan.md) rows 2–8, in that
order (dps first — it's the simplest; shadow_board last — it exercises everything).
`otyugh_cr5_compare` and `otyugh_cr5_monk` become one sim each with `[sweep]`; their
parity target is each captured variant baseline (`baseline/` subdirs from Phase 0).

Parity escalation rule (applies here and Phase 5): if a sim fails parity, first re-read
the old policy file for that monster and check the TOML expresses each branch; second,
suspect the new engine (add a targeted unit test); only third, conclude the old behavior
is unreproducible declaratively and write the escape hatch — and record in the sim README
which missing vocabulary forced it ([04 §5] design-pressure rule). Never widen the
tolerances.

### Definition of done (Phase 4)
- [ ] Expression tests: precedence, parenthesization, every registry function, unknown
      identifier rejected at load, `it`-binding in `any`/`all`.
- [ ] Multiattack selection unit tests: the three otyugh grapple states pick
      `slam_two`/`bite_and_grab`/`grab_two`; empty-resource option ineligibility;
      duplicate-priority load error; fallback warning path.
- [ ] All 7 otyugh sims migrated, `dnd5e-sim validate` clean, parity green per variant.
- [ ] Sweep sims reproduce old comparison numbers within tolerances.

---

## Phase 5 — Reactions + masks

**Read first:** [04 §4](04-behavior-rules.md), [03 §3–4](03-dnd5e-engine.md), and the
three mask policies in `dnd5e_combat/src/dnd5e_combat/monsters/masked_{bruiser,poet,hector}/__init__.py`
(with their `defaults.toml`) — the doc examples in [01 §1.12] cover the Bruiser; the Poet
and Hector must be translated the same way.

Build order: custom conditions (`[conditions.*]` — `grants`, `exclusive`,
`ends_with_source`, `expires`, `unless`) → `reactions.py` trigger bus →
`redirect_attack`/`swap_positions` → recharge resources → Hector's conditional
`damage_rider` → masks migration (network-value stats become a registered report section
in the sim… no: registered via a small `sims/masks/report_sections.py` loaded by the CLI
alongside the escape hatch, same `python:` mechanism).

The one ordering invariant that MUST have a test before anything else in this phase:
`ally_targeted_by_attack` reactions complete (including position swaps) **before** the
attack computes advantage/disadvantage, reach, cover, and range. The old engine documents
this at `engine.py` `attack()` — read the comment block there.

### Definition of done (Phase 5)
- [ ] Interpose ordering test green (assert the roll used post-swap positions/cover).
- [ ] Mark lifecycle tests: `per_source` exclusivity, `ends_with_source`, `unless`
      predicate keeps/sheds the mark correctly, reaction economy (one reaction/round).
- [ ] Poet insult expiry test (`end_of_source_next_turn`).
- [ ] masks migrated; parity green per captured variant; any escape hatch documented in
      `sims/masks/README.md`.

---

## Phase 6 — Retirement

**Read first:** [05 Phase 6](05-migration-plan.md).

Order matters: (1) move keep-worthy READMEs/PNGs into `sims/<name>/`; (2) delete
`dnd5e_combat/`, `dnd/` project trees (keep `dnd/monsters/masks/masked_troubadour.toml`
only if the Troubadour hasn't been converted to `dnd5e_data/monsters/` — prefer
converting then deleting), `sim_template/`; (3) `uv sync` from clean; (4) full test run;
(5) `grep -r "dnd5e_combat|sim_template" --include="*.py" --include="*.toml"` over the
repo (excluding `design/` and `sims/*/baseline/meta.json`) must be empty; (6) run every
sim in the checklist via `dnd5e-sim run`.

This phase deletes code permanently — **confirm with the user before step (2)**.

### Definition of done (Phase 6)
- [ ] All checklist sims run green via `dnd5e-sim run` from a fresh clone + `uv sync`.
- [ ] Grep clean; workspace tests green; old directories gone.
