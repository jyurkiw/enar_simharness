"""The six engine primitives the Southern Gate Guard Cartel needed
(sims/guard_cartel). Grouped in one file because they landed as one change;
each is general and available to any creature:

  1. `grant_temp_hp` + temp-HP absorption in `CombatContext.deal` (Rally)
  2. `[resources.*] recharge = "5-6"` actually rolling (Rally's recharge)
  3. the `grant_speed_zero` condition grant (the Slinger's Low Bolo)
  4. the `save_ends_start_of_bearer_turn` clock (both bolos)
  5. `make_attack`'s `actor` / `bonus_damage` / `uses_reaction` args
     (Commander's Strike — an *ally* swings, on its own reaction)
  6. `[simulation] grapple_escape` (RAW 2024: escaping costs your action)
"""

import pytest
from dnd_board import load_board_toml
from simharness.ledger import Ledger
from simharness.plugin import TrialContext

from dnd5e import conditions, movement
from dnd5e.creature import Creature
from dnd5e.effects import EffectScope, apply_effect
from dnd5e.loader import build_statblock
from dnd5e.statblock import (Ability, Behavior, ConditionDef, EffectCall, MultiattackOption,
                             Resource, Statblock, Stats)
from dnd5e.system import Dnd5eSystem, RosterSlot

OPEN_BOARD = '''
name = "open"
map = """
..........
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
        return [self]


def make_board(tmp_path):
    p = tmp_path / "board.toml"
    p.write_text(OPEN_BOARD)
    return load_board_toml(p)


def make_stats(**overrides):
    base = dict(strength=16, dexterity=12, constitution=14, intelligence=10, wisdom=12,
                charisma=10, ac=13, speed=30, initiative_bonus=0, proficiency=2,
                crit_range=20, reach=5, hit_dice=None, hp_average=40)
    base.update(overrides)
    return Stats(**base)


def make_ctx(dice_values, max_rounds=5):
    return TrialContext(dice=ScriptedDice(dice_values), ledger=Ledger(names=[], side_of={}),
                        trial_index=0, max_rounds=max_rounds)


def simple_statblock(name, **kw):
    abilities = {"hit": Ability(name="hit", kind="attack", to_hit=5, damage="1d6+2",
                                damage_type="bludgeoning", requires_sight=False)}
    return Statblock(name=name, display_name=name, classification={}, stats=make_stats(**kw),
                     abilities=abilities,
                     multiattack={"standard": MultiattackOption(name="standard", actions=("hit",))})


# ---- 1. temporary hit points ------------------------------------------------


def test_grant_temp_hp_absorbs_damage_before_real_hp(tmp_path):
    board = make_board(tmp_path)
    system = Dnd5eSystem(board=board, max_rounds=1, roster=[
        RosterSlot(statblock=simple_statblock("a"), instance_name="a", side="party", start=(0, 0)),
        RosterSlot(statblock=simple_statblock("b"), instance_name="b", side="monsters", start=(1, 0)),
    ])
    ctx = make_ctx([10, 10])
    system.setup_trial(ctx)
    a, b = ctx.game.creatures["a"], ctx.game.creatures["b"]
    b.temp_hp = 7

    ctx.game.combat_ctx.deal(a, b, 10, "hit")

    assert b.temp_hp == 0
    assert b.current_damage == 3          # 7 soaked, 3 through
    assert b.damage_total == 10           # the attacker still dealt 10


def test_grant_temp_hp_does_not_stack_and_takes_the_higher(tmp_path):
    board = make_board(tmp_path)
    system = Dnd5eSystem(board=board, max_rounds=1, roster=[
        RosterSlot(statblock=simple_statblock("a"), instance_name="a", side="party", start=(0, 0)),
        RosterSlot(statblock=simple_statblock("b"), instance_name="b", side="monsters", start=(1, 0)),
    ])
    ctx = make_ctx([10, 10, 12, 4])       # initiative x2, then two Rally rolls
    system.setup_trial(ctx)
    a, b = ctx.game.creatures["a"], ctx.game.creatures["b"]
    scope = EffectScope(ctx=ctx.game.combat_ctx, source=a, target=b)

    apply_effect(EffectCall(effect="grant_temp_hp", args={"amount": "1d12"}), scope)
    assert b.temp_hp == 12
    apply_effect(EffectCall(effect="grant_temp_hp", args={"amount": "1d12"}), scope)
    assert b.temp_hp == 12                # the 4 does not replace the 12


# ---- 2. resource recharge ---------------------------------------------------


def rally_statblock(name):
    sb = simple_statblock(name)
    return Statblock(name=sb.name, display_name=sb.display_name, classification={}, stats=sb.stats,
                     abilities=sb.abilities, multiattack=sb.multiattack,
                     resources={"rally": Resource(name="rally", uses=1, recharge="5-6")})


@pytest.mark.parametrize("d6, expected", [(6, 1), (5, 1), (4, 0), (1, 0)])
def test_recharge_resource_rolls_at_start_of_its_owners_turn(tmp_path, d6, expected):
    board = make_board(tmp_path)
    system = Dnd5eSystem(board=board, max_rounds=1, roster=[
        RosterSlot(statblock=rally_statblock("a"), instance_name="a", side="party", start=(0, 0)),
        RosterSlot(statblock=simple_statblock("b"), instance_name="b", side="monsters", start=(1, 0)),
    ])
    ctx = make_ctx([10, 10])
    system.setup_trial(ctx)
    a = ctx.game.creatures["a"]
    a.resources["rally"] = 0              # spent
    ctx.dice._values = [d6]

    system._tick_recharges(a, ctx.game)

    assert a.resources["rally"] == expected


def test_recharge_does_not_roll_while_the_pool_is_still_full(tmp_path):
    board = make_board(tmp_path)
    system = Dnd5eSystem(board=board, max_rounds=1, roster=[
        RosterSlot(statblock=rally_statblock("a"), instance_name="a", side="party", start=(0, 0)),
        RosterSlot(statblock=simple_statblock("b"), instance_name="b", side="monsters", start=(1, 0)),
    ])
    ctx = make_ctx([10, 10])
    system.setup_trial(ctx)
    a = ctx.game.creatures["a"]
    ctx.dice._values = []                 # any roll here would raise IndexError

    system._tick_recharges(a, ctx.game)

    assert a.resources["rally"] == 1


# ---- 3. grant_speed_zero ----------------------------------------------------


def test_speed_zero_condition_pins_movement_speed_to_zero(tmp_path):
    board = make_board(tmp_path)
    bolo = ConditionDef(name="low_bolo", grants=(EffectCall(effect="grant_speed_zero"),))
    mover = Statblock(name="m", display_name="m", classification={}, stats=make_stats(),
                      conditions={"low_bolo": bolo})
    system = Dnd5eSystem(board=board, max_rounds=1, roster=[
        RosterSlot(statblock=mover, instance_name="m", side="party", start=(0, 0)),
        RosterSlot(statblock=simple_statblock("b"), instance_name="b", side="monsters", start=(9, 2)),
    ])
    ctx = make_ctx([10, 10])
    system.setup_trial(ctx)
    m = ctx.game.creatures["m"]
    bf = ctx.game.battlefield

    assert movement.speed_ft(m, bf) == 30
    ctx.game.combat_ctx.apply_condition(m, "low_bolo")
    assert movement.speed_ft(m, bf) == 0

    movement.engage(m, ctx.game.creatures["b"], bf)
    assert m.coord == (0, 0)              # rooted


# ---- 4. save-ends clock -----------------------------------------------------


def bolo_carrier(name):
    """A creature whose file defines a save-ends bolo condition."""
    sb = simple_statblock(name)
    cdef = ConditionDef(name="high_bolo", expires="save_ends_start_of_bearer_turn",
                        save_ability="strength", save_dc=13)
    return Statblock(name=sb.name, display_name=sb.display_name, classification={}, stats=sb.stats,
                     abilities=sb.abilities, multiattack=sb.multiattack, conditions={"high_bolo": cdef})


@pytest.mark.parametrize("d20, still_there", [(20, False), (1, True)])
def test_save_ends_clock_rolls_at_the_start_of_the_bearers_turn(tmp_path, d20, still_there):
    board = make_board(tmp_path)
    system = Dnd5eSystem(board=board, max_rounds=1, roster=[
        RosterSlot(statblock=bolo_carrier("a"), instance_name="a", side="party", start=(0, 0)),
        RosterSlot(statblock=simple_statblock("b"), instance_name="b", side="monsters", start=(1, 0)),
    ])
    ctx = make_ctx([10, 10])
    system.setup_trial(ctx)
    a = ctx.game.creatures["a"]
    scope = EffectScope(ctx=ctx.game.combat_ctx, source=ctx.game.creatures["b"], target=a)
    apply_effect(EffectCall(effect="attach_condition", args={"condition": "high_bolo"}), scope)

    instance = a.condition("high_bolo")
    assert (instance.expires, instance.save_ability, instance.save_dc) == \
        ("save_ends_start_of_bearer_turn", "strength", 13)

    ctx.dice._values = [d20]
    system._tick_save_ends(a, ctx.game)

    assert a.has_condition("high_bolo") is still_there


def test_save_ends_clock_requires_save_ability_and_dc_at_load():
    cfg = {
        "name": "x", "classification": {"cr": 1},
        "stats": {"strength": 10, "dexterity": 10, "constitution": 10, "intelligence": 10,
                  "wisdom": 10, "charisma": 10, "ac": 12, "speed": 30},
        "conditions": {"bolo": {"expires": "save_ends_start_of_bearer_turn"}},
    }
    with pytest.raises(ValueError, match="save_ability"):
        build_statblock(cfg, source="x.toml")


# ---- 5. make_attack: a commanded ALLY swings --------------------------------


def commander_statblock():
    """Commander's Strike: a utility action that makes an ally attack, on the
    ally's reaction, with an extra 1d8."""
    strike = Ability(
        name="commanders_strike", kind="utility", targets="allies", max_targets=1,
        effects=(EffectCall(effect="make_attack", args={
            "actor": "target", "ability": "hit", "bonus_damage": "1d8", "uses_reaction": True}),),
    )
    return Statblock(
        name="cmd", display_name="cmd", classification={}, stats=make_stats(),
        abilities={"commanders_strike": strike},
        multiattack={"standard": MultiattackOption(name="standard", actions=("commanders_strike",))},
        behavior=Behavior(tactic="hold"),
    )


def build_command_trial(tmp_path, dice):
    board = make_board(tmp_path)
    system = Dnd5eSystem(board=board, max_rounds=1, roster=[
        RosterSlot(statblock=commander_statblock(), instance_name="cmd", side="monsters", start=(0, 0)),
        RosterSlot(statblock=simple_statblock("mook"), instance_name="mook", side="monsters", start=(1, 0)),
        RosterSlot(statblock=simple_statblock("pc", hp_average=60), instance_name="pc",
                   side="party", start=(2, 0)),
    ])
    ctx = make_ctx(dice)
    system.setup_trial(ctx)
    return system, ctx


def test_make_attack_actor_makes_the_ALLY_swing_with_its_bonus_damage(tmp_path):
    # initiative x3, then: the MOOK's attack d20=18 (hits AC 13), "1d6+2"=4,
    # "1d8" rider=6. The commander never rolls a die of its own.
    system, ctx = build_command_trial(tmp_path, [15, 10, 5, 18, 4, 6])
    cmd, mook, pc = (ctx.game.creatures[n] for n in ("cmd", "mook", "pc"))

    system.take_turn(ctx, "cmd")

    assert pc.current_damage == 4 + 6             # the mook's weapon, plus the 1d8 rider
    assert mook.round_scratch["reaction_used"] is True
    assert cmd.current_damage == 0 and cmd.coord == (0, 0)


def test_make_attack_uses_reaction_refuses_a_second_strike_the_same_round(tmp_path):
    system, ctx = build_command_trial(tmp_path, [15, 10, 5, 18, 4, 6])
    cmd, mook, pc = (ctx.game.creatures[n] for n in ("cmd", "mook", "pc"))
    mook.round_scratch["reaction_used"] = True

    scope = EffectScope(ctx=ctx.game.combat_ctx, source=cmd, target=mook)
    apply_effect(EffectCall(effect="make_attack", args={
        "actor": "target", "ability": "hit", "bonus_damage": "1d8", "uses_reaction": True}), scope)

    assert pc.current_damage == 0                 # reaction already spent — nothing happened


# ---- bonus: a melee weapon can't reach across the board ---------------------


def test_melee_only_attack_cannot_resolve_outside_its_reach(tmp_path):
    """Found via the Constable, which holds position 40 ft back to issue orders
    and was landing longsword hits from there: an ability with no `range_normal`
    fell into the ranged branch, which has no band to gate on."""
    board = make_board(tmp_path)
    system = Dnd5eSystem(board=board, max_rounds=1, roster=[
        RosterSlot(statblock=simple_statblock("a"), instance_name="a", side="party", start=(0, 0)),
        RosterSlot(statblock=simple_statblock("b"), instance_name="b", side="monsters", start=(9, 2)),
    ])
    ctx = make_ctx([10, 10])
    system.setup_trial(ctx)
    a, b = ctx.game.creatures["a"], ctx.game.creatures["b"]
    melee = a.statblock.abilities["hit"]

    out = ctx.game.combat_ctx.attack(a, b, bonus=99, damage="1d6+2", ability=melee)
    assert out.hit is False and out.damage == 0

    b.place(1, 0)                                  # step into reach
    ctx.dice._values = [10, 4]
    out = ctx.game.combat_ctx.attack(a, b, bonus=99, damage="1d6+2", ability=melee)
    assert out.hit is True


# ---- 6. grapple escape costs an action --------------------------------------


def test_grapple_escape_is_off_by_default(tmp_path):
    board = make_board(tmp_path)
    system = Dnd5eSystem(board=board, max_rounds=1, roster=[
        RosterSlot(statblock=simple_statblock("pc"), instance_name="pc", side="party", start=(0, 0)),
        RosterSlot(statblock=simple_statblock("grappler"), instance_name="grappler",
                   side="monsters", start=(1, 0)),
    ])
    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    pc, grappler = ctx.game.creatures["pc"], ctx.game.creatures["grappler"]
    ctx.game.combat_ctx.apply_condition(pc, conditions.GRAPPLED, source=grappler, escape_dc=13)

    ctx.dice._values = [18, 4]                    # would be the PC's attack, not an escape
    system.take_turn(ctx, "pc")

    assert pc.has_condition(conditions.GRAPPLED)  # never even tried
    assert grappler.current_damage > 0            # it attacked instead


def grapple_trial(tmp_path, *, payoff_at):
    """A PC held by `grappler`, with a second enemy (the grapple's payoff
    piece) parked at `payoff_at`."""
    board = make_board(tmp_path)
    system = Dnd5eSystem(board=board, max_rounds=1, grapple_escape=True, roster=[
        RosterSlot(statblock=simple_statblock("pc"), instance_name="pc", side="party", start=(0, 0)),
        RosterSlot(statblock=simple_statblock("grappler"), instance_name="grappler",
                   side="monsters", start=(1, 0)),
        RosterSlot(statblock=simple_statblock("payoff"), instance_name="payoff",
                   side="monsters", start=payoff_at),
    ])
    ctx = make_ctx([15, 10, 5])
    system.setup_trial(ctx)
    pc, grappler = ctx.game.creatures["pc"], ctx.game.creatures["grappler"]
    ctx.game.combat_ctx.apply_condition(pc, conditions.GRAPPLED, source=grappler, escape_dc=13)
    return system, ctx, pc, grappler


@pytest.mark.parametrize("d20, escaped", [(18, True), (2, False)])
def test_grapple_escape_costs_the_action_win_or_lose(tmp_path, d20, escaped):
    system, ctx, pc, grappler = grapple_trial(tmp_path, payoff_at=(2, 0))   # 10 ft away

    ctx.dice._values = [d20]                      # exactly one roll: the escape check
    system.take_turn(ctx, "pc")

    assert pc.has_condition(conditions.GRAPPLED) is not escaped
    assert grappler.current_damage == 0           # the turn went on the escape, not an attack


def test_grapple_escape_is_declined_when_only_the_grappler_is_close(tmp_path):
    # Nothing but the grappler within 10 ft: Speed 0 costs a melee PC nothing it
    # cares about, so it keeps swinging rather than burning a turn to break free.
    system, ctx, pc, grappler = grapple_trial(tmp_path, payoff_at=(9, 2))

    ctx.dice._values = [18, 4]                    # an attack, not an escape check
    system.take_turn(ctx, "pc")

    assert pc.has_condition(conditions.GRAPPLED)
    assert grappler.current_damage > 0
