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
- [ ] **01** Enemy statblocks: cathedral_guard, priest_acolyte, cult_fanatic, cult_agitator, cultist, priest (`cathedral-01-enemies`)
- [ ] **02** Level-6 PC copies of all 8 archetypes (`cathedral-02-pcs-l6`)
- [ ] **03** Cathedral board (25×40, aisle + pews + doors) (`cathedral-03-board`)
- [ ] **04** Minimal deathmatch sim runs to 10 rounds — MILESTONE (`cathedral-04-deathmatch`)
- [ ] **05** Sphere + cube AoE geometry in `aoe.py` + loader shapes (`cathedral-05-aoe-shapes`)
- [ ] **06** Wizard L6 spells (fireball/shatter/thunderwave) + 1/1/1 leveled budget (`cathedral-06-wizard-spells`)
- [ ] **07** Sculpt Spells (allies auto-succeed up to 1+level) (`cathedral-07-sculpt`)
- [ ] **08** Shield reaction spell (+5 AC, gated, 2 uses) (`cathedral-08-shield`)
- [ ] **09** Reinforcement waves (mid-trial spawn, r6 + every 3) (`cathedral-09-reinforcements`)
- [ ] **10** Extraction objective: seal object, box carry, retreat/escape win (`cathedral-10-extraction`)
- [ ] **11** Full sim wired + 10-round report + findings (`cathedral-11-run`)

## Open questions / assumptions (resolve in the morning)

- NPC stat values are standard MM/2024 approximations (Knight, Acolyte, Cult
  Fanatic, Spy, Cultist, Priest); not copied from the SRD PDF line-by-line. Flag
  for correction.
- "every 3 turns" read as **every 3 rounds** (waves at r6, r9).
- Reinforcement/extraction/scenario mechanics may need engine additions that
  don't exist yet; each is noted at its step. Where a clean generic mechanism is
  too big for the block, a scenario-scoped escape hatch is used and flagged.

## Running log (issues to revisit)

_(appended as steps land)_
