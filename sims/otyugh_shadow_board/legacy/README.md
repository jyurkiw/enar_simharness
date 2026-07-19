# otyugh_shadow_board

A board-based variant of [`otyugh_shadow_solo`](../otyugh_shadow_solo). Same
encounter — a Shadow Otyugh (CR7 retune candidate) vs the Beaumont playtest
party — but the **Photophage darkness is modeled geometrically** instead of as a
blanket Blinded condition.

## What's different

- The Otyugh emits a **darkness aura** that follows it around the `arena` map.
  Anyone standing in it is Blinded, and it can't be seen *through* — so ranged
  attackers have no line of sight to the Otyugh from range.
- The Fighter carries a **torch** (a light aura that follows them). Plain light
  burns back plain darkness where they overlap, so the Fighter must **close on
  the Otyugh to illuminate it**. Do that and the ranged attackers regain a sight
  line; if the Fighter drops, the light dies and the darkness swallows the
  Otyugh again — the kiters lose LOS and advance to try to regain it.

This exercises the full board stack: A* movement (melee close to reach, the
Otyugh lumbers in), reach-based melee vs. ranged resolution, weapon range bands,
the ranged **kiting** goal, and its **advance-to-regain-LOS** fallback when the
light goes out.

## Party darkvision

Every party character archetype now carries a `limited_darkvision` boolean
(default `false`). Set it true on a party member (in the party TOML or a scenario
override) to give them 30 ft darkvision into obscurement — a standard 60 ft
darkvision halved by the Photophage's light-eating effect. Within 30 ft they see
the Otyugh through its own darkness fine (no torch needed) and aren't Blinded for
standing in it; beyond 30 ft they're still as blind as anyone without it. This is
weaker than the Otyugh's own `darkvision` flag (full immunity, unlimited range —
unchanged), which is why the two are separate mechanisms in the engine
(`Battlefield.can_see` / `not_blinded_by_obscurement`).

## Caveats (it's a variant, not a drop-in replacement)

- The light source here is a torch on the Fighter, not the Wizard casting Light
  (the solo sim's `light_config`); this is the tactically interesting choice on
  a map, since melee brings the light forward.
- Save-based spells (the Cleric's Bane / Sacred Flame, the Wizard's Lightning
  Bolt / Thunderwave) currently ignore line of sight — only attack-roll actions
  are LOS/cover/range gated. Numbers will differ from the abstract sim.

## Run

```sh
uv sync
uv run python src/simulation.py
```
