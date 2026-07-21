"""Cathedral extraction party AI (escape hatch).

The intended competent line is "one bruiser breaks the sealed confessio while the
rest hold the horde off, then everyone runs with the box". The break-in half is a
targeting override: SealBreaker steers whichever PC it's attached to onto the
`objective`-tagged seal — so it charges up the aisle to the confessio and pounds
on it (AC 14 / 20 HP) instead of trading blows with cultists. Applied via a
sim-level `[overrides.<breaker>.behavior.custom]` so the shared L6 archetype
files stay clean.

The "grab the box and run / retreat" half is modeled at the sim/report level
rather than as a carry+escape state machine: once the seal is broken and the
party is still standing, the box is taken and (per the encounter's own rule) they
get away as long as nobody is down. So the success metric is simply "seal broken
by round 10 AND no PC down" — see sims/cathedral/simulation.toml.
"""

from __future__ import annotations


class SealBreaker:
    """Force this PC to attack the objective (the confessio seal) whenever it's a
    valid target, moving toward it via the normal engage tactic. Falls through to
    declarative targeting for everything else (e.g. before the seal is in sight)."""

    def choose_multiattack(self, me, view):
        return None

    def choose_target(self, me, ability, pool, view):
        for c in pool:
            if c.has_tag("objective"):
                return c
        return None

    def plan_movement(self, me, view):
        return None
