"""Integration tests for dnd5e_data's shadow_otyugh.toml + dnd5e_behaviors'
ShadowOtyughBrain (Task #55) — loads the real creature file (catching TOML
typos the smaller unit-test doubles elsewhere wouldn't) and exercises each
multiattack branch: retreat, drag_and_bite, hunt_light, grab_two, plus the
escape hatch's plan_movement (flee from the nearest light source, dragging
captives)."""

from __future__ import annotations

import dnd5e_data
import pytest
from dnd_board import load_board_toml

from dnd5e import escape_hatch
from dnd5e.battlefield import Aura, Battlefield
from dnd5e.behavior import BehaviorContext, select_multiattack, select_targets
from dnd5e.creature import ConditionInstance, Creature
from dnd5e.dice import Resolver
from dnd5e.flags import FlagBag
from dnd5e.loader import load_creature

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


@pytest.fixture(autouse=True)
def _clear_escape_hatch_cache():
    escape_hatch.clear_cache()
    yield
    escape_hatch.clear_cache()


def make_board(tmp_path):
    p = tmp_path / "board.toml"
    p.write_text(OPEN_BOARD)
    return load_board_toml(p)


def shadow_statblock():
    return load_creature(dnd5e_data.data_path("monsters", "shadow_otyugh.toml"))


class ScriptedDice:
    def __init__(self, values):
        self._values = list(values)

    def roll(self, code):
        return self._values.pop(0)


def make_creature(name, side, x, y, *, statblock=None, hp=None):
    sb = statblock or shadow_statblock()
    c = Creature(statblock=sb, instance_name=name, side=side)
    c.place(x, y)
    if hp is not None:
        c.hp = hp
    return c


def make_ctx(battlefield, *, dice_values=()):
    resolver = Resolver(ScriptedDice(list(dice_values)))
    return BehaviorContext(battlefield=battlefield, round_index=1, turn_order=[],
                           flags=FlagBag(), resolver=resolver)


def test_shadow_otyugh_loads_and_validates():
    sb = shadow_statblock()
    assert sb.behavior.custom == "python:dnd5e_behaviors.shadow_otyugh.ShadowOtyughBrain"
    assert set(sb.multiattack) == {"retreat", "drag_and_bite", "hunt_light", "grab_two"}


def test_bloodied_picks_retreat_regardless_of_grapple_state(tmp_path):
    board = make_board(tmp_path)
    shadow = make_creature("shadow_otyugh", "monsters", 0, 0, hp=150)
    shadow.current_damage = 100  # bloodied (75 remaining <= 75 half)
    fighter = make_creature("fighter", "party", 1, 0, statblock=shadow_statblock())  # stand-in enemy
    bf = Battlefield([shadow, fighter], board=board)
    bf.grapple("shadow_otyugh", "fighter")  # even while grappling, bloodied wins
    opt = select_multiattack(shadow, make_ctx(bf))
    assert opt.name == "retreat"


def test_grappling_anything_picks_drag_and_bite(tmp_path):
    board = make_board(tmp_path)
    shadow = make_creature("shadow_otyugh", "monsters", 0, 0)
    fighter = make_creature("fighter", "party", 1, 0)
    rogue = make_creature("rogue", "party", 2, 0)
    bf = Battlefield([shadow, fighter, rogue], board=board)
    bf.grapple("shadow_otyugh", "fighter")
    bf.grapple("shadow_otyugh", "rogue")  # even with 2 captives, never slam — see toml header note
    opt = select_multiattack(shadow, make_ctx(bf))
    assert opt.name == "drag_and_bite"


def test_ungrappled_light_source_picks_hunt_light(tmp_path):
    board = make_board(tmp_path)
    shadow = make_creature("shadow_otyugh", "monsters", 0, 0)
    torchbearer = make_creature("fighter", "party", 5, 0)
    torchbearer.add_condition(ConditionInstance(name="light_source", source="fighter"))
    bf = Battlefield([shadow, torchbearer], board=board)
    opt = select_multiattack(shadow, make_ctx(bf))
    assert opt.name == "hunt_light"


def test_grappled_light_source_does_not_trigger_hunt_light(tmp_path):
    board = make_board(tmp_path)
    shadow = make_creature("shadow_otyugh", "monsters", 0, 0)
    torchbearer = make_creature("fighter", "party", 5, 0)
    torchbearer.add_condition(ConditionInstance(name="light_source", source="fighter"))
    bf = Battlefield([shadow, torchbearer], board=board)
    bf.grapple("shadow_otyugh", "fighter")  # already grappled -> drag_and_bite wins, not hunt_light
    opt = select_multiattack(shadow, make_ctx(bf))
    assert opt.name == "drag_and_bite"


def test_nothing_grappled_no_light_not_bloodied_picks_grab_two(tmp_path):
    board = make_board(tmp_path)
    shadow = make_creature("shadow_otyugh", "monsters", 0, 0)
    fighter = make_creature("fighter", "party", 1, 0)
    bf = Battlefield([shadow, fighter], board=board)
    opt = select_multiattack(shadow, make_ctx(bf))
    assert opt.name == "grab_two"


def test_hunt_light_targets_resolve_to_the_light_source(tmp_path):
    board = make_board(tmp_path)
    sb = shadow_statblock()
    shadow = make_creature("shadow_otyugh", "monsters", 0, 0, statblock=sb)
    torchbearer = make_creature("fighter", "party", 5, 0)
    torchbearer.add_condition(ConditionInstance(name="light_source", source="fighter"))
    other = make_creature("rogue", "party", 3, 0)  # not the light source, should be ignored
    bf = Battlefield([shadow, torchbearer, other], board=board)
    # random-order roll over a single-element pool (just "fighter") each time.
    ctx = make_ctx(bf, dice_values=[1, 1])
    targets = select_targets(shadow, sb.abilities["bite_open"], ctx)
    assert [c.instance_name for c in targets] == ["fighter"]
    targets = select_targets(shadow, sb.abilities["tentacle_open"], ctx)
    assert [c.instance_name for c in targets] == ["fighter"]


def test_drag_and_bite_targets_bite_the_captive_and_tentacle_a_fresh_target(tmp_path):
    board = make_board(tmp_path)
    sb = shadow_statblock()
    shadow = make_creature("shadow_otyugh", "monsters", 0, 0, statblock=sb)
    captive = make_creature("fighter", "party", 1, 0)
    fresh = make_creature("rogue", "party", 2, 0)
    bf = Battlefield([shadow, captive, fresh], board=board)
    bf.grapple("shadow_otyugh", "fighter")
    # random-order roll over each single-element pool (bite's captive-only
    # set selector skips ordering entirely so needs none; tentacle's
    # non-set, single-candidate pool still draws one).
    ctx = make_ctx(bf, dice_values=[1])
    bite_targets = select_targets(shadow, sb.abilities["bite"], ctx)
    assert [c.instance_name for c in bite_targets] == ["fighter"]
    tentacle_targets = select_targets(shadow, sb.abilities["tentacle"], ctx)
    assert [c.instance_name for c in tentacle_targets] == ["rogue"]


def test_plan_movement_flees_from_nearest_light_dragging_captives(tmp_path):
    board = make_board(tmp_path)
    sb = shadow_statblock()
    handler = escape_hatch.resolve(sb.behavior.custom)

    shadow = make_creature("shadow_otyugh", "monsters", 5, 2, statblock=sb)
    captive = make_creature("fighter", "party", 5, 2)  # dragged along
    light = make_creature("wizard", "party", 0, 2)
    light.add_condition(ConditionInstance(name="light_source", source="wizard"))
    bf = Battlefield([shadow, captive, light], board=board)
    bf.grapple("shadow_otyugh", "fighter")

    from dnd5e.behavior import ConcreteScope
    ctx = make_ctx(bf)
    view = ConcreteScope(ctx, shadow)
    dest = handler.plan_movement(shadow, view)
    assert dest is not None
    # Fled away from the light (at x=0) — ends up farther along +x than it started.
    assert dest[0] > shadow.x


def test_plan_movement_none_when_not_grappling(tmp_path):
    board = make_board(tmp_path)
    sb = shadow_statblock()
    handler = escape_hatch.resolve(sb.behavior.custom)
    shadow = make_creature("shadow_otyugh", "monsters", 5, 2, statblock=sb)
    light = make_creature("wizard", "party", 0, 2)
    light.add_condition(ConditionInstance(name="light_source", source="wizard"))
    bf = Battlefield([shadow, light], board=board)
    from dnd5e.behavior import ConcreteScope
    ctx = make_ctx(bf)
    view = ConcreteScope(ctx, shadow)
    assert handler.plan_movement(shadow, view) is None


def test_plan_movement_none_when_grappling_but_no_light(tmp_path):
    board = make_board(tmp_path)
    sb = shadow_statblock()
    handler = escape_hatch.resolve(sb.behavior.custom)
    shadow = make_creature("shadow_otyugh", "monsters", 5, 2, statblock=sb)
    captive = make_creature("fighter", "party", 5, 2)
    bf = Battlefield([shadow, captive], board=board)
    bf.grapple("shadow_otyugh", "fighter")
    from dnd5e.behavior import ConcreteScope
    ctx = make_ctx(bf)
    view = ConcreteScope(ctx, shadow)
    assert handler.plan_movement(shadow, view) is None
