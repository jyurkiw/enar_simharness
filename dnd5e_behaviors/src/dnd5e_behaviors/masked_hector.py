"""Escape hatch for the Masked Hector (design doc 04 section 5), referenced
from `dnd5e_data/monsters/masked_hector.toml` as
`[behavior.custom] handler = "python:dnd5e_behaviors.masked_hector.MaskedHectorBrain"`.

Ported from `dnd5e_combat/monsters/masked_hector/__init__.py`'s
`_choose_target`: a Marked enemy it can reach this round (speed + reach)
always wins — the mark's +3d6 network payoff — otherwise it's *sticky*: it
keeps hammering last round's target rather than skipping around, switching
only when a fresh reachable Mark appears. A grappler-of-record is fought
first (adjacent, free). Everything else (the riders, Multiattack, movement)
is declarative — see the TOML's own comments. Only `choose_target` does
anything; `choose_multiattack`/`plan_movement` always fall through.
"""

from __future__ import annotations


class MaskedHectorBrain:
    def choose_multiattack(self, me, view):
        return None

    def choose_target(self, me, ability, pool, view):
        battlefield = view.battlefield
        grappler_name = battlefield.grappled_by(me.instance_name)
        if grappler_name:
            held_by = battlefield.creatures.get(grappler_name)
            if held_by is not None and not held_by.is_down:
                return self._remember(me, held_by)

        if not pool:
            return None

        reach_ft = me.speed_ft + me.reach_ft
        marked = [e for e in pool if view.has_condition(e, "marked") and view.distance(me, e) <= reach_ft]
        if marked:
            return self._remember(me, min(marked, key=lambda e: view.distance(me, e)))

        last_name = me.trial_scratch.get("target")
        last = battlefield.creatures.get(last_name) if last_name else None
        if last is not None and not last.is_down and view.can_see(me, last):
            return last

        return self._remember(me, min(pool, key=lambda e: view.distance(me, e)))

    def plan_movement(self, me, view):
        return None

    def _remember(self, me, target):
        me.trial_scratch["target"] = target.instance_name
        return target
