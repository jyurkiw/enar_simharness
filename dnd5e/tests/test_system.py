import pytest
from dieroller import Dice
from dnd_board import load_board_toml
from simharness.ledger import Ledger
from simharness.plugin import TrialContext
from simharness.runner import TrialRunner

from dnd5e import conditions
from dnd5e.creature import ConditionInstance
from dnd5e.statblock import Ability, Behavior, MultiattackOption, Statblock, Stats
from dnd5e.system import Dnd5eSystem, RosterSlot

OPEN_BOARD = '''
name = "open"
map = """
..........
..........
"""
[meta]
cell_feet = 5
'''


class ScriptedDice:
    def __init__(self, values):
        self._values = list(values)

    def roll(self, code):
        return self._values.pop(0)

    def spawn(self, n):
        return [self]  # not used by direct system.py tests


def make_board(tmp_path):
    p = tmp_path / "board.toml"
    p.write_text(OPEN_BOARD)
    return load_board_toml(p)


def make_stats(**overrides):
    base = dict(strength=16, dexterity=11, constitution=19, intelligence=6, wisdom=13,
               charisma=6, ac=14, speed=30, initiative_bonus=0, proficiency=3,
               crit_range=20, reach=5, hit_dice="2d10+4", hp_average=20)
    base.update(overrides)
    return Stats(**base)


def attacker_statblock(name, *, to_hit=6, damage="1d8+3", multiattack_actions=("hit",),
                       action_priority=(), **stat_overrides):
    abilities = {"hit": Ability(name="hit", kind="attack", to_hit=to_hit, damage=damage,
                                damage_type="slashing")}
    multiattack = {}
    if multiattack_actions:
        multiattack["standard"] = MultiattackOption(name="standard", actions=multiattack_actions, priority=0)
    return Statblock(name=name, display_name=name, classification={}, stats=make_stats(**stat_overrides),
                     abilities=abilities, multiattack=multiattack,
                     behavior=Behavior(action_priority=action_priority))


def make_ctx(dice_values, trials=1, max_rounds=5):
    return TrialContext(dice=ScriptedDice(dice_values), ledger=Ledger(names=[], side_of={}),
                        trial_index=0, max_rounds=max_rounds)


def build_system(board, *, max_rounds=5, hp_mode="average"):
    fighter = RosterSlot(statblock=attacker_statblock("fighter", hp_average=30), instance_name="fighter",
                         side="party", start=(0, 0))
    otyugh = RosterSlot(statblock=attacker_statblock("otyugh", hp_average=20, to_hit=6, damage="1d8+3"),
                        instance_name="otyugh", side="monsters", start=(1, 0))
    return Dnd5eSystem(board=board, roster=[fighter, otyugh], max_rounds=max_rounds, hp_mode=hp_mode)


def test_setup_trial_places_creatures_rolls_hp_and_initiative(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    # 2 creatures: initiative rolls (1d20 each), no hp rolling in average mode.
    ctx = make_ctx([15, 10])  # fighter rolls 15, otyugh rolls 10 -> fighter first
    system.setup_trial(ctx)
    assert set(ctx.game.creatures) == {"fighter", "otyugh"}
    assert ctx.game.turn_order == ["fighter", "otyugh"]
    assert ctx.game.creatures["fighter"].hp == 30  # average mode
    assert ctx.game.creatures["fighter"].coord == (0, 0)
    assert ctx.game.creatures["otyugh"].coord == (1, 0)


def test_initiative_ties_keep_roster_order(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([10, 10])  # tie
    system.setup_trial(ctx)
    assert ctx.game.turn_order == ["fighter", "otyugh"]  # roster order preserved


def test_hp_mode_rolled_uses_hit_dice(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board, hp_mode="rolled")
    # setup_trial rolls HP before initiative (roster order), so: 2 hp rolls
    # (fighter, otyugh) then 2 initiative rolls.
    ctx = make_ctx([9, 8, 15, 10])
    system.setup_trial(ctx)
    assert ctx.game.creatures["fighter"].hp == 9
    assert ctx.game.creatures["otyugh"].hp == 8


def test_turn_order_returns_static_initiative_order(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    assert system.turn_order(ctx) == ["fighter", "otyugh"]


def test_take_turn_resolves_attack_against_preferred_target(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([15, 10, 12, 5])  # init x2, then attack roll(12) + damage(5)
    system.setup_trial(ctx)
    system.take_turn(ctx, "fighter")
    otyugh = ctx.game.creatures["otyugh"]
    assert otyugh.current_damage == 5  # 12+6=18 >= ac14 -> hit for 5


def test_take_turn_down_creature_rolls_death_save_instead_of_acting(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    fighter = ctx.game.creatures["fighter"]
    fighter.current_damage = 999  # down
    ctx.game.combat_ctx.resolver.dice._values = [15]  # death save roll: 15 -> success
    system.take_turn(ctx, "fighter")
    assert fighter.death_save_successes == 1
    assert fighter.death_save_failures == 0


def test_death_save_natural_20_revives_to_one_hp(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    fighter = ctx.game.creatures["fighter"]
    fighter.current_damage = 999
    ctx.game.combat_ctx.resolver.dice._values = [20]
    system.take_turn(ctx, "fighter")
    assert fighter.hp_remaining == 1
    assert not fighter.is_down


def test_death_save_natural_1_counts_as_two_failures(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    fighter = ctx.game.creatures["fighter"]
    fighter.current_damage = 999
    ctx.game.combat_ctx.resolver.dice._values = [1]
    system.take_turn(ctx, "fighter")
    assert fighter.death_save_failures == 2


def test_death_save_stops_at_dead_or_stabilized(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    fighter = ctx.game.creatures["fighter"]
    fighter.current_damage = 999
    fighter.death_save_failures = 3  # already dead
    ctx.game.combat_ctx.resolver.dice._values = []  # no roll consumed
    system.take_turn(ctx, "fighter")  # must not raise (no dice to pop)
    assert fighter.is_dead


def test_take_turn_skipped_while_stunned(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    fighter = ctx.game.creatures["fighter"]
    fighter.add_condition(ConditionInstance(name=conditions.STUNNED))
    otyugh = ctx.game.creatures["otyugh"]
    system.take_turn(ctx, "fighter")
    assert otyugh.current_damage == 0  # no attack happened


def test_multiattack_priority_selects_highest(tmp_path):
    board = make_board(tmp_path)
    sb = Statblock(
        name="x", display_name="x", classification={}, stats=make_stats(),
        abilities={
            "a": Ability(name="a", kind="attack", to_hit=99, damage="1d4"),
            "b": Ability(name="b", kind="attack", to_hit=99, damage="1d4"),
        },
        multiattack={
            "low": MultiattackOption(name="low", actions=("a",), priority=0),
            "high": MultiattackOption(name="high", actions=("b", "b"), priority=10),
        },
    )
    slot = RosterSlot(statblock=sb, instance_name="x", side="party", start=(0, 0))
    target_slot = RosterSlot(statblock=attacker_statblock("otyugh", hp_average=999),
                             instance_name="otyugh", side="monsters", start=(1, 0))
    system = Dnd5eSystem(board=board, roster=[slot, target_slot], max_rounds=1)
    ctx = make_ctx([15, 10, 20, 1, 20, 1])  # init x2, then 2 attacks (b, b) each hit+dmg
    system.setup_trial(ctx)
    system.take_turn(ctx, "x")
    otyugh = ctx.game.creatures["otyugh"]
    assert otyugh.current_damage == 2  # two "b" attacks (the high-priority option), 1 dmg each


def test_no_multiattack_falls_back_to_first_action_priority(tmp_path):
    board = make_board(tmp_path)
    sb = Statblock(
        name="x", display_name="x", classification={}, stats=make_stats(),
        abilities={"a": Ability(name="a", kind="attack", to_hit=99, damage="1d4")},
        multiattack={},
        behavior=Behavior(action_priority=("a",)),
    )
    slot = RosterSlot(statblock=sb, instance_name="x", side="party", start=(0, 0))
    target_slot = RosterSlot(statblock=attacker_statblock("otyugh", hp_average=999),
                             instance_name="otyugh", side="monsters", start=(1, 0))
    system = Dnd5eSystem(board=board, roster=[slot, target_slot], max_rounds=1)
    ctx = make_ctx([15, 10, 20, 3])
    system.setup_trial(ctx)
    system.take_turn(ctx, "x")
    assert ctx.game.creatures["otyugh"].current_damage == 3


def test_is_over_when_a_side_is_wiped(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    assert system.is_over(ctx) is False
    ctx.game.creatures["otyugh"].current_damage = 999
    assert system.is_over(ctx) is True


def test_finalize_trial_outcome_columns(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    ctx.game.creatures["otyugh"].current_damage = 999
    outcome = system.finalize_trial(ctx)
    assert outcome["down_otyugh"] == 1
    assert outcome["dead_otyugh"] == 0
    assert outcome["hp_remaining_otyugh"] == 0
    assert outcome["wiped_monsters"] == 1
    assert outcome["wiped_party"] == 0
    assert outcome["any_dead_monsters"] == 0
    assert outcome["poisoned_otyugh"] == 0
    assert outcome["any_poisoned_monsters"] == 0


def test_finalize_trial_reports_real_poisoned_state(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    ctx.game.creatures["fighter"].add_condition(ConditionInstance(name=conditions.POISONED))
    outcome = system.finalize_trial(ctx)
    assert outcome["poisoned_fighter"] == 1
    assert outcome["any_poisoned_party"] == 1
    assert outcome["any_poisoned_monsters"] == 0


def test_full_trial_via_trial_runner_end_to_end(tmp_path):
    """Integration proof: the whole pipeline (TrialRunner -> Dnd5eSystem ->
    Battlefield/CombatContext) runs to completion via the real GameSystem
    protocol with a real seeded Dice, not scripted values."""
    board = make_board(tmp_path)
    system = build_system(board, max_rounds=10)
    runner = TrialRunner(system, seed=20260711, max_rounds=10, names=["fighter", "otyugh"],
                         side_of={"fighter": "party", "otyugh": "monsters"})
    ledger = runner.run(trials=200)
    assert len(ledger.rows) == 200
    for row in ledger.rows:
        assert "wiped_party" in row and "wiped_monsters" in row
        assert row["hp_remaining_fighter"] >= 0
        assert row["hp_remaining_otyugh"] >= 0
    # With both sides attacking each other every round for up to 10 rounds,
    # at least one side should be wiped in the overwhelming majority of trials.
    any_wipe = sum(1 for r in ledger.rows if r["wiped_party"] or r["wiped_monsters"])
    assert any_wipe > 150
