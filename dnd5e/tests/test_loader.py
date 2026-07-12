import pytest

from dnd5e.loader import NotYetSupportedError, build_statblock, load_creature


def write(tmp_path, name, body):
    p = tmp_path / f"{name}.toml"
    p.write_text(body)
    return p


MINIMAL_STATS = """
[stats]
strength = 16
dexterity = 11
constitution = 19
intelligence = 6
wisdom = 13
charisma = 6
ac = 14
speed = 30
"""


def test_minimal_creature_loads_with_derived_stats(tmp_path):
    p = write(tmp_path, "otyugh", f'name = "otyugh"\n{MINIMAL_STATS}')
    sb = load_creature(p)
    assert sb.name == "otyugh"
    assert sb.display_name == "Otyugh"
    assert sb.stats.strength == 16
    assert sb.stats.modifier("strength") == 3
    assert sb.stats.initiative_bonus == 0  # dex 11 -> modifier 0, defaulted
    assert sb.stats.proficiency == 2       # no cr/level given -> default challenge=1 -> +2


def test_name_must_match_file_stem(tmp_path):
    p = write(tmp_path, "otyugh", f'name = "not_otyugh"\n{MINIMAL_STATS}')
    with pytest.raises(ValueError, match="does not match file stem"):
        load_creature(p)


def test_missing_name_raises(tmp_path):
    p = write(tmp_path, "otyugh", MINIMAL_STATS)
    with pytest.raises(ValueError, match="missing required top-level 'name'"):
        load_creature(p)


def test_missing_ability_score_raises(tmp_path):
    p = write(tmp_path, "x", 'name = "x"\n[stats]\nstrength = 10\nac = 14\nspeed = 30\n')
    with pytest.raises(ValueError, match="missing required key"):
        load_creature(p)


def test_display_name_override(tmp_path):
    p = write(tmp_path, "otyugh", f'name = "otyugh"\ndisplay_name = "The Otyugh"\n{MINIMAL_STATS}')
    assert load_creature(p).display_name == "The Otyugh"


def test_proficiency_derived_from_cr(tmp_path):
    body = f'name = "x"\n[classification]\ncr = 9\n{MINIMAL_STATS}'
    sb = load_creature(write(tmp_path, "x", body))
    assert sb.stats.proficiency == 4


def test_proficiency_derived_from_level(tmp_path):
    body = f'name = "x"\n[classification]\nlevel = 5\n{MINIMAL_STATS}'
    sb = load_creature(write(tmp_path, "x", body))
    assert sb.stats.proficiency == 3


def test_initiative_bonus_explicit_wins_over_dex_default(tmp_path):
    # initiative_bonus is a [stats] key per the schema, not top-level.
    body = ('name = "x"\n[stats]\nstrength=16\ndexterity=11\nconstitution=19\nintelligence=6\n'
            'wisdom=13\ncharisma=6\nac=14\nspeed=30\ninitiative_bonus=7\n')
    sb = load_creature(write(tmp_path, "x", body))
    assert sb.stats.initiative_bonus == 7


def test_save_mod_explicit_override(tmp_path):
    body = f'name = "x"\n{MINIMAL_STATS}\n[stats.saves]\nconstitution = 7\n'
    sb = load_creature(write(tmp_path, "x", body))
    assert sb.stats.save_mod("constitution") == 7


CREATURE_WITH_ABILITIES = f'''
name = "otyugh"
{MINIMAL_STATS}
[abilities.bite]
kind = "attack"
to_hit = 6
damage = "2d8+3"
damage_type = "piercing"

[abilities.tentacle]
kind = "attack"
to_hit = 6
damage = "1d8+3"
damage_type = "bludgeoning"
on_hit = [ {{ effect = "attach_condition", condition = "grappled", escape_dc = 13 }} ]

[multiattack.standard]
actions = ["bite", "tentacle"]
priority = 0

[behavior]
action_priority = ["bite"]
'''


def test_creature_with_abilities_and_multiattack_loads(tmp_path):
    p = write(tmp_path, "otyugh", CREATURE_WITH_ABILITIES)
    sb = load_creature(p)
    assert set(sb.abilities) == {"bite", "tentacle"}
    assert sb.multiattack["standard"].actions == ("bite", "tentacle")
    assert sb.abilities["tentacle"].on_hit[0].effect == "attach_condition"
    assert sb.abilities["tentacle"].on_hit[0].args["condition"] == "grappled"
    assert sb.behavior.action_priority == ("bite",)


def test_unknown_ability_kind_raises(tmp_path):
    body = f'name = "x"\n{MINIMAL_STATS}\n[abilities.bite]\nkind = "teleport"\n'
    with pytest.raises(ValueError, match="not one of"):
        load_creature(write(tmp_path, "x", body))


def test_unknown_effect_name_raises(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.bite]\nkind = "attack"\n'
            'on_hit = [ { effect = "teleport" } ]\n')
    with pytest.raises(ValueError, match="unknown effect"):
        load_creature(write(tmp_path, "x", body))


def test_attach_condition_non_raw_condition_raises(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.bite]\nkind = "attack"\n'
            'on_hit = [ { effect = "attach_condition", condition = "bruisers_mark" } ]\n')
    with pytest.raises(ValueError, match="not a RAW condition"):
        load_creature(write(tmp_path, "x", body))


def test_multiattack_referencing_missing_action_raises(tmp_path):
    body = f'name = "x"\n{MINIMAL_STATS}\n[multiattack.bad]\nactions = ["nonexistent"]\n'
    with pytest.raises(ValueError, match="unknown action"):
        load_creature(write(tmp_path, "x", body))


def test_multiattack_priority_tie_raises(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n'
            '[abilities.a]\nkind = "attack"\nto_hit = 5\ndamage = "1d6"\n'
            '[multiattack.opt1]\nactions = ["a"]\npriority = 0\n'
            '[multiattack.opt2]\nactions = ["a"]\npriority = 0\n')
    with pytest.raises(ValueError, match="duplicate priority"):
        load_creature(write(tmp_path, "x", body))


def test_behavior_action_priority_unknown_action_raises(tmp_path):
    body = f'name = "x"\n{MINIMAL_STATS}\n[behavior]\naction_priority = ["nonexistent"]\n'
    with pytest.raises(ValueError, match="unknown action"):
        load_creature(write(tmp_path, "x", body))


def test_ability_costs_unknown_resource_raises(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.spell]\nkind = "attack"\nto_hit=5\ndamage="1d6"\n'
            'costs = { resource = "spell_slots_1" }\n')
    with pytest.raises(ValueError, match="unknown resource"):
        load_creature(write(tmp_path, "x", body))


def test_ability_costs_known_resource_loads(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n'
            '[resources.spell_slots_1]\nuses = 4\nper = "day"\n'
            '[abilities.spell]\nkind = "attack"\nto_hit=5\ndamage="1d6"\n'
            'costs = { resource = "spell_slots_1" }\n')
    sb = load_creature(write(tmp_path, "x", body))
    assert sb.resources["spell_slots_1"].uses == 4
    assert sb.abilities["spell"].costs == {"resource": "spell_slots_1"}


@pytest.mark.parametrize("body,match", [
    (f'name = "x"\n{MINIMAL_STATS}\n[abilities.bite]\nkind="attack"\ntarget_filter="true"\n', "target_filter"),
    (f'name = "x"\n{MINIMAL_STATS}\n[multiattack.a]\nactions=["bite"]\nwhen="true"\n', "multiattack 'when'"),
    (f'name = "x"\n{MINIMAL_STATS}\n[[behavior.targeting]]\npriority=1\n', "behavior.targeting"),
    (f'name = "x"\n{MINIMAL_STATS}\n[behavior.custom]\nhandler="python:x.Y"\n', "escape hatch"),
    (f'name = "x"\n{MINIMAL_STATS}\n[reactions.foo]\ntrigger="attack_hit"\n', "reactions"),
    (f'name = "x"\n{MINIMAL_STATS}\n[conditions.foo]\ngrants=[]\n', "conditions"),
])
def test_phase4_plus_features_raise_not_yet_supported(tmp_path, body, match):
    with pytest.raises(NotYetSupportedError, match=match):
        load_creature(write(tmp_path, "x", body))


def test_tactic_outside_phase3_set_raises(tmp_path):
    body = f'name = "x"\n{MINIMAL_STATS}\n[behavior]\ntactic = "hunt_light"\n'
    with pytest.raises(ValueError, match="not one of"):
        load_creature(write(tmp_path, "x", body))


def test_phase3_tactics_all_accepted(tmp_path):
    for tactic in ("engage", "kite", "hold"):
        body = f'name = "x"\n{MINIMAL_STATS}\n[behavior]\ntactic = "{tactic}"\n'
        sb = load_creature(write(tmp_path, "x", body))
        assert sb.behavior.tactic == tactic


def test_require_save_missing_required_keys_raises(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.bite]\nkind = "attack"\nto_hit=5\ndamage="1d6"\n'
            'on_hit = [ { effect = "require_save" } ]\n')
    with pytest.raises(ValueError, match="missing required key"):
        load_creature(write(tmp_path, "x", body))


def test_require_save_nested_on_fail_validated_recursively(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.bite]\nkind = "attack"\nto_hit=5\ndamage="1d6"\n\n'
            '[[abilities.bite.on_hit]]\neffect = "require_save"\nability = "con"\ndc = 15\n'
            'on_fail = [ { effect = "teleport" } ]\n')
    with pytest.raises(ValueError, match="unknown effect"):
        load_creature(write(tmp_path, "x", body))


def test_overrides_applied_before_validation(tmp_path):
    p = write(tmp_path, "otyugh", f'name = "otyugh"\n{MINIMAL_STATS}\n[stats.health]\naverage = 100\n')
    sb = load_creature(p, overrides={"stats": {"health": {"average": 999}}})
    assert sb.stats.hp_average == 999


def test_overrides_deep_merge_preserves_untouched_fields(tmp_path):
    p = write(tmp_path, "otyugh", f'name = "otyugh"\n{MINIMAL_STATS}\n[stats.health]\naverage = 100\n')
    sb = load_creature(p, overrides={"stats": {"ac": 20}})
    assert sb.stats.ac == 20
    assert sb.stats.hp_average == 100  # untouched by the override
    assert sb.stats.strength == 16     # untouched


def test_reactions_absent_key_is_fine(tmp_path):
    p = write(tmp_path, "x", f'name = "x"\n{MINIMAL_STATS}\n')
    sb = load_creature(p)
    assert sb.reactions == {}


def test_build_statblock_from_dict_directly():
    cfg = {"name": "x", "stats": {"strength": 10, "dexterity": 10, "constitution": 10,
                                  "intelligence": 10, "wisdom": 10, "charisma": 10,
                                  "ac": 10, "speed": 30}}
    sb = build_statblock(cfg, source="x")
    assert sb.name == "x"
