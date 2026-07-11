# 04 — Declarative Behavior Rules

How creatures decide what to do, expressed in TOML. Three consumers of the same expression
language: multiattack selection (`[multiattack.*].when`), targeting
(`[[behavior.targeting]].when`, ability `target_filter`), and reaction gating
(`[reactions.*].when`). Plus the Python escape hatch for what the language can't say.

## 1. Expression language (`dnd5e/expressions.py`)

A deliberately tiny, hand-rolled recursive-descent parser. **Not Python `eval`** — no
attribute access, no arbitrary calls, no state mutation. Parsed once at load time
(validating every identifier against the registries), evaluated many times per trial
against an evaluation scope.

### Grammar (EBNF)

```
expr        = or_expr ;
or_expr     = and_expr , { "or" , and_expr } ;
and_expr    = not_expr , { "and" , not_expr } ;
not_expr    = [ "not" ] , comparison ;
comparison  = sum , [ ( "==" | "!=" | "<" | "<=" | ">" | ">=" ) , sum ] ;
sum         = term , { ( "+" | "-" ) , term } ;
term        = primary , { ( "*" | "/" ) , primary } ;
primary     = number | string | "true" | "false"
            | selector | call | "(" , expr , ")" ;
call        = identifier , "(" , [ expr , { "," , expr } ] , ")" ;
selector    = identifier , { "." , identifier } ;     (* self, target, event.attacker *)
```

Types: number, bool, string, creature-ref, creature-set. Comparisons on numbers/strings;
`and/or/not` on bools; creature-sets flow into set functions (`count`, `nearest`, `any`).
Type errors are load-time errors where inferable, else clear runtime errors naming the
expression and file.

### Selector registry

| Selector | Meaning |
|---|---|
| `self` | the deciding creature |
| `target` | the candidate target (targeting/filter scope only) |
| `it` | the iteration variable inside `any(set, pred)` / `all(set, pred)` |
| `event.attacker`, `event.target`, `event.ability`, `event.damage` | reaction scope |
| `enemies`, `allies` | living creatures by side (excludes `self`) |
| `enemies_grappled_by_self` | enemies currently in `self`'s grapple graph edges |
| `enemies_within(ft)`, `allies_within(ft)` | range-filtered sets |
| `enemies_tagged(tag)`, `allies_tagged(tag)` | tag-filtered sets |
| `enemies_within_of(who, ft)` | enemies within range of another creature |
| `nearest_enemy`, `ally_lowest_hp` | common single-creature picks |

### Function registry (v1)

| Function | Returns |
|---|---|
| `count(set)` | int |
| `nearest(set)` / `farthest(set)` | creature (or none — comparisons against none are false) |
| `any(set, pred)` / `all(set, pred)` | bool, `it` bound per element |
| `has_condition(who, name)` | bool |
| `has_tag(who, tag)` | bool |
| `hp(who)` / `hp_pct(who)` | number |
| `is_bloodied(who)` / `is_down(who)` | bool |
| `distance(a, b)` | feet |
| `within(who, ft)` | bool (distance from `self`) |
| `can_see(a, b)` | bool (LOS + light + sight traits) |
| `in_reach(a, b)` | bool |
| `is_grappling(a, b)` / `is_grappled_by(a, b)` / `is_grappled(who)` | bool |
| `resource_available(name)` | bool (self's pool) |
| `round()` | int |
| `has_flag(name)` | bool (round/trial signal bag, see `set_flag`) |
| `any_yet_to_act(set)` | bool — any member's initiative slot is later this round |
| `side_of(who)` | string |

Adding a function = one registry entry in `expressions.py` + unit test + a row here.
Unknown names fail at load.

## 2. Multiattack selection

Algorithm, run once at the top of each turn:

1. Collect the creature's `[multiattack.*]` options.
2. Evaluate each option's `when` (missing `when` ⇒ eligible).
3. Among eligible options, pick the highest `priority`; ties are a load-time error
   (forces the author to be explicit).
4. If nothing is eligible (authoring gap), fall back to the lowest-priority option and
   log a warning — a monster should never stand idle because of a data bug.
5. Execute the option's `actions` in order. Each action independently targets (§3) and
   may move first (movement tactic) if no eligible target is in range/reach.

Abilities with `costs` whose resource is empty make any option containing them
ineligible — checked in step 2, so recharge monsters degrade to their fallback option
automatically.

## 3. Targeting

Per action, the target pool is computed as:

1. Start from the ability's `targets` selector (default: living visible enemies).
2. Apply the ability's `target_filter` expression, if any.
3. Walk `[[behavior.targeting]]` rules in descending `priority`; the first rule whose
   `when` matches at least one pool member restricts the pool to those members.
4. Pick from the final pool by the matched rule's `order` (`nearest` | `random` |
   `focus`); default `nearest`, ties by roster order, `random` drawn from the trial's
   seeded stream.

Multi-target abilities (`max_targets`) take the top N of the ordered pool.
`targets = "enemies_grappled_by_self"`-style set selectors skip steps 3–4 (the set *is*
the target list).

## 4. Reactions (`dnd5e/reactions.py`)

A trigger bus. Resolution points in `actions.py`/`system.py`/`movement.py` publish
events; the bus offers each event to every living creature's `[reactions.*]` entries whose
`trigger` matches, in initiative order, gated by:
the entry's `when` expression → reaction economy (`uses_reaction = true` consumes the
one-per-round reaction; `uses_bonus_action` similarly) → `costs`.

Trigger catalog (closed, v1):

| Trigger | Fires | `event.*` bindings |
|---|---|---|
| `ally_targeted_by_attack` | after target selection, **before any roll** | attacker, target, ability |
| `self_targeted_by_attack` | same point, target is self | attacker, ability |
| `attack_hit` / `attack_missed` | after the roll vs self | attacker, ability, damage |
| `taking_damage` | before damage applies to self (Uncanny Dodge halving = `damage_rider` with negative multiplier? No — a dedicated `reduce_damage` primitive is added when the Rogue migrates; flagged in [05](05-migration-plan.md)) | attacker, ability, damage |
| `enemy_left_reach` | opportunity attacks | mover |
| `ally_downed` | an ally drops to 0 | ally, attacker |
| `turn_start` / `turn_end` | own turn bookends (bonus-action tricks) | — |
| `round_flag_set` | a `set_flag` fired this round | flag |

Ordering invariant (preserved from the old engine): `ally_targeted_by_attack` effects
(`redirect_attack`, `swap_positions`) complete before the attack computes
advantage/disadvantage, reach, cover, and range — the roll resolves against the
post-reaction world.

## 5. The Python escape hatch

For behavior the language genuinely can't express (the Bruiser's network-optimizing
"is the mark exploitable by a reachable Hector" heuristic is the known case).

```toml
[behavior.custom]
handler = "python:behavior.OtyughBrain"    # module resolved from the sim directory
```

The class implements the `Behavior` protocol — the same interface the declarative
interpreter implements:

```python
class Behavior(Protocol):
    def choose_multiattack(self, me: CreatureView, view: CombatView) -> str | None: ...
    def choose_target(self, me, ability, pool, view) -> CreatureView | None: ...
    def plan_movement(self, me, view) -> MovePlan | None: ...
    def react(self, me, event, view) -> ReactionChoice | None: ...
```

Contract:
- **Returning `None` from any hook falls through to the declarative rules** — custom code
  overrides only the decisions it must, so a hatch class is typically 20 lines, not a
  policy rewrite.
- Hooks receive read-only views (`CreatureView`, `CombatView`) exposing the same queries
  as the expression functions, plus `view.eval("<expression>")` so custom code can lean on
  the same vocabulary. No raw engine internals, no direct state mutation — hooks *choose*,
  the engine *executes*. This keeps ledger recording, reaction economy, and clocks
  consistent regardless of who decided.
- The CLI adds the sim directory to `sys.path`; `python:package.module.Class` also
  resolves installed packages for shared hatch libraries.

Design pressure rule: every time a hatch is written, file a note (in the sim's README)
saying which missing function/primitive would have made it declarative. Recurring notes
justify growing the vocabulary; one-offs stay hatches.
