import pytest

from dnd5e.loader import build_statblock, load_creature


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


# ---- Phase 5: conditions / reactions / effect-call `when` -----------------------

def test_condition_def_parses_grants_exclusive_expires_unless(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n'
            '[conditions.marked]\n'
            'grants = [ { effect = "impose_disadvantage_except_source" } ]\n'
            'exclusive = "per_source"\n'
            'ends_with_source = true\n'
            'expires = "end_of_bearer_turn"\n'
            'unless = "attacked_other_than_source_this_turn"\n')
    sb = load_creature(write(tmp_path, "x", body))
    cdef = sb.conditions["marked"]
    assert [g.effect for g in cdef.grants] == ["impose_disadvantage_except_source"]
    assert cdef.exclusive == "per_source"
    assert cdef.expires == "end_of_bearer_turn"
    assert cdef.unless == "attacked_other_than_source_this_turn"


def test_condition_def_rounds_clock_accepted(tmp_path):
    body = f'name = "x"\n{MINIMAL_STATS}\n[conditions.dazed]\nexpires = "rounds:2"\n'
    sb = load_creature(write(tmp_path, "x", body))
    assert sb.conditions["dazed"].expires == "rounds:2"


def test_condition_def_unknown_clock_raises(tmp_path):
    body = f'name = "x"\n{MINIMAL_STATS}\n[conditions.dazed]\nexpires = "bogus"\n'
    with pytest.raises(ValueError, match="unknown clock"):
        load_creature(write(tmp_path, "x", body))


def test_condition_def_unknown_grant_raises(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[conditions.dazed]\n'
            'grants = [ { effect = "teleport" } ]\n')
    with pytest.raises(ValueError, match="unknown grant-context effect"):
        load_creature(write(tmp_path, "x", body))


def test_condition_def_unknown_exclusive_raises(tmp_path):
    body = f'name = "x"\n{MINIMAL_STATS}\n[conditions.dazed]\nexclusive = "per_universe"\n'
    with pytest.raises(ValueError, match="not one of"):
        load_creature(write(tmp_path, "x", body))


def test_attach_condition_accepts_a_locally_defined_custom_condition(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n'
            '[conditions.marked]\ngrants = []\n'
            '[abilities.bite]\nkind = "attack"\nto_hit=5\ndamage="1d6"\n'
            'on_hit = [ { effect = "attach_condition", condition = "marked" } ]\n')
    sb = load_creature(write(tmp_path, "x", body))
    assert sb.abilities["bite"].on_hit[0].args["condition"] == "marked"


def test_attach_condition_rejects_unknown_custom_condition(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.bite]\nkind = "attack"\nto_hit=5\ndamage="1d6"\n'
            'on_hit = [ { effect = "attach_condition", condition = "marked" } ]\n')
    with pytest.raises(ValueError, match="not a RAW condition"):
        load_creature(write(tmp_path, "x", body))


def test_reaction_parses_trigger_when_effects_and_economy(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n'
            '[reactions.deceptive_defense]\n'
            'trigger = "ally_targeted_by_attack"\n'
            'when = "distance(self, event.target) <= 30"\n'
            'uses_reaction = true\n'
            '[[reactions.deceptive_defense.effects]]\n'
            'effect = "redirect_attack"\n'
            'to = "self"\n')
    sb = load_creature(write(tmp_path, "x", body))
    reaction = sb.reactions["deceptive_defense"]
    assert reaction.trigger == "ally_targeted_by_attack"
    assert reaction.uses_reaction is True
    assert reaction.effects[0].effect == "redirect_attack"
    assert reaction.effects[0].args["to"] == "self"


def test_reaction_unknown_trigger_raises(tmp_path):
    body = f'name = "x"\n{MINIMAL_STATS}\n[reactions.foo]\ntrigger = "bogus_trigger"\n'
    with pytest.raises(ValueError, match="not one of"):
        load_creature(write(tmp_path, "x", body))


def test_effect_call_when_gate_parses_and_validates(tmp_path):
    # A `when` on an individual effect call (doc 01's masked_bruiser example)
    # is now supported — distinct from multiattack/targeting/target_filter
    # `when`, which Phase 4 already supported.
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.bite]\nkind = "attack"\nto_hit=5\ndamage="1d6"\n'
            'on_hit = [ { effect = "attach_condition", condition = "grappled", when = "true" } ]\n')
    sb = load_creature(write(tmp_path, "x", body))
    when_node = sb.abilities["bite"].on_hit[0].args["when"]
    assert when_node is not None  # a compiled expressions.Node, not the raw string


def test_effect_call_when_gate_unknown_identifier_raises_at_load(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.bite]\nkind = "attack"\nto_hit=5\ndamage="1d6"\n'
            'on_hit = [ { effect = "attach_condition", condition = "grappled", when = "nonsense_fn(target)" } ]\n')
    with pytest.raises(Exception):
        load_creature(write(tmp_path, "x", body))


def test_effect_call_target_ref_accepted(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.bite]\nkind = "attack"\nto_hit=5\ndamage="1d6"\n'
            'on_hit = [ { effect = "attach_condition", condition = "grappled", target = "event.attacker" } ]\n')
    sb = load_creature(write(tmp_path, "x", body))
    assert sb.abilities["bite"].on_hit[0].args["target"] == "event.attacker"


def test_effect_call_target_ref_invalid_raises(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.bite]\nkind = "attack"\nto_hit=5\ndamage="1d6"\n'
            'on_hit = [ { effect = "attach_condition", condition = "grappled", target = "bogus" } ]\n')
    with pytest.raises(ValueError, match="not a valid target reference"):
        load_creature(write(tmp_path, "x", body))


def test_attach_condition_accepts_expires_clock(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.strike]\nkind = "attack"\nto_hit=5\ndamage="1d6"\n'
            'on_hit = [ { effect = "attach_condition", condition = "stunned", expires = "start_of_source_next_turn" } ]\n')
    sb = load_creature(write(tmp_path, "x", body))
    assert sb.abilities["strike"].on_hit[0].args["expires"] == "start_of_source_next_turn"


def test_attach_condition_rejects_unknown_expires_clock(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.strike]\nkind = "attack"\nto_hit=5\ndamage="1d6"\n'
            'on_hit = [ { effect = "attach_condition", condition = "stunned", expires = "someday" } ]\n')
    with pytest.raises(ValueError, match="unknown clock"):
        load_creature(write(tmp_path, "x", body))


def test_reduce_damage_requires_factor(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[reactions.dodge]\ntrigger = "taking_damage"\n'
            'effects = [ { effect = "reduce_damage" } ]\n')
    with pytest.raises(ValueError, match="factor"):
        load_creature(write(tmp_path, "x", body))


def test_mark_turn_requires_key(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.bite]\nkind = "attack"\nto_hit=5\ndamage="1d6"\n'
            'on_hit = [ { effect = "mark_turn" } ]\n')
    with pytest.raises(ValueError, match="key"):
        load_creature(write(tmp_path, "x", body))


def test_reduce_damage_and_turn_marked_gate_load_cleanly(tmp_path):
    # The full Sneak-Attack-style gate: a once-per-turn damage_rider guarded by
    # turn_marked, plus the mark_turn that sets it — all valid at load time.
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.dagger]\nkind = "attack"\nto_hit=5\ndamage="1d4"\n'
            'on_hit = [ { effect = "damage_rider", damage = "3d6", when = "not turn_marked(\'sneak\')" },'
            ' { effect = "mark_turn", key = "sneak", when = "not turn_marked(\'sneak\')" } ]\n')
    sb = load_creature(write(tmp_path, "x", body))
    assert len(sb.abilities["dagger"].on_hit) == 2


# ---- Phase 4: target_filter / multiattack when / behavior.targeting / behavior.custom ----

def test_ability_target_filter_parses_and_validates(tmp_path):
    from dnd5e import expressions
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.tentacle]\nkind = "attack"\nto_hit=5\ndamage="1d6"\n'
            "target_filter = \"not is_grappled_by(target, self)\"\n")
    sb = load_creature(write(tmp_path, "x", body))
    assert isinstance(sb.abilities["tentacle"].target_filter, expressions.Node)


def test_ability_target_filter_unknown_identifier_raises_at_load(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.tentacle]\nkind = "attack"\nto_hit=5\ndamage="1d6"\n'
            'target_filter = "bogus_selector"\n')
    with pytest.raises(ValueError, match="unknown selector"):
        load_creature(write(tmp_path, "x", body))


def test_multiattack_when_parses_and_validates(tmp_path):
    from dnd5e import expressions
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.bite]\nkind="attack"\nto_hit=5\ndamage="1d6"\n'
            '[multiattack.a]\nactions=["bite"]\nwhen="count(enemies_grappled_by_self) >= 2"\npriority=1\n'
            '[multiattack.b]\nactions=["bite"]\npriority=0\n')
    sb = load_creature(write(tmp_path, "x", body))
    assert isinstance(sb.multiattack["a"].when, expressions.Node)
    assert sb.multiattack["b"].when is None


def test_multiattack_when_unknown_function_raises_at_load(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.bite]\nkind="attack"\nto_hit=5\ndamage="1d6"\n'
            '[multiattack.a]\nactions=["bite"]\nwhen="teleport(self)"\n')
    with pytest.raises(ValueError, match="unknown function"):
        load_creature(write(tmp_path, "x", body))


def test_behavior_targeting_rules_parse(tmp_path):
    from dnd5e import expressions
    body = (f'name = "x"\n{MINIMAL_STATS}\n'
            '[[behavior.targeting]]\nwhen = "is_grappled_by(target, self)"\npriority = 100\n'
            '[[behavior.targeting]]\npriority = 0\norder = "random"\n')
    sb = load_creature(write(tmp_path, "x", body))
    assert len(sb.behavior.targeting) == 2
    assert isinstance(sb.behavior.targeting[0].when, expressions.Node)
    assert sb.behavior.targeting[0].priority == 100
    assert sb.behavior.targeting[1].when is None
    assert sb.behavior.targeting[1].order == "random"


def test_behavior_targeting_invalid_order_raises(tmp_path):
    body = f'name = "x"\n{MINIMAL_STATS}\n[[behavior.targeting]]\norder = "bogus"\n'
    with pytest.raises(ValueError, match="not one of"):
        load_creature(write(tmp_path, "x", body))


def test_behavior_custom_handler_accepted(tmp_path):
    body = f'name = "x"\n{MINIMAL_STATS}\n[behavior.custom]\nhandler = "python:sim_behavior.OtyughBrain"\n'
    sb = load_creature(write(tmp_path, "x", body))
    assert sb.behavior.custom == "python:sim_behavior.OtyughBrain"


def test_behavior_custom_handler_must_start_with_python_prefix(tmp_path):
    body = f'name = "x"\n{MINIMAL_STATS}\n[behavior.custom]\nhandler = "sim_behavior.OtyughBrain"\n'
    with pytest.raises(ValueError, match="must start with 'python:'"):
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


def test_set_flag_missing_flag_key_raises(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.bite]\nkind = "attack"\nto_hit=5\ndamage="1d6"\n'
            'on_hit = [ { effect = "set_flag" } ]\n')
    with pytest.raises(ValueError, match="missing required key"):
        load_creature(write(tmp_path, "x", body))


def test_set_flag_invalid_scope_raises(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.bite]\nkind = "attack"\nto_hit=5\ndamage="1d6"\n'
            'on_hit = [ { effect = "set_flag", flag = "enemy_crit", scope = "encounter" } ]\n')
    with pytest.raises(ValueError, match="not one of"):
        load_creature(write(tmp_path, "x", body))


def test_set_flag_defaults_and_explicit_scope_both_accepted(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.bite]\nkind = "attack"\nto_hit=5\ndamage="1d6"\n'
            'on_hit = [ { effect = "set_flag", flag = "a" }, '
            '{ effect = "set_flag", flag = "b", scope = "trial" } ]\n')
    sb = load_creature(write(tmp_path, "x", body))
    assert sb.abilities["bite"].on_hit[0].args == {"flag": "a"}
    assert sb.abilities["bite"].on_hit[1].args == {"flag": "b", "scope": "trial"}


def test_end_trial_with_no_outcome_accepted(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.bite]\nkind = "attack"\nto_hit=5\ndamage="1d6"\n'
            'on_hit = [ { effect = "end_trial" } ]\n')
    sb = load_creature(write(tmp_path, "x", body))
    assert sb.abilities["bite"].on_hit[0].args == {}


def test_end_trial_with_outcome_table_accepted(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.bite]\nkind = "attack"\nto_hit=5\ndamage="1d6"\n'
            'on_hit = [ { effect = "end_trial", outcome = { retreated = 1 } } ]\n')
    sb = load_creature(write(tmp_path, "x", body))
    assert sb.abilities["bite"].on_hit[0].args == {"outcome": {"retreated": 1}}


def test_end_trial_outcome_must_be_a_table(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[abilities.bite]\nkind = "attack"\nto_hit=5\ndamage="1d6"\n'
            'on_hit = [ { effect = "end_trial", outcome = "retreated" } ]\n')
    with pytest.raises(ValueError, match="must be a table"):
        load_creature(write(tmp_path, "x", body))


def test_emit_light_missing_radius_raises(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[traits.torch]\n'
            'effects = [ { effect = "emit_light" } ]\n')
    with pytest.raises(ValueError, match="missing required key"):
        load_creature(write(tmp_path, "x", body))


def test_emit_light_accepted_on_a_trait(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[traits.torch]\n'
            'effects = [ { effect = "emit_light", radius = 20 } ]\n')
    sb = load_creature(write(tmp_path, "x", body))
    assert sb.traits["torch"].effects[0].args == {"radius": 20}


def test_limited_darkvision_and_darkvision_immunity_accepted_with_no_args(tmp_path):
    body = (f'name = "x"\n{MINIMAL_STATS}\n[traits.photophage]\n'
            'effects = [ { effect = "limited_darkvision" }, { effect = "darkvision_immunity" } ]\n')
    sb = load_creature(write(tmp_path, "x", body))
    assert [c.effect for c in sb.traits["photophage"].effects] == ["limited_darkvision", "darkvision_immunity"]


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
