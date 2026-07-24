# Building a simulation

How to go from "I want to know if this fight is fair" to numbers.

This walks the whole path: a minimal simulation, then the pieces you'll reach for
(overrides, environment, sweeps), then authoring creatures, then dropping to Python when
the declarative vocabulary genuinely can't express something.

**Reference pages:** [creatures](docs/creatures.md) · [expressions](docs/expressions.md) ·
[effects](docs/effects.md) · [python hooks](docs/python-hooks.md) · [boards](docs/boards.md)

---

## 1. The smallest possible simulation

A simulation is one directory under `sims/` containing a `simulation.toml`.

```
sims/my_fight/
└── simulation.toml
```

```toml
name = "my_fight"
description = "One otyugh against the standard party"

board = "lib:plain_room"        # `lib:` = from the shared dnd5e_data library

[simulation]
trials = 10000
max_rounds = 3
seed = 20260701

[[combatants]]
creature = "champion_fighter"   # resolved from the shared library
side = "party"
spawn = "party"                 # a spawn label painted on the board

[[combatants]]
creature = "hunter_ranger"
side = "party"
spawn = "party"

[[combatants]]
creature = "otyugh"
side = "monsters"
spawn = "monsters"

[output]
report = ["totals", "by_combatant"]
```

```bash
uv run --project dnd5e dnd5e-sim validate sims/my_fight/simulation.toml
uv run --project dnd5e dnd5e-sim run      sims/my_fight/simulation.toml --trials 500
```

> ⚠️ **`name`, `description` and `board` must appear before the first `[table]` header.**
> A top-level key written after `[simulation]` silently becomes `simulation.board`. This
> is the single most common authoring mistake; `validate` catches it.

`[simulation]` also takes `hp_mode` (`"average"`, the default, or `"rolled"`) and
`grapple_escape`:

```toml
[simulation]
grapple_escape = true    # default false
```

**`grapple_escape`** turns on RAW 2024's "escaping a grapple costs your action" — a
check against the grappler's escape DC, win or lose, taken only when another enemy has
closed within 10 ft (a creature that breaks free unconditionally is modeling *worse*
play than a competent table, not better — see `system._try_escape_grapple`). It's opt-in
because switching it on globally would rewrite the numbers of every sim captured while
grapple was an inert marker. **Turn it on for any encounter whose design keys damage off
being held** — without it, the first successful grapple is permanent.

### Sides, spawns and counts

`side` is any string; two sides is the norm (`party` / `monsters`). The trial ends when
one side is entirely down, or `max_rounds` elapses.

`spawn` names a spawn block painted on the board; slots are handed out round-robin, so
several combatants can share one label. Use `start = [x, y]` instead to pin an exact cell.

`count = 2` creates two instances, auto-suffixed `otyugh_1`, `otyugh_2`. With `count = 1`
the instance keeps the creature's own name. **Instance names are what appear in result
columns and what `[overrides.*]` and `environment.focus` refer to.**

```toml
[[combatants]]
creature = "otyugh"
side = "monsters"
spawn = "monsters"
count = 2
tags = ["brute"]        # arbitrary labels, queryable from behavior expressions
```

### Where creatures come from

For `creature = "otyugh"`, the loader takes the **first hit**:

1. each directory listed in top-level `sources`, relative to the sim
2. the sim's own `creatures/` directory
3. `dnd5e_data`'s `characters/`, then `monsters/`

So a sim-local `creatures/otyugh.toml` shadows the shared library — handy for a one-off
variant without disturbing other sims.

---

## 2. Tuning without copying files: `[overrides]`

Rather than fork a creature to change two numbers, override it per-simulation. Keys are
dotted paths into that creature's TOML, keyed by name.

```toml
[overrides.otyugh]
stats = { ac = 16 }

[overrides.otyugh.abilities.tentacle]
damage = "2d8+5"
```

Overrides deep-merge: nested tables merge, but lists replace wholesale. A per-instance
override (`[overrides.otyugh_2]`) wins over a base-name one (`[overrides.otyugh]`) — it
replaces it, they don't stack.

This is how you sweep a stat block without maintaining N near-identical creature files.

---

## 3. Environment

```toml
[environment]
focus = "otyugh"                 # the party's focus-fire target (an instance name)

[[environment.obscurement]]
kind = "darkness"                # fog | darkness | magical_darkness | light
radius = 30
follows = "shadow_otyugh"        # a moving aura, re-centred each round...
# center = [12, 9]               # ...or a fixed region instead
start_round = 1

[environment.light_plan]
source = "evoker_wizard"         # scripted "someone lights a torch"
round = 2
costs_action = true
```

Two things to know:

- **`focus` only does something if a creature's targeting asks for it.** It steers only
  creatures with a `[[behavior.targeting]]` rule using `order = "focus"`. Party archetypes
  don't have one by default; inject it per-sim via an override (see `sims/masks/`).
- **Obscurement is geometric.** A creature standing in heavy obscurement is blinded
  (disadvantage), and abilities that require sight can't target through it. `light_plan`
  clears a *condition*, not the geometry, so it can't undo a region — don't pair a
  blanket-radius aura with `light_plan` and expect it to lift.

---

## 4. Sweeps: many variants, one file

A `[sweep]` block replaces hand-rolled comparison scripts. Each axis names a dotted config
path and a list of values; variants are the cartesian product.

```toml
[[sweep.axes]]
target = "environment.focus"
values = ["otyugh_1", "otyugh_2"]

[[sweep.axes]]
target = "overrides"                     # swap a whole table
values = [
  { otyugh = { stats = { ac = 14 } } },
  { otyugh = { stats = { ac = 18 } } },
]

[sweep]
columns = ["side_dealt_party", "side_dealt_monsters", "wiped_party"]
```

```bash
uv run --project dnd5e dnd5e-sim sweep sims/my_fight/simulation.toml
```

Axes are independent and replace their target path wholesale — there's no "base + delta"
layering across axes. If two fields must vary together, sweep the table that contains both
(as the `overrides` example above does).

For analysis the generic table can't express, run the variants yourself in a small script —
`sims/masks/network_value_report.py` is a worked example that expands the same `[sweep]`
and reports grouped, encounter-specific metrics.

---

## 5. Authoring a creature

Full reference: **[docs/creatures.md](docs/creatures.md)**. The shape:

```toml
name = "cave_lurker"            # MUST match the filename
display_name = "Cave Lurker"

[classification]
cr = 3

[stats]
strength = 16
dexterity = 12
constitution = 14
intelligence = 6
wisdom = 10
charisma = 6
ac = 15
speed = 30

[stats.health]
average = 45

[abilities.claw]
kind = "attack"                 # attack | save | heal | utility
to_hit = 5
damage = "1d8+3"
damage_type = "slashing"
targets = "enemies"             # see the sight note below

[multiattack.standard]
actions = ["claw", "claw"]
priority = 0

[behavior]
tactic = "engage"               # engage | kite | hold
```

Three things that trip people up:

- **`name` must equal the filename** (`cave_lurker.toml`). The loader enforces it.
- **Multiattack options need distinct `priority` values** — ties are a load error, on
  purpose, so selection is never ambiguous. The engine picks the highest-priority option
  whose `when` passes; an option with no `when` is the fallback.
- **`targets` defaults to *visible* enemies.** For a mundane weapon that's wrong — RAW you
  can attack what you can't see, at disadvantage. Set `targets = "enemies"` on weapon
  attacks; leave the default only for abilities that genuinely require sight (most spells).

### Making behavior conditional

Any `when` / `target_filter` is a small expression language, validated at load time
(full reference: **[docs/expressions.md](docs/expressions.md)**):

```toml
[multiattack.finish_them]
actions = ["claw", "claw", "bite"]
when = "is_bloodied(target) or count(enemies) == 1"
priority = 10

[abilities.bite]
kind = "attack"
to_hit = 5
damage = "2d6+3"
target_filter = "not is_grappled_by(target, self)"

[[behavior.targeting]]
when = "has_tag(target, 'squishy')"
order = "nearest"               # nearest | random | focus
priority = 10
```

### Effects, conditions and reactions

`on_hit` / `on_crit` / `on_fail` / `on_success` lists run effect primitives; creatures can
define custom conditions and reactions. Full reference:
**[docs/effects.md](docs/effects.md)**.

```toml
[abilities.claw]
kind = "attack"
to_hit = 5
damage = "1d8+3"
on_hit = [
  { effect = "attach_condition", condition = "grappled", escape_dc = 13 },
  { effect = "damage_rider", damage = "2d6", name = "rend", when = "has_tag(target, 'soft')" },
]

# React when something happens (here: halve the first hit taken each round)
[reactions.tough_hide]
trigger = "taking_damage"
uses_reaction = true
effects = [ { effect = "reduce_damage", factor = 0.5 } ]
```

---

## 6. When TOML isn't enough: bespoke Python

Two different situations, two different tools. Full guide:
**[docs/python-hooks.md](docs/python-hooks.md)**.

### (a) Bespoke *decision-making* → the escape hatch

If a creature needs to choose in a way the expression language can't express — usually
because it needs memory across turns, or a board query with no primitive — write a small
handler class in `dnd5e_behaviors/` and point the creature at it:

```toml
[behavior]
tactic = "engage"
custom.handler = "python:dnd5e_behaviors.cave_lurker.CaveLurkerBrain"
```

```python
# dnd5e_behaviors/src/dnd5e_behaviors/cave_lurker.py
class CaveLurkerBrain:
    def choose_multiattack(self, me, view):
        return None                      # None = fall through to the TOML rules

    def choose_target(self, me, ability, pool, view):
        # sticky targeting: keep last round's victim unless it's gone
        last = view.battlefield.creatures.get(me.trial_scratch.get("target"))
        if last is not None and not last.is_down:
            return last
        chosen = min(pool, key=lambda e: view.distance(me, e))
        me.trial_scratch["target"] = chosen.instance_name
        return chosen

    def plan_movement(self, me, view):
        return None                      # None = use the named tactic
```

Every hook may return `None` to fall through, so you override only what you must. A sim
can also keep a local `behavior.py` next to its `simulation.toml` — the CLI puts the
working directory on `sys.path`.

### (b) A genuinely new *mechanic* → a new engine primitive

If the game needs a rule the engine doesn't have (a new kind of effect, trigger, or
query), add it to the engine — the vocabularies are closed on purpose, so unknown names
fail loudly at load rather than silently doing nothing. It's a small, three-part change:

1. implement it and register it (`effects.py`, `expressions.py`, or `conditions.py`)
2. add its load-time validation (`loader.py`)
3. add a unit test

[docs/python-hooks.md](docs/python-hooks.md) walks a worked example of each.

**Try declarative first.** More is expressible than it looks — a documented "impossible"
case in this project turned out to be a misreading of the evaluator. If you do reach for
Python, record in the creature file *which* missing vocabulary forced it; that's the
signal for what to add to the engine next.

---

## 7. A practical workflow

1. `dnd5e-sim validate` after every edit — it's instant and catches every typo'd name.
2. Iterate at `--trials 200`; the shape of the answer shows up fast.
3. Once it looks right, run the file's full trial count for numbers you'd act on.
4. Check the per-combatant table for anyone contributing ~0 damage — that usually means a
   targeting or sight problem, not a balance finding.
5. Keep the seed fixed while tuning so changes are attributable to your edit, not to noise.

### Common surprises

| Symptom | Usual cause |
|---|---|
| A creature deals no damage at all | `targets` defaults to *visible* enemies — add `targets = "enemies"` for weapons, or it can't see through darkness |
| A healer never heals | `allies` **excludes** downed creatures — use the `downed_allies` selector |
| An ability never fires | Its multiattack option's `when` is never true, or a higher-priority option always wins |
| "unknown selector/function/effect" at load | The vocabulary is closed — check the reference pages for the exact name |
| Numbers move when you only changed trial count | They shouldn't — trials are independent streams. Suspect shared mutable state |
