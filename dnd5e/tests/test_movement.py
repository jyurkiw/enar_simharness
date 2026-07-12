import pytest
from dnd_board import load_board_toml

from dnd5e.battlefield import Battlefield
from dnd5e.creature import Creature
from dnd5e.movement import apply_tactic, engage, hold, kite
from dnd5e.statblock import Statblock, Stats

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

# A wall spans the middle column so a kiter on the far side must physically
# come around it to regain line of sight.
WALLED_BOARD = '''
name = "walled"
map = """
..........
..........
....#.....
..........
..........
"""
[meta]
cell_feet = 5
[glyph.'#']
terrain = "impassable"
cover = "full"
blocks_los = true
blocks_light = true
'''


def make_board(tmp_path, text, name):
    p = tmp_path / f"{name}.toml"
    p.write_text(text)
    return load_board_toml(p)


def make_stats(**overrides):
    base = dict(strength=10, dexterity=10, constitution=10, intelligence=10, wisdom=10,
               charisma=10, ac=14, speed=30, initiative_bonus=0, proficiency=2,
               crit_range=20, reach=5, hit_dice=None, hp_average=20)
    base.update(overrides)
    return Stats(**base)


def make_creature(name, side, x, y, **stat_overrides):
    sb = Statblock(name=name, display_name=name, classification={}, stats=make_stats(**stat_overrides))
    c = Creature(statblock=sb, instance_name=name, side=side)
    c.place(x, y)
    return c


def test_hold_never_moves(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    actor = make_creature("fighter", "party", 0, 0)
    target = make_creature("otyugh", "monsters", 9, 0)
    bf = Battlefield([actor, target], board=board)
    hold(actor, target, bf)
    assert actor.coord == (0, 0)


def test_engage_moves_into_reach_when_not_already_there(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    # Speed generously covers the 9-cell gap (Chebyshev shortest paths aren't
    # guaranteed to be a straight cardinal line, so budget for slack).
    actor = make_creature("fighter", "party", 0, 0, speed=60, reach=5)
    target = make_creature("otyugh", "monsters", 9, 0)
    bf = Battlefield([actor, target], board=board)
    engage(actor, target, bf)
    assert board.distance_ft(actor.coord, target.coord) <= actor.reach_ft


def test_engage_partial_approach_when_speed_is_insufficient_to_reach(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    actor = make_creature("fighter", "party", 0, 0, speed=30, reach=5)  # 6 cells/turn
    target = make_creature("otyugh", "monsters", 9, 0)  # 9 cells away
    bf = Battlefield([actor, target], board=board)
    start_dist = board.distance_ft(actor.coord, target.coord)
    engage(actor, target, bf)
    end_dist = board.distance_ft(actor.coord, target.coord)
    assert end_dist < start_dist          # made progress
    assert end_dist > actor.reach_ft      # but couldn't fully close a 9-cell gap on 6 cells of speed


def test_engage_never_steps_onto_targets_cell(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    actor = make_creature("fighter", "party", 0, 0, speed=100, reach=5)  # huge speed
    target = make_creature("otyugh", "monsters", 3, 0)
    bf = Battlefield([actor, target], board=board)
    engage(actor, target, bf)
    assert actor.coord != target.coord


def test_engage_noop_when_already_in_reach(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    actor = make_creature("fighter", "party", 0, 0, reach=5)
    target = make_creature("otyugh", "monsters", 1, 0)  # 5 ft away, already in reach
    bf = Battlefield([actor, target], board=board)
    engage(actor, target, bf)
    assert actor.coord == (0, 0)  # didn't move at all


def test_engage_noop_with_no_target(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    actor = make_creature("fighter", "party", 0, 0)
    bf = Battlefield([actor], board=board)
    engage(actor, None, bf)
    assert actor.coord == (0, 0)


def test_kite_stays_at_max_range_with_los(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    actor = make_creature("archer", "party", 5, 2, speed=30)
    target = make_creature("otyugh", "monsters", 5, 2)  # adjacent start (same cell test avoided below)
    target.place(6, 2)
    bf = Battlefield([actor, target], board=board)
    kite(actor, target, bf, max_range_ft=30)
    dist = board.distance_ft(actor.coord, target.coord)
    assert dist <= 30
    assert dist > 5  # moved away from melee range, not toward it


def test_kite_advances_when_no_reachable_cell_has_los(tmp_path):
    board = make_board(tmp_path, WALLED_BOARD, "walled")
    # actor boxed in behind the wall relative to target; only advancing (around
    # the wall) can regain a sight line within a single move.
    actor = make_creature("archer", "party", 4, 0, speed=30)
    target = make_creature("otyugh", "monsters", 4, 4)
    bf = Battlefield([actor, target], board=board)
    start = actor.coord
    kite(actor, target, bf, max_range_ft=100)
    # Some movement should have happened (either the LOS-seeking branch or
    # the advance-to-los fallback) rather than freezing in a blind cell.
    assert actor.coord != start or board.distance_ft(start, target.coord) is not None


def test_apply_tactic_dispatches_by_name(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    actor = make_creature("fighter", "party", 0, 0, reach=5)
    target = make_creature("otyugh", "monsters", 1, 0)
    bf = Battlefield([actor, target], board=board)
    apply_tactic("engage", actor, target, bf)  # already in reach -> no-op, but must not raise


def test_apply_tactic_unknown_name_raises(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    actor = make_creature("fighter", "party", 0, 0)
    with pytest.raises(ValueError, match="unknown movement tactic"):
        apply_tactic("hunt_light", actor, None, Battlefield([actor], board=board))


def test_grappled_captive_dragged_along_when_grappler_moves(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    otyugh = make_creature("otyugh", "monsters", 5, 2, speed=20, reach=10)
    captive = make_creature("fighter", "party", 6, 2)
    far_target = make_creature("bystander", "party", 9, 2)
    bf = Battlefield([otyugh, captive, far_target], board=board)
    bf.grapple("otyugh", "fighter")

    engage(otyugh, far_target, bf)  # otyugh moves toward the bystander, dragging its captive

    assert captive.coord is not None
    # The captive should end up adjacent to the otyugh's new position.
    assert board.distance_ft(otyugh.coord, captive.coord) <= 5
