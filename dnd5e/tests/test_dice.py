import pytest

from dnd5e.dice import AttackRoll, Resolver, crit_code, die_maximum, split_damage


class ScriptedDice:
    """Returns a fixed sequence of results regardless of the roll code, so
    d20 advantage/disadvantage/crit-boundary logic can be tested without
    depending on real randomness."""

    def __init__(self, values):
        self._values = list(values)

    def roll(self, code):
        return self._values.pop(0)


def test_crit_code_doubles_leading_dice_count():
    assert crit_code("2d8+3") == "4d8+3"
    assert crit_code("1d6") == "2d6"
    assert crit_code("8d6") == "16d6"


def test_split_damage_separates_die_from_flat_modifiers():
    assert split_damage("1d8+4") == ("1d8", 4)
    assert split_damage("2d6-1") == ("2d6", -1)
    assert split_damage("1d8") == ("1d8", 0)


def test_die_maximum():
    assert die_maximum("1d8") == 8
    assert die_maximum("2d8") == 16
    assert die_maximum("3d6") == 18


def test_advantage_takes_the_higher_of_two_rolls():
    resolver = Resolver(ScriptedDice([5, 15]))
    out = resolver.attack(0, 10, advantage=True)
    assert out.natural == 15


def test_disadvantage_takes_the_lower_of_two_rolls():
    resolver = Resolver(ScriptedDice([5, 15]))
    out = resolver.attack(0, 10, disadvantage=True)
    assert out.natural == 5


def test_advantage_and_disadvantage_cancel_to_a_single_straight_roll():
    resolver = Resolver(ScriptedDice([12]))
    out = resolver.attack(0, 10, advantage=True, disadvantage=True)
    assert out.natural == 12


def test_natural_1_always_misses_regardless_of_bonus():
    resolver = Resolver(ScriptedDice([1]))
    out = resolver.attack(bonus=50, target_ac=1)
    assert out.natural == 1
    assert out.hit is False


def test_natural_20_always_hits_and_crits():
    resolver = Resolver(ScriptedDice([20]))
    out = resolver.attack(bonus=-50, target_ac=999)
    assert out.hit is True
    assert out.crit is True


def test_crit_range_below_20_still_crits():
    resolver = Resolver(ScriptedDice([19]))
    out = resolver.attack(bonus=0, target_ac=999, crit_range=19)
    assert out.crit is True
    assert out.hit is True  # a crit always hits


def test_meets_ac_exactly_hits():
    resolver = Resolver(ScriptedDice([10]))
    out = resolver.attack(bonus=5, target_ac=15)
    assert out.total == 15
    assert out.hit is True


def test_one_below_ac_misses():
    resolver = Resolver(ScriptedDice([10]))
    out = resolver.attack(bonus=4, target_ac=15)
    assert out.total == 14
    assert out.hit is False


def test_bonus_dice_add_and_penalty_dice_subtract_from_the_d20():
    # Bless (+1d4) and Bane (-1d4) both active nets to whatever the two dice sum to.
    resolver = Resolver(ScriptedDice([10, 3, 2]))  # d20=10, bonus d4=3, penalty d4=2
    out = resolver.attack(bonus=0, target_ac=0, bonus_dice=["1d4"], penalty_dice=["1d4"])
    assert out.total == 10 + 3 - 2


def test_save_meets_dc_succeeds():
    resolver = Resolver(ScriptedDice([10]))
    assert resolver.save(modifier=5, dc=15) is True


def test_save_below_dc_fails():
    resolver = Resolver(ScriptedDice([10]))
    assert resolver.save(modifier=4, dc=15) is False


def test_damage_rolls_the_code_as_given_when_not_a_crit():
    resolver = Resolver(ScriptedDice([7]))
    assert resolver.damage("2d8+3") == 7


def test_damage_doubles_dice_on_a_crit():
    calls = []

    class Recording(ScriptedDice):
        def roll(self, code):
            calls.append(code)
            return super().roll(code)

    resolver = Resolver(Recording([14]))
    resolver.damage("2d8+3", crit=True)
    assert calls == ["4d8+3"]


def test_great_weapon_fighting_rerolls_ones_and_twos_once():
    # 2d12+4 (greataxe rage): first die rolls 1 (reroll -> 9), second rolls 8 (no reroll).
    resolver = Resolver(ScriptedDice([1, 9, 8]))
    total = resolver.great_weapon("2d12+4")
    assert total == 9 + 8 + 4


def test_great_weapon_fighting_does_not_reroll_three_or_higher():
    resolver = Resolver(ScriptedDice([3, 8]))
    total = resolver.great_weapon("2d12+4")
    assert total == 3 + 8 + 4


def test_great_weapon_fighting_doubles_dice_count_on_crit():
    resolver = Resolver(ScriptedDice([5, 5]))  # 1d12 crit -> 2 dice rolled
    total = resolver.great_weapon("1d12+4", crit=True)
    assert total == 5 + 5 + 4


def test_resolver_roll_passthrough():
    resolver = Resolver(ScriptedDice([42]))
    assert resolver.roll("1d100") == 42
