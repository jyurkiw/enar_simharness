# Effects, conditions and reactions

Effects are the closed set of *things that can happen*. Conditions are mechanics stored as
data. Reactions are effects triggered by someone else's action.

All three vocabularies are validated at load time — an unregistered name is an error, never
a silent no-op.

See also: [creatures](creatures.md) · [expressions](expressions.md) · [python hooks](python-hooks.md)

---

## Effect calls

An effect call is an inline table in an `on_hit` / `on_crit` / `on_fail` / `on_success` /
`effects` list:

```toml
on_hit = [
  { effect = "attach_condition", condition = "grappled", escape_dc = 13 },
  { effect = "damage_rider", damage = "2d6", damage_type = "piercing", name = "sneak_attack",
    when = "not turn_marked('sneak')" },
]
```

> ⚠️ **TOML inline tables must be on one line.** Splitting `{ ... }` across lines is a parse
> error. These lists get long — keep each entry on its own single line.

Any effect call may carry:

- **`when`** — an expression gating it (evaluated with the source/target/event in scope).
- **`target`** — redirect this one effect at another creature: `"self"`, `"target"`,
  `"event.<field>"`, or `"expr:<expression>"`.

## The effect registry

| Effect | Arguments | Does |
|---|---|---|
| `attach_condition` | `condition`, `escape_dc?`, `expires?` | Apply a condition. `expires` gives a RAW condition a duration (see clocks). |
| `remove_condition` | `condition` | Remove it |
| `require_save` | `ability`, `dc`, `on_fail?`, `on_success?` | A nested save with its own effect lists |
| `damage_rider` | `damage`, `damage_type?`, `name?` | Extra dice on the triggering hit (crit-aware) |
| `reduce_damage` | `factor` | Multiply the pending hit's damage (reaction only) |
| `make_attack` | `ability` | Resolve one of the source's own abilities (reaction only) |
| `mark_turn` | `key` | Set a once-per-turn marker, read by `turn_marked(key)` |
| `set_flag` | `flag`, `scope?` (`round`/`trial`) | Set a flag, read by `has_flag()` |
| `end_trial` | `outcome?` | End the trial now, merging extra outcome columns |
| `redirect_attack` | `to` | Retarget the pending attack (reaction, pre-roll) |
| `swap_positions` | `with` | Exchange board positions |
| `emit_light` | `radius`, `start_round?` | Become a light source |
| `limited_darkvision` | `range?` | Trait: capped darkvision |
| `darkvision_immunity` | — | Trait: ignore heavy obscurement |

### Common patterns

**Once per turn** — gate on a marker, then set it. Order matters: the rider checks the
marker, then `mark_turn` sets it, so the second attack sees it.

```toml
on_hit = [
  { effect = "damage_rider", damage = "2d6", name = "sneak_attack", when = "not turn_marked('sneak')" },
  { effect = "mark_turn", key = "sneak", when = "not turn_marked('sneak')" },
]
```

**A save rider**

```toml
on_hit = [
  { effect = "require_save", ability = "constitution", dc = 14,
    on_fail = [ { effect = "attach_condition", condition = "stunned", expires = "start_of_source_next_turn" } ] },
]
```

**Extra outcome columns** — `end_trial`'s `outcome` merges into the result row, so a sim can
measure something bespoke:

```toml
effects = [
  { effect = "end_trial", outcome = { retreated = 1, killed_on_retreat = 1 }, when = "is_down(self)" },
  { effect = "end_trial", outcome = { retreated = 1 }, when = "not is_down(self)" },
]
```

---

## Conditions

RAW conditions are always available to `attach_condition`:

`bane` `bless` `blinded` `charmed` `deafened` `frightened` `grappled` `incapacitated`
`invisible` `paralyzed` `petrified` `poisoned` `prone` `restrained` `stunned` `unconscious`

Only some have mechanical effect: `blinded` (advantage to attackers, disadvantage on its
own attacks), `bane`/`bless` (±1d4 on d20 rolls), and `stunned`/`paralyzed`/`unconscious`/
`petrified` (skip the turn). The rest are markers you can query.

### Custom conditions

Define mechanics as **data** — the engine never tests a condition by name, it folds
whatever the condition `grants`:

```toml
[conditions.marked]
grants = [ { effect = "impose_disadvantage_except_source" } ]
exclusive = "per_source"          # per_source | per_target
ends_with_source = true           # default
expires = "end_of_bearer_turn"
unless = "attacked_other_than_source_this_turn"
```

**Grant effects** (folded by the engine, never dispatched):

| Grant | Effect |
|---|---|
| `grant_advantage_to_attackers` | Attacks against the bearer have advantage |
| `grant_self_advantage` | The bearer's own attacks have advantage |
| `impose_disadvantage` | The bearer's attacks have disadvantage |
| `impose_disadvantage_except_source` | …except against the condition's source |
| `grant_advantage_against` | *Registered, not yet wired* |

**Expiry clocks** (`expires`):

| Clock | Ticks |
|---|---|
| `start_of_source_next_turn` | Start of the applier's next turn |
| `end_of_source_next_turn` | End of the applier's next turn |
| `end_of_bearer_turn` | End of the bearer's own turn |
| `end_of_bearer_next_turn` | Treated as above (documented simplification) |
| `until_cured` | Never automatically |
| `rounds:<n>` | *Validated but not yet resolved at runtime* |

`unless` keeps a condition alive past its clock; the only predicate is
`attacked_other_than_source_this_turn`.

An `expires` on the **effect call** lets a RAW condition carry a duration — that's how
Stunning Strike works, since `stunned` has no definition of its own:

```toml
{ effect = "attach_condition", condition = "stunned", expires = "start_of_source_next_turn" }
```

---

## Reactions

```toml
[reactions.uncanny_dodge]
trigger = "taking_damage"
when = "event.amount > 5"       # optional
uses_reaction = true            # one per round (round_scratch economy)
uses_bonus_action = false
priority = 0                    # highest eligible fires
effects = [ { effect = "reduce_damage", factor = 0.5 } ]
```

**One reaction fires per offer**, chosen by priority among eligible candidates in
initiative order.

### Triggers

| Trigger | Published when | Notes |
|---|---|---|
| `ally_targeted_by_attack` | An ally is attacked | **Before any roll** — a redirect/swap completes before advantage, cover and range are computed |
| `self_targeted_by_attack` | This creature is attacked | Same pre-roll point |
| `taking_damage` | About to take *attack* damage | Where `reduce_damage` applies. Not published for save-based damage |
| `enemy_left_reach` | An enemy walks out of reach | Opportunity attacks |
| `turn_start` | Any creature's turn begins | Gate with `self == event.actor` for "my turn" |
| `attack_hit`, `attack_missed`, `ally_downed`, `turn_end`, `round_flag_set` | *Registered; nothing publishes them yet* | A reaction using these never fires |

`uses_reaction = true` gives the RAW one-per-round limit for free — a creature with both
Uncanny Dodge and an Opportunity Attack can only use one per round, correctly.

### Reaction examples

```toml
# Opportunity attack
[reactions.opportunity_attack]
trigger = "enemy_left_reach"
uses_reaction = true
effects = [ { effect = "make_attack", ability = "longsword" } ]

# Interpose: swap in and take the hit meant for an ally, then mark the attacker
[reactions.deceptive_defense]
trigger = "ally_targeted_by_attack"
when = "distance(self, event.target) <= 30 and can_see(self, event.attacker)"
uses_reaction = true
effects = [
  { effect = "swap_positions", with = "target" },
  { effect = "redirect_attack", to = "self" },
  { effect = "attach_condition", condition = "marked", target = "event.attacker" },
]

# Concentration: a save on taking damage that drops a self-condition
[reactions.concentration]
trigger = "taking_damage"
when = "has_condition(self, 'hunters_mark')"
effects = [
  { effect = "require_save", ability = "constitution", dc = 10,
    on_fail = [ { effect = "remove_condition", condition = "hunters_mark" } ] },
]
```

Note the last one omits `uses_reaction` — a Concentration check isn't the creature's
reaction, so it shouldn't consume the economy. Its `when` guard also stops it rolling
(and consuming RNG) when there's nothing to concentrate on.
