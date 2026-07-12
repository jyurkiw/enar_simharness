"""LOS / cover adjudication over a `dnd_board.Board`.

Phase 3 scope: plain line-of-sight and cover — no obscurement fields or
darkvision traits yet (`[[environment.obscurement]]`, `limited_darkvision`,
`darkvision_immunity` are Phase 4/5, design doc 03 section 5). `can_see` in
`battlefield.py` is currently just `line_of_sight`; this module is where the
obscurement-aware version grows into when that data lands, without changing
`battlefield.py`'s calling convention.
"""

from __future__ import annotations

from typing import Optional

from dnd_board import Board, Coord
from dnd_board import terrain as _terrain
from dnd_board import vision as _bvision


def line_of_sight(board: Board, a: Coord, b: Coord) -> bool:
    return _bvision.line_of_sight(board, a, b, None)


def cover_ac_bonus(board: Board, a: Coord, b: Coord) -> int:
    cover = _bvision.cover_between(board, a, b)
    return int(_terrain.COVER_AC_BONUS.get(cover, 0))


def has_full_cover(board: Board, a: Coord, b: Coord) -> bool:
    return _bvision.cover_between(board, a, b) == _terrain.Cover.FULL
