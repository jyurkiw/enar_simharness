import pytest

from dnd5e.creature import ConditionInstance, Creature
from dnd5e.dice import Resolver
from dnd5e.statblock import Resource, Statblock, Stats


def make_statblock(**stat_overrides):
    base = dict(
        strength=16, dexterity=11, constitution=19, intelligence=6, wisdom=13,
        charisma=6, ac=14, speed=30, initiative_bonus=0, proficiency=3,
        crit_range=20, reach=5, hit_dice="2d10+4", hp_average=15,
        saves={"constitution": 7},
    )
    base.update(stat_overrides)
    stats = Stats(**base)
    return Statblock(name="x", display_name="X", classification={}, stats=stats)


def make_creature(**stat_overrides):
    return Creature(statblock=make_statblock(**stat_overrides), instance_name="x", side="monsters")


class ScriptedDice:
    def __init__(self, values):
        self._values = list(values)

    def roll(self, code):
        return self._values.pop(0)


def test_hp_initialized_from_average_at_construction():
    c = make_creature(hp_average=44)
    assert c.hp == 44


def test_hp_remaining_and_bloodied_and_down_boundaries():
    c = make_creature(hp_average=40)
    c.current_damage = 0
    assert c.hp_remaining == 40 and not c.is_bloodied and not c.is_down
    c.current_damage = 20
    assert c.hp_remaining == 20 and c.is_bloodied and not c.is_down  # exactly half = bloodied
    c.current_damage = 39
    assert c.hp_remaining == 1 and c.is_bloodied and not c.is_down
    c.current_damage = 40
    assert c.hp_remaining == 0 and c.is_down
    c.current_damage = 999  # overkill never goes negative
    assert c.hp_remaining == 0


def test_is_dead_at_three_death_save_failures():
    c = make_creature()
    c.death_save_failures = 2
    assert not c.is_dead
    c.death_save_failures = 3
    assert c.is_dead


def test_is_stabilized_at_three_successes_unless_dead():
    c = make_creature()
    c.death_save_successes = 3
    assert c.is_stabilized
    c.death_save_failures = 3
    assert c.is_dead
    assert not c.is_stabilized  # dead takes precedence


def test_roll_hp_average_mode_uses_stat_average():
    c = make_creature(hp_average=100, hit_dice="12d10+48")
    c.roll_hp(Resolver(ScriptedDice([999])), mode="average")
    assert c.hp == 100  # dice never consulted


def test_roll_hp_rolled_mode_uses_hit_dice():
    c = make_creature(hp_average=100, hit_dice="12d10+48")
    c.roll_hp(Resolver(ScriptedDice([77])), mode="rolled")
    assert c.hp == 77


def test_roll_hp_rolled_mode_clamps_to_minimum_one():
    c = make_creature(hp_average=100, hit_dice="1d4-10")
    c.roll_hp(Resolver(ScriptedDice([-5])), mode="rolled")
    assert c.hp == 1


def test_roll_hp_rolled_mode_falls_back_to_average_when_no_hit_dice():
    c = make_creature(hp_average=50, hit_dice=None)
    c.roll_hp(Resolver(ScriptedDice([])), mode="rolled")
    assert c.hp == 50


def test_save_mod_reads_from_statblock_stats():
    c = make_creature()
    assert c.save_mod("constitution") == 7        # explicit override
    assert c.save_mod("wisdom") == c.statblock.stats.modifier("wisdom")


def test_place_sets_both_start_and_live_position():
    c = make_creature()
    c.place(5, 7)
    assert c.coord == (5, 7)
    assert (c.start_x, c.start_y) == (5, 7)


def test_coord_is_none_when_unplaced():
    c = make_creature()
    assert c.coord is None


def test_conditions_add_has_condition_remove():
    c = make_creature()
    assert not c.has_condition("grappled")
    c.add_condition(ConditionInstance(name="grappled", source="otyugh", escape_dc=13))
    assert c.has_condition("grappled")
    assert c.condition("grappled").escape_dc == 13
    c.remove_condition("grappled")
    assert not c.has_condition("grappled")


def test_add_condition_is_idempotent_for_same_name():
    c = make_creature()
    c.add_condition(ConditionInstance(name="grappled", source="a"))
    c.add_condition(ConditionInstance(name="grappled", source="b"))  # does not replace
    assert len(c.conditions) == 1
    assert c.condition("grappled").source == "a"


def test_reset_state_clears_everything_and_restores_resources():
    sb = make_statblock()
    sb = Statblock(name=sb.name, display_name=sb.display_name, classification=sb.classification,
                   stats=sb.stats, resources={"ki": Resource(name="ki", uses=5, per="encounter")})
    c = Creature(statblock=sb, instance_name="monk", side="party")
    c.place(3, 4)
    c.current_damage = 10
    c.damage_total = 10
    c.add_condition(ConditionInstance(name="prone"))
    c.death_save_failures = 2
    c.trial_scratch["x"] = 1
    c.round_scratch["y"] = 1
    c.turn_scratch["z"] = 1
    c.x, c.y = 9, 9  # simulate having moved mid-trial

    c.reset_state()

    assert c.current_damage == 0
    assert c.damage_total == 0
    assert c.conditions == []
    assert c.death_save_failures == 0
    assert c.death_save_successes == 0
    assert c.trial_scratch == {} and c.round_scratch == {} and c.turn_scratch == {}
    assert c.coord == (3, 4)          # back to spawn, not (9, 9)
    assert c.resources["ki"] == 5     # restored to max


def test_has_tag():
    c = Creature(statblock=make_statblock(), instance_name="x", side="party", tags=("tank", "striker"))
    assert c.has_tag("tank")
    assert not c.has_tag("skirmisher")


def test_speed_and_reach_proxy_statblock_stats():
    c = make_creature(speed=40, reach=10)
    assert c.speed_ft == 40
    assert c.reach_ft == 10
