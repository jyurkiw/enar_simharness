"""Geometric area-of-effect targeting (Lightning Bolt's line, and — later —
cones and spheres).

Two layers, kept separate on purpose:

  * `get_targets(...)` is the base primitive the user asked for: given a caster
    and a specific *aim*, it returns the creatures the shape would catch, split
    into `allies` and `enemies`. Callers just read `len(...)` — "how many
    friends / foes does this shot hit?"

  * `best_line(...)` is the *smart aim*: instead of brute-forcing every cell or
    angle, it only considers rays aimed at an actual enemy (a clustered pack has
    at most a handful of distinct bearings), and returns the one catching the
    most enemies subject to the friendly-fire rule. This is the standard grid-AoE
    trick — you never need to try a direction that doesn't pass through a target.

Friendly fire matters because a 5th-level evoker has no Sculpt Spells yet: a PC
caught in the line takes the hit. `allow_allies` is the seam for adding Sculpt
later — flip it True (for the allies Sculpt would protect) and ally-hitting
lines become acceptable again.
"""

from __future__ import annotations

from typing import Optional

from dnd_board import bresenham


def line_cells(board, origin: tuple, aim: tuple, length_cells: int) -> list:
    """The cells of a `length_cells`-long ray from `origin` toward `aim`,
    excluding the caster's own cell and stopping at the first wall (total cover
    the bolt can't punch through)."""
    (ox, oy), (ax, ay) = origin, aim
    dx, dy = ax - ox, ay - oy
    if dx == 0 and dy == 0:
        return []
    far = (ox + dx * length_cells, oy + dy * length_cells)
    cells = []
    for cell in bresenham(origin, far)[1:]:  # [1:] skips the caster's cell
        if len(cells) >= length_cells:
            break
        if not board.is_passable(*cell):
            break
        cells.append(cell)
    return cells


def get_targets(bf, caster, aim: tuple, length_cells: int) -> tuple[list, list]:
    """The base primitive: creatures a line from `caster` toward `aim` would
    catch, as `(allies, enemies)` (excluding the caster and the Down). Count the
    lists to answer "how many friends / foes in the blast?"."""
    cells = set(line_cells(bf.board, caster.coord, aim, length_cells))
    allies, enemies = [], []
    for c in bf.creatures.values():
        if c is caster or c.is_down or c.coord not in cells:
            continue
        (allies if c.side == caster.side else enemies).append(c)
    return allies, enemies


def best_line(bf, caster, length_cells: int, *, allow_allies: bool = False,
              min_enemies: int = 1) -> Optional[tuple[list, tuple]]:
    """The best-aimed line from the caster's current cell: `(enemies, aim)` for
    the ray hitting the most enemies while respecting the friendly-fire rule, or
    None if nothing clears the bar. Only rays aimed at a live enemy are tried
    (smart, not brute force)."""
    if caster.coord is None:
        return None
    best: Optional[tuple[list, tuple]] = None
    for foe in bf.enemies_of(caster):
        if foe.coord is None:
            continue
        allies, enemies = get_targets(bf, caster, foe.coord, length_cells)
        if allies and not allow_allies:
            continue  # would catch a PC — invalid without Sculpt Spells
        if len(enemies) < min_enemies:
            continue
        if best is None or len(enemies) > len(best[0]):
            best = (enemies, foe.coord)
    return best
