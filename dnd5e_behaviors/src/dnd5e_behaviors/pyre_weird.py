"""Escape hatch for the Pyre Weird, referenced from
`dnd5e_data/monsters/pyre_weird.toml`.

Structurally the mirror of `shadow_otyugh.ShadowOtyughBrain`: that one flees the
nearest LIGHT dragging captives, this one seeks the nearest FIRE dragging
captives. Everything else about the weird stayed declarative (the grapple/drain/
Consume chain is a three-option `[multiattack]` — see the TOML).

Two things need code, both about the hazard field:

* **Guttering.** "At the end of each of its turns, if the weird is not in a fire
  at least its own size and has not drained a Hit Die that turn, it makes a DC 13
  Con save or dies. It moves toward the nearest suitable fire by the shortest
  route, dragging any grappled creature with it." A fire is a `hazards.Hazard`,
  not a creature, so no declarative selector can name one — `plan_movement` picks
  the destination and `end_of_turn` rolls the save.
* **Dragging a captive into the fire.** Movement already drags grapple captives
  (`movement._settle_captives`), so seeking a fire cell *with* a captive is the
  whole "drag them into the flames" behavior for free.

The weird only leaves its fire when it has a reason (a reachable victim); with a
captive in hand it heads straight back to the nearest fire, which both satisfies
Guttering and parks the captive in a burning cell.
"""

from __future__ import annotations

from dnd_board import pathing

# How far the weird will stray from fire to reach a victim. Beyond this it stays
# home rather than committing suicide by Guttering.
LUNGE_FT = 30


class PyreWeirdBrain:
    def choose_multiattack(self, me, view):
        return None      # fully declarative — see pyre_weird.toml

    def choose_target(self, me, ability, pool, view):
        return None

    def plan_movement(self, me, view):
        """Holding a captive → head for the nearest fire (drags them in, and
        satisfies Guttering). Otherwise, if already standing in fire, only step
        out for a victim within `LUNGE_FT`; if standing outside fire, get back
        into one."""
        if me.coord is None:
            return None
        bf = view.battlefield
        round_index = view.round_index
        in_fire = bool(bf.hazards.covering(me.coord, round_index))

        if view.enemies_grappled_by_self():
            return self._nearest_fire_cell(me, bf, round_index)

        if not in_fire:
            return self._nearest_fire_cell(me, bf, round_index)

        # In fire and unencumbered: lunge only at something close.
        victims = [e for e in view.enemies() if e.coord is not None]
        if victims:
            nearest = min(victims, key=lambda e: view.distance(me, e))
            if view.distance(me, nearest) <= LUNGE_FT:
                return None          # let the `engage` tactic close normally
        return me.coord              # stay home in the flames

    def _nearest_fire_cell(self, me, bf, round_index):
        """The closest cell covered by an active hazard — reachable if possible,
        else the nearest one overall (so it keeps walking toward it across
        several turns)."""
        cells = set()
        for hazard in bf.hazards.active(round_index):
            cells |= set(hazard.cells)
        if not cells:
            return None
        if me.coord in cells:
            return me.coord
        occupied = bf.occupied_cells(exclude=(me.instance_name,))
        free = [c for c in cells if c not in occupied]
        if not free:
            return None
        reachable = pathing.reachable(bf.board, me.coord, me.speed_ft, blocked=occupied)
        in_range = [c for c in free if c in reachable]
        pool = in_range or free
        return min(pool, key=lambda c: bf.board.distance_ft(me.coord, c))
