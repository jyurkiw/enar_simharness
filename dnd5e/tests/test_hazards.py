"""P0 — the fire hazard field (sims/opera_house PLAN). A persistent damaging
region that ticks on whoever starts a turn in it; the burning building's core."""

import pytest
from dnd_board import load_board_toml
from simharness.ledger import Ledger
from simharness.plugin import TrialContext

from dnd5e.hazards import Hazard
from dnd5e.statblock import Ability, Behavior, EffectCall, MultiattackOption, Statblock, Stats
from dnd5e.system import Dnd5eSystem, RosterSlot

BOARD = '''
name = "room"
map = """
............
............
............
............
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


def board(tmp_path):
    p = tmp_path / "room.toml"
    p.write_text(BOARD)
    return load_board_toml(p)


def stats(**kw):
    base = dict(strength=12, dexterity=12, constitution=12, intelligence=10, wisdom=10,
                charisma=10, ac=12, speed=30, initiative_bonus=0, proficiency=2,
                crit_range=20, reach=5, hit_dice=None, hp_average=30)
    base.update(kw)
    return Stats(**base)


def dummy(name, **kw):
    hit = Ability(name="hit", kind="attack", to_hit=4, damage="1d6", damage_type="bludgeoning",
                  requires_sight=False)
    return Statblock(name=name, display_name=name, classification={}, stats=stats(**kw),
                     abilities={"hit": hit},
                     multiattack={"standard": MultiattackOption(name="standard", actions=("hit",))},
                     behavior=Behavior(tactic="hold"))


def make_ctx(values):
    return TrialContext(dice=ScriptedDice(values), ledger=Ledger(names=[], side_of={}),
                        trial_index=0, max_rounds=3)


def build(tmp_path, **kw):
    b = board(tmp_path)
    system = Dnd5eSystem(board=b, max_rounds=3, roster=[
        RosterSlot(statblock=dummy("a", **kw), instance_name="a", side="party", start=(1, 1)),
        RosterSlot(statblock=dummy("b"), instance_name="b", side="monsters", start=(9, 3)),
    ])
    ctx = make_ctx([10, 10])          # initiative rolls
    system.setup_trial(ctx)
    return system, ctx


def test_standing_in_a_hazard_burns_at_turn_start(tmp_path):
    system, ctx = build(tmp_path)
    a = ctx.game.creatures["a"]
    ctx.game.battlefield.hazards.add(Hazard(center=(1, 1), radius_ft=10, damage="2d6", damage_type="fire"))
    ctx.game.combat_ctx.round_index = 1

    ctx.dice._values = [7]            # 2d6 -> 7 fire
    system._tick_hazards(a, ctx.game, ctx)

    assert a.current_damage == 7


def test_a_creature_outside_the_footprint_does_not_burn(tmp_path):
    system, ctx = build(tmp_path)
    b = ctx.game.creatures["b"]       # at (9, 3), far from the fire at (1, 1)
    ctx.game.battlefield.hazards.add(Hazard(center=(1, 1), radius_ft=10, damage="2d6"))
    ctx.game.combat_ctx.round_index = 1

    system._tick_hazards(b, ctx.game, ctx)

    assert b.current_damage == 0


def test_environmental_fire_is_lethal_even_when_the_side_subdues(tmp_path):
    # A subduing monster side must NOT make fire nonlethal — fire has no side.
    b = board(tmp_path)
    system = Dnd5eSystem(board=b, max_rounds=1, subduing_side="monsters", roster=[
        RosterSlot(statblock=dummy("pc", hp_average=5), instance_name="pc", side="party", start=(1, 1)),
        RosterSlot(statblock=dummy("guard"), instance_name="guard", side="monsters", start=(9, 3)),
    ])
    ctx = make_ctx([10, 10])
    system.setup_trial(ctx)
    pc = ctx.game.creatures["pc"]
    ctx.game.battlefield.hazards.add(Hazard(center=(1, 1), radius_ft=10, damage="2d6"))
    ctx.game.combat_ctx.round_index = 1

    ctx.dice._values = [99]           # massive overkill fire
    system._tick_hazards(pc, ctx.game, ctx)

    assert pc.is_down and pc.is_dead  # fire kills; subdue only spares guard clubs


def test_hazard_expires(tmp_path):
    system, ctx = build(tmp_path)
    a = ctx.game.creatures["a"]
    ctx.game.battlefield.hazards.add(Hazard(center=(1, 1), radius_ft=10, damage="2d6", expires_round=2))

    ctx.round_index = 2
    ctx.dice._values = [7]
    system._tick_hazards(a, ctx.game, ctx)
    assert a.current_damage == 7      # still active on round 2

    ctx.round_index = 3
    system._tick_hazards(a, ctx.game, ctx)   # expired -> no dice drawn, no damage
    assert a.current_damage == 7


def test_create_hazard_effect_places_a_fire_that_burns_the_next_creature(tmp_path):
    from dnd5e.effects import EffectScope, apply_effect
    system, ctx = build(tmp_path)
    a, b = ctx.game.creatures["a"], ctx.game.creatures["b"]
    ctx.game.combat_ctx.round_index = 1
    # `a` drops a fire on `b` (its position), lasting 1 round.
    scope = EffectScope(ctx=ctx.game.combat_ctx, source=a, target=b)
    apply_effect(EffectCall(effect="create_hazard",
                            args={"radius": 10, "damage": "4d6", "duration": 1, "name": "debris"}), scope)

    assert len(ctx.game.battlefield.hazards.hazards) == 1
    ctx.dice._values = [14]
    system._tick_hazards(b, ctx.game, ctx)
    assert b.current_damage == 14
