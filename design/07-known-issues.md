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

## Bug A — Monster damage output overshoots baseline (systemic, cross-sim)

**Symptom:** total damage dealt by the monster side is 12-171% over the old-engine
baseline, magnitude scaling with rounds/monster-count (worse with more turns for the
per-turn overshoot to compound). Party-side damage and down/wipe rates are pulled off
along with it as a knock-on effect.

**Where:** every one of the 7 otyugh sims (`otyugh_cr5_dps` ~54% over, `_x2` compounds
it with 2 otyughs, `_compare`/`_monk` 55-72%/12-171% across variants, `_shadow_solo`/
`_pair`/`_board` 66-142% depending on rounds-per-monster). **Very likely also the
dominant driver** behind masks' `dealt_masked_bruiser`/`dealt_masked_hector_*` gaps
(Phase 5) — the Bruiser/Hectors run the exact same `select_targets`/`ctx.attack`
pipeline as the otyugh, and masks was never checked against this hypothesis before
Phase 5 was paused (see Bug C).

**Leading theory (not confirmed):** the otyugh's targeting was fixed in Phase 4 to
match the old engine's uniform-random target choice (`ctx.choice`, replacing an
initial "always nearest" default) — this now lands more hits against the party's
lower-AC members than the baseline shows. The *exact* remaining discrepancy (is it
purely AC-selection bias, a movement/reach interaction, or something in the resolver's
hit-math) was never isolated further — every sim just re-confirmed the same pattern
without digging into the resolver itself.

**Where to look first:** `dnd5e/src/dnd5e/actions.py`'s `attack()`/`_resolve_attack`
and `behavior.py`'s `select_targets` — compare a single fixed matchup (one otyugh, one
fixed-AC party member, no randomness in targeting) between old and new engines at the
resolver level before reintroducing target-selection randomness, to isolate whether
the gap is in target *selection* or in the roll/damage math itself.

---

## Bug B — thief_rogue's Cunning Strike rider was never implemented

**Symptom:** `dealt_thief_rogue` runs 18-45% under baseline everywhere; `poisoned_*`
(monster side) reads a flat 0% in the new engine vs. baseline's 39-99% — Cunning
Strike is what poisons the *target*, not the reverse, and it's simply missing.

**Where:** every otyugh sim, and masks (Phase 5) — same root cause resurfacing, not a
new bug there.

**Deliberate cut since:** Phase 3 (`thief_rogue.toml`'s conversion never carried this
over — needs a `damage_rider`-shaped effect plus turn-alternating "which effect fires
this turn" state that didn't exist in the engine yet at the time).

**What a fix touches:** `effects.py` already has `damage_rider` (built for masks'
Hector in Phase 5) — thief_rogue's ability likely just needs `on_hit` effects using it,
gated by whatever turn-alternating condition Cunning Strike actually uses (check
`dnd5e_combat/characters/thief_rogue/__init__.py` for the exact old-engine logic before
guessing at the TOML). Should be a comparatively small, well-contained fix once
someone sits down with it — worth doing early since it taints `poisoned_*` parity
checks on nearly every sim in the workspace.

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
