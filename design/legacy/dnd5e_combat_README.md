# dnd5e-combat

A reusable D&D 5e SRD combat engine for Monte Carlo simulations, built on
[`looper`](https://github.com/jyurkiw/looper) (event loop) and
[`py-die-roller`](https://github.com/jyurkiw/py-die-roller) (dice).

The goal is that a **party** and a **monster** are each defined once — as TOML
data plus a named behavior policy — and reused across any number of encounter
sims without rewriting them. A sim wires a roster together, points the engine
at it, and reads a damage ledger.

## Layers

- **Data (TOML)** — a combatant's stats, saves, AC/HP, initiative, and its
  named actions (attack bonus or save DC, damage code, conditions applied,
  riders), plus an optional default `action_priority` list.
- **Behavior (code)** — a `Policy` decides, each turn, which action(s) to take
  and against whom, reasoning over an abstract `Battlefield`. Simple combatants
  use the built-in `PriorityPolicy`; complex builds get a bespoke policy under
  `dnd5e_combat.policies`.
- **Engine** — a `looper`-driven turn loop (initiative → turn → resolve →
  apply → condition upkeep) that records every damage event to a `DamageLedger`.

## Positioning

Positioning is **abstract and binary** for now: combatants are either *engaged*
(adjacent/in reach) or not, and a grapple graph tracks who holds whom. A real
grid may replace this later; policies only ever query the `Battlefield`
interface, so they won't need to change when it does.
