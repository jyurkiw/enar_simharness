"""Escape hatch for the 5th-level Evoker's Lightning Bolt — referenced from
`dnd5e_data/characters/evoker_wizard.toml` as
`[behavior.custom] handler = "python:dnd5e_behaviors.evoker_wizard.EvokerBrain"`.

This is the "complicated AI block" the declarative `when` language can't express
cleanly: a *stochastic, per-round* decision about whether to spend a limited
spell slot, gated on a geometric friendly-fire check.

Calibration philosophy: model a competent-but-imperfect player, ~70-90% of
optimal. The point of this project is honest difficulty — a DM should get an
encounter that's hard because it *is* hard, not because the sim plays the PCs
dumb (which would force the DM to play monsters adversarially just to restore the
intended challenge). So the wizard is NOT reluctant: it casts Lightning Bolt
whenever it's clearly the right call — a clean multi-target line, OR a strong
lone target (an 8d6 nuke beats a cantrip) — just not with perfect reliability.

The turn logic (`choose_multiattack`):

  1. Out of slots -> cantrip (`standard`). The slot count is the usage ceiling.
  2. Find the best LINE that catches the most enemies and ZERO allies
     (`aoe.best_line`, allow_allies=False — no Sculpt Spells at level 5, so a PC
     in the line eats the bolt). Two bars:
       * a clean line on 2+ enemies -> the payoff shot;
       * a clean line on exactly 1 -> a solo nuke.
  3. Each carries a per-round CHANCE to actually fire (below), in the ~70-90%
     "competent play" band and rising to certainty by round 3 (so a slot is
     never wasted by being hoarded to the end). Set a round's chance to 1.0 to
     force "cast this round no matter what". The small early shortfall models a
     player who occasionally holds one beat for a better cluster — not a wizard
     that sandbags.

Why stochastic: it models a caster who plays well but not perfectly, and it's
why winning initiative matters — a wizard acting *before* the melee charges in
sees the pack clustered with no PCs in the line, so its best clean shot is
much bigger.

Sculpt Spells (a 6th-level Evoker feature) would let chosen allies auto-avoid the
damage — at which point ally-hitting lines become fine. That's a one-line change
here: set `SCULPT_SPELLS = True` to pass `allow_allies=True` to the aim search.
Left off because these PCs are 5th level.
"""

from __future__ import annotations

from dnd5e import aoe

# Per-round probability of firing, in the ~70-90% "competent player" band and
# rising to certainty by round 3 (rounds past the last key default to 1.0).
# Firing a clean 2+ line is almost always right, so the multi bar is near the top
# of the band; nuking a lone strong target is usually right but a player might
# hold one beat for adds, so the solo bar sits a touch lower. Tune here.
CAST_CHANCE_MULTI = {1: 0.90, 2: 0.95}
CAST_CHANCE_SOLO = {1: 0.70, 2: 0.85}

SLOT = "leveled_slots"
SPELL = "lightning_bolt"
SCULPT_SPELLS = False  # 6th-level Evoker feature; see module docstring.


class EvokerBrain:
    def choose_multiattack(self, me, view):
        ability = me.statblock.abilities.get(SPELL)
        if ability is None or ability.area is None:
            return None  # not this wizard / not configured — declarative fallback
        if me.resources.get(SLOT, 0) <= 0:
            return "standard"  # ceiling reached: out of slots -> cantrip

        bf = view.battlefield
        length = bf.board.feet_to_cells(ability.area["length_ft"])
        rnd = view.round_index

        # A clean line on 2+ foes is the shot we built the feature for.
        if aoe.best_line(bf, me, length, allow_allies=SCULPT_SPELLS, min_enemies=2) is not None \
                and self._willing(view, CAST_CHANCE_MULTI, rnd):
            return "blast"
        # Otherwise consider spending it on a lone target (still no friendly fire).
        if aoe.best_line(bf, me, length, allow_allies=SCULPT_SPELLS, min_enemies=1) is not None \
                and self._willing(view, CAST_CHANCE_SOLO, rnd):
            return "blast"
        return "standard"

    def choose_target(self, me, ability, pool, view):
        return None  # line targeting (aoe.best_line) is handled by select_targets

    def plan_movement(self, me, view):
        return None  # kite tactic as usual; maneuvering-to-line-up is a future step

    @staticmethod
    def _willing(view, curve: dict, rnd: int) -> bool:
        p = curve.get(rnd, 1.0)
        if p >= 1.0:
            return True
        if p <= 0.0:
            return False
        # Trial-seeded stream (never Python's random), so runs stay deterministic.
        return view.resolver.roll("1d100") <= round(p * 100)
