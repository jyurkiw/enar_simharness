"""P1 — damage-type defenses (resistance / vulnerability / immunity) and
condition immunity. Needed for the Pyre elementals (fire-immune, cold-vuln,
un-grappleable) and so the fire field ignores them."""

import pytest
from dnd_board import load_board_toml

from dnd5e import conditions
from dnd5e.hazards import Hazard
from dnd5e.statblock import Ability, Behavior, MultiattackOption, Statblock, Stats
from dnd5e.system import Dnd5eSystem, RosterSlot
from simharness.ledger import Ledger
from simharness.plugin import TrialContext

BOARD = '''
name = "room"
map = """
..........
..........
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


def stats(**kw):
    base = dict(strength=12, dexterity=12, constitution=12, intelligence=10, wisdom=10,
                charisma=10, ac=12, speed=30, initiative_bonus=0, proficiency=2,
                crit_range=20, reach=5, hit_dice=None, hp_average=40)
    base.update(kw); return Stats(**base)


def sb(name, **kw):
    return Statblock(name=name, display_name=name, classification={}, stats=stats(**kw),
                     abilities={"hit": Ability(name="hit", kind="attack", to_hit=4, damage="1d6")},
                     multiattack={"m": MultiattackOption(name="m", actions=("hit",))},
                     behavior=Behavior(tactic="hold"))


def setup(tmp_path, **target_kw):
    b = board(tmp_path)
    system = Dnd5eSystem(board=b, max_rounds=1, roster=[
        RosterSlot(statblock=sb("atk"), instance_name="atk", side="monsters", start=(0, 0)),
        RosterSlot(statblock=sb("def", **target_kw), instance_name="def", side="party", start=(1, 0)),
    ])
    ctx = TrialContext(dice=ScriptedDice([10, 10]), ledger=Ledger(names=[], side_of={}),
                       trial_index=0, max_rounds=1)
    system.setup_trial(ctx)
    return system, ctx


@pytest.mark.parametrize("kw, dtype, dealt", [
    ({"resistances": frozenset({"fire"})}, "fire", 5),        # 10 -> 5
    ({"vulnerabilities": frozenset({"cold"})}, "cold", 20),   # 10 -> 20
    ({"immunities": frozenset({"fire"})}, "fire", 0),         # 10 -> 0
    ({}, "fire", 10),                                          # no defense
    ({"resistances": frozenset({"fire"})}, "cold", 10),       # wrong type, unaffected
])
def test_deal_scales_by_damage_type(tmp_path, kw, dtype, dealt):
    system, ctx = setup(tmp_path, **kw)
    atk, dfn = ctx.game.creatures["atk"], ctx.game.creatures["def"]
    out = ctx.game.combat_ctx.deal(atk, dfn, 10, "hit", damage_type=dtype)
    assert out == dealt
    assert dfn.current_damage == dealt


def test_fire_immune_creature_ignores_the_fire_field(tmp_path):
    system, ctx = setup(tmp_path, immunities=frozenset({"fire"}))
    dfn = ctx.game.creatures["def"]
    ctx.game.battlefield.hazards.add(Hazard(center=(1, 0), radius_ft=10, damage="2d6", damage_type="fire"))
    ctx.round_index = 1
    system._tick_hazards(dfn, ctx.game, ctx)   # in the fire, but immune
    assert dfn.current_damage == 0


def test_condition_immunity_blocks_the_grapple(tmp_path):
    system, ctx = setup(tmp_path, condition_immunities=frozenset({"grappled"}))
    atk, dfn = ctx.game.creatures["atk"], ctx.game.creatures["def"]
    ctx.game.combat_ctx.apply_condition(dfn, conditions.GRAPPLED, source=atk, escape_dc=13)
    assert not dfn.has_condition(conditions.GRAPPLED)
    assert ctx.game.battlefield.grappled_by("def") is None
