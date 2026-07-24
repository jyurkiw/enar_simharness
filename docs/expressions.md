# The expression language

The small language behind `when`, `target_filter`, and `expr:` references.

It is **not** Python `eval` — it's a hand-rolled parser with no attribute access, no
arbitrary calls, and no mutation. Vocabularies are **closed**: every name is checked when
the file loads, so a typo is a load-time error naming the file and field, never a silent
no-op mid-run.

```toml
when = "count(enemies_grappled_by_self) >= 2"
target_filter = "not is_grappled_by(target, self)"
when = "is_bloodied(self) and round() > 1"
```

## Syntax

Operators: `and` `or` `not`, comparisons `== != < <= > >=`, arithmetic `+ - * /`,
parentheses. Literals: numbers, `true`/`false`, and single- or double-quoted strings.

Because the outer TOML value is usually double-quoted, use single quotes inside:

```toml
when = "has_tag(target, 'priority_strike')"
```

## Selectors

Bare names (no parentheses).

| Selector | Resolves to |
|---|---|
| `self` | The acting creature |
| `target` | The candidate/target in scope (in `target_filter`, each candidate) |
| `it` | The current element inside `any()` / `all()` |
| `enemies` | Living enemies |
| `allies` | Living allies — **excludes the Down** |
| `downed_allies` | Same-side creatures that *are* Down (the healer's pool) |
| `enemies_grappled_by_self` | Enemies this creature is grappling |
| `nearest_enemy` | Closest living enemy |
| `ally_lowest_hp` | Living ally with the least HP remaining |
| `event.<field>` | A triggering event's binding — reaction scope only (see below) |

> ⚠️ **`allies` excludes downed creatures.** So `any(allies, is_down(it))` is *permanently
> false* — a healer written that way can never see anyone to raise. Use `downed_allies`.

## Functions

| Function | Returns |
|---|---|
| `count(set)` | Size of a set |
| `any(set, pred)` / `all(set, pred)` | Predicate over a set, with `it` bound per element |
| `nearest(set)` / `farthest(set)` | One creature from a set |
| `has_condition(who, 'name')` | Condition present |
| `has_tag(who, 'tag')` | Combatant tag (from `[[combatants]].tags`) |
| `hp(who)` / `hp_pct(who)` | HP remaining / as a fraction of max |
| `is_bloodied(who)` / `is_down(who)` | ≤50% HP / at 0 HP |
| `temp_hp(who)` | Temporary hit points currently on `who` |
| `reaction_available(who)` | `who` still has its reaction this round — check before spending an action that needs *someone else's* |
| `distance(a, b)` | Feet between two creatures |
| `within(who, ft)` | Is `who` within `ft` of `self` |
| `can_see(a, b)` / `in_reach(a, b)` | Line of sight / melee reach |
| `is_grappling(a, b)` / `is_grappled_by(a, b)` / `is_grappled(who)` | Grapple state |
| `enemies_within(ft)` / `allies_within(ft)` | Sets within range of `self` |
| `enemies_within_of(who, ft)` / `allies_within_of(who, ft)` | Sets within `ft` of *another* creature |
| `enemies_tagged('tag')` / `allies_tagged('tag')` | Sets by tag |
| `resource_available('name')` | Resource pool not empty |
| `aoe_targets('ability')` | Enemies the ability's area (Lightning Bolt's line) would catch from here, along a line hitting no allies; 0 if not an area ability |
| `round()` | Current round number (1-based) |
| `has_flag('name')` | A round/trial flag set by `set_flag` |
| `turn_marked('key')` | A once-per-turn marker set by `mark_turn` |
| `any_yet_to_act(set)` | Anyone in the set acts later this round |
| `side_of(who)` | Side name |

## Nested `any()` works

`any()`/`all()` evaluate their **set argument in the enclosing scope, before rebinding
`it`**. So the outer `it` is still bound while the inner set is built:

```toml
# "is there a marked enemy that is ALSO within a hector's reach?"
when = "any(allies_tagged('hector'), any(enemies_within_of(it, 35), has_condition(it, 'marked')))"
#            └── outer it = the hector ──┘        └── inner it = the enemy ──┘
```

This project once recorded that as impossible and cut a feature over it. It isn't — there's
a regression test (`test_nested_any_keeps_the_outer_it_while_building_the_inner_set`)
pinning the behavior. **Check the evaluator before concluding something is inexpressible.**

## Scope: what's bound where

| Context | `self` | `target` | Notes |
|---|---|---|---|
| `[multiattack.*].when` | actor | — | Chosen before targets exist |
| `target_filter` | actor | each candidate | Runs once per candidate |
| `[[behavior.targeting]].when` | actor | each candidate | |
| `advantage_when` (on an attack) | attacker | the final target | Evaluated at swing time, after any redirect (Pack Tactics) |
| Effect-call `when` | effect source | effect target | Plus `event.*` for reactions |
| `[reactions.*].when` | the reactor | — | `event.*` available |

### `event.*` in reactions

Available fields depend on the trigger:

| Trigger | Fields |
|---|---|
| `ally_targeted_by_attack`, `self_targeted_by_attack` | `attacker`, `target`, `ability` |
| `taking_damage` | `attacker`, `target`, `ability`, `amount` |
| `enemy_left_reach` | `attacker` (the reactor), `target`/`mover` (who left) |
| `turn_start` | `actor` |

```toml
[reactions.sleight_of_crowd]
trigger = "turn_start"
when = "self == event.actor and count(allies_tagged('poet')) > 0"
```

## `expr:` creature references

Effect arguments that name a creature (`target`, `to`, `with`) accept four forms:
`"self"`, `"target"`, `"event.<field>"`, and `"expr:<expression>"` for anything the fixed
forms can't name:

```toml
effects = [ { effect = "swap_positions", with = "expr:nearest(allies_tagged('poet'))" } ]
```

The expression is parsed and validated at load time like any other. It may resolve to
nothing — effects treat that as a no-op.

## Gotchas

- **Closed vocabulary.** "unknown selector/function" at load means the name isn't in the
  tables above. Adding one is a deliberate engine change — see [python-hooks.md](python-hooks.md).
- **`allies` hides the Down** (above).
- **Quote nesting** — single quotes inside the double-quoted TOML string.
- **`distance` needs both creatures placed**; a selector that resolved to nothing will
  error rather than compare. Guard with `count(...) > 0` first.
