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
| `targets` | A selector naming the candidate pool. **Omitted = the default single-target enemy pool.** |
| `target_filter` | An expression filtering that pool; `target` is each candidate. |
| `max_targets` | How many to keep (default 1 for ordered pools). |
| `requires_sight` | Whether the default pool is filtered to what the actor can see. Default `true`. |
| `advantage_when` | An expression; if true at swing time (target in scope), the attack has advantage. |
| `area` | A geometric area of effect (`{ shape = "line", length_ft = 100 }`) — see "Area of effect". |

> ⚠️ **Two related traps, both about single- vs multi-target attacks:**
>
> - **Sight.** With `targets` omitted the default pool is *visible* enemies, so a weapon in
>   darkness silently does nothing. Right for spells, wrong for weapons — set
>   **`requires_sight = false`** on mundane weapons (keeps them single-target).
> - **Don't use a set selector for a single-target attack.** `targets = "enemies"` looks
>   like "attack an enemy", but `enemies` is a *set* selector: with no `max_targets` it hits
>   **every** enemy. Harmless with one enemy on the board, a 6× damage bug against a pack.
>   For "one enemy, no sight needed", use `requires_sight = false` and leave `targets` off.

Set selectors (`enemies`, `allies`, `enemies_grappled_by_self`, `downed_allies`) are for
genuinely multi-target abilities (an AoE save, a party buff). They skip the ordering rules —
the set *is* the target list, capped by `max_targets`.

`advantage_when` is how conditional advantage like Pack Tactics is expressed (advantage if a
pack-mate is adjacent to the target):

```toml
advantage_when = "count(allies_within_of(target, 5)) > 0"
```

### Area of effect

`area` makes an ability *geometric* instead of picking from a pool: the caster aims the shape
to catch the most enemies, and **every** enemy inside it becomes a target. Pair it with
`kind = "save"` — each caught creature rolls its own save (this is the RAW "each creature in
the line makes a Dexterity save"). No `targets`/`max_targets` needed; the geometry is the pool.

```toml
[abilities.lightning_bolt]
kind = "save"
ability = "dexterity"
dc = 14
damage = "8d6"
half_on_save = true
area = { shape = "line", length_ft = 100 }   # 100-ft, 5-ft-wide line from the caster
```

| Shape | Params | Notes |
|---|---|---|
| `line` | `length_ft` | A 5-ft-wide (one-cell) ray from the caster, aimed to clip the most foes; stops at walls. |

Only `line` (Lightning Bolt) is modeled today; a foe *one cell off* the ray isn't caught, so
it slightly under-counts a real table — but it captures what matters: a **clustered** pack eats
one bolt across several bodies, a spread-out one doesn't. Cone/sphere would be added here.

The aim is **friendly-fire-aware**: it only ever picks a line that hits **no allies** (a
5th-level evoker has no Sculpt Spells, so a PC in the line takes the hit too). The geometry
primitive behind this — `aoe.get_targets(...)`, which returns `(allies, enemies)` for a given
aim — is reusable from a Python hook (see [python-hooks.md](python-hooks.md)); the evoker's
"cast only on a clean 2+ line, up to its slot ceiling" logic is a hook, not `when` clauses.

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
