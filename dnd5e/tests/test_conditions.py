from dnd5e import conditions


def test_raw_conditions_is_the_closed_doc03_set():
    assert conditions.RAW_CONDITIONS == {
        "bane", "bless", "blinded", "charmed", "deafened", "frightened", "grappled",
        "incapacitated", "invisible", "paralyzed", "petrified", "poisoned",
        "prone", "restrained", "stunned", "unconscious",
    }


def test_d20_dice_bless_grants_bonus_bane_grants_penalty():
    bonus, penalty = conditions.d20_dice([conditions.BLESS])
    assert bonus == ["1d4"]
    assert penalty == []
    bonus, penalty = conditions.d20_dice([conditions.BANE])
    assert bonus == []
    assert penalty == ["1d4"]


def test_d20_dice_ignores_conditions_with_no_roll_effect():
    bonus, penalty = conditions.d20_dice([conditions.GRAPPLED, conditions.POISONED])
    assert bonus == []
    assert penalty == []


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


def test_ac_bonus_for_sums_shield_grant():
    """Shield's grant_ac_bonus folds into the target's AC via ac_bonus_for."""
    from dnd5e import conditions
    from dnd5e.creature import ConditionInstance, Creature
    from dnd5e.statblock import ConditionDef, EffectCall, Statblock, Stats

    shielded = ConditionDef(name="shielded",
                            grants=(EffectCall(effect="grant_ac_bonus", args={"amount": 5}),))
    stats = Stats(strength=10, dexterity=10, constitution=10, intelligence=10, wisdom=10, charisma=10,
                  ac=12, speed=30, initiative_bonus=0, proficiency=2, crit_range=20, reach=5,
                  hit_dice=None, hp_average=10)
    wiz = Creature(statblock=Statblock(name="w", display_name="w", classification={}, stats=stats),
                   instance_name="w", side="party")
    defs = {"shielded": shielded}
    assert conditions.ac_bonus_for(wiz, condition_defs=defs) == 0
    wiz.add_condition(ConditionInstance(name="shielded", source="w"))
    assert conditions.ac_bonus_for(wiz, condition_defs=defs) == 5
