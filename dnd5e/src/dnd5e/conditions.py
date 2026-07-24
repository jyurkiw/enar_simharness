"""RAW condition names and the small set of mechanical hooks the engine itself
implements, plus (Phase 5) the custom-condition machinery: `[conditions.<name>]`
definitions (`statblock.ConditionDef`) carry their mechanics as a `grants` list
of grant-context effects, folded generically here — the engine never tests a
custom condition's *name*, only what it grants. See design doc 03 section 3.

Fidelity target is the OLD engine's actual behavior (parity), not RAW purism:
`dnd5e_combat/conditions.py` only ever wired real (dis)advantage mechanics for
`blinded` (the boolean advantage/disadvantage flag) — stunned, poisoned,
prone etc. are markers with no roll effect there either (stunned's only real
effect is the turn-skip, implemented in system.py, not here). Bane/Bless use a
*separate* mechanism, bonus/penalty d20 dice (`d20_dice` below, lifted from
`dnd5e_combat/conditions.py`'s own `d20_dice`) — wired into `actions.py`'s
`attack`/`saving_throw` as of Phase 4, once life_cleric became the first
creature to actually cast them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .creature import ConditionInstance, Creature
    from .statblock import ConditionDef

# The closed set of RAW condition names (design doc 03 section 3) an
# `attach_condition` effect may reference, plus the engine-computed states
# that are never attached directly (down/bloodied/dead are derived from HP —
# see creature.py).
BANE = "bane"
BLESS = "bless"
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
    BANE, BLESS, BLINDED, CHARMED, DEAFENED, FRIGHTENED, GRAPPLED, INCAPACITATED,
    INVISIBLE, PARALYZED, PETRIFIED, POISONED, PRONE, RESTRAINED, STUNNED, UNCONSCIOUS,
})

# d20 modifier contributions, as (bonus_code, penalty_code), applied to the
# affected creature's own attack rolls and saving throws.
_D20_EFFECTS = {
    BLESS: ("1d4", None),
    BANE: (None, "1d4"),
}


def d20_dice(condition_names) -> tuple[list[str], list[str]]:
    """(bonus_dice, penalty_dice) codes for a creature's d20 rolls, given the
    names of conditions currently on it."""
    bonus: list[str] = []
    penalty: list[str] = []
    for name in condition_names:
        effect = _D20_EFFECTS.get(name)
        if not effect:
            continue
        plus, minus = effect
        if plus:
            bonus.append(plus)
        if minus:
            penalty.append(minus)
    return bonus, penalty

# Engine-computed per-creature states, never attached via `attach_condition`
# (see creature.py's hp_remaining-derived properties).
DOWN = "down"
BLOODIED = "bloodied"
DEAD = "dead"

ENGINE_STATES = frozenset({DOWN, BLOODIED, DEAD})

# Marker the `light_plan` mechanic (system.py) attaches to its `source` once
# it fires — read via `has_condition(who, "light_source")` (that expression
# function doesn't validate against ATTACHABLE_CONDITIONS, only `attach_
# condition`-from-TOML does), never attached by a creature ability itself.
LIGHT_SOURCE = "light_source"

# Sentinel `ConditionInstance.source` value system.py's obscurement sync uses
# to tag the Blinded it applies for standing in heavy obscurement, so it only
# ever removes a Blinded it applied itself (never one from another effect).
OBSCUREMENT_SOURCE = "obscurement"

# Every RAW name `attach_condition` may legally reference. A file's own
# `[conditions.*]` names join this set per-file at load time (loader.py's
# `known_conditions` threading) — there's no single global custom-condition
# set, since a condition may be attached to a creature whose own file never
# defines it (the Bruiser's Mark, attached to party members).
ATTACHABLE_CONDITIONS = RAW_CONDITIONS

# ---- Phase 5: reaction triggers (design doc 04 section 4) -----------------------

# The closed trigger catalog. Only `ally_targeted_by_attack`/`turn_start` are
# actually published by this engine so far (the masks network's Deceptive
# Defense and Sleight of Crowd) — the rest are registered (so a creature file
# can reference them without a loader change) but nothing publishes them yet;
# a reaction with one of those triggers simply never fires.
REACTION_TRIGGERS = frozenset({
    "ally_targeted_by_attack", "self_targeted_by_attack",
    "attack_hit", "attack_missed", "taking_damage",
    "enemy_left_reach", "ally_downed", "turn_start", "turn_end", "round_flag_set",
})

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

# ---- Phase 5: custom conditions (design doc 03 section 3) ----------------------

# Grant-context effect names legal inside a `[conditions.*].grants` list or a
# trait's `effects` (design doc 03 section 4's table) — validated by
# loader.py, folded generically by `grants_for` below. `grant_advantage_
# against` is registered (so a future creature can reference it without a
# loader change) but has no fold logic yet — nothing in scope uses it. The
# others ARE wired into `actions.py`'s `attack`: `grant_advantage_to_
# attackers`/`impose_disadvantage_except_source` (masks), and `grant_self_
# advantage` (Bug-A follow-up: the Berserker Barbarian's Reckless Attack —
# advantage on the *bearer's own* attacks, folded on the attacker side).
GRANT_EFFECTS = frozenset({
    "grant_advantage_to_attackers", "grant_advantage_against",
    "impose_disadvantage", "impose_disadvantage_except_source",
    "grant_self_advantage", "grant_ac_bonus", "grant_speed_zero",
})

# Closed clock keywords a `[conditions.*].expires` may reference (design doc
# 03 section 3). "rounds:<n>" is prefix-matched, not a literal member — see
# `is_known_clock`.
CLOCK_KEYWORDS = frozenset({
    "start_of_source_next_turn", "end_of_source_next_turn",
    "end_of_bearer_turn", "end_of_bearer_next_turn", "until_cured",
    # "…or succeeds on a DC N <ability> saving throw at the start of each of
    # its turns" (the Guard Cartel Slinger's bolos). The condition definition
    # must also carry `save_ability` + `save_dc`; system.py rolls it in
    # `_tick_start_of_turn` for whoever's turn is beginning.
    "save_ends_start_of_bearer_turn",
})

# Clocks that need `save_ability`/`save_dc` on the condition definition.
SAVE_ENDS_CLOCKS = frozenset({"save_ends_start_of_bearer_turn"})


def is_known_clock(expires: str) -> bool:
    if expires in CLOCK_KEYWORDS:
        return True
    if expires.startswith("rounds:"):
        return expires[len("rounds:"):].isdigit()
    return False


# Closed predicate names a `[conditions.*].unless` may reference, evaluated at
# expiry time by system.py's clock-tick step. v1's one member matches the old
# engine's Bruiser's Mark: "attacked_other_than_source_this_turn" is true when
# `actions.attack`'s `impose_disadvantage_except_source` fold stamped
# `turn_scratch["attacked_other_than_source"]` this turn (i.e. the bearer
# swung at someone other than the condition's source — keeping the heat on
# keeps the mark, RAW).
UNLESS_PREDICATES = frozenset({"attacked_other_than_source_this_turn"})


def grants_for(creature: "Creature", grant_name: str, *,
               condition_defs: dict) -> list:
    """Every `ConditionInstance` attached to `creature` whose definition
    grants `grant_name` — the caller inspects `.source` etc. as needed (e.g.
    `impose_disadvantage_except_source` cares *which* source to exempt, not
    just whether the grant is present). `condition_defs` is the workspace-
    wide `dict[str, statblock.ConditionDef]` `system.py` builds once from
    every roster member's `[conditions.*]` (a condition's definition lives on
    whichever creature file introduces it, but may be *attached* to a
    creature whose own file never defines it — the Bruiser's Mark, attached
    to party members, is exactly this)."""
    matches = []
    for instance in creature.conditions:
        cdef = condition_defs.get(instance.name)
        if cdef is None:
            continue
        if any(g.effect == grant_name for g in cdef.grants):
            matches.append(instance)
    return matches


def is_neutralized(creature: "Creature", *, condition_defs: dict) -> bool:
    """True if any condition on `creature` is defined `neutralizes = true` — it's
    been taken out of the fight without being killed (the cartel's manacled
    condition). `battlefield.enemies_of` drops such creatures from targeting, so
    the guards leave a bound PC helpless on the floor and move on."""
    for instance in creature.conditions:
        cdef = condition_defs.get(instance.name)
        if cdef is not None and cdef.neutralizes:
            return True
    return False


def speed_is_zero(creature: "Creature", *, condition_defs: dict) -> bool:
    """True when any condition on `creature` grants `grant_speed_zero` — the
    Guard Cartel Slinger's Low Bolo ("the target's Speed becomes 0"). Read by
    `movement.py` rather than by `Creature.speed_ft`, because a Creature has no
    handle on the workspace-wide condition registry and movement always does
    (via the Battlefield)."""
    return bool(grants_for(creature, "grant_speed_zero", condition_defs=condition_defs))


def ac_bonus_for(creature: "Creature", *, condition_defs: dict) -> int:
    """Sum of every `grant_ac_bonus` amount from conditions on `creature` — the
    Shield spell's +5, folded into the target's AC by `actions.attack`."""
    total = 0
    for instance in creature.conditions:
        cdef = condition_defs.get(instance.name)
        if cdef is None:
            continue
        for g in cdef.grants:
            if g.effect == "grant_ac_bonus":
                total += int(g.args.get("amount", 0))
    return total
