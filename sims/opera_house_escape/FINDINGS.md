# Phase 2 — escaping the burning opera house

**The "guards beat you down" branch.** The party lost the guard fight, woke at
1 HP and manacled on the stage floor, and must run the length of a burning opera
house to the south door past the Pyre Weirds. **Can they get out?**

All numbers: 200 trials/variant, `escape_report.py`, seed 20260726.

```bash
uv run --project ../../dnd5e python escape_report.py --trials 500
```

---

## The headline

| Scenario | any PC escapes | ALL escape | mean escaped | mean PCs dead | whole party dies | rounds |
|---|---|---|---|---|---|---|
| no key, all 5 bound (ignored the advice) | 53% | 0% | 0.75/5 | 1.97 | 2% | 14.0 |
| no key, 3 bound (2 wake free) | 45% | 0% | 0.58/5 | 2.40 | 2% | 12.5 |
| **manacle key, all 5 bound** | **70%** | **0%** | **1.06/5** | **1.66** | **0%** | 11.7 |
| manacle key, 3 bound | 60% | 0% | 0.76/5 | 1.94 | 0% | 11.0 |
| manacle key, **2 fires** in the aisle | 100% | **20%** | **3.26/5** | 1.12 | 0% | 13.2 |

**This is not a TPK generator — it's a "some of you don't make it" generator.**
The whole party dies in 0-2% of trials. But getting *everyone* out is currently
close to impossible: typically **one or two PCs reach the door and about two
die** on the way.

## The three findings

### 1. The fire IS the encounter. The weirds are set dressing.

Damage taken per trial, manacle-key variant:

| source | per trial |
|---|---|
| **fire (environmental)** | **104.4** |
| weird Constrict | 32.7 |
| weird drain | 4.3 |
| Consume | **0.00** |

Fire does **3x** what both Pyre Weirds manage combined. The party's own damage
output (longbow 93, Hunter's Mark 39...) goes into killing weirds that were never
the real threat. If the intent is that the *weirds* are the phase-2 obstacle,
they currently aren't — the building is.

### 2. Consume never fires. The Hit-Dice timer is dead weight.

`Consume damage per trial: 0.00`, and the party ends with **13.4 of 15 Hit Dice
left**. Confirmed across both this sim and the P2 1v1 probe: **PCs die to fire and
Constrict long before the drain empties their Hit Dice.**

Per the "keep it in and measure it" call — the measurement is in, and it says
Consume is unreachable *as written*. It is not doing design work. Options:
- **Cut it** (the design doc's own [AI] note suspected this).
- **Move the gate** from "0 Hit Dice" to "2 or fewer", which at the post-heal 3 HD
  the wake-up leaves would put it ~1 round into a grapple — reachable.
- **Drain faster** (2+ HD/round).

My recommendation: move the gate rather than cut, since the *flavor* (drained to
a husk, then consumed) is good and only the arithmetic is wrong.

### 3. The manacle key is worth ~17 points of survival — Martinique is right.

53% → 70% any-PC-escape, mean escapees 0.75 → 1.06, and deaths 1.97 → 1.66. It
matters, and it matters in the direction the fiction wants: **taking her advice
converts a likely disaster into a survivable one.** Notably, waking with 2 PCs
*free* instead of all-5-bound is WORSE (45%/53%) — the free ones spend their
turns unlocking allies while the fire eats everyone, so a key beats spare hands.

---

## FINAL MODEL (2026-07): no fire at all — a pure weird fight

**Design ruling:** in the retreat phase the PCs are inside the belly of the
beast, and the elemental does not shoot projectiles into its own stomach.
Falling wreckage and obstacle fires here are **narrative only**. The only fire
that exists anywhere is wreckage the elemental throws, and it throws none in this
phase. So:

* **All ambient fire hazards removed.** There is no fire on the board.
* **The weirds' limitations are removed** (the prose's own rule): `sustain`
  disabled — no Guttering, the smoke sustains them — plus **speed 40 and
  `ignores_difficult_terrain`** (a new general stat). Flight is the big one: the
  house is wall-to-wall chairs, so the weirds drift over difficult terrain at
  full speed while the PCs slog through it at half.
* **The elemental's only job is summoning.** It now summons weirds *without*
  needing a fire to rise from (smoke-borne) at `summon_at`, mid-aisle between the
  party and the door — otherwise the prose's "spawn three Pyre Weirds" could
  never happen with no fire on the board, and the elemental would contribute
  literally nothing.

**Result (200 trials/variant):**

| scenario | any escapes | ALL escape | mean escaped | mean PCs dead | rounds |
|---|---|---|---|---|---|
| no key, all 5 bound | 90% | 1% | 2.42/5 | **1.76** | 15.1 |
| **manacle key, all 5 bound** | **98%** | 2% | **3.04/5** | **1.16** | 13.0 |
| key, 1 weird in the aisle | 100% | 2% | 3.31/5 | 1.07 | 13.1 |
| key, 3 weirds in the aisle | 100% | 2% | 3.21/5 | 1.09 | 13.1 |

Damage to the party is now **weirds and nothing else**: Constrict 83.4/trial,
drain 10.2. **This is the encounter the design asked for** — about three of five
get out, roughly one dies, and everything that happens to them is a weird's doing.

The key is still worth having (90% -> 98% any-escape, deaths 1.76 -> 1.16), so
Martinique's advice survives the retune.

### RESOLVED: Consume cut, Pyre's Due kept, and a real grapple bug fixed

Three things closed this out:

1. **A genuine engine bug: grapple never held anyone.** `movement.py` checked
   only the custom `grant_speed_zero`, never Grappled or Restrained — both Speed
   0 by RAW. A grappled PC could simply walk away, which is *why* no grapple ever
   survived to the weird's next turn. Fixed. Effect here: deaths 1.76 -> ~1.9,
   escapees 2.42 -> ~2.0. **Blast radius: every grapple sim (`guard_cartel`, the
   cathedral and otyugh families) needs re-baselining** — `guard_cartel` spot-
   checked at 117.6/621 dealt, 34.5% wiped (was ~116/619, 36-38%; within noise at
   200 trials, but the Hound's whole design is grappling).
2. **Drain rate is not the lever.** Swept 1/2/3 HD per round *after* the grapple
   fix: HD drained 5.1 -> 5.8 -> 6.4, Consume 0.00 at every rate, deaths and
   escapes flat. Two structural reasons: drain floors at 0 (a PC has only 3 HD,
   so extra rate is wasted), and Constrict's 2d6+3/turn empties HIT POINTS long
   before the drain empties HIT DICE.
3. **So Consume is CUT** — it fired zero times across four separate measurements.
   The only party it could ever catch is one that arrived with its Hit Dice
   already spent, which isn't worth a second kill switch. **The drain stays**:
   its job is fear and attrition (~34% of the party's HD pool), not kills — which
   is the water-weird role working as designed.

**Pyre's Due stays, for theatre not math.** Removing it costs ~0.6 deaths/run and
changes nothing else. It's kept because a weird's job is to be frightening in a
specific way: a water weird drowns you, a pyre weird leaves nothing to bury or
raise. See the rationale block in `pyre_weird.toml` — don't optimize it away.

### (superseded) Consume never fires — the gate needs moving

`Consume damage per trial: 0.00`, party Hit Dice **11.4 of 15 left**. Only ~3.6
HD are drained across the whole party, and Consume needs a *single* PC at 0 —
three consecutive rounds grappled by the same weird, which the party's damage
output never allows. Third measurement, same answer.

**Recommendation (unchanged, now firmer): move the gate from "0 Hit Dice" to
"2 or fewer".** At the 3 HD the wake-up heal leaves, that fires after ~1 round of
grappling — reachable, and it would put the Hit-Dice drain at the centre of the
encounter where the design wants it. Cutting Consume entirely is the alternative;
leaving it as written means it is decorative.

## SUPERSEDED — earlier retune (kept for the reasoning)

## RETUNE (2026-07): fire damage cut so the WEIRDS are the danger

Design goal: *"I'd like the main danger to be having your hit dice drained by
the weirds."* The elemental's own attacks were cut **-1d6 across the board**
(`drop_d6 = 1`) — but in phase 2 the elemental is in smolder mode and doesn't
attack, so **the lever that actually matters here is the ambient fire dice**.
Dropping those `2d6 -> 1d6` does exactly what was wanted:

| ambient fire | any escape | ALL escape | mean escaped | mean dead | **fire dmg** | **weird dmg** | HD left |
|---|---|---|---|---|---|---|---|
| 2d6 (before) | 53% | 0% | 0.75 | 1.97 | **92.7** | 55.6 | 12.7/15 |
| **1d6 (now)** | **94%** | **13%** | **2.79** | **1.43** | **54.3** | **62.5** | **11.4/15** |

**The threat ranking flipped.** Fire went from *out-damaging* the weirds
(92.7 vs 55.6) to *losing* to them (54.3 vs 62.5), and Hit-Dice drain rose
(12.7 -> 11.4 left) because PCs now survive long enough to be grappled and
drained rather than simply burning to death in the aisle. **The weirds are now
the encounter.**

The escape got much more survivable as a side effect (0% -> 13% all-out), which
is the honest cost of the change: fire was doing the lethality, so removing it
removes lethality. If the fight needs teeth back, add them on the **weird** side
(a third weird in the aisle, or the Consume gate fix below) rather than by
turning the fire back up — that keeps the danger where the design wants it.

## The fire dial — and the headline is deliberately the hard one

Four 15-ft blazes sit down the centre aisle, with a Pyre Weird in the path. **That
is the intended default, not a worst case**: a hazard squarely in the party's way
is the honest configuration to publish, because a DM can always ease up mid-session
and feel clever for it, whereas a fight that reads hard and plays trivial can't be
fixed after the fact. The numbers above are the ones to design against.

The sensitivity, so the DM has a dial to turn *down*:

| fires in the aisle | any escapes | ALL escape | mean escaped |
|---|---|---|---|
| **4 — the default, and the number to publish** | **70%** | **0%** | **1.06/5** |
| 2 (how to ease up if a table is drowning) | 100% | 20% | 3.26/5 |

Halving the fire roughly triples the survivors, so the lever is strong and precise
— but it's a lever for the table, not a reason to soften the book.

*(The `0 fires` row in the report reads 0% escaped / 2.2 rounds — an artifact, not
a result: with no fire the weirds immediately gutter out, every monster dies, and
the trial ends on the standard "one side is down" rule before anyone walks
anywhere. Read it as "the party strolls out unopposed".)*

## Caveats

- **The run is long.** 60 rows from stage to south door, ~11-14 rounds. Most of the
  damage is simply *time spent inside a burning building*, which is the right
  shape for the scene but means board geometry is as load-bearing as the monsters.
- **PCs run, they don't fight smart.** The objective model moves them toward the
  exit and lets them attack only what ends up in reach — no deliberate "kill the
  weird blocking the aisle first", no dousing, no dragging a downed ally out. A
  real party would do better; treat these as a floor.
- **Downed ≠ dead.** ~2 PCs end each trial down-but-not-dead. The trial ends when
  everyone is out or down, so their death saves are frozen mid-roll; the true
  death toll after the dust settles is somewhat higher than "mean PCs dead".
- Nico (a rescue objective), the retreat-cover Slingers, light obscurement, and
  the weirds' phase-2 fly speed are all out of scope — see `simulation.toml`.
