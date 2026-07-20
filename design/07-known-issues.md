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

> **Parity is a migration-validation tool, not ground truth.** The baselines were captured
> from the old *abstract* engine (no board, front/back positioning only). Where the new
> board-based engine models something the old one structurally could not, a divergence is
> **expected and correct** — the new engine is the better model and the baseline is simply
> unable to represent the situation. **Kiting is the standing example** (decided 2026-07):
> a ranged attacker that keeps its distance on a real board is a powerful, legitimate
> tactic; the abstract engine had no way to express it, so its numbers are lower. Do not
> "fix" the engine toward the baseline in these cases, and do not re-open them as bugs —
> see Bug A's multi-otyugh note and Bug C. Genuine bugs are the ones where the new engine
> gets its *own* rules wrong (missing class features, an unreachable ability, a mis-aimed
> heal) — those are what the entries below are for.

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

**Now also fixed — the vanguard and monk parties (2026-07, same follow-up):** the other
two parties overshot for the same reason (their own members missing features), rebuilt the
same way:
- **berserker_barbarian**: Rage (+2 dmg baked in; physical resistance via a `taking_damage`
  + `reduce_damage` reaction) and Reckless Attack (a `reckless` self-condition granting the
  new `grant_self_advantage` fold + `grant_advantage_to_attackers`). dealt −22% → −2%.
- **devotion_paladin**: Divine Smite on crit (`on_crit` `damage_rider` 2d8 → 4d8), matching
  the old crit-only behavior.
- **open_hand_monk**: Flurry of Blows (4-attack multiattack gated on `resource_available('ki')`)
  and Stunning Strike (CON save on the first hit each turn → `stunned` with `expires =
  "start_of_source_next_turn"`, so the otyugh skips a turn). dealt −43% → −22% (rest is
  redistribution).
- **martial_arts_monk**: round-1 Stunning Strike (offense was already on-baseline).

Result: `otyugh_cr5_compare/vanguard` +72% → **+3%**; `otyugh_cr5_monk/monk_1x` +73% → **+12%**,
`monk_2x` +16% → **−7%**. Two more reusable primitives (unit-tested): the `grant_self_advantage`
grant fold (Reckless), and an explicit `expires` clock on `attach_condition` (a RAW condition
attached with a duration — Stunning Strike's timed stun). Great Weapon Master crit-chains, GWF
rerolls, and ki-spend depletion remain cut (small, within tolerance for ≤3-round fights).

**What's genuinely left (NOT a party-feature gap — different root causes):**
- **Multi-otyugh standard sims *under*shoot** (`otyugh_cr5_x2`/`_monk standard_2x`, monster
  damage ~−25%): in the longer 2-otyugh fight the ranger kites safely on the board (takes
  10.4 dmg vs the abstract baseline's 12.5), rarely loses Concentration, keeps Hunter's Mark
  up, and deals ~+31%. **Expected board divergence, decided closed** — same call as Bug C
  and the parity note at the top of this doc: kiting is a valid tactic the abstract baseline
  couldn't represent. Not a bug; do not re-open.
- **Shadow sims** (`otyugh_shadow_solo/pair/board`: −36%/+10%/+62%) — all improved from the
  party rebuild (board was +142% pre-rebuild) but remain out of tolerance because of the
  **shadow otyugh's own darkness/blindness dynamics** (the party fights blinded → disadvantage,
  so the shadow otyugh's survival/damage interacts differently than a plain otyugh's). A
  separate investigation, starting at the obscurement/vision interaction, not the party TOMLs.
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

## Bug C — masks parity — RESOLVED (real bug fixed; the rest is expected board divergence)

**Status (2026-07, after the Bug A/B party rebuild):** most of Bug C turned out to be
downstream of Bug A/B, exactly as suspected. The original symptoms are gone or inverted:
`down_thief_rogue` was ~7x baseline (0.6-0.7 vs 0.09) and is now **0.12**; the monster
side no longer overshoots at all. One genuine masks-era bug was found and fixed, and one
design question remains.

**Genuine bug found and fixed — the Life Cleric's triage heal never fired.**
`life_cleric.toml` defined `cure_wounds` but **no multiattack option ever selected it**,
and it had no `targets`, so had it ever been reached the default "visible enemies" pool
would have aimed the heal at a monster. That was why front-liners went Down ~5x more than
baseline *while taking less total damage* — they dropped early and then stopped being hit.
Restored as a `triage` multiattack option (priority 40, above the Bane/Bless opener) with
`when = "count(downed_allies) > 0"`. This needed a new **`downed_allies` selector**:
`allies` deliberately excludes the Down (`battlefield.allies_of`), so `any(allies,
is_down(it))` is permanently false and a healer literally could not see who to raise —
a trap worth remembering when writing any "help the dying" rule.

**The rest of the masks divergence is expected board behavior — DECIDED, do not "fix".**
In masks (8 rounds, 30x30 arena) the ranger's `kite` tactic stands "as far from the target
as possible while within weapon range", and a 150 ft longbow on a 150 ft board means *the
whole board*. Measured: the ranger takes damage **1.05 times per trial across 8 rounds**
(8.4 damage), is essentially never targeted (the monsters' nearest-first targeting never
reaches it), keeps Hunter's Mark up the entire fight, and deals **+32%** vs baseline —
which makes the monster side undershoot **~-42%**. It also explains the residual rogue
pressure: the Bruiser *wants* a `priority_strike` target (ranger/rogue) but can never catch
the ranger, so the rogue absorbs all of it.

**This is kiting working as intended, not a bug** (see the parity note at the top of this
doc). A ranged attacker holding distance on a real board is a powerful, valid tactic; the
old *abstract* engine had no positioning and structurally could not represent it, so its
baseline is simply lower. `kite` stays as documented in `movement.py`. For the record, a
capped standoff was measured and rejected (2000 trials, adventurers_natural; baseline
monsters 95.59, ranger 128.55) — it moves the numbers toward the baseline but only by
suppressing the tactic, and still doesn't close the gap:

| kite cap | monsters dealt | ranger dealt | ranger taken |
|---|---|---|---|
| none (150 ft — **kept**) | 55.6 (−42%) | 169.5 (+32%) | 7.9 |
| 60 ft (rejected) | 70.4 (−26%) | 147.4 (+15%) | 28.3 |
| 30 ft (rejected) | 76.6 (−20%) | 145.5 (+13%) | 35.5 |

Note the residue even at a 30 ft cap: the ranger's riders (Hunter's Mark every hit +
Colossus Slayer every turn) scale better across an 8-round fight than the old engine's did,
and that old rider logic is unrecoverable — further evidence that chasing the baseline here
would mean distorting a correct model to match a less capable one.

**Bug C is closed.** masks will not match its Phase 0 baseline on the ranger/monster-damage
columns, by design; treat those baselines as historical, not as a target.

**Full design-decision context** (what's declarative vs. hatched, what was cut and
why): `design/06-implementation-guide.md`'s Phase 5 section, and `masked_bruiser.toml`/
`masked_poet.toml`/`masked_hector.toml`'s own header comments.

---

## Gap D — Sleight of Crowd (masks Bruiser bonus action) — CLOSED

**Was:** the Bruiser never repositioned to shield a threatened Poet, because
`swap_positions`'s `with` only resolved `"self"` / `"target"` / `"event.<field>"` —
none of which can name "a Poet ally".

**Closed (2026-07)** by adding a general fourth creature-reference form,
**`"expr:<expression>"`**, to every effect argument that names a creature
(`target`/`to`/`with`). `loader._compile_target_ref` parses and validates it at load
time like every other expression (so a typo fails loudly at load, never mid-trial) and
stores a compiled `Node`; `effects._resolve_ref` evaluates it against the effect's
scope. An `expr:` reference may legitimately resolve to `None` (nothing matched), so
`swap_positions`/`redirect_attack` now no-op in that case rather than crashing.

`masked_bruiser.toml` now carries `[reactions.sleight_of_crowd]` (trigger `turn_start`,
`uses_bonus_action`), gated on the old policy's own test — the nearest Poet is within
30 ft *and* has an enemy within 10 ft — swapping via
`with = "expr:nearest(allies_tagged('poet'))"`. It fires rarely in practice (~0.011/trial):
the Poets kite well and are seldom threatened, which is the same accepted board-kiting
effect as Bug C, not a wiring problem. Pure repositioning, so it barely moves the sim's
numbers — the point is that the vocabulary no longer blocks it.

## Gap E — the Bruiser's "don't move an already-well-placed mark" heuristic — CLOSED
(and the Phase 5 reasoning that cut it was **wrong**)

**Was:** recorded as inexpressible because it "would need two *independently* nested
`any()` calls, and the `it` binding is a single slot, so a second `any()` inside the
first clobbers it."

**That reasoning was incorrect.** `any()`/`all()` evaluate their **set argument in the
enclosing scope, before rebinding `it`** (see `expressions._eval_call` — `creatures =
evaluate(node.args[0], scope)` happens first, then the predicate runs against
`scope.with_it(c)`). So the outer `it` is still bound while the inner set is built, and

    any(allies_tagged('hector'), any(enemies_within_of(it, 35), has_condition(it, 'marked')))

works today with **no engine change** — outer `it` is the hector when
`enemies_within_of(it, 35)` is evaluated, inner `it` is the enemy in the predicate.
Locked in by `test_nested_any_keeps_the_outer_it_while_building_the_inner_set`.

`masked_bruiser.toml`'s rapier mark now carries that guard, and it measurably does its
job: mark applications drop from **1.472 to 1.087 per trial** (−26% churn) versus the
un-guarded condition — i.e. the Bruiser stops moving a mark that is already sitting on a
Hector-reachable striker, exactly as the old policy did.

**Lesson worth keeping:** before recording something as "the expression language can't
express this", check the evaluator — nested set-comprehension-ish queries are more
capable than the single-`it` slot suggests.

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
