# Cathedral Extraction — Implementation Plan & Checklist

**Branch:** `cathedral-encounter`. Every step below is committed and tagged
(`cathedral-NN-slug`); the checklist is updated *in the same commit* so this file
always reflects what's done. To resume: read the checklist, `git log --oneline`,
pick up the first unchecked box.

## The encounter

Central chamber of the Cathedral. The party must break into a sealed confessio,
grab the box (saint's ashes + Quill), and **escape** — this is an *extraction*,
not a deathmatch. Success = box carried out with **nobody down**.

**Defenders** (all fight to the death for Praesidius Antoine du Monte):
2 Cathedral Guard (Knight, CR3), 2 Priest Acolyte (Acolyte, CR1/4),
2 Cult Fanatic (CR2), 6 Cult Agitator (Spy, CR1), 8 Cultist (CR1/8).
**Reinforcements:** after round 5, a group of **4 Cathedral Guard + 1 Priest
(CR2)** arrives from the back every 3 rounds (so rounds 6 and 9 within a 10-round
test).

**Objective:** behind the lectern is the confessio; the concrete seal is
**AC 14, 20 HP** (attack it to break in — noisy). Once broken, the box is picked
up as an action by anyone adjacent to the pulpit; it needs both hands but you can
run with it.

**PC plan (the intended competent line):** fighter/barbarian spends a round
breaking the seal → rogue/monk grabs the box and runs → everyone retreats. PCs
get **1 round of attacks after retreat begins**, then are assumed to escape *iff
nobody is down*.

**Board:** ~25 wide × 40 long. Central aisle, pews flanking (difficult terrain +
half cover). PC entry mid-south (y=40, x≈11–14). Lectern ≈ (x8, y10). Enemies
enter from the back (north, low y).

## PCs → level 6

Copy the level-5 archetypes to `*_l6.toml` (leave L5 files untouched), raised per
SRD class progression. Wizard also gains **fireball, shatter, thunder wave,
shield**, an evoker **Sculpt Spells**, and a **3-leveled-spell budget** (one each
of 1st/2nd/3rd per fight; shield is a separate 2-use reaction).

## New engine work (the big rocks)

- **Sphere + cube AoE** (fireball, shatter; thunder wave) on top of `aoe.py`'s line.
- **Sculpt Spells:** allies inside an evocation area auto-succeed / take no damage,
  up to `1 + spell level` of them. (`aoe.best_line` already has an `allow_allies`
  seam.)
- **Shield reaction:** `self_targeted_by_attack` → +5 AC vs that attack, gated
  (below half HP, or during retreat), 2 uses. Needs a temp-AC-bonus grant read by
  `actions.attack`.
- **Reinforcement waves:** mid-trial spawning (engine has none yet).
- **Extraction scenario:** a destructible seal object (no turns, has AC/HP), a box
  pickup/carry action, a party escape-hatch brain driving break→grab→retreat, and
  a flag-based win condition via `end_trial` outcome.

## Checklist

- [x] **00** Plan doc + branch (`cathedral-00-plan`)
- [x] **01** Enemy statblocks: cathedral_guard, priest_acolyte, cult_fanatic, cult_agitator, cultist, priest (`cathedral-01-enemies`)
- [x] **02** Level-6 PC copies of all 8 archetypes (`cathedral-02-pcs-l6`)
- [x] **03** Cathedral board (25×40, aisle + pews + doors) (`cathedral-03-board`)
- [x] **04** Minimal deathmatch sim runs to 10 rounds — MILESTONE (`cathedral-04-deathmatch`)
- [x] **05** Sphere + cube AoE geometry in `aoe.py` + loader shapes (`cathedral-05-aoe-shapes`)
- [x] **06** Wizard L6 spells (fireball/shatter/thunderwave) + 1/1/1 leveled budget (`cathedral-06-wizard-spells`)
- [x] **07** Sculpt Spells (allies auto-succeed up to 1+level) (`cathedral-07-sculpt`)
- [x] **08** Shield reaction spell (+5 AC, gated, 2 uses) (`cathedral-08-shield`)
- [x] **09** Reinforcement waves (mid-trial spawn, r6 + every 3) (`cathedral-09-reinforcements`)
- [x] **10** Extraction objective: seal object, box carry, retreat/escape win (`cathedral-10-extraction`)
- [x] **11** Full sim wired + 10-round report + findings (`cathedral-11-run`)

## Open questions / assumptions (resolve in the morning)

- NPC stat values are standard MM/2024 approximations (Knight, Acolyte, Cult
  Fanatic, Spy, Cultist, Priest); not copied from the SRD PDF line-by-line. Flag
  for correction.
- "every 3 turns" read as **every 3 rounds** (waves at r6, r9).
- Reinforcement/extraction/scenario mechanics may need engine additions that
  don't exist yet; each is noted at its step. Where a clean generic mechanism is
  too big for the block, a scenario-scoped escape hatch is used and flagged.

## FINDINGS — 10-round run (500 trials/party, step 11)

The full sim runs end-to-end to 10 rounds (CLI `dnd5e-sim run
sims/cathedral/simulation.toml`, both parties via sweep). Result, as currently
modeled:

| metric | STANDARD | ALTERNATE |
|---|---|---|
| seal broken (broke in) | 6.6% | 11.2% |
| no PC down all fight | 0.0% | 0.0% |
| **extraction success** (seal broken + nobody down) | **0.0%** | **0.0%** |
| full party wipe | 100% | 99.8% |
| party damage dealt (mean) | 341 | 313 |

**This is a near-certain TPK as modeled.** Reinforcement guards (r6) take ~0%
damage — the party is already spent before they arrive, so the base 20-strong
horde is doing the wiping; the waves barely matter. Two things are tangled here
and want a morning look:

1. **The encounter is genuinely enormous.** 5 level-6 PCs vs 20 defenders
   (2 Knight, 2 Fanatic, 6 Spy, 8 Cultist, 2 Acolyte) across a 40-long room,
   with the objective at the *far* end by the horde. Even with the fully-spelled
   Sculpt evoker, that's a lot of bodies and a long, exposed approach.
2. **The extraction tactic isn't really modeled yet.** The party currently
   fights an *attrition* battle in the open (breaker charges the seal, everyone
   else trades blows) — there is no modeled smash-and-grab-and-**retreat**. The
   intended line (break in fast, grab, everyone runs, 1 round of cover attacks,
   gone) would cut exposure dramatically and is the thing most likely to move
   these numbers. That needs: a real retreat mode (party disengages south once
   `seal_broken`), the `party_retreating` flag (already referenced by Shield),
   and a proper carry/escape end-state. This is the biggest remaining build.

So: the machinery all works and the answer to "test to 10 rounds" is delivered,
but the 0% should be read as "this is a death-trap for a stand-and-fight party" —
whether it's a *fair* smash-and-grab needs the retreat model before we trust the
number. Likely also worth revisiting: fewer defenders or a nearer seal, and the
deferred Paladin Aura (would help the alternate party's saves vs the casters).

## Running log (issues to revisit)

- **02:** L6 copies are HP+level bumps only (ASI is levels 4/8, not 6). Deferred
  L6 class features that need engine work, to revisit: **Paladin Aura of
  Protection** (allies within 10 ft +CHA to saves — needs a save-bonus aura, no
  such grant exists yet); Cleric extra slots / Channel Divinity (no combat delta
  in these sims); Monk Ki-Empowered/martial-die unchanged at L6. Header line-2
  comment still reads "level 5" (cosmetic; line-1 AUTO-DERIVED note clarifies).
  Wizard L6 spells (fireball/shatter/thunderwave/shield) + Sculpt land in steps
  06–08 on `evoker_wizard_l6.toml`.
- **04:** Deathmatch validation runs clean to 10 rounds; party TPK 98.7% as
  expected (5v20, no AoE wizard yet, no extraction win). Note: on the 40-long
  board both sides start ~34 cells apart, so a pure deathmatch burns early rounds
  closing distance — a non-issue for the extraction (the seal is at the north
  chancel *near* the horde, so PCs charge toward the objective, not away). Kept
  `deathmatch.toml` as a standing pure-combat reference.
- **09:** Reinforcements spawn at round start via system.turn_order and are
  **appended to the tail** of the initiative order (no per-wave initiative roll —
  they act last on arrival; a fair simplification, flag if it matters). Ledger
  now knows wave names/sides (cli). Verified: wave-6 arrives and acts, monster
  damage 240->295. Wave-9 rarely fires in a deathmatch (trial ends first) — it'll
  matter more in the shorter extraction runs only if the party lingers.

## UPDATE — objective targeting + emergency AoE (steps 12–13)

Two general features added (in response to "melee-only objective" + "emergency
Fireball feast"), plus a real bug fixed:

- **BUG FIX:** statblock-level `tags` were dropped by the loader, so **Sculpt
  Spells had been inert in-sim** the whole time. `has_tag` now unions statblock +
  combatant tags. The L6 evoker's Sculpt is finally live.
- **`engaged_by = [tags]`** (agent-scoped target reservation): only agents with a
  matching tag target the creature, and they prioritize it; everyone else ignores
  it (direct + AoE). Seal is `engaged_by=["breaker"]`; melee carry `breaker`.
- **Emergency AoE is declarative**: `[multiattack.X]` `when=<situation>` + ability
  `costs` + resource `uses=X` already means "use A up to X times in situation Z,
  above the routine". Wizard's 3rd-level slots -> 3; dropped the forcing hatch so
  Fireball fires every round a 2+ cluster exists until slots are gone.

Result (500 trials/party):

| metric | STANDARD | ALTERNATE |
|---|---|---|
| seal broken (REACH objective) | 94% | 96% |
| extraction success (seal + nobody down) | 15% | 38% |
| full wipe | 80% | 49% |

From a guaranteed TPK to hard-but-survivable — and the smash-and-grab now
reliably reaches the objective. **Remaining lever:** the retreat/escape model
(break in -> grab -> everyone runs -> 1 cover round -> gone). Because success is
currently "nobody down after 10 rounds of standing and fighting", modeling the
actual retreat should push extraction well up from 15/38%.

## UPDATE — retreat / extraction model (step 14)

New first-class `[extraction]` scenario block (loader.ExtractionSpec + system):
```toml
[extraction]
objective = "confessio_seal"   # the creature whose destruction = "box secured"
exit = [12, 39]                # party flees toward this cell
cover_rounds = 1               # rounds of cover fire after securing, then gone
```
Once the objective is down, the system sets `party_retreating` (arms Shield's
2nd trigger too), party members flee toward `exit` (still firing cover), and after
`cover_rounds` the trial ends. `finalize_trial` scores **`secured`** (box grabbed)
and **`extracted`** (secured AND nobody down) — the encounter's own get-away rule.

Result (500 trials/party), the smash-and-grab finally modeled:

| metric | STANDARD | ALTERNATE |
|---|---|---|
| secured (reached + grabbed the box) | 94% | 96% |
| **extracted clean** (nobody down) | **33%** | **17%** |
| any PC down | 66% | 83% |
| full wipe | **4%** | **1%** |

The fight is now what the brief wanted: reaching and grabbing the box is nearly
automatic, a total wipe almost never happens, and getting EVERYONE out clean is
the genuine challenge. Tactical finding: the ranged-heavier standard party
extracts cleaner (33%) than the all-melee-front alternate (17%), which commits
more bodies deep and eats more casualties on the way out. Levers to raise the
clean rate: `cover_rounds`, party composition, and the still-deferred Paladin
Aura of Protection (would shore up the alternate party's saves).
