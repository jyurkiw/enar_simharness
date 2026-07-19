"""LOS / cover / obscurement adjudication over a `dnd_board.Board`.

Phase 4 adds obscurement (`[[environment.obscurement]]`, design doc 01
section 3): `line_of_sight` now threads an optional `dnd_board.ObscurementField`
through to `dnd_board.vision.line_of_sight` (which already supported one —
heavy obscurement blocks a sight line the same way full cover does). Cover
itself is unaffected by obscurement (a separate concept), so
`cover_ac_bonus`/`has_full_cover` are unchanged.

What obscurement means for a *creature standing in it* (blinded unless
immune/darkvision-capped) is adjudicated in `battlefield.py`'s `can_see`, not
here — this module stays pure geometry over a board + an obscurement field,
with no notion of a "creature" or its traits (mirroring `dnd5e_combat.
battlefield.Battlefield.can_see`'s split between raw sight-line geometry and
per-creature immunity).
"""

from __future__ import annotations

from typing import Optional

from dnd_board import Board, Coord, ObscurementField
from dnd_board import terrain as _terrain
from dnd_board import vision as _bvision


def line_of_sight(board: Board, a: Coord, b: Coord,
                  obscurement: Optional[ObscurementField] = None) -> bool:
    return _bvision.line_of_sight(board, a, b, obscurement)


def cover_ac_bonus(board: Board, a: Coord, b: Coord) -> int:
    cover = _bvision.cover_between(board, a, b)
    return int(_terrain.COVER_AC_BONUS.get(cover, 0))


def has_full_cover(board: Board, a: Coord, b: Coord) -> bool:
    return _bvision.cover_between(board, a, b) == _terrain.Cover.FULL
