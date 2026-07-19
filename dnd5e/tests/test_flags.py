import pytest

from dnd5e.flags import FlagBag


def test_set_and_has_round_flag():
    bag = FlagBag()
    assert not bag.has("enemy_crit")
    bag.set("enemy_crit", scope="round")
    assert bag.has("enemy_crit")


def test_set_and_has_trial_flag():
    bag = FlagBag()
    bag.set("slam_both_failed", scope="trial")
    assert bag.has("slam_both_failed")


def test_unknown_scope_raises():
    bag = FlagBag()
    with pytest.raises(ValueError, match="unknown flag scope"):
        bag.set("x", scope="bogus")


def test_clear_round_only_clears_round_flags():
    bag = FlagBag()
    bag.set("a", scope="round")
    bag.set("b", scope="trial")
    bag.clear_round()
    assert not bag.has("a")
    assert bag.has("b")


def test_clear_all_clears_everything():
    bag = FlagBag()
    bag.set("a", scope="round")
    bag.set("b", scope="trial")
    bag.clear_all()
    assert not bag.has("a")
    assert not bag.has("b")
