"""Escape hatch for the Shadow Otyugh (design doc 04 section 5), referenced
from `dnd5e_data/monsters/shadow_otyugh.toml` as
`[behavior.custom] handler = "python:dnd5e_behaviors.shadow_otyugh.ShadowOtyughBrain"`.

Ported from `dnd5e_combat/monsters/shadow_otyugh/__init__.py`'s `take_turn`.
Most of that policy turned out to be expressible declaratively once broken
down (see shadow_otyugh.toml's own comments for exactly which `when`/
`target_filter` clause replaces which branch): the bloodied retreat is a
`when = "is_bloodied(self)"` multiattack option; "always bite-and-grab once
grappling anything" is `when = "is_grappling(self)"`; "hunt the party's light
source" is `target_filter = "has_condition(target, 'light_source')"` gated by
`when = "any(enemies, has_condition(it, 'light_source') and not
is_grappled(it))"`. Only the drag-into-darkness movement — flee from the
nearest light source, dragging captives along, something no named
`movement.py` tactic captures and the expression language has no "farthest
reachable cell from X" primitive for — needs real code. That's this class's
entire job: `choose_multiattack`/`choose_target` always return `None` (pure
declarative fallback); only `plan_movement` does anything.
"""

from __future__ import annotations

from dnd_board import pathing


class ShadowOtyughBrain:
    def choose_multiattack(self, me, view):
        return None

    def choose_target(self, me, ability, pool, view):
        return None

    def plan_movement(self, me, view):
        if not view.enemies_grappled_by_self():
            return None
        light = self._nearest_light_source(me, view)
        if light is None or light.coord is None or me.coord is None:
            return None
        bf = view.battlefield
        occ = bf.occupied_cells(exclude=(me.instance_name,))
        candidates = pathing.reachable(bf.board, me.coord, me.speed_ft, blocked=occ)
        candidates.add(me.coord)
        # Farthest reachable cell from the light — port of
        # dnd5e_combat.battlefield.Battlefield.flee_from.
        return max(candidates, key=lambda c: bf.board.distance_ft(c, light.coord))

    def _nearest_light_source(self, me, view):
        lights = [e for e in view.enemies()
                 if not e.is_down and e.coord is not None and view.has_condition(e, "light_source")]
        if not lights:
            return None
        return min(lights, key=lambda e: view.distance(me, e))
