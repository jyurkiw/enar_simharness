"""Every board TOML this library ships must load cleanly. Regression coverage
for the production data files (distinct from dnd_board's own loader tests,
which exercise the loader against synthetic fixtures)."""

from pathlib import Path

import pytest
from dnd_board import load_board_toml

import dnd5e_data

BOARD_FILES = sorted(dnd5e_data.data_path("boards").glob("*.toml"))


def test_at_least_one_board_is_shipped():
    assert BOARD_FILES, "dnd5e_data/boards/ has no .toml files to validate"


@pytest.mark.parametrize("path", BOARD_FILES, ids=lambda p: p.stem)
def test_board_loads_without_error(path: Path):
    board = load_board_toml(path)
    assert board.width > 0
    assert board.height > 0


@pytest.mark.parametrize("path", BOARD_FILES, ids=lambda p: p.stem)
def test_board_has_party_and_monster_spawns(path: Path):
    board = load_board_toml(path)
    assert board.spawns.get("party"), f"{path}: no party spawn cells"
    assert board.spawns.get("monsters"), f"{path}: no monster spawn cells"
