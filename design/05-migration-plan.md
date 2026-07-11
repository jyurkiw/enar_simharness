# 05 — Migration & Implementation Plan

Phased build of the new system with per-phase verification, ending with the retirement of
`dnd5e_combat`, the per-sim project scaffolding, and `sim_template`.

> **Executing agent: this doc defines the phases and their acceptance criteria; the
> step-by-step instructions (commands, file skeletons, build order within each phase,
> gotchas) are in [06-implementation-guide.md](06-implementation-guide.md). Work from 06,
> verify against 05.**

## Parity methodology

The new engine draws dice in a different order by construction (per-trial spawned streams,
different resolution sequencing), so old-vs-new can never be RNG-identical. Parity is
**statistical equivalence of the outcome distributions**:

- Run both engines at the sim's original scenario values with **trials ≥ 10,000**
  (temporarily raising sims configured lower).
- Compare with `simharness.stats.compare` on: `side_dealt_<side>` (both sides),
  `dealt_<name>` / `taken_<name>` per combatant, `wiped_<side>`, `any_dead_<side>`,
  and any sim-specific outcome columns (`retreated`, `poisoned_*`).
- **Tolerances: relative Δmean ≤ 3%; relative Δ at p10/p50/p90 ≤ 5%** (binary-rate columns
  like `wiped_*` compare as absolute percentage-point deltas ≤ 2pp).
- A failure means a semantic difference — diagnose it; either the data expression is wrong
  (fix the TOML), the new engine has a bug (fix it), or the old behavior was itself a bug
  we're deliberately not preserving (document it in the sim's README and re-baseline).

### Baseline capture (before anything else changes)

A throwaway script (`scratch/capture_baselines.py`, run once per sim) that runs each old
sim at 10k trials with its scenario seed and dumps `ledger.rows` to
`sims/<name>/baseline/rows.json` plus the printed report to `report.txt`. These files are
committed and are the comparison targets for `dnd5e-sim run --baseline`.

Formerly-abstract sims get their board authored **before** baseline capture is compared —
the board (a featureless room sized so front-liners close in round 1 and back-liners sit
at their old effective ranges, mirroring the front/back semantics) is part of the migrated
sim's definition, and small distributional shifts from geometry are expected and
documented per sim.

## Phases

Each phase lands with its tests green and everything previously migrated still passing.

### Phase 0 — Workspace + baselines
- Root `pyproject.toml` with `[tool.uv.workspace]`; `design/` docs (this set) committed.
- Capture baselines for all 9 sims (list below).
- Fix the `masked_troubadour.toml` TOML syntax error (line 38 unquoted string) so nothing
  in-tree is invalid TOML.
- **Verify:** every old sim still runs; baselines exist and re-run reproducibly.

### Phase 1 — `simharness`
- `plugin.py`, `runner.py`, `ledger.py`, `stats.py`, `report.py`, `sweep.py`, `config.py`
  per [02](02-simharness.md).
- **Verify:** coin-flip acceptance game; determinism tests (same seed ⇒ identical rows;
  trial *i* stable under trial-count changes); sweep expansion test; `compare()`
  self-test (a run compared with itself passes at 0 tolerance).

### Phase 2 — Board TOML
- `dnd_board.loaders.load_board_toml` per [01 §2](01-toml-schemas.md); rectangularity and
  vocab validation; default-palette inheritance; `boardtool view --toml`.
- Author boards: `dnd5e_data/boards/arena.toml` (port of `arena.txt`) + featureless rooms
  for the abstract sims.
- **Verify:** round-trip test — `arena.toml` loads to a `Board` equal (all layers, spawns,
  meta) to the boardtool-compiled `arena.npz`; existing `dnd_board` test suite untouched
  and green.

### Phase 3 — `dnd5e` core + first sim
- `loader/statblock/creature/actions/conditions(RAW)/movement/vision/battlefield/dice/
  system/cli` per [03](03-dnd5e-engine.md) — declarative behavior limited to
  `action_priority` + implicit multiattack (no expressions yet).
- Convert to new creature TOML: the 9 characters + the plain otyugh + board_demo's three
  inline PCs (fighter/barbarian/archer → sim-local `creatures/`).
- Migrate **board_demo** (`sims/board_demo/`).
- **Verify:** unit tests per module (attack math incl. cover/range bands, save halving,
  death saves, grapple release on down, condition clocks); `dnd5e-sim validate` over all
  converted files; board_demo parity vs baseline.

### Phase 4 — Expressions + declarative behavior + otyugh family
- `expressions.py` (parser + registries), `behavior.py` (multiattack selection §2,
  targeting §3 of [04](04-behavior-rules.md)), environment auras/light_plan,
  `set_flag`/`has_flag`, `end_trial` (shadow-otyugh retreat), escape-hatch loading.
- Migrate all 7 otyugh sims; compare-style sims (`otyugh_cr5_compare`, `otyugh_cr5_monk`)
  become `[sweep]`-driven single sims.
- **Verify:** expression parser property tests (round-trip, precedence, load-time unknown-
  identifier rejection); multiattack selection unit tests against the three otyugh grapple
  states; per-sim parity; sweep output matches the old comparison tables' numbers within
  tolerances.

### Phase 5 — Reactions + masks
- `reactions.py` trigger bus; `redirect_attack`/`swap_positions`; custom conditions with
  `grants`/`exclusive`/`unless` clocks (Bruiser mark, Poet insult); recharge resources;
  `reduce_damage` primitive if the party build needs Uncanny Dodge (flagged in
  [04 §4](04-behavior-rules.md)); escape-hatch `behavior.py` for the Bruiser's
  mark-exploitability heuristic if (and only if) parity demands it.
- Migrate **masks** (including its network-value custom stats — these become a small
  registered report section, not a bespoke script).
- **Verify:** interpose ordering test (reaction fires pre-roll; adv/disadv/cover computed
  post-swap); mark lifecycle tests (exclusivity, ends-with-source, `unless` predicate);
  masks parity vs baseline.

### Phase 6 — Retirement
- Delete `dnd5e_combat/`, every old `dnd/<sim>/` project tree (READMEs and result PNGs
  worth keeping move into the new `sims/<name>/`), `sim_template/`.
- **Verify:** `grep -r "dnd5e_combat\|sim_template"` finds nothing outside `design/`;
  full workspace test run green; every sim in the checklist runs via `dnd5e-sim run`;
  a fresh `uv sync` from a clean clone works.

## Per-sim migration checklist

| # | Old sim | New sim | Board | Notes |
|---|---|---|---|---|
| 1 | `dnd/board_demo` | `sims/board_demo` | port of `arena` | Phase 3; inline PCs → sim-local creature files |
| 2 | `dnd/otyugh/otyugh_cr5_dps` | `sims/otyugh_cr5_dps` | featureless room | Phase 4 |
| 3 | `dnd/otyugh/otyugh_cr5_x2` | `sims/otyugh_cr5_x2` | featureless room | Phase 4; `count = 2`; pack-rule targeting expression — escape hatch if parity fails |
| 4 | `dnd/otyugh/otyugh_cr5_compare` | `sims/otyugh_cr5_compare` | featureless room | Phase 4; two scenarios → one sim + `[sweep]` over party |
| 5 | `dnd/otyugh/otyugh_cr5_monk` | `sims/otyugh_cr5_monk` | featureless room | Phase 4; 4 scenarios → `[sweep]` (party × count) |
| 6 | `dnd/otyugh/otyugh_shadow_solo` | `sims/otyugh_shadow_solo` | featureless room | Phase 4; retreat = `end_trial` effect |
| 7 | `dnd/otyugh/otyugh_shadow_pair` | `sims/otyugh_shadow_pair` | featureless room | Phase 4 |
| 8 | `dnd/otyugh/otyugh_shadow_board` | `sims/otyugh_shadow_board` | port of its board | Phase 4; darkness aura + light_plan already data-shaped |
| 9 | `dnd/masks` | `sims/masks` | featureless room (or authored arena) | Phase 5; Bruiser/Poet/Hector; `scaling.py` → `[sweep]`; custom network stats → registered report section |

Per-sim procedure: author/port board → convert creatures → write `simulation.toml` with
`[overrides]` replacing the old `[stats.*]` block → `dnd5e-sim validate` →
`dnd5e-sim run --baseline baseline/rows.json` → investigate failures per the methodology →
commit with the parity report in the sim's README.

## Risks and mitigations

- **Expression language scope creep.** Mitigation: the vocabulary is closed and grows only
  via the design-pressure rule ([04 §5](04-behavior-rules.md)); anything exotic goes to
  the escape hatch first.
- **Parity failures from board-always (D5).** The formerly-abstract sims will shift
  slightly (movement rounds, opportunity attacks). Mitigation: featureless-room boards
  sized to reproduce old effective ranges; documented, re-baselined deltas where geometry
  legitimately changes outcomes.
- **Old-policy quirks that resist declarative expression** (Bruiser reaction-holding,
  otyugh pack rule). Mitigation: the escape hatch is a first-class, tested mechanism —
  fidelity never blocks on the language.
- **`dieroller.spawn` stream independence.** Verify statistically in Phase 1 (cross-trial
  correlation test) before building on it.
