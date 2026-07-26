# Opera House — finishing the encounter sim (fire + two elementals)

**Status:** planning complete, implementation not started. This is a living
checklist (cathedral-PLAN style). To resume: read the locked decisions, then the
build phases, and pick up the first unchecked box.

Source material:
- Fire mechanics / phase structure: `Chapter 3 - Parties, Streets, and Secrets.docx`,
  section "Burning Down the House" (paras ~337-377).
- Statblocks: `design/monsters/opera_house_elementals.md` (Pyre Elemental + Pyre Weird,
  marked `[AI]` draft — several DCs still open there).
- Phase-1 guard fight: already built — `simulation.toml`, `FINDINGS.md`.

---

## The picture: this is TWO sims, and the elemental is the fire itself

The Pyre Elemental is not a monster — it's the **burning building wearing an
initiative slot**. Treating it as a hazard *driver* (no HP/AC, places fire and
summons weirds) rather than a `Creature` is what keeps it from breaking the
engine. The encounter splits into two independent sims with hand-authored
starting states, so we never model the continuous phase-1→phase-2 handoff:

- **Sim A — Phase 1 + fire.** The existing guard fight plus the fire that ignites
  round 2. Fire is **lethal** (the `subduing_side` mechanic only covers guard
  clubs — the prose is explicit: subdue "will not protect PCs from falling debris
  or spreading fires"). Q: does the fire kill conscious PCs, or just add chaos and
  chew on the guards while the party still ends up subdued?
- **Sim B — Phase 2, "the guards beat you down" branch (PRIORITY).** The party
  wakes at 1 HP, manacled, on the floor, everywhere lightly obscured, and must
  free itself and escape SOUTH past 2-3 Pyre Weirds while the building burns.
  Q: **can they get out, or die in the fire?** This is where deaths finally
  happen, by design.

---

## LOCKED DECISIONS (Jeff, this session)

1. **Build order:** Sim B (phase-2 escape) first and fully; Sim A (fire on the
   phase-1 guard fight) as a lighter follow-on.
2. **Keep Consume in.** Model the Hit-Dice drain timer + the Consume finisher and
   MEASURE how deadly it is before deciding whether to cut. (It can always be cut
   later if too strong.) See the phase-2 HD interaction note below — it makes
   Consume genuinely reachable in Sim B, which is the point.
3. **Manacle exit = an ally frees you, or you brought your own key.** The item's
   own DC 20+ self-escape stays a near-impossible trap; the intended outs are a
   free ally spending an action to unlock a bound one, or a "brought a manacle
   key" party flag. (Fiction: Martinique warns the PCs to bring a key in case of
   more guards; ignoring her is at their own risk.) So Sim B models
   ally-frees-ally and an optional `brought_key` flag — NOT reliable self-escape.

Still open (do not block Phase 0 on these — see Open Questions): the elemental/
weird save DCs, weird size, and whether the HD drain scales.

---

## The phase-2 Hit-Dice interaction (why Consume matters in Sim B)

Hit Dice = character level (6 for the L6 party). The weird drains 1 HD/round
while grappling; Consume unlocks at 0 HD remaining. On waking (para 374) a PC
"may spend up to half their hit dice to heal." So:

- A PC who heals (spends 3 of 6 HD) wakes healthier but is **~3 rounds from
  Consume** if grappled.
- A PC who hoards HD stays at 1 HP (dies fast to fire ticks + Constrict →
  Pyre's Due) but is ~6 rounds from Consume.

That heal-vs-hoard tension is a real thing to simulate, and it's exactly why we
keep Consume in rather than cutting it blind. Model the wake-up heal as a setup
choice (spend `floor(level/2)` HD) and let remaining HD drive the drain timer.

---

## Build phases (checklist)

- [x] **P0 — Fire hazard field (the big rock, shared by both sims).** DONE.
      `dnd5e/hazards.py` (`Hazard` + `HazardField`); `battlefield.hazards`;
      `CombatContext.environmental_damage` (lethal, no side, bypasses
      `subduing_side`); `system._tick_hazards` at each turn start + prune each
      round; `create_hazard` effect (drops a sphere). Ledger tolerates the
      synthetic "fire" source. 5 tests in `test_hazards.py`. (Damage typing /
      fire immunity is P1; for now every non-downed creature in a fire burns.)
      A `HazardField` on `Battlefield`, sibling to `ObscurementField`: a set of
      fire regions, each with damage dice, damage type, and a lifetime (e.g.
      "until the start of the placer's next turn" or "permanent/spreading"). A
      start-of-turn system hook (mirrors `_sync_obscurement`) deals fire damage to
      any creature standing in a region — the "tick." This damage is **lethal by
      construction**: environmental, no attacker side, so `subduing_side` never
      applies. New effect primitive `create_hazard` (place a sphere) reusing
      `aoe.py`'s sphere geometry (already built for the cathedral). Load-time
      validation + a unit test (tick damages a stander; the placer's own side can
      be made immune via P1).
- [x] **P1 — Damage typing + condition immunity.** DONE.
      `Stats.resistances/vulnerabilities/immunities/condition_immunities`
      (`[stats]` keys); `CombatContext._apply_damage_type` in `deal` +
      `environmental_damage` (immune 0 / vuln ×2 / resist ½); `apply_condition`
      no-ops an immune condition; `_tick_hazards` skips fire-immune before
      rolling. 7 tests in `test_damage_types.py`. (Fire-resistance grapple
      LADDER on Constrict deferred to P2 — PCs aren't fire-immune anyway.)
      Add `resistances` / `vulnerabilities` / `immunities` (damage-type lists) and
      `condition_immunities` to `Stats`/`Statblock`. `CombatContext.deal` scales
      by type (½ / ×2 / 0); `apply_condition` no-ops an immune condition. Clean,
      general, overdue. Needed so weirds are fire-immune (stand in their own
      fire), cold-vulnerable, and un-grappleable, and so the fire field ignores
      the elementals. Tests for each of scale-down / scale-up / zero / immune-
      condition-noop.
- [x] **P2 — Pyre Weird statblock + its bespoke bits.** DONE.
      `monsters/pyre_weird.toml` + `dnd5e_behaviors/pyre_weird.py`. New engine
      pieces, all general: `Creature.hit_dice_remaining` (= level, seeded by
      `_prime`) + `[simulation] hit_dice_spent` (the wake-up heal);
      `drain_hit_die` and `instant_death` effects; `hit_dice(who)` expression
      function; `kills_captive_at_zero` statblock flag (Pyre's Due — checked in
      `_sync_hp_conditions` against the victim's *grappler*, so it fires no
      matter what dealt the blow and OVERRIDES a `subduing_side` knockout);
      `[sustain]` block + `system._tick_sustain` (Guttering — end turn outside
      your hazard, without having fed, and save or die). 12 tests in
      `test_pyre_weird.py`. Deferred as planned: Water Susceptibility, phase-2
      fly speed, the rescuer-takes-fire extraction clause.

      **FIRST MEASUREMENT (throwaway probe, 1 weird vs 1 lone L6 PC, fire on the
      board, 400 trials): PC dies 97.5% of the time in ~5 rounds — and it is
      PYRE'S DUE doing the killing, not Consume.** Constrict (2d6+3) + drain
      (2d6) + the fire tick (2d6) is ~24 damage/round against 45 HP, so a
      grappled PC hits 0 in 2-3 rounds — long before the Hit-Dice timer empties.
      `hit_dice_spent=0` vs `=3` changed nothing (97.5% both), which is the tell.
      **Caveat: 1v1 with no allies is the worst case** — the real phase 2 has 5
      PCs who can pull each other free (which also starves the weird via
      Guttering). Whether Consume is worth keeping is a P4 question, answered
      with the real party; the mechanism is built and unit-pinned either way.
      AC 13, HP 65, fire-immune/cold-vuln, immune to grappled/prone/etc. (P1).
      - Constrict: +5, reach 10, 2d6+3 fire, grapple (escape DC 13) + pull 10 ft
        + Restrained; one grapple at a time (`is_source_of('weird_grapple')`
        gate, same pattern as the Vise's one-prisoner rule).
      - Per-turn drain: at the weird's turn start, a grappled captive loses 1 HD
        and takes 2d6 fire. Needs a **Hit-Dice pool** on creatures (= level) and
        a `drain_hit_die` effect.
      - **Consume:** Con save DC 13 vs a captive with 0 HD → drop to 0 HP.
      - **Pyre's Due:** an `instant_death` effect (dies, no saves, no corpse),
        fired when a creature grappled by the weird hits 0 HP. Wire via the
        on-0-HP path (a grappler flagged `kills_captive_at_zero`).
      - **Guttering + drag-to-fire:** an escape hatch, structurally identical to
        `dnd5e_behaviors/shadow_otyugh.py` (flee-to-darkness) but inverted —
        flee TO the nearest fire, dragging the captive; if end-of-turn not in
        fire and didn't drain, DC 13 Con or die.
      - Defer: Water Susceptibility (no water source in-sim), phase-2 fly speed.
- [x] **P3 — Pyre Elemental hazard driver (environment actor, NOT a Creature).** DONE.
      New engine concept, general: **`[[hazard_actors]]`** — a bodiless force
      with an initiative slot (`loader.HazardActorSpec`, `system.HazardView`,
      `_take_hazard_turn`, `_offer_legendary` after every creature turn,
      `spawn_creature` shared with reinforcements, `GameState.hazard_scratch`
      for per-trial driver state). It is never a `Creature`, so it can't be
      targeted, killed, or keep a side alive — exactly what "no HP, no AC,
      unaffectable without Wish" requires. Driver in
      `dnd5e_behaviors/pyre_elemental.py`: Multiattack (2x Falling Debris, one
      upgradable to Large on a 5-6 recharge), the DC 16 Dex spheres that LEAVE
      fire, 3 legendary actions/round (Enflame Pyre / Drop Debris / Summon Weird,
      max 2 active), the d12 target table abstracted to a side-weighted cluster
      aim, and it ignores the unconscious. 7 tests in `test_pyre_elemental.py`.

      **MEASUREMENT 1 — at full aggression it is a party-wipe machine.** 5 L6 PCs
      on the opera board, elemental only, no guards, 200 trials: **all 5 PCs down
      by round 3, 100% of party HP spent.** Damage breakdown per trial: debris
      178, fire ticks 49, enflame 34. Spreading the party 20 ft apart roughly
      halves it (5.00 -> 2.71 PCs down), so clustering is the dominant variable.
      This is FAITHFUL to the written statblock (2x 4d6 DC 16 spheres + 4d6
      Enflame + persistent fire is simply enormous) — the statblock is that
      strong, the model isn't wrong.

      **MEASUREMENT 2 -> a required scoping rule for P4.** Because of the above,
      Sim B CANNOT run the elemental in attack mode or the escape is an
      execution, not a fight. The prose already says so: once the nobles flee,
      "the Pyre Elemental will stop attacking anyone in the front of the house
      like the PCs... It will, however, spawn three Pyre Weirds in the main room
      between the PCs and the last remaining exit." Implemented as
      **`mode = "smolder"`** on the hazard actor: it stops dropping debris and
      spends legendary actions only on summoning weirds, while keeping the
      existing fires alight. **P4 must use `mode = "smolder"`; Sim A (P5) uses
      the default attack mode**, where most of that output lands on guards.
      A system-level driver with an initiative slot. Each round: pick target(s)
      (start with a "largest cluster / random PC" heuristic; the d12 table is a
      later refinement), drop Falling Debris (a Dex-save DC 16 sphere, 4d6, that
      leaves a `create_hazard` fire), and spend up to 3 legendary actions after
      other creatures' turns on Enflame Pyre / Drop Debris / Summon Pyre Weird
      (max 2 active). Ignores unconscious PCs (prose). Untargetable/unkillable by
      construction (it's not on either side's roster as a `Creature`). This is the
      "breaks things" piece — keep it OUT of the `Creature` model.
- [x] **P4 — Sim B: the phase-2 escape (the priority deliverable).** DONE —
      `sims/opera_house_escape/` (`simulation.toml`, `escape_report.py`,
      **`FINDINGS.md`** ← the answers). New engine pieces, all general:
      `[wake_up]` (start a side beaten: HP floor, spend-HD-to-heal, N of them
      bound) + the bonds-escape action (`system._try_break_bonds`: auto with a
      key, else DC 20, and a free member can unlock an adjacent ally);
      `[objective] direction = "south"` and **`require_all`** (arrivals leave the
      board and the trial runs until every survivor is out — without it the trial
      ends on the FIRST escapee and "all escaped" reads 0% by construction, which
      it did until fixed); `[[initial_hazards]]` (the house is already alight);
      `[[combatants]] name` (explicit instance names — two Weirds from one
      creature file at different cells collided on the bare name).

      **THE ANSWERS (200 trials/variant):**
      * **Not a TPK generator** — whole party dies 0-2%. It's a "some of you
        don't make it" generator: typically ~1 escapes and ~2 die.
      * **Fire IS the encounter**: 104 dmg/trial vs 33 from both Weirds combined.
      * **CONSUME NEVER FIRES — 0.00 dmg/trial, 13.4 of 15 HD left.** The
        measurement Jeff asked for. PCs die to fire/Constrict long before the
        drain empties. Recommendation: move its gate from "0 HD" to "<=2 HD"
        (reachable at the post-heal 3 HD) rather than cut — the flavor is good,
        only the arithmetic is wrong.
      * **The manacle key is worth ~17pp** (53% -> 70% any-escape): Martinique's
        advice is real. Waking with 2 PCs *free* is WORSE than all-bound-with-key
        — they burn turns unlocking allies.
      * **CAVEAT, and it's the big one:** fire placement is AUTHORED (the prose
        doesn't say where the house burns) and dominates everything — halving it
        (4 aisle fires -> 2) takes mean escapees 1.06 -> 3.26 and all-escape
        0% -> 20%. Set that dial deliberately before trusting any other number.
      Hand-authored start: 5 L6 PCs at 1 HP, manacled (restrained + speed 0),
      near the stage (north); each has spent `floor(level/2)` HD on the wake-up
      heal (a setup step) with the rest as the drain-timer pool. A reach-zone
      `[objective]` pointed **SOUTH** (inverse of the current north objective —
      generalize `reach_y` to a direction, or add `reach_y_min`). 2-3 Pyre Weirds
      seeded between party and the south door; fire field lit across the room;
      light obscurement on. New mechanic: **free-an-ally** action (a non-manacled
      PC unlocks a bound ally's manacles — auto or trivial check) and an optional
      `brought_key` party flag letting a PC self-free. Self-escape stays the
      near-impossible DC-20 trap. Report: escape rate, deaths (by source: fire vs
      Consume vs Pyre's Due), rounds, and the heal-vs-hoard HD split.
- [x] **P5 — Sim A: phase-1 + fire (follow-on).** DONE — the `[[hazard_actors]]`
      Pyre Elemental ignites round 2 in full attack mode on top of the guard
      fight; `rush_report.py` gained a fire table (PC damage by tag + guard
      collateral). Also fixed a fidelity bug in the driver's d12 mapping: the
      published table is 6/12 guards, 4/12 PCs, 2/12 *stage folk this sim doesn't
      model* — those two slots are now a genuine miss instead of being folded
      onto the party (which had over-targeted the PCs by a sixth).

      **RESULT — the fire rewrites phase 1** (200 trials; full table in
      FINDINGS.md): rounds 10.6 -> **3.5**, clean subdual **85.5% -> 0%**, a PC
      left dying 0% -> **99.5%**, a PC actually dies 0% -> **16.5%**. Elemental
      damage to PCs is **222/trial** vs everything 27 guards manage, and it drops
      **14.6 of 27 guards** too.

      **THE DESIGN TENSION TO DECIDE: fire breaks the clean phase-2 hand-off.**
      The subdue rule exists so a beaten party wakes manacled, not dead — but
      fire doesn't subdue, and once lit it becomes the thing that drops PCs. The
      prose already licenses this ("will not protect PCs from falling debris or
      spreading fires"); the sim prices it. Three legitimate options, none applied
      (publish hard, let the DM ease off): accept it / light the fire on round 3-4
      so the guards finish the capture first / weight its opening rounds toward
      the guard ranks. Levers 2 and 3 are one-line changes.

**ALL PHASES COMPLETE.** Both sims run and report:
`sims/opera_house` (phase 1 + fire) and `sims/opera_house_escape` (phase 2).
Remaining known gaps are the deferred ones listed above (stage subplot, cover
slingers, conditional trickle, weird fly speed) plus the Consume gate
recommendation from P4.
      Bolt the P3 driver + P0 field onto the existing guard sim, igniting round 2.
      Report: do conscious PCs die to fire; does fire shift the subdue rate;
      collateral on the guards.

---

## What to reuse / abstract / defer

- **Reuse:** `aoe.py` sphere geometry (cathedral), `ObscurementField`/`Region` +
  `refresh_auras` (fire field is modeled on it), reinforcement spawning (weirds),
  `subduing_side`, the reach-zone `[objective]`, `neutralizes`, grapple + the
  `is_source_of` one-captive gate, the shadow_otyugh flee-to-hazard escape hatch.
- **Abstract:** d12 target table → cluster heuristic; Mélisse / Nico / the stage
  subplot → out of scope for PC-survival (as in phase 1); light obscurement →
  the existing obscurement system's lightest setting (mostly flavor here).
- **Defer:** weird fly speed + smoke-lets-weirds-live nuance, Water
  Susceptibility, the rescuer-takes-fire clause on manacle/weird extraction,
  the Pyre Elemental burning the *rest of the city* (post-escape epilogue).

---

## Open questions (from the elemental doc, that matter for the sim)

- **[Q] Weird Guttering / Consume save DC.** Draft is DC 13. The doc floats
  14/18/22 for the extinguish save. Sim will report Consume/Guttering kill rates;
  pick the DC from what survival % you want once we see numbers.
- **[Q] Weird size / HD die.** Statted Large (d10, the 65-HP basis). Confirm — it
  affects the minimum fire footprint and what Constrict can grab.
- **[Q] HD drain rate.** 1/round as written. If Consume proves too weak at L6
  even post-heal, the lever is draining >1/round (or the fixed-gate fallback).
  We're keeping it in to measure first (locked decision 2).
- **[Q] Elemental Falling Debris DC / dice.** Draft DC 16, 4d6 / Large 8d6. These
  drive how lethal the fire is in Sim A; tune from the Sim A report.

---

## Milestones

1. **P0+P1 land** → a sim can have lethal fire on the board and typed damage. First
   provable win: a test creature takes fire ticks, a fire-immune one doesn't.
2. **P2 lands** → a Pyre Weird can grapple, drag into fire, and instakill via
   Pyre's Due; Consume fires against a 0-HD captive. Unit-tested.
3. **P4 lands (Sim B)** → the real number: phase-2 escape rate and cause-of-death
   split for the beaten-down party. THIS is the deliverable Jeff is waiting on.
4. **P5 lands (Sim A)** → whether fire changes the phase-1 subdue picture.
