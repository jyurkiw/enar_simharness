from dnd5e import conditions


def test_raw_conditions_is_the_closed_doc03_set():
    assert conditions.RAW_CONDITIONS == {
        "blinded", "charmed", "deafened", "frightened", "grappled",
        "incapacitated", "invisible", "paralyzed", "petrified", "poisoned",
        "prone", "restrained", "stunned", "unconscious",
    }


def test_engine_states_are_not_attachable():
    assert conditions.ENGINE_STATES.isdisjoint(conditions.ATTACHABLE_CONDITIONS)
    assert conditions.DOWN in conditions.ENGINE_STATES
    assert conditions.DOWN not in conditions.ATTACHABLE_CONDITIONS


def test_only_blinded_grants_attacker_advantage_matching_old_engine():
    # Fidelity to dnd5e_combat/conditions.py's actual behavior, not RAW
    # purism — the old engine never wired stunned/poisoned/prone into this set.
    assert conditions.GRANTS_ATTACKERS_ADVANTAGE == {conditions.BLINDED}


def test_only_blinded_imposes_attack_disadvantage_matching_old_engine():
    assert conditions.IMPOSES_ATTACK_DISADVANTAGE == {conditions.BLINDED}


def test_stunned_skips_turn():
    assert conditions.STUNNED in conditions.SKIPS_TURN


def test_grappled_does_not_skip_turn_or_grant_advantage():
    assert conditions.GRAPPLED not in conditions.SKIPS_TURN
    assert conditions.GRAPPLED not in conditions.GRANTS_ATTACKERS_ADVANTAGE
