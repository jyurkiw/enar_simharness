# masks — the "masked guests" network sim

A board-based Monte Carlo of the **masked guests** monster network for D&D 5e
(2024), built to validate/tune the draft statblocks. One encounter — **1 Masked
Bruiser (CR4), 2 Masked Poets (CR3), 2 Masked Hectors (CR3)** — run against two
level-5 parties on the packaged `arena` board, under three party targeting
strategies, to measure how much the mutual-dependency network is worth and how
fast it collapses when the party breaks it.

```sh
uv sync
uv run python src/simulation.py   # network-value analysis (three party strategies)
uv run python src/scaling.py      # difficulty & scaling sweep across group sizes
```

Statblock sources (draft, pending this pass):
`E:\Data\enigma-narrative\possession-of-beaumont\design\monsters\masked-guests\`.

## The network, and how each piece is modeled

The three statblocks form a generator → consumer → protector loop. All of it is
implemented in the shared `dnd5e_combat` engine (new conditions + one new engine
hook) so nothing is hard-coded in this sim:

| Node | Mechanic | Engine implementation |
|---|---|---|
| **Poet** (generator) | *Scathing Insult* — target CHA save DC 13; on a fail, 2d10 psychic **and attacks against it have Advantage** until end of the Poet's next turn. | New `INSULTED` condition in the `GRANTS_ATTACKERS_ADVANTAGE` set. Its value stores the expiry round; the engine drops it at `begin_round` (`_expire_insults`). |
| **Hector** (consumer) | 2× Dagger Strike; **+2d6 if the roll had Advantage**, **+3d6 if the target is Marked** (removing the mark). | `AttackOutcome.advantaged` reports net advantage (drives +2d6); the policy checks/consumes `MARKED_BY_BRUISER` (drives +3d6). Targeting is **Marked-first then sticky**: it always swings at a Marked enemy it can reach, otherwise stays on last round's target, switching only for a new reachable mark. |
| **Bruiser** (protector) | *Cruel Rapier* (2 attacks; "the target **may** be marked"); *Bruiser's Mark* (disadvantage vs anyone but the Bruiser); *Deceptive Defense* (reaction: swap with an attacked ally, become the target, mark the attacker); *Sleight of Crowd* (bonus-action swap). | **Bruiser's Mark** is a *target-conditional* disadvantage resolved centrally in `CombatContext.attack` — not a blanket condition. Both the rapier and Deceptive Defense place the mark, and the Bruiser keeps it on a **Hector-reachable priority striker** (see marking policy below). **Deceptive Defense** is a new **pre-attack reaction hook**. |

### Deceptive Defense — the new engine hook

Deceptive Defense is a *pre-attack* reaction that redirects a hit to a different
creature — the piece the design brief flagged as the hardest. The engine's
existing reaction hook (`on_incoming_damage`) fires *after* a hit lands, too late
to change the target. So a new hook was added:

- `Policy.intercept_attack(guardian, attacker, target, ctx)` — called by
  `CombatContext._resolve_interception` at the very top of `attack()`, **before
  any dice**, for every living ally of the creature being attacked. It returns a
  replacement target (or `None`). Only the Masked Bruiser overrides it.
- `AttackOutcome.target` carries the creature the attack actually resolved
  against, so callers deal damage / apply riders to the redirected defender.
- The Bruiser's override gates on **one reaction per round**, the **30 ft**
  range (measured on the board), and **line of sight to the attacker**; then it
  swaps board cells with the ally, marks the attacker, and returns itself.

This is a genuine no-op for every other build: with no interceptor the target is
unchanged and no dice are drawn, so existing sims are byte-for-byte identical
(verified with `PYTHONHASHSEED=0`).

### Mark lifecycle

The mark ends (a) the moment the Bruiser dies (checked in `attack()`), and
(b) at the end of the marked creature's turn **unless** it attacked someone other
than the Bruiser that turn (`_end_of_turn`, tracked by the `mark_hit_other`
turn flag). Attacking only the Bruiser sheds the mark but wastes the turn on the
HP-bag; keeping the heat on the Poets/Hectors keeps the mark alive for a Hector
to cash in — exactly the tension the statblock intends.

### Bruiser marking policy (who gets the mark, and why)

The Bruiser has a single mark and two ways to place it (Cruel Rapier on its turn,
Deceptive Defense as a reaction). It works to keep that mark **on a priority
striker the Hectors can actually reach this round** — its `priority_targets`
(default `["ranger", "rogue"]`, per-party tunable). In practice that means the
**melee rogue**, not the **kiting ranger**:

- *Cruel Rapier* favors attacking a Hector-reachable priority striker and marks
  it on a hit, unless the mark is already well-placed on one.
- *Deceptive Defense* still fires to protect any ally from its highest-damage
  foes (it **holds** the reaction for a ranger/rogue rather than burning it on a
  weak attacker), and it always does the swap+redirect — but it **only spends the
  mark on a Hector-reachable striker**. It won't move the mark off the rogue onto
  the ranger, because a mark on the unreachable ranger gives the melee Hectors no
  +3d6.

This was a deliberate tuning decision surfaced by the sim: naively "mark the
highest-damage foe" parked the mark on the ranger 76% of the time (a kiting
archer the Hectors can't reach), and the +3d6 almost never fired. Restricting the
mark to reachable strikers moves it onto the rogue ~90% of the time so the network
actually connects. The trade-off — the ranger no longer eats the mark's
disadvantage debuff — is intentional; the Bruiser still tanks the ranger's shots
via the Deceptive Defense redirect.

## Board & positioning

The packaged `arena` map: the party spawns west and must cross a central wall's
gap. The Hectors sit front (just east of the gap), the Bruiser mid (within 30 ft
of every node so its reaction covers all four squishies), and the fragile Poets
in the back corners. The party has to punch through to silence the generators.

## What it measures

Per party (Standard `adventurers` and `beaumont_playtest`), three strategies:

- **Natural** — focus-fire a Hector (network intact).
- **Break generator** — focus-fire the Poets (kill the Advantage source).
- **Break mark** — focus-fire the Bruiser (kill the Mark + redirection source).

Reported: group and per-node damage, party HP taken, party wipe / any-PC-death /
per-PC down+death rates, monster wipe rate, and the **collapse in Hector damage**
between the intact and broken network. Charts: `masks_*_totals_hist.png`,
`masks_*_{dealt,taken}_by_combatant.png`, and `masks_network_value_*.png`.

## Headline findings (1000 trials each, draft numbers)

- **The Bruiser tanks as intended — attacking it or the back line is a trap.**
  The Bruiser is a damage sponge that *wants* to be hit, and the sim confirms the
  dynamic: focus-firing the Bruiser is a waste of the party's burst (it soaks the
  most damage of any node, ~33 HP/fight, via Deceptive Defense redirects), and
  chasing the back-line **Poets** is actively punished — Hector damage jumps ~+77%
  and party HP taken climbs ~+17 (to ~95) as the party burns tempo crossing the
  room while the freed Hectors farm. The party's correct line is the "natural"
  one: kill the visible front-line Hectors first (lowest HP taken, ~77). So the
  Bruiser's *presence* successfully makes going after the damage/support nodes
  riskier — exactly its design goal — even though its own numbers are nominal.
- **The mark's contribution to Hector offense is modest — Hector survival time
  dominates.** Because only one creature is marked at a time, the +3d6 fires
  about once per round at most, so how long the Hectors live (a function of which
  node the party focuses) swings their damage far more than the mark does. The
  mark's larger role is the *disadvantage tax* it and Deceptive Defense levy on
  whoever tries to punch past the Bruiser.
- **The group under-threatens a level-5 party at these draft numbers.** It deals
  only ~77 total HP over the fight; party wipes ~0%, any-PC-death ~1%, monsters
  wiped ~90%. For its ~3,900 raw XP (moderate-to-high band for five level-5 PCs)
  it plays well below a deadly encounter — the Bruiser's HP, the Hectors'
  base/rider damage, and the Poets' survivability are the dials to raise.
- **The riders fire as designed.** With the network connected the Hectors' mean
  damage per hit runs ~7 (vs the 4.5 base); the smart-marking policy keeps the
  mark on a Hector-reachable rogue ~90% of the time (up from ~24% under naive
  "mark the biggest threat"); Scathing Insult sticks on the majority of targets
  (CHA save DC 13 vs +0 CHA PCs).

## Tuning the statblocks (`[stats]` in `scenario.toml`)

All the scalable numbers live in one place — the `[stats.<archetype>]` tables at
the bottom of [`src/scenario.toml`](src/scenario.toml) — so you can retune the
encounter without touching any Python:

```toml
[stats.masked_hector]
ac = 16
hp = 60
attacks_per_turn = 2          # the multiattack count
advantage_rider = "2d6"
mark_rider = "3d6"
[stats.masked_hector.actions.dagger_strike]
to_hit = 4
damage = "1d4+2"
```

Editable per archetype: **HP, AC, to-hit / save DC, damage codes, the Hector's
rider dice, and `attacks_per_turn`** (the multiattack breakdown). Both sims apply
these to every instance (`src/tuning.py` → `apply_stats`), so a change here flows
into the network-value run *and* the scaling sweep. The values shipped reproduce
the current draft statblocks; they override the engine archetype defaults.

`[stats.masked_bruiser]` also carries **`limited_marking`** (default `true`), a
rules toggle rather than a number:

- `true` (RAW) — one creature marked **at a time**; marking a new target ends
  the mark on whoever held it. This is the statblock as written and everything
  measured above.
- `false` — one mark **per target** instead — the Bruiser can hold marks on
  several targets simultaneously (still never re-marks the same target twice).
  With the default `priority_targets` this lets both the ranger *and* the rogue
  carry a mark at once, giving either Hector an exploitable target more often.

Both modes are implemented in `masked_bruiser`'s `_apply_mark` / `_mark_exploitable`
in the shared engine; `false` is an experimental variant, not a proposed rule
change to the statblock.

## Difficulty & scaling (`src/scaling.py`)

Sweeping the group from 3 to 11 monsters (keeping the network ratio) against both
parties, with the 2024 XP budget for five level-5 PCs as the yardstick
(Low 2,500 / Moderate 5,000 / High 7,500):

| Group B/P/H | XP | Tier | Party HP taken | any-PC death | party wipe | monsters wiped |
|---|---|---|---|---|---|---|
| 1/1/1 | 2,500 | Low–Mod | ~18% | ~0% | 0% | ~100% |
| **1/2/2 (base)** | **3,900** | **Low–Mod** | **~40–47%** | **~1%** | **0%** | **~90%** |
| 1/2/3 | 4,600 | Low–Mod | ~60–73% | 3–5% | 0–0.4% | ~40–50% |
| 2/2/3 | 5,700 | Mod–High | ~120–130% | 15–21% | **18–31%** | ~0% |
| 2/3/4 | 7,100 | Mod–High | ~130–140% | ~18–20% | 42–54% | ~0% |
| 2/4/5 | 8,500 | ≥ High | ~135–145% | ~15% | 71–84% | ~0% |

Two findings:

- **The base encounter (3,900 XP) is a Low–Moderate fight, and plays like one:**
  the party spends ~40–47% of its HP, almost never loses a PC, and wipes the
  group ~90% of the time. Its outcome matches its XP tier — the statblocks are
  *correctly costed*, the encounter simply isn't sized to be scary.
- **Difficulty is a step-function, not a smooth dial, because it's gated by
  total monster HP vs the party's burst.** The party outputs ~380 damage over a
  fight. While the group's total HP is under that (1/2/2 = 334), the party kills
  it inside its alpha and takes little; once total HP clears ~400–500
  (the second Bruiser, 2/2/3 = 498 HP), the group survives the alpha and then
  *grinds the party down* — party wipes jump from ~0% to ~20–30% with a single
  added tank. There's very little "hard but safe" middle ground.

The lever this points at: the monsters threaten the party almost entirely by
**surviving** (their per-round damage is low), so piling on HP makes difficulty
swing violently around the kill/no-kill threshold. To get a tunable, *fair* hard
encounter, raise the monsters' **damage per round** (Hector base/riders, Poet DC,
more Hectors) rather than stacking Bruiser HP — so a group that survives a bit
longer ramps difficulty smoothly instead of flipping to a near-TPK. (Note the
8-round cap understates deadliness in the top tiers, where the monsters win the
attrition race and would keep grinding past round 8.)

## Modeling caveats

- **Melee weapons have no range cap in the engine.** A rangeless melee action
  made from outside reach resolves under the ranged rules (LOS + cover, no range
  band) rather than whiffing — a pre-existing engine behavior shared by every
  board sim, not specific to this one. It slightly softens the "melee can't reach
  the back-line Poet" effect but doesn't change the qualitative findings.
- **Save-based effects ignore line of sight** (as in the other board sims). Only
  attack-roll actions are LOS/cover gated. Scathing Insult is a save and so isn't
  sight-gated here.
- **Deceptive Defense redirects the whole triggering attack**; subsequent attacks
  in the same Multiattack keep their original target. The place-swap is honored,
  so a redirected attacker's later swings may find their original target
  displaced. Its mark is modeled as tactical ("may"): the reaction always does
  the protective swap/redirect but only spends the Bruiser's one mark on a
  Hector-reachable striker (see the marking policy above).
- Cross-process runs vary slightly (set-iteration order under hash
  randomization, like the other board sims); Monte Carlo means are stable to
  ~1%. Pin `PYTHONHASHSEED=0` for bit-reproducible runs.
