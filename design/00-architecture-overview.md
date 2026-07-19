# 00 — Architecture Overview

Next-gen rewrite of the D&D Monte Carlo simulation system. Companion docs:

| Doc | Contents |
|---|---|
| [01-toml-schemas.md](01-toml-schemas.md) | Normative creature / board / simulation TOML schemas + worked acid tests |
| [02-simharness.md](02-simharness.md) | Game-agnostic harness: trial runner, ledger, stats, reporting, sweeps |
| [03-dnd5e-engine.md](03-dnd5e-engine.md) | The 5e 2024 rules engine: turn pipeline, conditions, effect primitives |
| [04-behavior-rules.md](04-behavior-rules.md) | Declarative behavior: expression grammar, multiattack selection, reactions, escape hatch |
| [05-migration-plan.md](05-migration-plan.md) | Phases, parity methodology, per-sim migration checklist |
| [06-implementation-guide.md](06-implementation-guide.md) | Operational how-to for the executing agent: commands, skeletons, build order, gotchas |

## Why

The current system (`dnd5e_combat` + ~9 per-sim uv projects under `dnd/`) works but violates
the principles we want going forward:

1. **Behavior is Python, not data.** Every archetype is a `Policy` subclass
   (`dnd5e_combat/src/dnd5e_combat/monsters/otyugh/__init__.py` etc.). Multiattack logic,
   targeting, and reactions are buried in per-monster code.
2. **Layering leaks.** `engine.py` — supposedly the generic combat core — hardcodes
   monster-specific rules: `MARKED_BY_BRUISER` disadvantage and end-of-turn expiry
   (`engine.py` `attack()` / `_end_of_turn`), the Poet's `INSULTED` expiry
   (`_expire_insults`), and the light-plan / photophage machinery (`_produce_light`,
   `light_config`).
3. **Scaffolding duplication.** `tuning.py` is byte-identical across all 7 otyugh sims;
   every `simulation.py` repeats the same load → assemble → run → report skeleton; scenario
   TOMLs copy-paste `[stats.*]` tuning blocks; every sim carries its own
   pyproject/uv.lock/.venv.
4. **Two incompatible creature formats.** The engine's `defaults.toml` format vs the richer
   orphaned authoring prototype `dnd/monsters/masks/masked_troubadour.toml`.

## The three layers

Strict separation, each in its own package. Dependencies point downward only.

```
┌──────────────────────────────────────────────────────────────┐
│  SIMULATIONS (pure data)              sims/<name>/           │
│  simulation.toml + local creatures/, boards/, behavior.py    │
└───────────────┬──────────────────────────────────────────────┘
                │ run by the dnd5e-sim CLI
┌───────────────▼──────────────────────────────────────────────┐
│  GAME SYSTEM (5e 2024 rules)          dnd5e/                 │
│  statblock loading, actions, conditions, effects,            │
│  expressions, declarative behavior, reactions, movement,     │
│  vision, dice.  Implements the GameSystem protocol.          │
└───────┬───────────────────────────────┬──────────────────────┘
        │                               │
┌───────▼───────────────┐   ┌───────────▼──────────────────────┐
│  HARNESS (agnostic)   │   │  BOARD (agnostic)   dnd_board/   │
│  simharness/          │   │  grid, A*, LOS, cover, light —   │
│  TrialRunner, Ledger, │   │  kept as-is + new TOML loader    │
│  stats, report, sweep │   │  (loaders.load_board_toml)       │
└───────────────────────┘   └──────────────────────────────────┘
        │                               │
     looper                      tcod / numpy
   py-die-roller
```

- **`simharness`** knows nothing about D&D. It owns the Monte Carlo loop (trials,
  per-trial seeding, looper wiring), the generic per-trial `Ledger`, statistics
  (including `compare()` used for migration parity testing), rich/matplotlib reporting,
  and the sweep runner. Its only contract with a game is the `GameSystem` protocol
  ([02](02-simharness.md)). SNSS or any other system can implement the same protocol later.
- **`dnd5e`** is the 5e 2024 engine. It parses creature/simulation TOML into frozen
  dataclasses, resolves attacks/saves/damage/conditions, interprets declarative behavior,
  and dispatches reactions. It contains **zero named monsters** — everything creature-
  specific is expressed in data via a closed registry of effect primitives
  ([03](03-dnd5e-engine.md)) and the expression language ([04](04-behavior-rules.md)).
- **`sims/`** are directories of TOML. No pyproject, no venv, no Python (except an
  optional `behavior.py` escape hatch). One CLI runs them all:
  `dnd5e-sim run sims/otyugh_shadow_board/simulation.toml`.

## Repo layout

```
E:\Repos\simulations\
├── pyproject.toml           # uv workspace root ([tool.uv.workspace])
├── design/                  # these docs
├── simharness/              # harness package (src layout)
├── dnd_board/               # KEPT; gains loaders.py (board TOML, no npz step)
├── dnd5e/                   # 5e engine package + `dnd5e-sim` console script
├── dnd5e_data/              # shared TOML library: characters/ monsters/ boards/
│                            #   (a package only so importlib.resources can find it)
├── dnd5e_behaviors/         # Python escape-hatch Behavior classes (04 §5), added Phase 4 —
│                            #   kept separate from both dnd5e (no creature-specific code) and
│                            #   dnd5e_data (data only); "python:dnd5e_behaviors.<mod>.<Class>"
├── sims/                    # pure-data simulations
│   └── <sim_name>/
│       ├── simulation.toml
│       ├── creatures/       # optional sim-local creatures/overrides
│       ├── boards/          # optional sim-local boards
│       └── behavior.py      # optional Python escape hatch (sim-local; shared hatches live in
│                            #   dnd5e_behaviors/ instead — see e.g. shadow_otyugh's)
├── dnd5e_combat/            # OLD — frozen during migration, deleted in phase 6
└── snss/, sim_template/     # out of scope (sim_template retired in phase 6)
```

Dependency wiring (uv workspace members: `simharness`, `dnd_board`, `dnd5e`, `dnd5e_data`,
`dnd5e_behaviors`):

- `simharness` → `looper`, `py-die-roller`, `rich`, `matplotlib`, `numpy`
- `dnd5e` → `simharness`, `dnd_board`, `dnd5e_data`, `dnd5e_behaviors`, `py-die-roller`
- `dnd5e_data` → (nothing; data only)
- `dnd5e_behaviors` → `dnd_board` only — deliberately **not** `dnd5e` (which depends on
  `dnd5e_behaviors`, so its own environment has hatch classes importable at run time; a
  dependency back the other way would be a cycle). Hatch classes interact with `Creature`/
  `Battlefield` via duck typing against `dnd5e.escape_hatch.Behavior`'s protocol, never an
  import of it.
- `simharness` **never** imports `dnd5e`, `dnd_board`, or `dnd5e_behaviors`.

## Decisions log

| # | Decision | Rationale |
|---|---|---|
| D1 | New packages built alongside old code; migrate sims; then retire `dnd5e_combat` | Clean-slate layering without breaking existing sims mid-flight; parity testing against the old engine stays possible until the end |
| D2 | Behavior is declarative TOML rules with a Python escape hatch | Most tactical logic (multiattack choice, targeting, reaction triggers) fits a small condition/priority language; the hatch keeps fidelity for genuinely bespoke logic without polluting the engine |
| D3 | Multiattack = explicitly enumerated action combinations under `[multiattack]`, chosen by `when`/`priority` | Deliberately avoids a general "attack replacement" grammar; enumerating the handful of real combinations per monster is simpler, more obvious, and more maintainable than parsing 5.5e statblock replacement text |
| D4 | Boards are single TOML files with an embedded ASCII map | Human-editable, no compile step, one file to reference from a sim. Reuses the existing `[glyph.*]`/`[meta]` palette format verbatim |
| D5 | Board is always required; abstract front/back mode is deleted | One geometry path in the engine. Formerly-abstract sims get small featureless boards during migration |
| D6 | Sims are pure data run by one CLI | Kills the 9 copies of pyproject/uv.lock/simulation.py/tuning.py |
| D7 | Every creature TOML has a `name`; simulation TOML overrides are keyed by that name | Uniform override mechanism (`[overrides.<name>]`) replaces the copy-pasted `[stats.*]` tuning blocks and `apply_stats` |
| D8 | Parity for migrated sims is statistical, not RNG-identical | The new engine draws dice in a different order by construction; equality of aggregate distributions is the meaningful test (see [05](05-migration-plan.md)) |
| D9 | Closed, validated vocabularies (effect primitives, expression functions) | Unknown names fail at **load time**, never mid-trial; adding vocabulary is a deliberate, tested engine change |

## Where each current hardcoding goes

The acid test of the design: every monster-specific line in today's `engine.py` must land in
data or in a generic mechanism.

| Today (in `dnd5e_combat/engine.py` / policies) | Tomorrow |
|---|---|
| `MARKED_BY_BRUISER` disadvantage-vs-others in `attack()` | Generic custom condition carrying a `impose_disadvantage_except_source` grant, defined in `masked_bruiser.toml` ([01 §creature](01-toml-schemas.md), [03 §conditions](03-dnd5e-engine.md)) |
| Mark expiry at end of turn unless `mark_hit_other` (`_end_of_turn`) | Generic condition clock: `expires = "end_of_bearer_turn"` + `unless = "attacked_other_than_source_this_turn"` predicate ([03 §clocks](03-dnd5e-engine.md)) |
| Mark ends when Bruiser dies | Generic: all conditions with a `source` end when the source dies (`ends_with_source = true`, default for sourced conditions) |
| Poet `INSULTED` expiry round stored in condition value (`_expire_insults`) | Same generic clock system: `expires = "end_of_source_next_turn"` |
| `INSULTED`/`RECKLESS`/`BLINDED` advantage sets (`conditions.GRANTS_ATTACKERS_ADVANTAGE`) | RAW conditions keep built-in meaning; custom conditions declare `grants = [...]` lists the engine consults — it never matches condition names |
| Deceptive Defense interception (`_resolve_interception` + `MaskedBruiser.intercept_attack`) | Generic reaction trigger `ally_targeted_by_attack` + `redirect_attack`/`swap_positions` effect primitives; the "hold for a priority striker" heuristic is expressible in the `when` clause ([04 §reactions](04-behavior-rules.md)) |
| Otyugh grapple-state multiattack branching (policy code) | `[multiattack.*]` options with `when` expressions over `enemies_grappled_by_self` ([01 §otyugh](01-toml-schemas.md)) |
| Photophage darkness aura / `light_config` / `_produce_light` | `[[environment.obscurement]] follows = "<name>"` + `[environment.light_plan]` in the simulation TOML; `emit_light` effect primitive; vision traits (`darkvision`, `limited_darkvision`) on creatures |
| Stun expiry at start of source's next turn (`take_turn`) | Generic clock `expires = "start_of_source_next_turn"` |
| `round_flags` signals (`enemy_crit`, `slam_both_failed`) | `set_flag` effect primitive + `has_flag()` expression function |
| `attacks_per_turn` looped in policies | Multiattack options list the same ability N times (`actions = ["rapier", "rapier"]`) |
| Grapple release on grappler down (`_sync_hp_conditions`) | Stays engine-generic (it already is — RAW grapple rule, no monster names) |
| Death saves, bloodied, focus fire | Stay engine-generic (already generic) |

## Naming conventions

- Package names: `simharness`, `dnd5e`, `dnd5e_data`. The CLI is `dnd5e-sim`.
- TOML file names are the creature's `name` field in snake_case (`otyugh.toml` has
  `name = "otyugh"`); the loader validates the match and fails loudly on mismatch.
- All distances in feet; all durations in rounds or clock keywords ([03](03-dnd5e-engine.md)).
