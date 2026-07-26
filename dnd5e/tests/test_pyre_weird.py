"""P2 — the Pyre Weird: the grapple -> drain -> Consume chain, Pyre's Due
(instant death while grappled), and Guttering (starves outside fire).
See sims/opera_house/PLAN.md."""

import pytest
from dnd_board import load_board_toml
from simharness.ledger import Ledger
from simharness.plugin import TrialContext

from dnd5e import conditions
from dnd5e.hazards import Hazard
from dnd5e.loader import load_creature
from dnd5e.statblock import (Ability, Behavior, EffectCall, MultiattackOption, Statblock, Stats)
from dnd5e.system import Dnd5eSystem, RosterSlot
import dnd5e_data

BOARD = '''
name = "room"
map = """
..............
..............
..............
"""
[meta]
cell_feet = 5
'''


class ScriptedDice:
    def __init__(self, values): self._values = list(values)
    def roll(self, code): return self._values.pop(0)
    def spawn(self, n): return [self]


def board(tmp_path):
    p = tmp_path / "room.toml"; p.write_text(BOARD)
    return load_board_toml(p)


def weird_statblock():
    return load_creature(dnd5e_data.data_path("monsters", "pyre_weird.toml"))


def pc_statblock(name, level=6, hp=45):
    hit = Ability(name="hit", kind="attack", to_hit=6, damage="1d8+3",
                  damage_type="slashing", requires_sight=False)
    return Statblock(name=name, display_name=name, classification={"level": level},
                     stats=Stats(strength=14, dexterity=14, constitution=14, intelligence=10,
                                 wisdom=12, charisma=10, ac=16, speed=30, initiative_bonus=2,
                                 proficiency=3, crit_range=20, reach=5, hit_dice=None,
                                 hp_average=hp),
                     abilities={"hit": hit},
                     multiattack={"m": MultiattackOption(name="m", actions=("hit",))},
                     behavior=Behavior(tactic="hold"))


def build(tmp_path, *, hit_dice_spent=0, max_rounds=5, subduing_side=None):
    b = board(tmp_path)
    system = Dnd5eSystem(board=b, max_rounds=max_rounds, hit_dice_spent=hit_dice_spent,
                         subduing_side=subduing_side, roster=[
        RosterSlot(statblock=weird_statblock(), instance_name="weird", side="monsters", start=(1, 1)),
        RosterSlot(statblock=pc_statblock("pc"), instance_name="pc", side="party", start=(2, 1)),
    ])
    ctx = TrialContext(dice=ScriptedDice([10, 5]), ledger=Ledger(names=[], side_of={}),
                       trial_index=0, max_rounds=max_rounds)
    ctx.round_index = 1
    system.setup_trial(ctx)
    return system, ctx


# ---- the statblock itself ----------------------------------------------------


def test_weird_is_fire_immune_cold_vulnerable_and_ungrappleable(tmp_path):
    system, ctx = build(tmp_path)
    weird, pc = ctx.game.creatures["weird"], ctx.game.creatures["pc"]
    cc = ctx.game.combat_ctx

    assert cc.deal(pc, weird, 20, "flame", damage_type="fire") == 0     # immune
    assert cc.deal(pc, weird, 20, "frost", damage_type="cold") == 40    # vulnerable
    cc.apply_condition(weird, conditions.GRAPPLED, source=pc, escape_dc=13)
    assert not weird.has_condition(conditions.GRAPPLED)                 # condition-immune


def test_weird_ignores_the_fire_it_lives_in(tmp_path):
    system, ctx = build(tmp_path)
    weird = ctx.game.creatures["weird"]
    ctx.game.battlefield.hazards.add(Hazard(center=(1, 1), radius_ft=10, damage="4d6",
                                            damage_type="fire"))
    system._tick_hazards(weird, ctx.game, ctx)
    assert weird.current_damage == 0


# ---- Hit Dice + the drain timer ---------------------------------------------


def test_hit_dice_seed_from_level_and_hit_dice_spent(tmp_path):
    system, ctx = build(tmp_path)
    assert ctx.game.creatures["pc"].hit_dice_remaining == 6     # level 6, none spent

    system2, ctx2 = build(tmp_path, hit_dice_spent=3)           # "spent half healing"
    assert ctx2.game.creatures["pc"].hit_dice_remaining == 3


def test_drain_burns_a_hit_die_and_satisfies_guttering(tmp_path):
    from dnd5e.effects import EffectScope, apply_effect
    system, ctx = build(tmp_path)
    weird, pc = ctx.game.creatures["weird"], ctx.game.creatures["pc"]
    scope = EffectScope(ctx=ctx.game.combat_ctx, source=weird, target=pc)

    apply_effect(EffectCall(effect="drain_hit_die", args={"amount": 1}), scope)

    assert pc.hit_dice_remaining == 5
    assert weird.turn_scratch["drained_hit_die"] is True     # fed, so it won't gutter


def test_consume_was_cut_the_weird_kills_by_damage_alone(tmp_path):
    """Consume (the 0-Hit-Dice finisher) was removed after firing zero times in
    three measurements: Constrict drops a victim to 0 HIT POINTS long before the
    drain reaches 0 HIT DICE, so Pyre's Due always got there first. The drain
    stays — its job is fear and attrition, not kills."""
    from dnd5e.behavior import BehaviorContext, select_multiattack
    system, ctx = build(tmp_path)
    weird, pc = ctx.game.creatures["weird"], ctx.game.creatures["pc"]
    assert "consume" not in weird.statblock.abilities
    assert "finish" not in weird.statblock.multiattack

    # Even a fully drained captive just keeps getting drained — no finisher.
    ctx.game.combat_ctx.apply_condition(pc, conditions.GRAPPLED, source=weird, escape_dc=13)
    pc.hit_dice_remaining = 0
    bctx = BehaviorContext(battlefield=ctx.game.battlefield, round_index=1, turn_order=[],
                           flags=ctx.game.flags, resolver=ctx.game.combat_ctx.resolver)
    assert select_multiattack(weird, bctx).name == "drain_captive"


# ---- Pyre's Due --------------------------------------------------------------


def test_pyres_due_kills_a_captive_reduced_to_zero(tmp_path):
    system, ctx = build(tmp_path)
    weird, pc = ctx.game.creatures["weird"], ctx.game.creatures["pc"]
    cc = ctx.game.combat_ctx
    cc.apply_condition(pc, conditions.GRAPPLED, source=weird, escape_dc=13)

    cc.deal(weird, pc, 999, "constrict", damage_type="fire")

    assert pc.is_down and pc.is_dead          # no death saves, no corpse
    assert not pc.has_condition(conditions.GRAPPLED)   # released on death


def test_pyres_due_overrides_a_subduing_knockout(tmp_path):
    # A guard's merciful club still kills if a weird has hold of you.
    system, ctx = build(tmp_path, subduing_side="monsters")
    weird, pc = ctx.game.creatures["weird"], ctx.game.creatures["pc"]
    cc = ctx.game.combat_ctx
    cc.apply_condition(pc, conditions.GRAPPLED, source=weird, escape_dc=13)

    cc.deal(weird, pc, 999, "club", damage_type="bludgeoning")

    assert pc.is_dead


def test_a_free_pc_reduced_to_zero_is_not_killed_by_pyres_due(tmp_path):
    system, ctx = build(tmp_path)
    weird, pc = ctx.game.creatures["weird"], ctx.game.creatures["pc"]
    ctx.game.combat_ctx.deal(weird, pc, 50, "constrict", damage_type="fire")
    assert pc.is_down and not pc.is_dead      # ungrappled: ordinary death saves


# ---- Guttering ---------------------------------------------------------------


@pytest.mark.parametrize("save_roll, dies", [(2, True), (19, False)])
def test_guttering_kills_a_weird_that_ends_its_turn_outside_fire(tmp_path, save_roll, dies):
    system, ctx = build(tmp_path)
    weird = ctx.game.creatures["weird"]
    ctx.dice._values = [save_roll]            # the DC 13 Con save

    system._tick_sustain(weird, ctx.game, ctx)

    assert weird.is_dead is dies


def test_a_weird_standing_in_fire_never_gutters(tmp_path):
    system, ctx = build(tmp_path)
    weird = ctx.game.creatures["weird"]
    ctx.game.battlefield.hazards.add(Hazard(center=(1, 1), radius_ft=10, damage="2d6",
                                            damage_type="fire"))
    ctx.dice._values = []                     # any save roll would raise IndexError

    system._tick_sustain(weird, ctx.game, ctx)

    assert not weird.is_dead


def test_a_weird_that_fed_this_turn_never_gutters(tmp_path):
    system, ctx = build(tmp_path)
    weird = ctx.game.creatures["weird"]
    weird.turn_scratch["drained_hit_die"] = True
    ctx.dice._values = []                     # no save rolled — feeding sufficed

    system._tick_sustain(weird, ctx.game, ctx)

    assert not weird.is_dead
