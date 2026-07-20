# Creature TOML reference

One creature per file. **`name` must equal the filename** (`otyugh.toml` → `name = "otyugh"`)
— the loader enforces it, because `name` is the creature's identity everywhere else
(result columns, `[overrides.*]`, `environment.focus`).

Files live in `dnd5e_data/src/dnd5e_data/characters/` or `.../monsters/`, or in a sim's own
`creatures/` directory (which shadows the library).

See also: [expressions](expressions.md) · [effects](effects.md) · [python hooks](python-hooks.md)

---

## Skeleton

```toml
name = "otyugh"                 # required, == filename
display_name = "Otyugh"         # optional, defaults to a title-cased name

[classification]
cr = 5                          # or `level = 5` for a PC; drives default proficiency
size = "Large"
type = "Aberration"

[stats]
strength = 16
dexterity = 10
constitution = 18
intelligence = 10
wisdom = 12
charisma = 10
ac = 14
speed = 30                      # feet
# optional:
initiative_bonus = 0            # defaults to the dex modifier
proficiency = 3                 # defaults from cr/level
crit_range = 20                 # 19 for a Champion Fighter
reach = 5

[stats.health]
average = 104                   # used by hp_mode = "average" (the default)
hit_dice = "12d10+48"           # used by hp_mode = "rolled"

[stats.saves]                   # explicit save modifiers; unlisted = ability modifier
constitution = 7

[stats.senses]
darkvision = 120
passive_perception = 11
```

## Abilities

`kind` is one of `attack`, `save`, `heal`, `utility`.

```toml
[abilities.tentacle]            # kind = "attack": attacker rolls
kind = "attack"
to_hit = 6
damage = "2d8+3"
damage_type = "piercing"
crit_range = 20
range_normal = 150              # omit for melee; beyond this = disadvantage
range_long = 600                # beyond this = automatic miss
targets = "enemies"             # see "Targeting" below
on_hit = [ { effect = "attach_condition", condition = "grappled", escape_dc = 13 } ]
on_crit = [ ... ]

[abilities.tentacle_slam]       # kind = "save": the TARGET rolls
kind = "save"
ability = "constitution"
dc = 14
damage = "3d8+3"
damage_type = "bludgeoning"
half_on_save = true
targets = "enemies_grappled_by_self"
max_targets = 2
on_fail = [ { effect = "attach_condition", condition = "stunned" } ]
on_success = [ ... ]

[abilities.cure_wounds]         # kind = "heal"
kind = "heal"
amount = "1d8+7"
targets = "downed_allies"

[abilities.bless]               # kind = "utility": just runs effects
kind = "utility"
targets = "allies"
effects = [ { effect = "attach_condition", condition = "bless" } ]
```

Optional on any ability: `costs = { resource = "ki", amount = 1 }` (makes a multiattack
option ineligible when the resource is exhausted), `uses_bonus_action`, `description`.

### Targeting

| Field | Meaning |
|---|---|
| `targets` | A selector naming the candidate pool. **Omitted = living *visible* enemies.** |
| `target_filter` | An expression filtering that pool; `target` is each candidate. |
| `max_targets` | How many to keep (default 1 for ordered pools). |

> ⚠️ **The sight default is the #1 authoring trap.** Leaving `targets` off means the ability
> can only pick targets it can *see*, so in darkness it silently does nothing. That's right
> for spells that require sight, and wrong for weapons. **Put `targets = "enemies"` on
> mundane weapon attacks.**

Set selectors (`enemies`, `allies`, `enemies_grappled_by_self`, `downed_allies`) skip the
ordering rules — the set *is* the target list, capped by `max_targets`.

## Multiattack

Each option is one complete turn's worth of actions. The engine picks the **highest-priority
option whose `when` passes**; an option with no `when` is the fallback.

```toml
[multiattack.slam_two]
actions = ["tentacle_slam"]
when = "count(enemies_grappled_by_self) >= 2"
priority = 30

[multiattack.grab_two]
actions = ["tentacle", "tentacle"]      # same ability twice = two attacks
priority = 0                            # no `when` = fallback
```

> ⚠️ **Priorities must be distinct** across all options — a tie is a load-time error, by
> design, so selection is never ambiguous.

## Traits — passive, applied once at trial setup

```toml
[traits.darkvision]
effects = [ { effect = "darkvision_immunity" } ]
```

## Behavior

```toml
[behavior]
tactic = "engage"               # engage | kite | hold
action_priority = ["claw"]      # fallback when there's no [multiattack]
custom.handler = "python:dnd5e_behaviors.my_monster.MyBrain"   # optional escape hatch

[[behavior.targeting]]          # first matching rule wins, by priority
when = "has_tag(target, 'squishy')"
order = "nearest"               # nearest | random | focus
priority = 10
```

- `engage` — close to melee reach.
- `kite` — stand as far from the target as possible while staying in weapon range with line
  of sight. **On a large board this means the far corner** — a powerful, deliberate tactic.
- `hold` — never move.

`order = "focus"` is the only thing that makes `environment.focus` do anything.

## Resources

```toml
[resources.ki]
uses = 5
per = "encounter"               # or "day"
recharge = "5-6"
```

Queried by `resource_available('ki')`. **Note:** there is currently no `spend_resource`
effect, so resources are checked but never decremented — fine when the pool outlasts the
fight, misleading otherwise.

## Conditions and reactions

Both are covered in **[effects.md](effects.md)**: `[conditions.*]` defines a custom
condition as data (a `grants` list, exclusivity, an expiry clock), and `[reactions.*]`
hooks a trigger from the reaction bus.

```toml
[conditions.marked]
grants = [ { effect = "impose_disadvantage_except_source" } ]
exclusive = "per_source"
expires = "end_of_bearer_turn"

[reactions.uncanny_dodge]
trigger = "taking_damage"
uses_reaction = true
effects = [ { effect = "reduce_damage", factor = 0.5 } ]
```

## Worked examples in the repo

| File | Shows |
|---|---|
| `monsters/otyugh.toml` | State-gated multiattack, `target_filter`, random targeting |
| `characters/thief_rogue.toml` | Once-per-turn rider (Sneak Attack), a damage-reduction reaction |
| `characters/hunter_ranger.toml` | Concentration modeled with a condition + reaction |
| `monsters/masked_bruiser.toml` | Custom condition, two reactions, `expr:` creature refs |
| `monsters/shadow_otyugh.toml` | Escape hatch + `end_trial` outcome columns |
