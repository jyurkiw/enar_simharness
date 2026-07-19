from dnd_board import ObscurementField, Region, load_board_toml

from dnd5e.vision import cover_ac_bonus, has_full_cover, line_of_sight

# Column 2 has a wall (full cover, blocks LOS) at row 1; column 4 has a pillar
# (three-quarters cover, does NOT block LOS) at row 1. Observer/target
# endpoints always sit on open floor (rows 0/2) so no test uses an impassable
# cell as a position — only as an obstacle *between* two real positions.
BOARD_TOML = '''
name = "test_board"

map = """
.......
..#.o..
.......
"""

[meta]
cell_feet = 5

[glyph.'#']
terrain = "impassable"
cover = "full"
blocks_los = true
blocks_light = true

[glyph.'o']
terrain = "impassable"
cover = "three_quarters"
blocks_los = false
'''


def make_board(tmp_path):
    p = tmp_path / "board.toml"
    p.write_text(BOARD_TOML)
    return load_board_toml(p)


def test_clear_line_of_sight_across_open_floor(tmp_path):
    board = make_board(tmp_path)
    assert line_of_sight(board, (0, 0), (6, 0)) is True


def test_wall_blocks_line_of_sight(tmp_path):
    board = make_board(tmp_path)
    assert line_of_sight(board, (2, 0), (2, 2)) is False


def test_pillar_does_not_block_line_of_sight(tmp_path):
    board = make_board(tmp_path)
    assert line_of_sight(board, (4, 0), (4, 2)) is True


def test_cover_ac_bonus_zero_with_clear_path(tmp_path):
    board = make_board(tmp_path)
    assert cover_ac_bonus(board, (0, 0), (6, 0)) == 0


def test_cover_ac_bonus_from_three_quarters_pillar(tmp_path):
    board = make_board(tmp_path)
    assert cover_ac_bonus(board, (4, 0), (4, 2)) == 5  # three_quarters = +5 AC


def test_has_full_cover_behind_wall(tmp_path):
    board = make_board(tmp_path)
    assert has_full_cover(board, (2, 0), (2, 2)) is True


def test_has_full_cover_false_for_pillar_only(tmp_path):
    board = make_board(tmp_path)
    assert has_full_cover(board, (4, 0), (4, 2)) is False


def test_line_of_sight_blocked_by_obscurement_between_endpoints(tmp_path):
    board = make_board(tmp_path)
    obsc = ObscurementField(cell_feet=5, regions=[Region(center=(3, 0), radius_ft=10, kind="darkness")])
    assert line_of_sight(board, (0, 0), (6, 0), obsc) is False


def test_line_of_sight_unaffected_when_no_obscurement_passed(tmp_path):
    board = make_board(tmp_path)
    assert line_of_sight(board, (0, 0), (6, 0)) is True
