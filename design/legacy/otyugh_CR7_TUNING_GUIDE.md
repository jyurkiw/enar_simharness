# Shadow Otyugh — CR 7 Statblock Tuning Guide

How to use the sims to design the CR 7 "Shadow Otyugh" statblock for
*Possession of Beaumont*. Design source of truth:
`E:\Data\enigma-narrative\possession-of-beaumont\design\monsters\otyugh_variant.md`.

The whole point of this sim is **tune by outcome, not by matching a table**. The
Photophage aura, grapple, and poison make the creature's *effective* CR higher
than its raw numbers, so use the CR 7 reference bands below as a sanity anchor,
then push numbers until the **design-target metrics** land where you want them.

---

## 1. The tuning loop

1. **Edit the statblock:**
   `dnd5e_combat/src/dnd5e_combat/monsters/shadow_otyugh/defaults.toml`
2. **Rerun the sim** (the library is an editable dependency, so edits are picked
   up live — no reinstall):
   ```
   cd dnd/otyugh/otyugh_shadow_solo
   uv run python src/simulation.py
   ```
3. **Read the metrics** (see §5–6) against the design targets (§4).
4. **Repeat.** Change *one* lever at a time so you can attribute the effect.

Change one number, rerun, read, repeat. That's the entire workflow.

---

## 2. File map — what to edit for what

| You want to change… | Edit this file |
|---|---|
| **Numbers** (AC, HP, to-hit, damage, save/escape DCs) | `dnd5e_combat/.../monsters/shadow_otyugh/defaults.toml` |
| **Number of attacks** / tactics (extra tentacle, targeting) | `dnd5e_combat/.../monsters/shadow_otyugh/__init__.py` (policy) |
| **Rounds, party, light plan** (scenario knobs) | `dnd/otyugh/otyugh_shadow_solo/src/scenario.toml` |
| **The party's HP/Con** | `dnd5e_combat/.../data/parties/beaumont_playtest.toml` |
| **What the sim reports** | `dnd/otyugh/otyugh_shadow_solo/src/simulation.py` |

Editing `shadow_otyugh` only affects the shadow sims. The base `otyugh`
archetype (and `otyugh_cr5_*` sims) are untouched, so you always have an
un-tuned baseline to compare against.

---

## 3. The statblock knobs (`shadow_otyugh/defaults.toml`)

```toml
ac = 14                       # Armor Class
hp = 150                      # Hit Points  (SEE GOTCHA: Bloodied retreat halves the fighting HP)
saves = { dex = 0, con = 7, wis = 1 }   # monster's own saves (vs Bane, Sacred Flame, Lightning Bolt, etc.)
actions.bite      = { ... to_hit = 6, damage = "2d8+3" ... }          # applies Poisoned (in policy)
actions.tentacle  = { ... to_hit = 6, damage = "2d8+3", escape_dc = 13 }  # applies Grappled on hit
actions.tentacle_slam = { ... save_dc = 14, damage = "3d8+3" ... }    # DC 14 Con, half on save, Stuns on fail
```

| Field | Controls | Raise it to… |
|---|---|---|
| `ac` | How often the party hits it → how long it survives | Make it survive longer / land more attacks before Bloodied |
| `hp` | Combat duration → number of bites (poison) and slams | Widen the pre-Bloodied window (poison & danger up) |
| `actions.*.to_hit` | Otyugh accuracy → damage dealt & poison landed | Make it threaten the front-line, not just the light-bearer |
| `actions.*.damage` | Damage per hit (dice notation, crit-doubled automatically) | Raise damage-per-round toward the CR 7 band |
| `actions.tentacle_slam.save_dc` | How often grappled PCs eat full slam + Stun | Make grapples more punishing |
| `actions.tentacle.escape_dc` | (Currently unused — PCs don't spend actions to escape) | n/a in this model |
| `saves.*` | Its resistance to Bane / Sacred Flame / Lightning Bolt | Make caster control less reliable |

**Attack count** (1 bite + 2 tentacles per turn) is in the **policy**, not the
TOML. To raise damage-per-round you can either bump the damage dice here, or add
an attack in `shadow_otyugh/__init__.py` (`super().take_turn` /
`_hunt_light_source`). Bumping dice is the low-risk lever; start there.

---

## 4. Design targets → which metric measures each

From `otyugh_variant.md`:

| Design goal | Sim metric (from the report) | Current status (HP 150) |
|---|---|---|
| Poison lands on ≥1 PC in the **majority** of trials | `party with >=1 poisoned` | **62.9%** ✅ |
| **Very dangerous** fight | `party dmg taken`, `party wiped`, PC death rate | taken ~30, wipe 0%, deaths ~0.1% — not yet |
| A PC dropping to 0 as a realistic **bonus** | "Who dies" table + `down` rates | wizard drops ~9%, dies ~0.1% |
| ~3–4 rounds before retreat | (round horizon = `rounds` in scenario) | horizon is 3; bump to 4 to match |
| Retreat at Bloodied; can parting shots kill it? | "Shadow Otyugh outcome" table | ~95% retreat, OAs kill ~8% of retreats |

Note the **death safety net**: death saves (3 failures to die) plus the Life
Cleric now prioritising downed allies means PCs get knocked out far more often
than they actually die. If you want deaths to be a *realistic* outcome, you
must push **burst** (to-hit + damage + save DC), not just HP — HP only lengthens
the fight, it doesn't spike anyone.

---

## 5. CR 7 reference bands (DMG monster statistics — sanity anchor only)

| Stat | CR 7 band | Current Shadow Otyugh |
|---|---|---|
| Armor Class | 15 | 14 |
| Hit Points | 161–175 | 150 |
| Attack bonus | +6 | +6 ✅ |
| Damage / round | 45–50 | ~36 on a full 3-attack turn (before misses) |
| Save DC | 15 | 14 (slam) |

**Do not just slam these in.** This creature's threat is *control* (darkness
double-negative, grapple, poison), like the Chain Devil comp in the design doc —
it can legitimately sit **below** the HP/DPR median because the Photophage aura
raises its *effective* offense (advantage on every attack) and suppresses the
party's (disadvantage). Tune to the §4 outcomes; use this table only to catch
numbers that are wildly off-band.

A reasonable first CR 7 pass to try (then adjust by outcome):
- `ac = 14 → 15`
- `hp = 150 → 165`
- bite/tentacle `2d8+3 → 3d8+3` (raises damage-per-round toward the band)
- `tentacle_slam.save_dc = 14 → 15`

---

## 6. Reading the sim output

The run prints three blocks:

**Damage table** — mean/median/min/max damage dealt & taken, per combatant.
`dealt by shadow_otyugh` ÷ rounds ≈ its realized damage-per-round (already
includes misses and the aura's advantage).

**Survival table** — per side and per combatant:
- `... wiped` — whole side reduced to 0 HP (TPK / kill).
- `... with >=1 dead` — a member actually **died** (3 failed death saves / massive overkill), not just downed.
- `... with >=1 poisoned` — **your poison hard-target metric.**
- per PC: `down% / dead% / avg HP left / poisoned%` — `down` = reached 0 HP (may have been revived); `dead` = actually died.

**Shadow Otyugh outcome table** — killed-outright vs. retreated-at-Bloodied vs.
escaped, and the opportunity-attack kill rate on retreat.

**Who dies table** — per-PC death rate + "any PC dies". This is the direct
answer to "how often, and which one."

---

## 7. Scenario knobs (non-statblock levers) — `otyugh_shadow_solo/src/scenario.toml`

```toml
[simulation]
rounds = 3            # combat horizon. Bump to 4 to match the doc's "3-4 rounds".

[encounter]
party = "beaumont_playtest"   # swap party file to test different comps

[encounter.light]     # who counters the darkness, and at what cost
source = "wizard"     # combatant name; becomes the Otyugh's hunted target
round = 1             # which round they produce light
costs_action = true   # true = casts Light (loses their action); false = lit torch (free)
```

The **light plan is a huge lever** and part of the design, not a bug:
- `source = "wizard", costs_action = true` — the squishy caster pays an action
  and becomes the target. Hard mode (poison ~62%, real risk to the wizard).
- `source = "fighter", costs_action = false` — the tank lights the room for free
  and soaks the aggro on AC 21. Easy mode (poison ~12%, nobody at risk). This is
  **accepted play** — a party that hands the torch to the fighter *should* do
  well. Just be aware which light plan you're tuning against; tune the statblock
  against the plan you consider the "expected" table behaviour.

---

## 8. Tuning recipes

| Symptom | Lever |
|---|---|
| Poison below majority | ↑ `hp` (more rounds alive = more bites) |
| Not dangerous / nobody at risk but the light-bearer | ↑ `to_hit`, ↑ damage dice, ↑ `save_dc` (burst, not HP) |
| Want actual deaths (not just knockdowns) | ↑ burst hard; consider a 3rd tentacle in the policy; remember the cleric + death saves are a strong net |
| Retreats too fast / eats too few attacks | ↑ `hp` (Bloodied = HP/2) |
| Opportunity attacks kill it too easily on retreat | ↑ `hp` (more HP left when it flees) |
| Caster control (Bane/Sacred Flame) too reliable | ↑ `saves.wis` / `saves.dex` |

---

## 9. Gotchas

- **Bloodied retreat halves the effective combat HP.** It flees when it starts a
  turn at ≤ HP/2, so `hp = 165` means it only fights through ~82 damage. HP is
  worth "half" what it looks like for pacing purposes.
- **The aura mostly bites round 1.** Once the light plan fires (default: wizard,
  round 1), the party's Blindness clears for the rest of the fight. If you want
  the darkness to matter longer, that's a *policy/design* change (e.g. it
  re-darkens, or light only partially counters), not a number.
- **Effective CR > raw CR.** Advantage-on-all-attacks (darkness) + grapple lockdown
  + poison push the felt difficulty above what the AC/HP/DPR numbers imply. Expect
  to land *below* the CR 7 bands and still feel like CR 7.
- **One lever at a time.** Metrics are noisy (1000 trials, high variance); change
  two things and you can't tell which moved the needle. Bump trials in
  `scenario.toml` if a difference looks like it might be noise.
- **When you're happy, port the numbers back** to the statblock body in
  `otyugh_variant.md`. The sim's `defaults.toml` is the scratchpad; the design
  doc is the deliverable.
