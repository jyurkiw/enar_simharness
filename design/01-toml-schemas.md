# 01 — TOML Schemas

Normative schemas for the three data file types: **creature**, **board**, **simulation**.
Expression syntax used in `when = "..."` strings is defined in
[04-behavior-rules.md](04-behavior-rules.md); effect primitives referenced in `effects`,
`on_hit`, etc. are defined in [03-dnd5e-engine.md](03-dnd5e-engine.md).

Validation philosophy (applies to every schema): closed vocabularies. Unknown keys, unknown
`kind` values, unknown effect primitives, and unknown expression functions are **load-time
errors** with the file path and table name in the message. A simulation never crashes
mid-trial because of a typo in data.

---

## 1. Creature files (characters and monsters)

One file per creature. Characters and monsters share the same schema — "character" vs
"monster" is decided by which `side` a simulation assigns the creature to, not by the file.

### 1.1 Top level

```toml
name = "otyugh"              # REQUIRED. Canonical key: must match the file stem;
                             # used by [overrides.<name>] in simulation files.
display_name = "Otyugh"      # optional; defaults to title-cased name
```

### 1.2 `[classification]` — descriptive, not mechanical

```toml
[classification]
size = "Large"               # Tiny|Small|Medium|Large|Huge|Gargantuan
type = "Aberration"
alignment = "Neutral"
cr = 5                       # number; characters may use `level` instead
tags = ["tank"]              # free-form role tags, referenced by expressions (has_tag)
```

### 1.3 `[stats]` — flat key-value pairs

```toml
[stats]
strength = 16                # the six ability SCORES (modifiers are derived)
dexterity = 11
constitution = 19
intelligence = 6
wisdom = 13
charisma = 6
ac = 14
speed = 30                   # feet
initiative_bonus = 0         # optional; defaults to dex modifier
proficiency = 3              # optional; defaults from cr/level
crit_range = 20              # optional (Champion Fighter: 19)
reach = 5                    # optional default melee reach in feet

[stats.health]
hit_dice = "12d10+48"        # dieroller code; used when hp_mode = "rolled"
average = 114                # used when hp_mode = "average" (the default)

[stats.saves]                # only proficient/special saves; others derive from scores
constitution = 7

[stats.skills]               # optional
perception = 4

[stats.senses]
darkvision = 120             # feet; absent = none. See traits for limited_darkvision.
passive_perception = 11
```

Derivation rules (loader computes, data may override): ability modifier =
`(score - 10) // 2`; unlisted save = ability modifier; `initiative_bonus` = dex mod.

### 1.4 `[abilities.*]` — everything the creature can actively do

Each ability is a named table. `kind` is a closed set: `attack`, `save`, `heal`, `utility`.

```toml
[abilities.bite]
kind = "attack"
to_hit = 6
damage = "2d8+3"             # dieroller code
damage_type = "piercing"
reach = 5                    # overrides stats.reach for this ability

# on_hit: effect primitives applied when the attack hits (after damage).
# Short effects may be written inline (`on_hit = [ { effect = "...", ... } ]`);
# longer ones use array-of-tables — the two forms are equivalent TOML.
[[abilities.bite.on_hit]]
effect = "require_save"
ability = "con"
dc = 15
on_fail = [ { effect = "attach_condition", condition = "diseased" } ]

[abilities.tentacle]
kind = "attack"
to_hit = 6
damage = "1d8+3"
damage_type = "bludgeoning"
reach = 10
target_filter = "not is_grappled_by(target, self)"   # optional eligibility expression
on_hit = [
  { effect = "attach_condition", condition = "grappled", escape_dc = 13 },
]

[abilities.tentacle_slam]
kind = "save"
ability = "con"              # the TARGET rolls this save
dc = 14
damage = "2d10+3"
damage_type = "bludgeoning"
half_on_save = true
targets = "enemies_grappled_by_self"   # selector (04 §selectors); default "chosen"
max_targets = 2

[[abilities.tentacle_slam.on_fail]]
effect = "attach_condition"
condition = "stunned"
expires = "start_of_source_next_turn"

# heal example (Life Cleric)
[abilities.cure_wounds]
kind = "heal"
amount = "2d8+5"
range = 5
targets = "ally_lowest_hp"
costs = { resource = "spell_slots_1" }

# utility example (cast Light)
[abilities.light]
kind = "utility"
effects = [ { effect = "emit_light", radius = 20 } ]
```

Common optional keys on any ability: `range` / `range_normal` + `range_long` (ranged
attacks), `costs = { resource = "<name>", amount = 1 }`, `uses_bonus_action = true`,
`recharge_ref` (see resources), `description` (prose, ignored by the engine).

### 1.5 `[multiattack]` — enumerated action combinations

Every combination of actions the creature may take on one turn is listed explicitly, as a
keyed table with an `actions` list. **No attack-replacement grammar.** Selection: options
whose `when` evaluates true are eligible; the highest `priority` wins; omitted `when` means
always eligible. Exactly one option runs per turn. A creature with no `[multiattack]` gets
an implicit single-option multiattack from `behavior.action_priority` (below).

```toml
[multiattack.slam_two]                 # 2+ enemies grappled: slam them both
actions = ["tentacle_slam"]            # tentacle_slam is multi-target by itself
when = "count(enemies_grappled_by_self) >= 2"
priority = 30

[multiattack.bite_and_grab]            # 1 grappled: bite the captive, grab another
actions = ["bite", "tentacle"]
when = "count(enemies_grappled_by_self) == 1"
priority = 20

[multiattack.grab_two]                 # none grappled: two tentacles, two targets
actions = ["tentacle", "tentacle"]
priority = 0                           # no `when` = the fallback
```

Repetition is explicit: a fighter's two longsword swings are
`actions = ["longsword", "longsword"]` — this replaces the old `attacks_per_turn` data key.
Per-action targeting inside an option is controlled by `[behavior.targeting]` and by each
ability's `targets`/`target_filter` (see [04 §targeting](04-behavior-rules.md)).

### 1.6 `[traits.*]` — passive, always-on mechanics

```toml
[traits.limited_sight]
description = "Sees only 30 ft into darkness or heavy obscurement."
effects = [ { effect = "limited_darkvision", range = 30 } ]

[traits.savage_attacker]
description = "Once per turn, roll weapon damage twice and keep the higher."
effects = [ { effect = "damage_reroll_keep_best", per_turn = 1 } ]
```

A trait is a list of passive effect primitives. Prose `description` is for humans.

### 1.7 `[conditions.*]` — custom condition definitions

Bespoke conditions a creature's abilities can attach (RAW conditions need no definition).
The mechanics ride entirely in the definition — the engine never special-cases a condition
by name ([03 §conditions](03-dnd5e-engine.md)).

```toml
[conditions.bruisers_mark]
grants = [ { effect = "impose_disadvantage_except_source" } ]  # grant-type primitives
exclusive = "per_source"     # attaching to a new bearer detaches the old one
                             #   (per_source | per_target | none; default none)
ends_with_source = true      # detach when the source goes down (default true if sourced)
expires = "end_of_bearer_turn"                    # clock keyword (03 §clocks)
unless = "attacked_other_than_source_this_turn"   # expiry-suppressing predicate
```

### 1.8 `[reactions.*]` — triggered responses

```toml
[reactions.deceptive_defense]
trigger = "ally_targeted_by_attack"    # closed trigger catalog (04 §reactions)
when = "distance(self, event.target) <= 30 and can_see(self, event.attacker)"
effects = [
  { effect = "redirect_attack", to = "self" },
  { effect = "swap_positions", with = "event.target" },
]
uses_reaction = true                   # consumes the one reaction per round
priority = 10                          # among this creature's eligible reactions
```

`event.*` selectors expose the triggering event's participants to the `when` expression
and the effects (`event.attacker`, `event.target`, `event.ability`, `event.damage`).

### 1.9 `[resources.*]` — limited-use pools

```toml
[resources.breath_weapon]
uses = 1
recharge = "5-6"             # roll 1d6 at the start of the owner's turn; 5-6 restores

[resources.spell_slots_1]
uses = 4
per = "day"                  # day | encounter (encounter = per trial)
```

Abilities reference resources via `costs`. `resource_available("name")` is queryable in
expressions.

### 1.10 `[behavior]` — declarative tactics

```toml
[behavior]
tactic = "engage"            # movement tactic: engage | kite | hold | hunt_light | guard
action_priority = ["longsword"]   # used only when there is no [multiattack]

[[behavior.targeting]]       # ordered rules; first match sets the target pool
when = "is_grappled_by(target, self)"
priority = 100
[[behavior.targeting]]
when = "hp_pct(target) < 0.3"
priority = 50
[[behavior.targeting]]
priority = 0
order = "nearest"            # tie-break within the pool: nearest | random | focus

[behavior.custom]            # OPTIONAL Python escape hatch (04 §escape-hatch)
handler = "python:behavior.OtyughBrain"
```

### 1.11 Worked example: full `otyugh.toml`

The acid test — everything `dnd5e_combat/monsters/otyugh/__init__.py` does today, as data.

```toml
name = "otyugh"
display_name = "Otyugh"

[classification]
size = "Large"
type = "Aberration"
alignment = "Neutral"
cr = 5

[stats]
strength = 16
dexterity = 11
constitution = 19
intelligence = 6
wisdom = 13
charisma = 6
ac = 14
speed = 30

[stats.health]
hit_dice = "12d10+48"
average = 114

[stats.saves]
constitution = 7

[stats.senses]
passive_perception = 11

[traits.limited_sight]
description = "Sees only 30 ft into magical darkness."
effects = [ { effect = "limited_darkvision", range = 30 } ]

[abilities.bite]
kind = "attack"
to_hit = 6
damage = "2d8+3"
damage_type = "piercing"
reach = 5
on_crit = [ { effect = "set_flag", flag = "enemy_crit", scope = "round" } ]

[abilities.tentacle]
kind = "attack"
to_hit = 6
damage = "1d8+3"
damage_type = "bludgeoning"
reach = 10
target_filter = "not is_grappled_by(target, self)"
on_hit = [ { effect = "attach_condition", condition = "grappled", escape_dc = 13 } ]
on_crit = [ { effect = "set_flag", flag = "enemy_crit", scope = "round" } ]

[abilities.tentacle_slam]
kind = "save"
ability = "con"
dc = 14
damage = "2d10+3"
damage_type = "bludgeoning"
half_on_save = true
targets = "enemies_grappled_by_self"
max_targets = 2
on_all_saved = [ { effect = "set_flag", flag = "slam_both_failed", scope = "round" } ]

[[abilities.tentacle_slam.on_fail]]
effect = "attach_condition"
condition = "stunned"
expires = "start_of_source_next_turn"

[multiattack.slam_two]
actions = ["tentacle_slam"]
when = "count(enemies_grappled_by_self) >= 2"
priority = 30

[multiattack.bite_and_grab]
actions = ["bite", "tentacle"]
when = "count(enemies_grappled_by_self) == 1"
priority = 20

[multiattack.grab_two]
actions = ["tentacle", "tentacle"]
priority = 0

[behavior]
tactic = "engage"

[[behavior.targeting]]
when = "is_grappled_by(target, self)"     # bite the captive first
priority = 100
[[behavior.targeting]]
# pack rule: while an ally has the tank pinned, pressure the back line
when = "any(allies, is_grappling(it, nearest(enemies_tagged('tank')))) and not has_tag(target, 'tank') and not has_tag(target, 'skirmisher')"
priority = 50
[[behavior.targeting]]
priority = 0
order = "random"
```

Fidelity notes vs the old policy: the old code's "bite the tank if it already acted"
opportunistic third attack and the exact random-pool mechanics are approximations either
way (the old policy already diverges from RAW). If parity testing (05) shows the pack rule
expression can't reproduce the old distribution within tolerance, the pack rule moves to
the escape hatch for the multi-otyugh sims — the schema stays unchanged.

### 1.12 Worked example: `masked_bruiser.toml` (reactions + custom condition)

```toml
name = "masked_bruiser"
display_name = "Masked Bruiser"

[classification]
size = "Medium"
type = "Humanoid"
cr = 4
tags = ["bruiser"]

[stats]
strength = 14
dexterity = 16
constitution = 16
intelligence = 10
wisdom = 12
charisma = 10
ac = 15
speed = 30

[stats.health]
average = 88

# --- Bruiser's Mark: a custom condition, defined once, attached by two abilities.
[conditions.bruisers_mark]
# marked creature attacks at disadvantage vs everyone EXCEPT the mark's source
grants = [ { effect = "impose_disadvantage_except_source" } ]
exclusive = "per_source"       # one creature marked at a time per Bruiser (RAW);
                               # overridable to "per_target" for the variant sims
ends_with_source = true        # mark drops when the Bruiser goes down
expires = "end_of_bearer_turn"
unless = "attacked_other_than_source_this_turn"   # keeping the heat on keeps the mark

[abilities.rapier]
kind = "attack"
to_hit = 7
damage = "1d8+3"
damage_type = "piercing"
reach = 5

[[abilities.rapier.on_hit]]
effect = "attach_condition"
condition = "bruisers_mark"
when = "has_tag(target, 'striker')"

[multiattack.standard]
actions = ["rapier", "rapier"]
priority = 0

[reactions.deceptive_defense]
trigger = "ally_targeted_by_attack"
when = """
distance(self, event.target) <= 30
and can_see(self, event.attacker)
and (has_tag(event.attacker, 'striker') or not any_yet_to_act(enemies_tagged('striker')))
"""
uses_reaction = true

[[reactions.deceptive_defense.effects]]
effect = "redirect_attack"
to = "self"
[[reactions.deceptive_defense.effects]]
effect = "swap_positions"
with = "event.target"
[[reactions.deceptive_defense.effects]]
effect = "attach_condition"
condition = "bruisers_mark"
target = "event.attacker"
when = "has_tag(event.attacker, 'striker')"

[reactions.sleight_of_crowd]
trigger = "turn_start"                    # bonus-action swap to shield the Poet
when = "distance(self, nearest(allies_tagged('poet'))) <= 30 and count(enemies_within_of(nearest(allies_tagged('poet')), 10)) > 0"
effects = [ { effect = "swap_positions", with = "nearest(allies_tagged('poet'))" } ]
uses_reaction = false
uses_bonus_action = true

[behavior]
tactic = "engage"
[[behavior.targeting]]
when = "has_tag(target, 'striker')"
priority = 50
order = "nearest"
[[behavior.targeting]]
priority = 0
order = "nearest"
```

Notes:
- `priority_targets` (old data key, default ranger/rogue) becomes a `striker` tag placed on
  those party members in the simulation file — tags are the generic mechanism.
- The deliberately drawn escape-hatch line: the declarative version shown marks any
  striker it hits. The old policy's full network-optimizing heuristic — only (re)place the
  mark when no current mark is "exploitable" by a Hector that can reach the bearer this
  round (`_mark_exploitable`, `_reachable_by_hector`) — is not expressible in the v1
  vocabulary and lives in `sims/masks/behavior.py` if parity requires it
  ([04 §escape-hatch](04-behavior-rules.md)).
- The Poet's Scathing Insult uses the same `[conditions.*]` mechanism:
  `grants = [{ effect = "grant_advantage_to_attackers" }]`,
  `expires = "end_of_source_next_turn"`. No engine code involved.

---

## 2. Board files

One TOML per board, containing the ASCII map inline. The `[glyph.*]` and `[meta]` formats
are **identical** to today's `dnd_board` palette format
(`dnd_board/src/dnd_board/palette.py`, `data/palettes/default.toml`), so the existing
parser is reused. `dnd_board.loaders.load_board_toml(path)` returns a `Board`; no `.npz`.

```toml
name = "shadow_cave"

[meta]
cell_feet = 5
diagonal = "chebyshev"       # chebyshev | 5105

map = """
##############################
#............................#
#..P......~~~~~..........o...#
#..P......~~~~~..............#
#..P.........###.........M...#
#............#...............#
#....x.......#...........o...#
##############################
"""

# Glyph tables exactly as in the current palette format. A board may omit
# glyphs to inherit the default palette; local entries override.
[glyph.'#']
terrain = "wall"
blocks_los = true
blocks_light = true

[glyph.'~']
terrain = "difficult"

[glyph.'x']
cover = "half"

[glyph.'o']
cover = "three_quarters"
blocks_los = false

[glyph.'P']
spawn = "party"              # spawn-zone label, as today

[glyph.'M']
spawn = "monsters"
```

Rules:
- Glyph keys are single characters; unknown terrain/cover names are load errors (existing
  `PaletteError` behavior).
- `map` must be rectangular after stripping the leading/trailing blank line; ragged rows
  are a load error reporting the row number.
- Spawn glyphs collect into `Board.spawns[label]` in reading order (top-left to
  bottom-right), matching current behavior. Simulation files may reference a spawn label
  (round-robin assignment) or an explicit `[x, y]`.
- `boardtool view` gains a `--toml` mode for visual inspection; the `.npz` pipeline remains
  for non-sim users of `dnd_board` but sims never touch it.

---

## 3. Simulation files

```toml
name = "otyugh_shadow_board"
description = "Shadow Otyugh vs the standard party in its dark cave."

[simulation]
trials = 10000
max_rounds = 10
seed = 8675309
hp_mode = "average"          # average | rolled (rolled uses stats.health.hit_dice)

# Board: path relative to this file, or "lib:<name>" for dnd5e_data/boards/<name>.toml
board = "boards/shadow_cave.toml"

# Creature resolution order for `creature = "<name>"` references:
#   1. explicit relative paths in `sources`
#   2. this sim's creatures/ directory
#   3. dnd5e_data (characters/ then monsters/)
# First hit wins, so a sim-local file shadows the library.
sources = ["creatures"]

[[combatants]]
creature = "shadow_otyugh"
side = "monsters"
spawn = "monsters"           # spawn label from the board; or start = [26, 14]
count = 1                    # count > 1 auto-names shadow_otyugh_1, _2, ...

[[combatants]]
creature = "champion_fighter"
side = "party"
spawn = "party"
tags = ["tank"]              # instance-level tag additions

[[combatants]]
creature = "thief_rogue"
side = "party"
spawn = "party"
tags = ["striker"]

# --- name-keyed overrides (deep-merged onto the creature file) ----------------
[overrides.shadow_otyugh]
stats.health.average = 120
abilities.tentacle.to_hit = 7

[overrides.champion_fighter]
behavior.tactic = "hunt_light"

# --- environment ---------------------------------------------------------------
[environment]
focus = "shadow_otyugh"      # party's focus-fire target (optional)

[[environment.obscurement]]
kind = "magical_darkness"    # fog | darkness | magical_darkness | light
follows = "shadow_otyugh"    # aura centered on a combatant; or center = [x, y]
radius = 30

[environment.light_plan]     # scripted "someone lights a torch" moment
source = "evoker_wizard"
round = 2
costs_action = true

# --- sweeps (optional; replaces every hand-rolled sweep script) -----------------
[sweep]
[[sweep.axes]]
target = "overrides.shadow_otyugh.abilities.tentacle.to_hit"
values = [6, 7, 8]
[[sweep.axes]]
target = "simulation.seed"   # any dotted path into this file is sweepable
values = [1, 2, 3]

# --- output ----------------------------------------------------------------------
[output]
dir = "out"                  # relative to the sim directory
report = ["totals", "by_combatant", "survival"]
charts = ["totals_hist", "dealt_by_combatant", "taken_by_combatant"]
```

### 3.1 Override semantics

`[overrides.<name>]` tables are applied to the loaded creature dict with **deep_merge**
(same semantics as today's `dnd5e_combat.loader.deep_merge`): nested tables merge
recursively; scalars and **lists replace wholesale**. TOML dotted keys
(`stats.health.average = 120`) are the natural syntax for deep single-value overrides.
Overrides apply before validation, so an override can't produce an invalid creature
silently. When `count > 1`, the override applies to every instance;
`[overrides.shadow_otyugh_2]` targets one instance.

### 3.2 What replaced what

| Old mechanism | New mechanism |
|---|---|
| `tuning.py` + `[stats.<archetype>]` blocks | `[overrides.<name>]` |
| Per-sim `simulation.py` | `dnd5e-sim run <simulation.toml>` |
| Sweep scripts (`masks/scaling.py`, compare sims) | `[sweep]` + `dnd5e-sim sweep` |
| `data/parties/*.toml` composition files | `[[combatants]]` lists (a party file may be
  factored into a TOML fragment included via `sources`; v1 keeps it inline) |
| `[[encounter.party_member]]` inline stat blocks | sim-local `creatures/*.toml` |
