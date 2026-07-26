# The opera house — first-pass findings

**The big fight**, first pass. 5 level-6 PCs vs the Guard Cartel's opera-house
deployment: 18 opening guards (10 Watchmen, 5 Vises, 2 Hounds, 1 Constable) plus
two timed pit reinforcement waves. The only question this pass answers is the one
that matters before the fire layer goes on: **can the party avoid a TPK?**

Scope, omissions and caveats are all in `simulation.toml`'s header — read them;
the number is only honest with them in view. The big ones: the stage subplot
(Nico/Guy/Véronique) isn't on the board, the two slinger cover squads and the
conditional "trickle" aren't modeled, and the guards' "won't fight to kill"
falls out for free because downed creatures leave every targeting pool.

## The framework held

34 combatants across three timed spawns, on a 42×79 board, ran without trouble.
That was the real stress test and it passed.

## Exposure per round (`timeline_report.py`, 200 trials)

The scene has a built-in clock — the guards flee ~one round after Véronique
leaves (≤ start of round 4), so the party's guard-fighting window is ~5 rounds.
The table shows the party's state *if the guards left at round N*:

| guards leave at | party HP spent | ≥1 PC down | ≥1 PC dead | TPK | openers down /18 | reinf dmg |
|---|---|---|---|---|---|---|
| round 3 | 18% | 31% | 0.0% | **0%** | 12.1 | 0 |
| round 4 | 24% | 35% | 0.0% | **0%** | 13.4 | 0 |
| **round 5** | **28%** | **38%** | **0.0%** | **0%** | 14.5 | 0 |
| round 6 | 30% | 41% | 1.5% | **0%** | 15.3 | 1 |
| round 7 | 32% | 36% | 2.0% | **0%** | 16.1 | 1 |
| round 8 | 33% | 31% | 5.5% | **0%** | 16.6 | 1 |
| round 9 | 34% | 29% | 6.0% | **0%** | 16.9 | 2 |

### What it says

- **No TPK, anywhere on the curve.** The failure state doesn't occur — 0% even
  if the fight drags to round 9. Within the realistic ~5-round window the party
  spends about a quarter of its HP and has a ~38% chance someone has been *down*
  at some point, but **nobody dies** (deaths only start leaking in past round 6,
  which is already past when the guards leave). This is the reassuring result
  for layering fire on top: the guards alone leave the party with headroom.
- **The pit reinforcements never arrive.** `reinf dmg dealt` is ~0 across the
  whole curve — both waves spawn at the pit, ~45 squares north of where the PCs
  are confronted, and can't cross a 79-deep house in the round budget. So this
  is really *"5 level-6 PCs vs the 18 southern openers in isolation,"* which they
  dismantle (≈1150 dealt / ≈115 taken in a bare run). **This is the first real
  design lever to decide** (Jeff's steer: give the pit waves ranged reach and/or
  closer entrances — deferred until the stage-timing and fire clock are settled,
  since those set the true round budget).
- **The openers are light on their own.** ~14.5 of 18 down by round 5 for ~28%
  party HP. The encounter's teeth are meant to be the *accumulating waves*; with
  the waves absent, the opener is a warm-up.

## What this tells the surrounding design

- **Round budget:** the guard fight is decided in the first ~5 rounds, and the
  stage subplot (Nico subdued "by end of round 3") fits comfortably inside it.
- **Fire has room:** since the guards don't threaten a wipe, the burning-house
  layer can be a genuine second threat without instantly compounding to a TPK.

## The manacle-preference model (2026-07)

The guards now try to CAPTURE, not just damage:
- **Manacle preference** — a Vise binds a controlled, still-conscious PC
  (grappled/stunned/restrained) in preference to clubbing it (`[multiattack.bind]`
  priority above the club).
- **`neutralizes`** (new general engine flag) — a manacled PC drops out of the
  guards' targeting (`battlefield.enemies_of`): the cartel leaves it helpless and
  moves on, instead of the swarm clubbing a bound PC to 0. This is the mechanic
  that's *supposed* to turn a defeat into a survivable capture.
- **Recharge 5-6** manacles (opera override) — "pick up and re-use" instead of
  1/day; **one prisoner per Vise** at a time (`not is_source_of('manacled')`).
- **Bind the downed** (`manacle_downed` + `downed_enemies` selector) — a helpless
  0-HP PC gets bound on the floor when there's nothing else to do.

**Result in the rush model (200 trials): it fires but barely converts.** Manacle
incidence is 90%, `neutralizes` works — yet the *survivable, bound-but-conscious*
outcome is still ~1%, and the effective-TPK (nobody conscious) is ~82%.

**Why, and it's a real finding, not a modeling fault:** 18 guards beat a
controlled PC from full to 0 in the *same round* it's grabbed — faster than a
Vise's initiative comes up to bind it. So the manacles land almost entirely on
the *already-downed* (bound helpless on the floor = still dying under the user's
definition), not on conscious PCs. Confirmed robust: the one-prisoner gate didn't
change it, and `guard_cartel` (a non-swarm skirmish) is unaffected by the base
changes.

The manacle preference's payoff therefore shows up in a **non-suicidal** fight,
not the blind rush — i.e. it's gated behind the same guard-placement work being
deferred to after the fire. The one change that would produce conscious captures
*in a swarm* is the guards **easing off** a controlled PC (holding fire so the
binder can bind it before it's downed) — a bigger behavioural change than the
written "won't hesitate to reduce to 0," flagged for the placement pass.

## The guards ARREST — subduing model (2026-07)

The base-guard reframe that resolves the whole failure question: the guards are an
arrest force, so a defeated party isn't a dead party — it's the scripted hand-off
into the burning-building phase 2. Modeled with a new `[simulation] subduing_side`
flag: when a member of that side reduces a PC to 0 HP, the PC is knocked out cold
and STABLE (RAW: a melee hit to 0 may knock unconscious) instead of dying — no
death saves, no massive-damage instakill. (RAW knockout is melee-only; applied
force-wide here for the arrest premise.)

**Result — the blind rush, guards subduing (200 trials):**

| Outcome | Of trials |
|---|---|
| A PC actually **died** | **0.0%** |
| left dying on death saves | 0.0% |
| **Subdued → phase 2** (party fully down, cleanly KO'd & stable) | **85.5%** |
| Escaped (≥1 PC reached the stage) | 14% |
| mean PCs knocked out & stable at end | 4.74 / 5 |
| mean PCs manacled at end | 1.87 |
| mean PCs dead at end | 0.00 |

**There is no guard-caused TPK.** A defeat resolves as the party unconscious and
stable on the floor — ~2 of them manacled — which is exactly the phase-2 opening:
everyone wakes up, bound, surrounded by fire. The only thing that can now kill a
PC here is the fire (phase 2, unmodeled). ~2 manacled (not 5) is the recharge +
one-prisoner-per-Vise limit at work: everyone is KO'd, but only some get the
cuffs — which maps cleanly onto "put the PCs' own rune-inscribed manacles on Nico
and let the rest burn": there aren't enough guard manacles to bind the whole
party anyway.

This supersedes the grim "79-82% effective TPK" read from the pre-subdue model:
that was measuring death-save dying, which the guards no longer inflict.

## P5 — THE FIRE IS IN (2026-07). It changes the phase-1 answer completely.

The Pyre Elemental now ignites on round 2 (Mathieu's lantern), in full attack
mode, on top of the 18-guard fight. 200 trials, rush-to-the-stage party:

| measure | guards only (before) | **+ fire (now)** |
|---|---|---|
| rounds to resolve | 10.6 | **3.5** |
| party HP spent | 98% | 100% |
| SUBDUED -> phase 2 | 85.5% | **100%** |
| ...**cleanly** (all KO'd & stable) | **85.5%** | **0%** |
| a PC left DYING on death saves | 0% | **99.5%** |
| a PC actually DIES | 0.0% | **16.5%** |
| mean PCs dead | 0.00 | 0.20 |

Elemental damage to the PCs: **222 per trial** (debris 131, enflame 51, fire
ticks 39) — several times what 27 guards manage. It also mauls its own side:
**14.6 of 27 guards down** at the end, which is faithful to the d12 table (6 of
its 12 outcomes target guards) and is exactly the "indiscriminate force of
nature" the scene wants.

### The finding that matters: fire breaks the clean hand-off

The subdue rule exists so a beaten party wakes up *manacled, not dead*. **Fire
doesn't subdue.** Once it ignites, it — not the guards — becomes the thing that
drops PCs, so instead of 85% clean knockouts we get **99.5% of trials with
someone bleeding out** and **16.5% with an outright death before phase 2 even
starts**.

This is not a bug and not a modeling artifact: the prose says so explicitly —
subdual "will not, however, protect PCs from falling debris or spreading fires."
It's the design working as written. What the number adds is *how much* it bites:
the fight collapses from ~11 rounds to **3.5**, and the intended "you wake up in
manacles" outcome now arrives with a body or two on the floor.

**Worth a decision, not a fix** (all three are legitimate; the sim can price any
of them):
1. **Accept it** — the fire is meant to be a killer, one death per ~5 runs is the
   price of a burning building, and the prose's "PCs reduced to 0 wake up with 1
   hit point" arguably covers everyone at 0 regardless of cause.
2. **Light the fire later** (round 3-4) so the guards get to finish subduing
   first, preserving the clean capture and making the fire a phase-2 problem.
3. **Aim it at the guards early** — narratively it's "encompassing the entire
   building", not hunting the party; weighting its first rounds toward the guard
   ranks would keep the pressure without stealing the capture.

Not softened here, per the standing call: publish the hard number, let the DM
ease off. Levers 2 and 3 are one-line changes if you want them.

### RETUNE: -1d6 on every elemental attack barely moves phase 1

`drop_d6 = 1` (Falling Debris 4d6->3d6 and its fire 2d6->1d6, Large 8d6->7d6 /
4d6->3d6, Enflame 4d6->3d6), 200 trials:

| measure | full dice | **-1d6** |
|---|---|---|
| elemental damage to PCs | 222 | **207** (-7%) |
| rounds to resolve | 3.5 | **4.2** |
| clean subdual | 0% | 0% |
| a PC actually dies | 16.5% | **22.0%** |
| mean PCs KO'd & stable | 0.92 | 1.45 |

**Cutting the dice did not make phase 1 safer, and may have made it slightly
worse.** The reason is structural: total damage here is bounded by the party's
hit points (~232), not by the elemental's dice — the fight runs until the party
is down either way, so weaker hits just mean *more rounds of hits*. The party
buys ~0.7 extra rounds and spends them being on fire.

(The death-rate rise 16.5% -> 22.0% is about 2 standard errors at 200 trials —
suggestive, not conclusive. The safe reading is "no improvement", not "actively
worse".)

### TIMING SWEEP: when should the elemental start attacking?

Two clocks are now separate and TOML-configurable on the hazard actor:
`start_round` (the lantern falls — fire on the board) and **`attack_round`** (it
becomes a monster: debris, Enflame, legendary actions). Swept with
`elemental_timing_report.py`, 150 trials each:

| attack_round | rounds | reached stage | PC dies | clean subdual | guards down | fire dmg to PCs | closest PC |
|---|---|---|---|---|---|---|---|
| 2 *(= 4; clamped)* | 7.0 | 0% | **19%** | 2% | 17.8 | 156 | row 41 |
| 4 | 7.0 | 0% | **19%** | 2% | 17.8 | 156 | row 41 |
| 6 | 7.3 | 0% | 4% | 1% | 15.3 | 110 | row 39 |
| 8 | 8.3 | 0% | 0% | 3% | 13.5 | 72 | row 35 |
| 10 | 9.8 | 1% | 1% | 37% | 13.2 | 25 | row 29 |
| **never** | 10.5 | **15%** | 1% | **84%** | 11.4 | 0 | row 26 |

**HYPOTHESIS REFUTED.** The prediction was that delaying the elemental would make
things *worse* for the PCs, since it's the only thing that hurts the guards.
Half of that is true — guards down falls 17.8 -> 11.4 without it — but it is
swamped: the elemental spends **156 damage on the PCs** to buy them ~6 dead
guards. Delay improves every PC metric monotonically (deaths 19% -> 1%, clean
subdual 2% -> 84%, northernmost reach row 41 -> 26). **The party does not need
the elemental's help killing guards; it needs the elemental to leave them alone.**

Two mechanical notes from the sweep:
* `attack_round` 2 and 4 are identical because `start_round = 4` gates the actor
  waking at all. To attack earlier, `start_round` must move too.
* **The lantern fire is currently inert.** At `never`, fire damage to PCs is
  **0** — `ignite_at` is the stage (row 8) and the party never gets north of row
  26. So the round-4 ignition is pure scenery today; *all* the fire's bite comes
  from debris once it starts attacking. To make the burning building pressure
  the party during the guard fight, the fire has to start where the FIGHT is
  (the southern seats), not on the stage.

**And the finding underneath all of it:** even with the elemental switched off
entirely, only **15%** of trials reach the stage. The elemental was never the
blocker — 18+ guards and 60 rows of difficult terrain are. If "fight your way to
Nico" is meant to be achievable, the lever is guard placement or the party's
entry point, not the fire's timing.

**So if phase 1's fire needs to be less punishing, the dice are the wrong lever.**
Use the timing/targeting levers above (light it round 3-4, or aim its opening
rounds at the guards) — those change how many rounds the party spends exposed,
which is what actually drives the number.

## Open levers (deferred, per "let's see how things turn out first")

1. Make the pit waves matter — ranged weapons, closer/side entrances, or a party
   that advances north into them (a longer, objective-driven fight).
2. The two slinger cover squads + the conditional squad-#1 trickle, once the
   noble-retreat timing is fixed.
3. The Constable-death reprieve and the guards' round-5 flee, once the fire clock
   sets the real end-of-scene.
