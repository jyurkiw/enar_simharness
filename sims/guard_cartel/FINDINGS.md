# The plaza guard squad — findings

**Encounter:** 3× Southern Gate Guard Cartel Vise (CR 2), 1× Hound (CR 3),
1× Slinger (CR 2), 1× Constable (CR 4), on an open plaza, versus five level-6
adventurers. The squad retreats if the Constable is defeated.

**Balance intention:** between *low* and *moderate* difficulty.

All numbers below: 5,000 trials, seed 20260723, `max_rounds = 12`.

```bash
uv run --project ../../dnd5e python difficulty_report.py
```

---

## Verdict: it lands in the band, on the moderate side of it

| Measure | Value |
|---|---|
| Rounds to resolve | 8.1 |
| Party HP spent | **34%** |
| At least one PC down | **28.2%** |
| Mean PCs down at the end | 0.41 |
| A PC actually dies | 3.2% |
| Total party wipe | 0.3% |
| Squad broken (Constable down → retreat) | 57.4% |
| Squad wiped to the last guard | 39.4% |
| Damage dealt, squad / party | 108 / 627 |

The party wins essentially always (0.3% wipe, and see the caveat below — that
tail is pessimistic), spends about a third of its hit points doing it, and has
roughly a one-in-four chance that somebody goes down along the way. That is
recognisably *between* low and moderate: too costly to be a speed bump, not
punishing enough to be a real threat to the party's survival.

It reads slightly hotter than its XP tag suggests. The squad is **3,600 XP**
against the 2024 DMG's level-6 budgets for five characters (low 3,000, moderate
6,000, high 12,000) — 20% of the way from low to moderate on paper, but nearer
50–60% of the way there in play. The Constable is why (below).

**The lever, measured.** The Vise is the roster's designated common guard, so
its count is the natural dial (`difficulty_report.py --dial`):

| Vises | XP | Rounds | Party HP spent | ≥1 PC down | PC death | TPK |
|---|---|---|---|---|---|---|
| 2 | 3,150 | 7.2 | 29% | 20.9% | 1.5% | 0.1% |
| **3 (as specified)** | **3,600** | **8.1** | **34%** | **28.2%** | **3.2%** | **0.3%** |
| 4 | 4,050 | 8.8 | 37% | 36.7% | 4.9% | 0.3% |

One Vise is worth roughly 8 points of "somebody goes down" and 4–5 points of
party HP. Drop to 2 for a cleanly-low encounter; go to 4 to sit at moderate.
Nothing needs changing to hit the stated intention — 3 is the right number.

---

## Three findings worth the design's attention

### 1. This is the Constable plus an escort, not a control network

The roster is designed as a mutual-dependency network: the Hound and Slinger
undershoot their damage benchmarks on purpose, and the Vise's club triples off
the conditions they create. In play, that payoff is **11% of the squad's
damage**:

| Source | Per trial | Share |
|---|---|---|
| Constable's longsword | 41.0 | 37.8% |
| Constable's orders (Commander's Strike + the ally's swing) | 19.0 | 17.6% |
| Hound's Catch | 11.8 | 10.9% |
| Slinger's Stone | 10.6 | 9.8% |
| Vise's base club | 9.9 | 9.1% |
| **Condition payoff** (`vise_held` + `vise_restrained` + `finish_prone`) | **12.0** | **11.1%** |

**The Constable is 55% of the squad's output by itself.** The Catch → Trip →
Finish chain — the roster's whole premise — completes rarely: 1.4 Catches per
trial, but only 0.2 Trips and 0.15 Finishes. Two reasons, both structural:

* **The mooks die before the chain closes.** AC 13 and no resistances against a
  level-6 party is paper. A Vise absorbs a bit over 100 damage and is gone; the
  Hound gets two or three turns.
* **Grapples don't hold.** Escape is a DC 13 check against a party whose melee
  carry +6 or better — about 70% per attempt. The Hound catches someone, and
  they're usually free before it can Trip them.

This isn't a bug and it isn't necessarily wrong — the design brief says the
Constable is meant to be the one piece that ablates HP at a normal clip, and it
is. But the *control* half of the roster is currently contributing about a
ninth of the fight's damage, so if the Hound and Slinger are supposed to be
carrying their CR through control, that's not visible here. Levers if it should
be: raise the Hound's grapple DC, give the mooks AC 15 rather than 13, or lean
on the Manacles (Restrained is the tier that actually pays — `vise_restrained`
out-earns `vise_held` 6.6 to 4.1 despite firing far less often).

### 2. The retreat rule is the encounter's real win condition

The squad breaks and withdraws in **57.4%** of trials; it fights to the last
guard in only 39.4%. Because the retreat triggers on the Constable falling, and
the Constable is also the squad's damage engine, "kill the officer" is both the
fastest way to end the fight and the way that stops the most incoming damage.
That's a good encounter — it rewards reading the battlefield — but it means the
fight is far easier for a party that identifies the Constable early than for one
that grinds through Vises. Nothing in the sim models the party *knowing* to do
that (they target nearest by default), so **the real-table number is likely
better for the party than 57.4%**.

### 3. An all-melee party has a much worse time

`difficulty_report.py --parties`:

| Party | Rounds | Party HP spent | ≥1 PC down | PC death | TPK | Squad retreated |
|---|---|---|---|---|---|---|
| Standard (fighter/ranger/rogue/cleric/wizard) | 8.1 | 34% | 28.2% | 3.2% | 0.3% | 57.4% |
| Vanguard (barbarian/paladin/monk/cleric/wizard) | 8.4 | **49%** | **35.3%** | **10.2%** | **3.2%** | 71.7% |

The vanguard party walks into exactly what the network is built to punish:
everybody in the Hound's reach, everybody in club range, nobody at 40 ft where
the Slinger has to spend its turn chasing. It spends half its hit points and
loses a character one time in ten. **The "between low and moderate" verdict is a
statement about the ranged-heavy standard party; against an all-melee line-up
this squad is a solidly moderate fight.** Worth knowing before dropping it in
front of a table that happens to be built that way.

---

## Caveats on the numbers

* **The simulated party never retreats or surrenders.** It fights to the last
  hit point for up to 12 rounds. Every wipe/death figure above is therefore a
  ceiling; a real table would break off. Read 0.3% TPK as "effectively zero".
* **Capture is not scored.** The Vise's Manacles and the "guards capture, don't
  kill" default are modeled only as damage and the Restrained condition — a
  manacled-and-unconscious PC is scored as "down", not "captured". If the
  ambush's intended outcome is *taken alive*, that needs its own outcome column
  and is a separate piece of work.
* **The bolos' second escape route is not modeled.** RAW a bolo also comes off
  if the target spends an action removing it; only the DC 13 Strength save at
  the start of each turn is implemented. Bolos therefore last slightly longer
  in-sim than at a table where a player might choose to burn the action.
* **Commanding Voice is modeled as Halt only.** Approach/Flee/Grovel would each
  need forced-movement or forced-prone primitives the engine doesn't have.
* **Escaping a grapple costs the PC its action** (RAW 2024), but only when
  another enemy has closed within 10 ft — see `system._try_escape_grapple` for
  why an unconditional escape models *worse* play, not better.
* **A grappled PC is Speed 0, not otherwise impaired**, which is RAW; the Vises'
  damage tiers are what make being held actually hurt.

## What the engine grew for this roster

All general, all unit-tested (`dnd5e/tests/test_guard_cartel_primitives.py`):
`grant_temp_hp` + temp-HP absorption; `recharge = "5-6"` actually rolling (the
field had been parsed and ignored since Phase 3); the `grant_speed_zero`
condition grant; the `save_ends_start_of_bearer_turn` clock; `make_attack`'s
`actor`/`bonus_damage`/`uses_reaction` arguments; and `[simulation]
grapple_escape`.

**One real bug fell out of it, now fixed:** a melee-only attack (an ability with
no `range_normal`) fell into the ranged resolution branch, which has no range
band to gate on — so a longsword could be swung across the whole board. Nothing
had noticed because on the 30-ft `plain_room` boards every melee monster closes
in round 1. The Constable, which deliberately holds position 40 ft back, was
landing longsword hits from there; fixing it took this encounter's TPK rate from
2.4% to 0.3%.

**That fix has a real blast radius on other sims and it is written up in
`design/07-known-issues.md`** — `sims/cathedral` moves the most (its horde of 20
melee defenders on a 40-long nave was full of out-of-reach swings: monster damage
−21%, party damage +42%), so its recorded findings need re-running before they're
trusted. One test in `test_system.py` had encoded the old behavior and was
corrected (`test_marked_condition_survives_end_of_turn_if_bearer_attacked_someone_else`).
