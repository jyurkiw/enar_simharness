# Python hooks: escape hatches and new mechanics

Two different problems, two different tools.

| You need… | Use | Lives in |
|---|---|---|
| A creature to *decide* something TOML can't express | **Escape hatch** — a handler class | `dnd5e_behaviors/` (or a sim-local `behavior.py`) |
| A *rule the game doesn't have yet* (new effect, trigger, query) | **New engine primitive** | `dnd5e/` |

**Try declarative first.** The expression language is more capable than it looks — this
project once cut a feature as "inexpressible" over a misreading of the evaluator
([nested `any()` works](expressions.md#nested-any-works)). If you do drop to Python,
record in the creature file *which* missing vocabulary forced it; that's the signal for
what the engine should grow next.

---

## 1. The escape hatch: bespoke decisions

For behavior that needs memory across turns, or a board query with no primitive.

Point the creature at a class:

```toml
[behavior]
tactic = "engage"
custom.handler = "python:dnd5e_behaviors.my_monster.MyBrain"
```

Write the class:

```python
# dnd5e_behaviors/src/dnd5e_behaviors/my_monster.py
class MyBrain:
    def choose_multiattack(self, me, view):
        """Return a [multiattack.<name>] key to force it, or None to fall through."""
        return None

    def choose_target(self, me, ability, pool, view):
        """Return one creature from `pool` to move to the front, or None."""
        return None

    def plan_movement(self, me, view):
        """Return an explicit (x, y) to move toward, or None to use the tactic."""
        return None
```

**Every hook may return `None` to fall through** to the declarative rules, so you override
only what you must. The handler is cached and shared across creatures and trials — keep it
**stateless**; per-creature state belongs on the creature.

### What you get

- `me` — the `Creature`. Useful: `me.instance_name`, `me.hp_remaining`, `me.is_down`,
  `me.coord`, `me.speed_ft`, `me.reach_ft`, `me.has_tag(...)`, `me.has_condition(...)`.
- `view` — the same scope the expressions use: `view.enemies()`, `view.allies()`,
  `view.downed_allies()`, `view.distance(a, b)`, `view.can_see(a, b)`,
  `view.has_condition(who, name)`, plus `view.battlefield` for board/occupancy queries and
  `view.eval("<expression>")` to reuse the declarative vocabulary.

### Per-creature state

Three scratch dicts, cleared at different times:

| Dict | Cleared |
|---|---|
| `me.turn_scratch` | Start of that creature's turn |
| `me.round_scratch` | Start of each round (this is the reaction economy) |
| `me.trial_scratch` | Start of each trial |

Sticky targeting — remember last round's victim — is `trial_scratch`:

```python
def choose_target(self, me, ability, pool, view):
    last = view.battlefield.creatures.get(me.trial_scratch.get("target"))
    if last is not None and not last.is_down and view.can_see(me, last):
        return last                                    # stay on it
    chosen = min(pool, key=lambda e: view.distance(me, e))
    me.trial_scratch["target"] = chosen.instance_name
    return chosen
```

### Sim-local handlers

A sim can keep its own `behavior.py` beside `simulation.toml` and reference
`"python:behavior.MyBrain"` — the CLI puts the working directory on `sys.path`. Good for
one-off encounter logic; put anything reusable in `dnd5e_behaviors/`.

### Worked example

`dnd5e_behaviors/src/dnd5e_behaviors/shadow_otyugh.py` implements exactly one hook
(`plan_movement`: flee the nearest light source, dragging captives). Everything else about
that monster stayed declarative — a good model for how small these should be.

---

## 2. Adding a new engine primitive

When the *game* needs a rule the engine lacks. Vocabularies are closed on purpose, so this
is a deliberate three-part change: **implement + register**, **validate at load**, **test**.

### A new effect

```python
# dnd5e/src/dnd5e/effects.py

# 1. register the name
ACTION_EFFECTS = frozenset({..., "knock_prone"})

# 2. implement it
def _knock_prone(args: dict, scope: EffectScope) -> None:
    """`scope.source` acts, `scope.target` receives; `scope.ctx` is the
    CombatContext; `scope.event` carries reaction bindings."""
    scope.ctx.apply_condition(scope.target, "prone", source=scope.source)

# 3. dispatch it
_DISPATCH = {..., "knock_prone": _knock_prone}
```

```python
# dnd5e/src/dnd5e/loader.py — fail loudly at load, not mid-trial
elif call.effect == "knock_prone":
    require_keys(call.args, ["dc"], where=where)
```

Then a test in `dnd5e/tests/test_effects.py`. Now any creature can use
`{ effect = "knock_prone", dc = 13 }`.

### A new expression function or selector

Register the name in `expressions.py` (`FUNCTION_NAMES` / `SELECTOR_NAMES`), add it to the
`Scope` protocol, wire it into `_CALL_TABLE` (or `_eval_selector`), and implement it on
`ConcreteScope` in `behavior.py`. Test in `test_behavior.py`.

### A new reaction trigger

The trigger catalog is `conditions.REACTION_TRIGGERS`. Several names are registered but
**nothing publishes them** — a reaction using those never fires. To wire one up, publish it
from wherever the event actually happens:

```python
reactions.offer("attack_hit", {"attacker": a, "target": t, "ability": ab},
                candidates=[t], behavior_ctx=behavior_ctx, combat_ctx=ctx)
```

Two rules learned the hard way:

- **Publish where the event truly occurs**, and mind the ordering. `ally_targeted_by_attack`
  fires *before any roll* precisely so a redirect/swap lands before advantage, cover and
  range are computed.
- **Guard the fast path.** `offer` is cheap only if you skip creatures with no reactions —
  otherwise you build a scope on every hit in every trial. And a reaction that rolls dice
  changes the RNG stream, so gate it (`when`) rather than rolling and discarding.

### Reaction side channels

Reactions that must influence the *in-flight* action write to a `CombatContext` side channel
that the caller reads back — that's how `redirect_attack` and `reduce_damage` work:

```python
# effect writes
scope.ctx.reduce_pending_damage(args["factor"])

# caller reads back
dealt = ctx.offer_taking_damage(defender, out.damage, attacker=actor, ability=ability)
```

Follow that shape for anything similar: reset the channel before offering, read after.

---

## Checklist for engine changes

1. Register the name (closed vocabularies are the safety net — keep them accurate).
2. Implement it.
3. Add load-time validation, with the file/field in the message.
4. Add a unit test — especially for *ordering* (does the reaction land before the roll?).
5. Run the sims: `uv run --project dnd5e pytest .`, then the affected simulations. A rules
   change moves numbers; check the blast radius before assuming it's an improvement.
6. Note the change in the relevant creature file, so the next reader knows why it exists.
