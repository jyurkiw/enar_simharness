# Masked Guests — Monte Carlo sim prompt

Hand the prompt below to a fresh session to build the sim. Context: the three
statblocks form a mutual-dependency network (Poet generates advantage → Hectors
consume advantage + Bruiser's mark → Bruiser tanks and redirects). The sim exists
to validate/tune those draft numbers and quantify how much the network synergy is
worth and how fast it collapses when broken.

---

Build a board-based Monte Carlo simulation of the "masked guests" monster network
for D&D 5e (2024), to validate/tune their draft statblocks.

USE THE SKILL: invoke the `board-sim-integration` skill and follow it. The
combat-agnostic board package `dnd_board` already exists at
E:\Repos\simulations\dnd_board and the engine `dnd5e_combat`
(E:\Repos\simulations\dnd5e_combat) is already integrated with it — do NOT build
a new board engine. Mirror the existing board sims as templates:
  - dnd\otyugh\otyugh_shadow_board  (single-monster board sim)
  - dnd\otyugh\otyugh_shadow_pair   (multi-monster board sim, sight-aware targeting)
Follow dnd5e_combat's conventions: monster archetypes under
src/dnd5e_combat/monsters/<name>/ (defaults.toml + a Policy subclass + register
in monsters/__init__.py), conditions in conditions.py, scenario TOML, and a sim
project folder with pyproject.toml + src/simulation.py + src/scenario.toml.

SOURCE STATBLOCKS (read these first; they contain the exact numbers + design intent):
  E:\Data\enigma-narrative\possession-of-beaumont\design\monsters\masked-guests\masked_bruiser.md
  E:\Data\enigma-narrative\possession-of-beaumont\design\monsters\masked-guests\masked_hector.md
  E:\Data\enigma-narrative\possession-of-beaumont\design\monsters\masked-guests\masked_poet.md

MONSTER GROUP (one encounter): 1 Masked Bruiser (CR4), 2 Masked Poets (CR3),
2 Masked Hectors (CR3). This is the COMPLETE mutual-dependency network — the whole
point of the sim is to measure how much the synergy is worth and how fast it
collapses when the party breaks it.

OPPONENTS: run the same monster group against BOTH of these existing parties and
report them side by side (like otyugh_cr5_compare):
  - data/parties/adventurers.toml       (standard level-5 party)
  - data/parties/beaumont_playtest.toml (Beaumont tuning-baseline party)

TARGET DIRECTORY for the sim project: E:\Repos\simulations\dnd\masks

NETWORK MECHANICS TO MODEL (this is the core work — get these right):
  * Poet — Scathing Insult (action, 60 ft, one target it can see): CHA save DC 13;
    on fail 2d10 psychic AND until end of the Poet's next turn, attack rolls
    against that target have ADVANTAGE (grant, not the target's own disadvantage).
    Model as a new condition in the GRANTS_ATTACKERS_ADVANTAGE set. The Poet has
    no weapon/multiattack — Scathing Insult is its whole turn. It is fragile
    (AC 13, HP 55) and the network's advantage generator.
  * Bruiser — Bruiser's Mark: a marked creature has DISADVANTAGE on attacks against
    anyone OTHER than the Bruiser (attacking the Bruiser is penalty-free); the mark
    ends at end of the marked creature's turn if it attacked only the Bruiser, and
    ends if the Bruiser dies; only one creature marked at a time. This is a
    target-CONDITIONAL disadvantage (depends on whether the target == the Bruiser),
    like the existing grappled-by-a-different-enemy rule — implement in attack()/
    the party policies accordingly, not as a blanket condition.
      - Deceptive Defense (REACTION): when a creature it can see attacks an ally
        within 30 ft, the Bruiser swaps places with that ally, becomes the target
        of the attack instead, and marks the attacker. This is a pre-roll,
        attack-redirecting reaction + place swap — the HARDEST piece; it likely
        needs a new engine hook (a reaction that fires before an attack resolves
        and can change the target). Flag it, design the hook cleanly, and gate it
        on the 30 ft range using the board.
      - Sleight of Crowd (bonus action): teleport-swap places with a willing ally
        within 30 ft (repositioning tool — use to protect the Poet / tank hits).
      - Bruiser is a "bag of HP that does nominal damage": AC 14, HP 104,
        2x Rapier +6 (1d8+4). Its value is the mark + damage redirection, not DPR.
  * Hector — 2x Dagger Strike +4 (1d4+2). Riders that CONSUME the network:
      +2d6 piercing if the attack roll had ADVANTAGE (from the Poet's Insult), and
      +3d6 if the target is marked with Bruiser's Mark (removing the mark). AC 16,
      HP 60. Depends entirely on the Poet (advantage) and Bruiser (mark) — on its
      own it is far below CR3 damage.

BOARD / POSITIONING (why this must be a board sim, not abstract):
  * Place the Poet in the back (it must survive; it's the generator), the Bruiser
    mid to cover allies within its 30 ft reaction range, the Hectors in front.
  * The party must cross to reach the Poet — the sim should reveal whether the
    party can punch through to kill the Poet/Bruiser and break the network, or
    whether the Bruiser's swaps + mark keep the squishy nodes alive.
  * Reuse the packaged `arena` board (or author a small ballroom-style map with
    boardtool if you want thematic cover). Movement AI: monsters approach/protect,
    party uses the existing sight-aware targeting.

WHAT TO MEASURE (report per party, side by side):
  * Group DPR and per-monster damage; party HP taken and healing/spell-slot drain.
  * Survival: party wipe %, any-PC-death %, per-PC down/death rates; monster wipe %.
  * NETWORK VALUE: compare "full network" vs "network broken." At minimum, add a
    variant where the party focus-fires the Poet (and/or Bruiser) first, and show
    how much the Hectors' damage collapses when the advantage/mark riders stop
    firing. This is the key design question the statblocks are waiting on.
  * Relate results to the encounter's ~3,200 XP budget vs a level-5 party.

CONVENTIONS & VERIFICATION:
  * Keep the board opt-in / abstract fallback intact; don't regress existing sims.
  * Reuse existing engine helpers (approach/kite/can_see/preferred_target, the
    conditions machinery, the DamageLedger/report). Add new conditions rather than
    hardcoding.
  * Verify: run each party scenario at ~1000 trials; trace a few turns to confirm
    the reaction swap, the mark disadvantage, the advantage grant, and the Hector
    riders all fire correctly; confirm fights are finite and numbers are sane.
  * The statblocks are explicitly DRAFT pending this Monte Carlo pass — surface
    any numbers that look badly over/under-tuned and note them against the CR
    benchmark tables already in the statblock files.

---

## Implementation notes (for whoever runs this)

- **Deceptive Defense is the hard part.** It's a *pre-attack* reaction that
  redirects a hit to a different creature and swaps positions. The engine's
  current reaction hook (`on_incoming_damage`) fires *after* a hit lands, so this
  needs a new "before-attack, can-change-target" hook. Consider building that hook
  first, then layering the mark + swap on top.
- **The mark's disadvantage is target-conditional** (penalty only when *not*
  attacking the Bruiser) — same shape as the grappled-by-a-different-enemy rule
  already in the champion/rogue policies. Copy that pattern.
