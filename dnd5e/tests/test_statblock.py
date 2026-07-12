from dnd5e.statblock import (
    Ability,
    Behavior,
    EffectCall,
    MultiattackOption,
    Statblock,
    Stats,
)


def make_stats(**overrides):
    base = dict(
        strength=16, dexterity=11, constitution=19, intelligence=6, wisdom=13,
        charisma=6, ac=14, speed=30, initiative_bonus=0, proficiency=3,
        crit_range=20, reach=5, hit_dice="12d10+48", hp_average=114,
    )
    base.update(overrides)
    return Stats(**base)


def test_modifier_derivation_floor_division():
    stats = make_stats(strength=16, dexterity=11, constitution=19, intelligence=6)
    assert stats.modifier("strength") == 3    # (16-10)//2
    assert stats.modifier("dexterity") == 0   # (11-10)//2 = 0 (floor)
    assert stats.modifier("constitution") == 4  # (19-10)//2 = 4
    assert stats.modifier("intelligence") == -2  # (6-10)//2 = -2


def test_modifier_odd_and_even_scores_giving_same_modifier():
    # 18 and 19 both give +4 — the "flavor" score doesn't change the math.
    assert make_stats(constitution=18).modifier("constitution") == 4
    assert make_stats(constitution=19).modifier("constitution") == 4


def test_save_mod_uses_explicit_override_when_present():
    stats = make_stats(constitution=19, saves={"constitution": 7})
    assert stats.save_mod("constitution") == 7  # not the bare +4 modifier


def test_save_mod_falls_back_to_ability_modifier():
    stats = make_stats(wisdom=13)
    assert stats.save_mod("wisdom") == stats.modifier("wisdom") == 1


def test_effect_call_from_dict_separates_effect_name_from_args():
    call = EffectCall.from_dict({"effect": "attach_condition", "condition": "grappled", "escape_dc": 13})
    assert call.effect == "attach_condition"
    assert call.args == {"condition": "grappled", "escape_dc": 13}


def test_ability_defaults():
    ability = Ability(name="bite", kind="attack", to_hit=6, damage="2d8+3")
    assert ability.crit_range == 20
    assert ability.on_hit == ()
    assert ability.costs is None


def test_multiattack_option_no_when_means_always_eligible_by_convention():
    option = MultiattackOption(name="standard", actions=("longsword", "longsword"))
    assert option.when is None
    assert option.priority == 0


def test_behavior_defaults_to_engage_tactic_no_priority():
    behavior = Behavior()
    assert behavior.tactic == "engage"
    assert behavior.action_priority == ()


def test_statblock_challenge_or_level_prefers_cr():
    sb = Statblock(name="otyugh", display_name="Otyugh",
                   classification={"cr": 5, "level": 99}, stats=make_stats())
    assert sb.challenge_or_level == 5


def test_statblock_challenge_or_level_falls_back_to_level():
    sb = Statblock(name="fighter", display_name="Fighter",
                   classification={"level": 5}, stats=make_stats())
    assert sb.challenge_or_level == 5


def test_statblock_defaults_are_empty_not_none():
    sb = Statblock(name="x", display_name="X", classification={}, stats=make_stats())
    assert sb.abilities == {}
    assert sb.multiattack == {}
    assert sb.traits == {}
    assert sb.reactions == {}
    assert sb.resources == {}
    assert isinstance(sb.behavior, Behavior)
