import logging

import pytest
from dnd_board import load_board_toml

from dnd5e import escape_hatch, expressions
from dnd5e.battlefield import Battlefield
from dnd5e.behavior import BehaviorContext, select_multiattack, select_targets
from dnd5e.creature import Creature
from dnd5e.dice import Resolver
from dnd5e.flags import FlagBag
from dnd5e.statblock import (
    Ability, Behavior, MultiattackOption, Resource, Statblock, Stats, TargetingRule,
)


@pytest.fixture(autouse=True)
def _clear_escape_hatch_cache():
    escape_hatch.clear_cache()
    yield
    escape_hatch.clear_cache()

OPEN_BOARD = '''
name = "open"
map = """
..........
..........
..........
..........
..........
"""
[meta]
cell_feet = 5
'''


class ScriptedDice:
    """Pops the next scripted value regardless of the dice code — matches
    test_system.py's convention for deterministic-roll tests."""

    def __init__(self, values):
        self._values = list(values)

    def roll(self, code):
        return self._values.pop(0)


def make_board(tmp_path):
    p = tmp_path / "board.toml"
    p.write_text(OPEN_BOARD)
    return load_board_toml(p)


def make_stats(**overrides):
    base = dict(strength=16, dexterity=11, constitution=19, intelligence=6, wisdom=13,
               charisma=6, ac=14, speed=30, initiative_bonus=0, proficiency=3,
               crit_range=20, reach=5, hit_dice=None, hp_average=20)
    base.update(overrides)
    return Stats(**base)


def make_creature(name, side, x, y, *, statblock=None, hp=None, **stat_overrides):
    sb = statblock or Statblock(name=name, display_name=name, classification={},
                                stats=make_stats(hp_average=hp or 20, **stat_overrides))
    c = Creature(statblock=sb, instance_name=name, side=side)
    c.place(x, y)
    return c


def expr(source):
    return expressions.parse_and_validate(source, where="test")


def make_ctx(battlefield, *, dice_values=(), round_index=1, turn_order=None):
    resolver = Resolver(ScriptedDice(list(dice_values)))
    return BehaviorContext(battlefield=battlefield, round_index=round_index,
                           turn_order=turn_order or [], flags=FlagBag(), resolver=resolver)


# =============================================================================
# Multiattack selection — the Otyugh acid test (design doc 01 section 1.11)
# =============================================================================

def otyugh_statblock():
    abilities = {
        "bite": Ability(name="bite", kind="attack", to_hit=6, damage="2d8+3", damage_type="piercing"),
        "tentacle": Ability(name="tentacle", kind="attack", to_hit=6, damage="2d6+3", damage_type="bludgeoning"),
        "tentacle_slam": Ability(name="tentacle_slam", kind="save", ability="constitution", dc=14,
                                 damage="2d10+3", damage_type="bludgeoning", half_on_save=True,
                                 targets="enemies_grappled_by_self", max_targets=2),
    }
    multiattack = {
        "slam_two": MultiattackOption(name="slam_two", actions=("tentacle_slam",),
                                      when=expr("count(enemies_grappled_by_self) >= 2"), priority=30),
        "bite_and_grab": MultiattackOption(name="bite_and_grab", actions=("bite", "tentacle"),
                                           when=expr("count(enemies_grappled_by_self) == 1"), priority=20),
        "grab_two": MultiattackOption(name="grab_two", actions=("tentacle", "tentacle"), priority=0),
    }
    return Statblock(name="otyugh", display_name="Otyugh", classification={"cr": 5},
                     stats=make_stats(hp_average=104), abilities=abilities, multiattack=multiattack)


def test_multiattack_zero_grapples_picks_grab_two(tmp_path):
    board = make_board(tmp_path)
    otyugh = make_creature("otyugh", "monsters", 0, 0, statblock=otyugh_statblock())
    fighter = make_creature("fighter", "party", 1, 0)
    bf = Battlefield([otyugh, fighter], board=board)
    opt = select_multiattack(otyugh, make_ctx(bf))
    assert opt.name == "grab_two"


def test_multiattack_one_grapple_picks_bite_and_grab(tmp_path):
    board = make_board(tmp_path)
    otyugh = make_creature("otyugh", "monsters", 0, 0, statblock=otyugh_statblock())
    fighter = make_creature("fighter", "party", 1, 0)
    bf = Battlefield([otyugh, fighter], board=board)
    bf.grapple("otyugh", "fighter")
    opt = select_multiattack(otyugh, make_ctx(bf))
    assert opt.name == "bite_and_grab"


def test_multiattack_two_grapples_picks_slam_two(tmp_path):
    board = make_board(tmp_path)
    otyugh = make_creature("otyugh", "monsters", 0, 0, statblock=otyugh_statblock())
    fighter = make_creature("fighter", "party", 1, 0)
    rogue = make_creature("rogue", "party", 2, 0)
    bf = Battlefield([otyugh, fighter, rogue], board=board)
    bf.grapple("otyugh", "fighter")
    bf.grapple("otyugh", "rogue")
    opt = select_multiattack(otyugh, make_ctx(bf))
    assert opt.name == "slam_two"


# =============================================================================
# Multiattack selection — costs, and the no-eligible-option fallback
# =============================================================================

def test_multiattack_skips_option_with_unavailable_resource(tmp_path):
    board = make_board(tmp_path)
    abilities = {
        "special": Ability(name="special", kind="attack", to_hit=5, damage="1d6", damage_type="slashing",
                           costs={"resource": "charges", "amount": 1}),
        "basic": Ability(name="basic", kind="attack", to_hit=5, damage="1d4", damage_type="slashing"),
    }
    multiattack = {
        "big": MultiattackOption(name="big", actions=("special",), priority=10),
        "small": MultiattackOption(name="small", actions=("basic",), priority=0),
    }
    sb = Statblock(name="creature", display_name="creature", classification={}, stats=make_stats(),
                   abilities=abilities, multiattack=multiattack,
                   resources={"charges": Resource(name="charges", uses=1)})
    actor = make_creature("actor", "monsters", 0, 0, statblock=sb)
    actor.reset_state()
    actor.resources["charges"] = 0
    bf = Battlefield([actor], board=board)
    opt = select_multiattack(actor, make_ctx(bf))
    assert opt.name == "small"


def test_multiattack_available_resource_keeps_option_eligible(tmp_path):
    board = make_board(tmp_path)
    abilities = {
        "special": Ability(name="special", kind="attack", to_hit=5, damage="1d6", damage_type="slashing",
                           costs={"resource": "charges", "amount": 1}),
        "basic": Ability(name="basic", kind="attack", to_hit=5, damage="1d4", damage_type="slashing"),
    }
    multiattack = {
        "big": MultiattackOption(name="big", actions=("special",), priority=10),
        "small": MultiattackOption(name="small", actions=("basic",), priority=0),
    }
    sb = Statblock(name="creature", display_name="creature", classification={}, stats=make_stats(),
                   abilities=abilities, multiattack=multiattack,
                   resources={"charges": Resource(name="charges", uses=1)})
    actor = make_creature("actor", "monsters", 0, 0, statblock=sb)
    actor.reset_state()
    bf = Battlefield([actor], board=board)
    opt = select_multiattack(actor, make_ctx(bf))
    assert opt.name == "big"


def test_multiattack_fallback_when_nothing_eligible_logs_warning(tmp_path, caplog):
    board = make_board(tmp_path)
    abilities = {"basic": Ability(name="basic", kind="attack", to_hit=5, damage="1d4", damage_type="slashing")}
    multiattack = {
        "a": MultiattackOption(name="a", actions=("basic",), when=expr("count(enemies) >= 5"), priority=10),
        "b": MultiattackOption(name="b", actions=("basic",), when=expr("count(enemies) >= 10"), priority=5),
    }
    sb = Statblock(name="creature", display_name="creature", classification={}, stats=make_stats(),
                   abilities=abilities, multiattack=multiattack)
    actor = make_creature("actor", "monsters", 0, 0, statblock=sb)
    bf = Battlefield([actor], board=board)
    with caplog.at_level(logging.WARNING):
        opt = select_multiattack(actor, make_ctx(bf))
    assert opt.name == "b"  # the lowest-priority option, per the fallback rule
    assert "no eligible multiattack option" in caplog.text


def test_multiattack_falls_back_to_implicit_action_priority_when_no_multiattack_table(tmp_path):
    board = make_board(tmp_path)
    abilities = {"basic": Ability(name="basic", kind="attack", to_hit=5, damage="1d4", damage_type="slashing")}
    sb = Statblock(name="creature", display_name="creature", classification={}, stats=make_stats(),
                   abilities=abilities, behavior=Behavior(action_priority=("basic",)))
    actor = make_creature("actor", "monsters", 0, 0, statblock=sb)
    bf = Battlefield([actor], board=board)
    opt = select_multiattack(actor, make_ctx(bf))
    assert opt.actions == ("basic",)


# =============================================================================
# Targeting (design doc 04 section 3)
# =============================================================================

def attacker_statblock(*, targeting=(), targets=None, target_filter=None, max_targets=None):
    ability = Ability(name="hit", kind="attack", to_hit=5, damage="1d6", damage_type="slashing",
                      targets=targets, target_filter=target_filter, max_targets=max_targets)
    return Statblock(name="actor", display_name="actor", classification={}, stats=make_stats(),
                     abilities={"hit": ability}, behavior=Behavior(targeting=targeting))


def test_target_filter_narrows_pool(tmp_path):
    board = make_board(tmp_path)
    sb = attacker_statblock(target_filter=expr("hp_pct(target) < 0.5"))
    actor = make_creature("actor", "monsters", 0, 0, statblock=sb)
    bloodied = make_creature("bloodied", "party", 1, 0, hp=20)
    bloodied.current_damage = 15  # hp_pct = 0.25
    healthy = make_creature("healthy", "party", 2, 0, hp=20)
    bf = Battlefield([actor, bloodied, healthy], board=board)
    result = select_targets(actor, sb.abilities["hit"], make_ctx(bf))
    assert [c.instance_name for c in result] == ["bloodied"]


def test_targeting_rule_restricts_pool_when_it_matches(tmp_path):
    board = make_board(tmp_path)
    rules = (
        TargetingRule(when=expr("is_bloodied(target)"), priority=10, order="nearest"),
        TargetingRule(when=None, priority=0, order="nearest"),
    )
    sb = attacker_statblock(targeting=rules)
    actor = make_creature("actor", "monsters", 0, 0, statblock=sb)
    bloodied = make_creature("bloodied", "party", 9, 0, hp=20)  # far, but bloodied
    bloodied.current_damage = 15
    healthy = make_creature("healthy", "party", 1, 0, hp=20)   # near, but healthy
    bf = Battlefield([actor, bloodied, healthy], board=board)
    result = select_targets(actor, sb.abilities["hit"], make_ctx(bf))
    assert [c.instance_name for c in result] == ["bloodied"]


def test_targeting_rule_falls_through_to_fallback_rule(tmp_path):
    board = make_board(tmp_path)
    rules = (
        TargetingRule(when=expr("is_bloodied(target)"), priority=10, order="nearest"),
        TargetingRule(when=None, priority=0, order="nearest"),
    )
    sb = attacker_statblock(targeting=rules)
    actor = make_creature("actor", "monsters", 0, 0, statblock=sb)
    a = make_creature("a", "party", 5, 0, hp=20)
    b = make_creature("b", "party", 1, 0, hp=20)
    bf = Battlefield([actor, a, b], board=board)
    result = select_targets(actor, sb.abilities["hit"], make_ctx(bf))
    # No one bloodied -> the fallback rule matches everyone -> nearest first.
    assert [c.instance_name for c in result] == ["b"]


def test_order_nearest_ties_by_roster_order(tmp_path):
    board = make_board(tmp_path)
    sb = attacker_statblock(max_targets=3)
    actor = make_creature("actor", "monsters", 0, 0, statblock=sb)
    a = make_creature("a", "party", 5, 0)
    b = make_creature("b", "party", 5, 0)
    c = make_creature("c", "party", 3, 0)
    bf = Battlefield([actor, a, b, c], board=board)
    result = select_targets(actor, sb.abilities["hit"], make_ctx(bf))
    assert [x.instance_name for x in result] == ["c", "a", "b"]


def test_order_focus_promotes_focused_target(tmp_path):
    board = make_board(tmp_path)
    rules = (TargetingRule(when=None, priority=0, order="focus"),)
    sb = attacker_statblock(targeting=rules, max_targets=3)
    actor = make_creature("actor", "monsters", 0, 0, statblock=sb)
    a = make_creature("a", "party", 1, 0)
    b = make_creature("b", "party", 5, 0)
    c = make_creature("c", "party", 9, 0)
    bf = Battlefield([actor, a, b, c], board=board)
    bf.focus["monsters"] = "c"
    result = select_targets(actor, sb.abilities["hit"], make_ctx(bf))
    assert result[0].instance_name == "c"
    assert {x.instance_name for x in result} == {"a", "b", "c"}


def test_order_random_draws_from_trials_seeded_stream(tmp_path):
    board = make_board(tmp_path)
    rules = (TargetingRule(when=None, priority=0, order="random"),)
    sb = attacker_statblock(targeting=rules, max_targets=3)
    actor = make_creature("actor", "monsters", 0, 0, statblock=sb)
    a = make_creature("a", "party", 1, 0)
    b = make_creature("b", "party", 2, 0)
    c = make_creature("c", "party", 3, 0)
    bf = Battlefield([actor, a, b, c], board=board)
    # Pool starts as [a, b, c] (roster order). 1d3=2 -> pop index1 (b);
    # remaining [a, c]; 1d2=1 -> pop index0 (a); remaining [c]; 1d1=1 -> pop c.
    ctx = make_ctx(bf, dice_values=[2, 1, 1])
    result = select_targets(actor, sb.abilities["hit"], ctx)
    assert [x.instance_name for x in result] == ["b", "a", "c"]


def test_max_targets_truncates_ordered_pool(tmp_path):
    board = make_board(tmp_path)
    sb = attacker_statblock(max_targets=1)
    actor = make_creature("actor", "monsters", 0, 0, statblock=sb)
    near = make_creature("near", "party", 1, 0)
    far = make_creature("far", "party", 9, 0)
    bf = Battlefield([actor, near, far], board=board)
    result = select_targets(actor, sb.abilities["hit"], make_ctx(bf))
    assert [x.instance_name for x in result] == ["near"]


def test_set_selector_skips_targeting_rules_and_ordering(tmp_path):
    board = make_board(tmp_path)
    # A targeting rule that would (if applied) restrict/reorder the pool —
    # proving the set-selector path skips it entirely (design doc 04 section 3).
    rules = (TargetingRule(when=None, priority=0, order="focus"),)
    sb = attacker_statblock(targeting=rules, targets="enemies_grappled_by_self")
    actor = make_creature("actor", "monsters", 0, 0, statblock=sb)
    far = make_creature("far", "party", 9, 0)
    near = make_creature("near", "party", 1, 0)
    bf = Battlefield([actor, far, near], board=board)
    bf.focus["monsters"] = "near"  # would promote "near" first under the focus rule
    bf.grapple("actor", "far")
    bf.grapple("actor", "near")
    result = select_targets(actor, sb.abilities["hit"], make_ctx(bf))
    # Raw grapple insertion order, NOT focus-reordered.
    assert [x.instance_name for x in result] == ["far", "near"]


def test_set_selector_still_applies_target_filter(tmp_path):
    board = make_board(tmp_path)
    sb = attacker_statblock(targets="enemies_grappled_by_self",
                            target_filter=expr("is_bloodied(target)"))
    actor = make_creature("actor", "monsters", 0, 0, statblock=sb)
    bloodied = make_creature("bloodied", "party", 1, 0, hp=20)
    bloodied.current_damage = 15
    healthy = make_creature("healthy", "party", 2, 0, hp=20)
    bf = Battlefield([actor, bloodied, healthy], board=board)
    bf.grapple("actor", "bloodied")
    bf.grapple("actor", "healthy")
    result = select_targets(actor, sb.abilities["hit"], make_ctx(bf))
    assert [x.instance_name for x in result] == ["bloodied"]


# =============================================================================
# Escape hatch (design doc 04 section 5)
# =============================================================================

class _ForceOption:
    """choose_multiattack always forces a specific option name."""

    def __init__(self, name):
        self._name = name

    def choose_multiattack(self, me, view):
        return self._name

    def choose_target(self, me, ability, pool, view):
        return None

    def plan_movement(self, me, view):
        return None


class _FallThrough:
    """Every hook returns None: pure declarative fallback."""

    def choose_multiattack(self, me, view):
        return None

    def choose_target(self, me, ability, pool, view):
        return None

    def plan_movement(self, me, view):
        return None


class _PreferFarthest:
    """choose_target picks the pool member farthest from self, via
    view.eval to prove the escape hatch can lean on the expression
    vocabulary rather than the raw Battlefield API."""

    def choose_target(self, me, ability, pool, view):
        return max(pool, key=lambda c: view.with_it(c).eval("distance(self, it)"))

    def choose_multiattack(self, me, view):
        return None

    def plan_movement(self, me, view):
        return None


def test_escape_hatch_choose_multiattack_overrides_declarative_selection(tmp_path):
    board = make_board(tmp_path)
    escape_hatch._CACHE["python:test.ForceOption"] = _ForceOption("low_priority")
    abilities = {"basic": Ability(name="basic", kind="attack", to_hit=5, damage="1d4", damage_type="slashing")}
    multiattack = {
        "high_priority": MultiattackOption(name="high_priority", actions=("basic",), priority=10),
        "low_priority": MultiattackOption(name="low_priority", actions=("basic",), priority=0),
    }
    sb = Statblock(name="actor", display_name="actor", classification={}, stats=make_stats(),
                   abilities=abilities, multiattack=multiattack,
                   behavior=Behavior(custom="python:test.ForceOption"))
    actor = make_creature("actor", "monsters", 0, 0, statblock=sb)
    bf = Battlefield([actor], board=board)
    opt = select_multiattack(actor, make_ctx(bf))
    assert opt.name == "low_priority"  # declarative would have picked high_priority


def test_escape_hatch_none_falls_through_to_declarative_multiattack(tmp_path):
    board = make_board(tmp_path)
    escape_hatch._CACHE["python:test.FallThrough"] = _FallThrough()
    abilities = {"basic": Ability(name="basic", kind="attack", to_hit=5, damage="1d4", damage_type="slashing")}
    multiattack = {"only": MultiattackOption(name="only", actions=("basic",), priority=0)}
    sb = Statblock(name="actor", display_name="actor", classification={}, stats=make_stats(),
                   abilities=abilities, multiattack=multiattack,
                   behavior=Behavior(custom="python:test.FallThrough"))
    actor = make_creature("actor", "monsters", 0, 0, statblock=sb)
    bf = Battlefield([actor], board=board)
    opt = select_multiattack(actor, make_ctx(bf))
    assert opt.name == "only"


def test_escape_hatch_choose_target_overrides_the_primary_pick(tmp_path):
    board = make_board(tmp_path)
    escape_hatch._CACHE["python:test.PreferFarthest"] = _PreferFarthest()
    sb = attacker_statblock()
    sb = Statblock(name=sb.name, display_name=sb.display_name, classification=sb.classification,
                   stats=sb.stats, abilities=sb.abilities,
                   behavior=Behavior(custom="python:test.PreferFarthest"))
    actor = make_creature("actor", "monsters", 0, 0, statblock=sb)
    near = make_creature("near", "party", 1, 0)
    far = make_creature("far", "party", 9, 0)
    bf = Battlefield([actor, near, far], board=board)
    result = select_targets(actor, sb.abilities["hit"], make_ctx(bf))
    assert result[0].instance_name == "far"  # declarative "nearest" would have picked "near"


def test_escape_hatch_choose_target_none_keeps_declarative_order(tmp_path):
    board = make_board(tmp_path)
    escape_hatch._CACHE["python:test.FallThrough"] = _FallThrough()
    sb = attacker_statblock()
    sb = Statblock(name=sb.name, display_name=sb.display_name, classification=sb.classification,
                   stats=sb.stats, abilities=sb.abilities,
                   behavior=Behavior(custom="python:test.FallThrough"))
    actor = make_creature("actor", "monsters", 0, 0, statblock=sb)
    near = make_creature("near", "party", 1, 0)
    far = make_creature("far", "party", 9, 0)
    bf = Battlefield([actor, near, far], board=board)
    result = select_targets(actor, sb.abilities["hit"], make_ctx(bf))
    assert result[0].instance_name == "near"


# =============================================================================
# turn_marked / mark_turn once-per-turn gate (design doc 07, Bug A)
# =============================================================================

def test_turn_marked_reads_the_acting_creatures_turn_scratch(tmp_path):
    from dnd5e.behavior import ConcreteScope
    board = make_board(tmp_path)
    actor = make_creature("rogue", "party", 0, 0)
    bf = Battlefield([actor], board=board)
    scope = ConcreteScope(make_ctx(bf), actor)
    assert scope.turn_marked("sneak") is False
    actor.turn_scratch["sneak"] = True
    assert scope.turn_marked("sneak") is True


def test_downed_allies_selector_sees_the_dying_that_allies_excludes(tmp_path):
    """`allies` filters out the Down (battlefield.allies_of), so a healer needs
    `downed_allies` to find who to raise (design doc 07, Bug C)."""
    from dnd5e.behavior import ConcreteScope
    board = make_board(tmp_path)
    cleric = make_creature("cleric", "party", 0, 0)
    hurt = make_creature("rogue", "party", 1, 0, hp=20)
    bf = Battlefield([cleric, hurt], board=board)
    scope = ConcreteScope(make_ctx(bf), cleric)

    assert [c.instance_name for c in scope.allies()] == ["rogue"]
    assert scope.downed_allies() == []

    hurt.current_damage = 999            # now Down
    assert scope.allies() == []                                   # allies_of hides it
    assert [c.instance_name for c in scope.downed_allies()] == ["rogue"]
