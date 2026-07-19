# Known issues — parity gaps and deliberate cuts

A consolidated backlog of every unresolved parity gap and deliberate scope cut found
during Phases 3-5, so a follow-up pass can work through them without re-reading every
sim's own `PARITY STATUS` comment first. **Intentionally not tackled during
implementation** (Phases 0-6 are about getting the new engine built and every sim
migrated, not about matching the old engine to the last percentage point) — revisit
this list once the whole workspace is otherwise done (Phase 6's retirement checklist).

Each entry: what's wrong, where it shows up, current best theory, and what a fix would
touch. Ordered roughly by how many sims it taints (fix the top ones first — several of
the sim-level "FAILs" below are actually the same root cause reappearing).

---

## Bug A — Monster damage output overshoots baseline — ROOT-CAUSED & FIXED (standard party)

**Status (2026-07, follow-up session):** diagnosed to completion and fixed for the
standard "adventurers" party. **The otyugh's own mechanics were never wrong** — hit rate
scales correctly with AC, crit rate is ~5%, damage-per-hit is exactly its dice. The
"overshoot" was entirely *the otyugh getting ~0.6 more turns per trial* because the
**party was killing it too slowly and soaking too much damage** — specifically, party
members were missing class features cut back in Phase 3/4:

- **thief_rogue** had no Sneak Attack (dealing ~half its real damage) and no Uncanny
  Dodge (soaking ~3x the damage it should). It's a primary striker; at half strength the
  otyugh lived longer *and* the rogue's inflated damage-taken padded the monster's total.
- **hunter_ranger** had no Hunter's Mark or Colossus Slayer riders — the party's top
  baseline DPS (~42) was dealing ~26.

Restoring both (see the rebuild in each creature file, and the new primitives below)
took `otyugh_cr5_dps` from **+54% to −6%**; likewise `otyugh_cr5_compare/standard` and
`otyugh_cr5_monk/standard_1x` (single otyugh, standard party). Decisive evidence: scaling
party damage +25% barely moved the otyugh, but restoring the two rogue features alone
dropped it from +57% to +7%.

**New reusable primitives this required** (all with unit tests, all now available to any
creature): `reduce_damage` effect + `taking_damage` reaction publish point in
`_resolve_attack` (Uncanny Dodge; reusable for Barbarian Rage resistance); `mark_turn`
effect + `turn_marked(key)` predicate (once-per-turn riders like Sneak Attack); and the
Concentration pattern (a `taking_damage` reaction doing a CON save that drops a
self-condition gating a rider — Hunter's Mark).

**What's left (deliberately not done — same root cause, different members):**
- **Other parties still overshoot** because *their* members are missing features:
  `otyugh_cr5_compare/vanguard` (+72%) and `otyugh_cr5_monk/monk_*` (+73%/+16%) need the
  same rebuild for the barbarian (Rage/Reckless), paladin (Divine Smite), and monk (Flurry
  of Blows / Martial Arts). Identical technique, now-existing tools — mostly TOML.
- **Multi-otyugh standard sims now *under*shoot** (`otyugh_cr5_x2`/`_monk standard_2x`,
  monster damage ~−25%): in the longer 2-otyugh fight the ranger *kites too safely on the
  board* (takes 10.4 dmg vs the abstract baseline's 12.5), so it rarely loses Concentration
  and keeps Hunter's Mark up the whole fight, dealing ~+31%. This is an **inherent
  board-vs-abstract difference** (the abstract old engine had no kiting), not a distortable
  bug — the Concentration mechanic is correct and does fire; the board is simply safer.
  Left as an accepted model difference.
- `poisoned_otyugh` still undershoots (~0.48 vs baseline 0.92) — see Bug B.

---

## Bug B — thief_rogue was missing Sneak Attack / Uncanny Dodge / Cunning Strike — MOSTLY FIXED

**Status (2026-07, same follow-up session as Bug A):** the rogue was rebuilt as part of
fixing Bug A (the two are the same root cause). `thief_rogue.toml` now has Sneak Attack
(once-per-turn 2d6 rider via `turn_marked`), Uncanny Dodge (`taking_damage` reaction +
`reduce_damage`), and a Cunning Strike Poison approximation. Result on `otyugh_cr5_dps`:
`dealt_thief_rogue` −25% → **−3%**, `taken_thief_rogue` +219% → **+16%**. Bug B's damage
side is closed.

**Remaining, and now known to be irreducible:** `poisoned_<monster>` still undershoots
(~0.48 vs baseline ~0.92). The rogue's poison is modeled as a DC-15 CON save on the sneak
hit; the otyugh's good CON save (+7) means it resists ~65% of the time, so over ~2-3 rogue
turns it ends up poisoned ~48%, not 92%. The old engine clearly applied poison far more
reliably (lower DC, no save, or more attempts via its exact alternating poison/trip
Cunning Strike logic), but **that logic is unrecoverable** — the old engine is deleted.
Since `poisoned` is a purely cosmetic marker (no roll effect in either engine — see
`conditions.py`), this column will stay a documented cosmetic miss rather than be
force-fit by distorting the save. Not worth further chasing.

The sneak die is 2d6 (not the full 3d6) as a stand-in for the 2024 Cunning Strike
dice-for-effect trade; with 3d6 `dealt_thief_rogue` overshot (+17%), so 2d6 is the tuned
value, documented in the file header as an approximation of the (lost) exact rider.

---

## Bug C — masks (Phase 5) parity fails badly, not just marginally

**Symptom:** most `dealt_*`/`taken_*` columns 20-60% off baseline, several `down_*`
rates off by 10-58 percentage points — `down_thief_rogue` alone is ~7x baseline
(0.09 -> 0.6-0.7). Categorically worse than any otyugh sim's gap above.

**Where:** `sims/masks`, all 6 sweep variants. Full numbers: re-run
`scratch/check_masks_parity.py` (seeds come from each `sims/masks/<variant>/baseline/
meta.json`, so it's reproducible without re-deriving anything).

**Not this sim's own new bug:** the `poisoned_*` mismatch is Bug B, not new. Chase Bug
A first — masks' Bruiser/Hectors share the exact pipeline Bug A already taints.

**Genuinely new leads, unconfirmed:**
1. The "Break generator" focus strategy (kill the Poets first, which should suppress
   the Hectors' `+2d6` advantage rider) shows *higher* Hector damage than "Natural" in
   a quick check — backwards from the old engine's own finding. Check whether
   `event.advantaged` (set by `actions._resolve_attack`, read by `masked_hector.toml`'s
   `damage_rider` `when` clause) is actually wired correctly, or whether this is a real
   emergent effect of the fight resolving differently under that strategy (e.g. more
   Hector turns before the Poets' Insult would've mattered anyway).
2. `down_thief_rogue`'s huge jump may be the new `priority_strike` tag (added this
   phase specifically for masks — see `sims/masks/simulation.toml`) over-concentrating
   both the Bruiser's own attacks *and* its Deceptive Defense reaction onto ranger/rogue
   every single trial, rather than spreading across the party the way the old engine's
   looser heuristics did. Test: temporarily strip the `priority_strike`-tag-favoring
   `[[behavior.targeting]]` rules from `masked_bruiser.toml` and re-run the parity check
   — if the gap shrinks a lot, this is the (or a) real driver.

**Full design-decision context** (what's declarative vs. hatched, what was cut and
why): `design/06-implementation-guide.md`'s Phase 5 section, and `masked_bruiser.toml`/
`masked_poet.toml`/`masked_hector.toml`'s own header comments.

---

## Gap D — Sleight of Crowd (masks Bruiser bonus action) isn't implemented at all

**Symptom:** the Bruiser never repositions to shield a threatened Poet. Pure
positioning, no direct damage/hit-rate effect, so it's a lower-priority gap than A-C.

**Why it's not just a TOML omission:** `swap_positions`'s `with` field only resolves
`"self"` / `"target"` / `"event.<field>"` (`effects._resolve_ref`) — there's no way to
say "swap with the first ally tagged 'poet'". A real fix needs one of:
- Extend `_resolve_ref`/`loader._validate_target_ref` to accept a 4th form, e.g.
  `"expr:<selector>"`, evaluated via the same `_effect_when_scope` machinery already
  used for effect-call `when` clauses (parse at load time like every other `when`, not
  per-dispatch). This is the more general fix and would also unblock Gap E below.
- Or something narrower/uglier specific to masks (not recommended — the whole point of
  the effect-ref vocabulary is staying game-agnostic).

## Gap E — the Bruiser's "don't move an already-well-placed mark" heuristic is cut

**Symptom:** the Bruiser's own Cruel Rapier hit may re-attach the Mark to its current
attack target even when the Mark is already sitting on a Hector-reachable striker
elsewhere (harmless in the common case — the Bruiser usually attacks the same target
turn over turn, so re-attaching is a same-name no-op — but diverges when Deceptive
Defense marks a different ally moments before the Bruiser's own attack lands).

**Why it's not a TOML omission:** would need two *independently* nested `any()` calls
in one expression (one iterating currently-marked enemies, one iterating Hector allies)
— the expression language's `it` binding is a single slot per `ConcreteScope`, so a
second `any()` inside the first clobbers it. Not fixable by better TOML authoring;
needs either a grammar extension (a second loop variable, e.g. `any2`/nested-`it`
support) or accepting this as permanent.

---

## Lower-priority, smaller cuts (not expected to matter much, but recorded)

- **`killed_on_retreat` (shadow otyugh sims)**: an opportunity-attack/parting-shot on a
  fleeing creature. Documented cut since Phase 4, deferred because it needed Phase 5's
  reaction bus — that bus now exists (`enemy_left_reach` is in `conditions.
  REACTION_TRIGGERS` already) but **nothing publishes it yet** (`reactions.py`'s own
  docstring: only `ally_targeted_by_attack`/`self_targeted_by_attack`/`turn_start` are
  wired). Implementing this needs a publish point in `movement.py` or wherever a
  creature's position changes relative to an adjacent enemy, then the shadow otyugh
  sims' own `retreated`/`killed_on_retreat` columns would need re-checking.
- Poet's `tactic = "kite"` is a looser approximation of the old policy's "step away only
  if an enemy has closed within 15 ft" (kite re-maximizes distance from its own target
  every turn, not distance from the nearest threat specifically) — flagged in
  `masked_poet.toml`'s header, likely a minor contributor to Bug C at most.
