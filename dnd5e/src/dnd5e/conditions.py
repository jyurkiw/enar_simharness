"""RAW condition names and the small set of mechanical hooks the engine itself
implements. Phase 3 scope only (design doc 06): custom conditions
(`[conditions.<name>]`, `grants` lists, clocks) are Phase 5 — see design doc
03 section 3 for the target design this is a subset of.

Fidelity target is the OLD engine's actual behavior (parity), not RAW purism:
`dnd5e_combat/conditions.py` only ever wired real (dis)advantage mechanics for
`blinded` — stunned, poisoned, prone etc. are markers with no roll effect
there either (stunned's only real effect is the turn-skip, implemented in
system.py, not here). This module reproduces exactly that scope rather than
"improving" on the old engine's RAW coverage, so migrated sims stay
comparable to their baselines.
"""

from __future__ import annotations

# The closed set of RAW condition names (design doc 03 section 3) an
# `attach_condition` effect may reference, plus the engine-computed states
# that are never attached directly (down/bloodied/dead are derived from HP —
# see creature.py).
BLINDED = "blinded"
CHARMED = "charmed"
DEAFENED = "deafened"
FRIGHTENED = "frightened"
GRAPPLED = "grappled"
INCAPACITATED = "incapacitated"
INVISIBLE = "invisible"
PARALYZED = "paralyzed"
PETRIFIED = "petrified"
POISONED = "poisoned"
PRONE = "prone"
RESTRAINED = "restrained"
STUNNED = "stunned"
UNCONSCIOUS = "unconscious"

RAW_CONDITIONS = frozenset({
    BLINDED, CHARMED, DEAFENED, FRIGHTENED, GRAPPLED, INCAPACITATED, INVISIBLE,
    PARALYZED, PETRIFIED, POISONED, PRONE, RESTRAINED, STUNNED, UNCONSCIOUS,
})

# Engine-computed per-creature states, never attached via `attach_condition`
# (see creature.py's hp_remaining-derived properties).
DOWN = "down"
BLOODIED = "bloodied"
DEAD = "dead"

ENGINE_STATES = frozenset({DOWN, BLOODIED, DEAD})

# Every name `attach_condition` may legally reference in Phase 3 (custom
# conditions from `[conditions.*]` join this set in Phase 5).
ATTACHABLE_CONDITIONS = RAW_CONDITIONS

# Conditions that hand any attacker advantage against the affected creature,
# checked on the *defender* by actions.attack.
GRANTS_ATTACKERS_ADVANTAGE = frozenset({BLINDED})

# Conditions that impose disadvantage on the affected creature's own attacks,
# checked on the *attacker* by actions.attack.
IMPOSES_ATTACK_DISADVANTAGE = frozenset({BLINDED})

# Conditions whose only mechanical effect (in this engine, matching the old
# one) is skipping the bearer's turn entirely — checked by system.py's
# incapacity gate.
SKIPS_TURN = frozenset({STUNNED, PARALYZED, UNCONSCIOUS, PETRIFIED})
