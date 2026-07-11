# 03 — dnd5e: the 5e 2024 Rules Engine

`dnd5e` implements `simharness.GameSystem` for D&D 5e (2024). It parses the TOML schemas
of [01](01-toml-schemas.md), resolves combat, and interprets the declarative behavior
language of [04](04-behavior-rules.md). Design invariant: **no creature names, no
creature-specific branches anywhere in this package.** Everything a specific monster does
is data plus the closed vocabularies defined here.

```
dnd5e/src/dnd5e/
├── __init__.py
├── cli.py            # `dnd5e-sim run|sweep|validate <simulation.toml>`
├── system.py         # Dnd5eSystem (GameSystem impl) + turn pipeline
├── loader.py         # sim/creature TOML -> validated model; source resolution; overrides
├── statblock.py      # frozen dataclasses: Statblock, Ability, Trait, Reaction,
│                     #   MultiattackOption, ConditionDef, Resource
├── creature.py       # Creature: runtime state (hp, conditions, position, resources)
├── actions.py        # attack / save / heal / utility resolution
├── conditions.py     # RAW condition semantics + custom-condition grants + clocks
├── effects.py        # effect-primitive registry (closed set, §4)
├── expressions.py    # `when` evaluator (04)
├── behavior.py       # declarative interpreter + escape-hatch loading (04)
├── reactions.py      # trigger bus (04 §reactions)
├── movement.py       # named movement tactics over dnd_board
├── vision.py         # LOS / obscurement / darkvision adjudication
├── battlefield.py    # sides, grapple graph, focus; thin facade over dnd_board.Board
└── dice.py           # Resolver over ctx.dice (lift of dnd5e_combat/dice.py)
```

## 1. Loading (`loader.py`, `statblock.py`)

Pipeline: `simulation.toml` → resolve each `creature` reference through the source chain
(sim `sources` paths → sim `creatures/` → `dnd5e_data`) → parse creature TOML →
apply `[overrides.<name>]` via `deep_merge` → validate → freeze into `Statblock`.

Validation (all load-time, all with file/table context in the error):
- closed vocab checks: ability `kind`, effect names, trigger names, tactic names,
  condition clock keywords, terrain/cover names;
- referential checks: every name in `multiattack.*.actions` exists in `[abilities]`;
  every `costs.resource` exists in `[resources]`; every `condition` referenced by
  `attach_condition` is RAW or defined in `[conditions.*]`; `name` matches the file stem;
- expression checks: every `when` / `target_filter` string **parses** and references only
  registered functions/selectors (04) — evaluated lazily, validated eagerly;
- board checks: spawn labels referenced by combatants exist on the board; explicit
  `start` coordinates are in bounds and passable.

`Statblock` and its parts are frozen; all mutation lives in `Creature` (per-trial state:
`current_damage`, `conditions: list[ConditionInstance]`, `x/y`, resource pools, death
saves, `turn_scratch`/`round_scratch`).

## 2. Turn pipeline (`system.py`)

`Dnd5eSystem.take_turn(ctx, actor_id)`:

```
1. tick clocks         start-of-turn expiries (start_of_source_next_turn stuns, ...);
                       roll recharges for the actor's resources
2. sync environment    refresh follow-auras; re-derive obscurement blindness (vision.py)
3. incapacity gates    down -> death save and stop; stunned/incapacitated -> stop
4. reactions: turn_start   fire eligible turn_start-triggered entries (bonus-action
                       swaps like Sleight of Crowd live here)
5. behavior            select multiattack option (04 §selection); for each action:
                       pick target (04 §targeting), move if needed (movement.py),
                       resolve (actions.py), run on_hit/on_fail/on_crit effects
6. end-of-turn clocks  end_of_bearer_turn expiries with their `unless` predicates
```

Reaction triggers fire synchronously from inside resolution (e.g.
`ally_targeted_by_attack` fires from `actions.attack` **before any roll**, so
advantage/reach/cover are computed against the post-redirect target — preserving the
current engine's documented invariant at `engine.py:113-123`).

Trial lifecycle: `setup_trial` resets creatures, rolls hp (per `hp_mode`), places pieces
(spawn labels round-robin, explicit starts win), rolls initiative (`1d20 + bonus`, ties
keep roster order); `is_over` = any side wiped or a `end_trial` effect fired;
`finalize_trial` emits the same outcome columns as today (`down_*`, `dead_*`,
`hp_remaining_*`, `wiped_*`, `any_dead_*`, plus condition counts) so old reports and
parity comparisons line up.

## 3. Conditions (`conditions.py`)

Two tiers, one representation (`ConditionInstance(name, source, clock, data)`):

**RAW conditions** (closed built-in set: blinded, charmed, deafened, frightened, grappled,
incapacitated, invisible, paralyzed, petrified, poisoned, prone, restrained, stunned,
unconscious, plus engine-states down/bloodied/dead) have their mechanics implemented in
engine code — e.g. blinded ⇒ attacker disadvantage + attackers advantage; grappled ⇒
speed 0 and tracked in the grapple graph; stunned ⇒ auto-fail str/dex saves, attackers
advantage. This is fine: they're game rules, not creature rules.

**Custom conditions** are declared in creature TOML under `[conditions.<name>]` and carry
their mechanics as data:

```toml
[conditions.bruisers_mark]
grants = [ { effect = "impose_disadvantage_except_source" } ]
exclusive = "per_source"          # attaching to a new bearer detaches the old one
ends_with_source = true
expires = "end_of_bearer_turn"
unless = "attacked_other_than_source_this_turn"
```

The engine computes advantage/disadvantage by **folding over every condition's grants** —
it never tests condition names. Adding a new marking/insulting/hexing monster requires no
engine change.

**Clocks** (closed keyword set, evaluated by the pipeline's tick steps):
`start_of_source_next_turn`, `end_of_source_next_turn`, `end_of_bearer_turn`,
`end_of_bearer_next_turn`, `rounds:<n>`, `until_cured`. `unless` names a registered
predicate evaluated at expiry time (v1 predicates: `attacked_other_than_source_this_turn`
— tracked generically by `actions.attack` stamping `turn_scratch`). `ends_with_source`
detaches on source down/death (default true for sourced conditions; the grapple graph
release on grappler-down is this same rule).

## 4. Effect primitives (`effects.py`)

The closed registry. Each primitive is a small pure-ish function
`(effect_args, scope) -> None` where `scope` exposes the event participants
(`self`, `target`, `event.*`) and the engine APIs. Referencing an unregistered name is a
load error. v1 set:

| Primitive | Args | Meaning |
|---|---|---|
| `attach_condition` | `condition`, `target?`, `escape_dc?`, `expires?`, `when?` | attach a RAW or custom condition |
| `remove_condition` | `condition`, `target?` | detach |
| `require_save` | `ability`, `dc`, `on_fail`, `on_success?` | nested secondary save |
| `damage_rider` | `damage`, `damage_type?`, `when?` | extra dice on the triggering hit (Hector's +2d6/+3d6) |
| `damage_reroll_keep_best` | `per_turn?` | Savage Attacker-style reroll |
| `grant_advantage_to_attackers` | — | (grant) bearer is easier to hit |
| `grant_advantage_against` | `to` | (grant) named creature gets advantage vs bearer |
| `impose_disadvantage` | — | (grant) bearer attacks at disadvantage |
| `impose_disadvantage_except_source` | — | (grant) disadvantage vs everyone but the condition's source |
| `redirect_attack` | `to` | reaction-only: retarget the pending attack |
| `swap_positions` | `with` | exchange board coordinates |
| `push` | `distance`, `direction?` | forced movement |
| `emit_light` | `radius` | become a light source (clears local obscurement blindness) |
| `limited_darkvision` | `range` | (trait) sight into obscurement capped at range |
| `darkvision_immunity` | — | (trait) unaffected by darkness obscurement |
| `spend_resource` / `restore_resource` | `resource`, `amount?` | pool bookkeeping |
| `set_flag` | `flag`, `scope=round\|trial` | signal bag write (`has_flag()` reads) |
| `end_trial` | `outcome?` | flee/retreat — finalize immediately, merging outcome keys |

Grant-type primitives (`grant_*`, `impose_*`) are only legal inside a condition's
`grants` list or a trait's `effects`; action-type primitives only inside
`on_hit`/`on_fail`/`on_crit`/`on_all_saved`/reaction `effects`. The registry declares
each primitive's legal contexts and validates placement at load.

Growing the vocabulary is a deliberate engine change: registry entry + unit test + a row
in this table.

## 5. Vision, movement, battlefield

- `vision.py` generalizes `dnd5e_combat/battlefield.py`'s obscurement logic: heavy
  obscurement ⇒ blinded (source-tagged so other blindings are untouched), pierced by
  `darkvision_immunity`, range-capped by `limited_darkvision`; `can_see(a, b)` composes
  board LOS + light field + sight traits. No monster names (the current
  `not_blinded_by_obscurement` special-casing becomes trait queries).
- `movement.py` implements the named tactics (`engage`, `kite`, `hold`, `hunt_light`,
  `guard`) as compositions of `dnd_board` primitives (`path`, `reachable`, `step_toward`)
  with occupancy — lifted from `Battlefield.approach/kite/flee_from`. Opportunity attacks:
  leaving a hostile's reach triggers the `enemy_left_reach` reaction (a default
  opportunity-attack reaction is auto-attached to melee creatures, overridable in data).
- `battlefield.py` keeps sides, the grapple graph, and focus; **board is
  constructor-required** — every `board is None` fallback branch from the old facade is
  deleted (decision D5).
- Ranged gating in `actions.attack` reproduces today's semantics: outside reach ⇒ needs
  LOS, full cover auto-misses, half/three-quarters cover adds AC, past normal range ⇒
  disadvantage, past long ⇒ miss.

## 6. The CLI (`cli.py`)

- `dnd5e-sim run <simulation.toml>` — load, validate, run, `print_report`, `save_charts`
  per `[output]`.
- `dnd5e-sim sweep <simulation.toml>` — expand `[sweep]`, run variants, comparison
  table/chart.
- `dnd5e-sim validate <path>` — load-time validation only, for any creature/board/sim
  file (fast feedback while authoring).
- `--seed`, `--trials`, `--out` overrides; `--baseline <rows.json>` runs
  `simharness.stats.compare` against a saved baseline (the migration workflow).

The CLI adds the sim directory to `sys.path` before resolving `python:` escape-hatch
references ([04 §escape-hatch](04-behavior-rules.md)).
