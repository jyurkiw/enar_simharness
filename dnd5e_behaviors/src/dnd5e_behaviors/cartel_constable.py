"""Escape hatch for the Southern Gate Guard Cartel Constable, referenced from
`dnd5e_data/monsters/cartel_constable.toml`.

The brief: *"The Constable will generally stand back and issue orders using
their Commander's Strike and Rally actions as long as there are enough Vises and
Hounds to benefit from their orders. When there aren't enough of them to
benefit, or if they are engaged in melee, they will advance with their longsword
and fight directly."*

**Which half of that is declarative:** all of the *action* selection. Whether to
shout, rally, order, or swing is four `[multiattack.*]` options gated on
`count(enemies_within(5))`, `count(allies_tagged(...))` and
`reaction_available(...)` — see the TOML. This class deliberately implements
only `plan_movement`.

**Why movement needs code.** "Stand back" is a *position* — hold a spot away
from the front line but inside the 30 ft leash Commander's Strike and Rally both
require — and no named tactic in `movement.py` expresses it:

* `engage` walks into melee — right for a fighting turn, wrong for a commanding
  one.
* `kite` maximizes distance from *its current target*, and on a commanding turn
  that target is an **ally** (Rally and Commander's Strike both target allies) —
  so kiting would run it AWAY from the squad it's trying to command.
* `hold` never advances, so the Constable could never switch to its longsword.

So the statblock keeps `tactic = "engage"` for fighting turns (this class
returns `None` and falls through) and this hook takes over on commanding turns.

One engine detail this has to respect: `system._take_turn_body` re-plans
movement before *each* action in a multiattack option, so a hook that returns a
fresh "run away" cell three times would move at triple speed. The fall-back is
therefore latched per turn via `turn_scratch`, and afterwards the hook returns
the Constable's own cell (a no-op move) rather than `None` (which would fall
through to the tactic).
"""

from __future__ import annotations

from dnd_board import pathing

# Commander's Strike and Rally both read "an ally within 30 feet". Hold a little
# inside that so a mook stepping forward doesn't drop off the leash.
LEASH_FT = 25
# Below this, the Constable counts as "engaged in melee" and stops commanding.
ENGAGED_FT = 5
# Two or more Vises/Hounds still standing = "enough of them to benefit".
MIN_COMMANDABLE = 2


class ConstableBrain:
    def choose_multiattack(self, me, view):
        return None      # fully declarative — see cartel_constable.toml

    def choose_target(self, me, ability, pool, view):
        return None

    def plan_movement(self, me, view):
        if me.coord is None or not self._commanding(me, view):
            return None                  # fighting directly: plain `engage`
        if me.turn_scratch.get("fell_back"):
            return me.coord          # already repositioned this turn: stand fast
        me.turn_scratch["fell_back"] = True
        return self._fallback_cell(me, view)

    # ---- helpers ------------------------------------------------------------

    def _commanding(self, me, view):
        """The brief's two conditions, both of which end command mode: an enemy
        in melee with the Constable, or too few Vises/Hounds left to order
        around. `view.allies()` excludes the Down, so casualties count
        themselves out."""
        enemies = [e for e in view.enemies() if e.coord is not None]
        if any(view.distance(me, e) <= ENGAGED_FT for e in enemies):
            return False
        mooks = [a for a in view.allies()
                 if a.has_tag("vise") or a.has_tag("hound")]
        return len(mooks) >= MIN_COMMANDABLE

    def _fallback_cell(self, me, view):
        """The best reachable cell: as far from the nearest enemy as possible
        while staying within `LEASH_FT` of a commandable mook. Falls back to
        pure distance if the leash can't be honored (better to be alive and out
        of orders than dead in the front rank)."""
        bf = view.battlefield
        enemies = [e for e in view.enemies() if e.coord is not None]
        if not enemies:
            return me.coord
        occ = bf.occupied_cells(exclude=(me.instance_name,))
        cells = pathing.reachable(bf.board, me.coord, me.speed_ft, blocked=occ)
        cells.add(me.coord)

        mooks = [a for a in view.allies()
                 if a.coord is not None and (a.has_tag("vise") or a.has_tag("hound"))]

        def threat(cell):
            return min(bf.board.distance_ft(cell, e.coord) for e in enemies)

        leashed = [c for c in cells
                   if any(bf.board.distance_ft(c, m.coord) <= LEASH_FT for m in mooks)]
        return max(leashed or cells, key=threat)
