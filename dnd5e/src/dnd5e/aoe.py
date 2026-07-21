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

Friendly fire lives entirely in the *aim*: only enemies are ever returned as
targets, so an ally in an area simply isn't hit. The `max_allies` knob is how
many allies a placement may include — 0 means friendly-fire-safe (a PC in the
area disqualifies it), and Sculpt Spells raises it to `1 + spell level` via
`sculpt_limit` (an evoker shields that many allies caught in the blast, letting
it drop Fireball right on the melee).
"""

from __future__ import annotations

import math
from typing import Optional

from dnd_board import bresenham

# Cube directions (thunder wave "originates from you"): the four orthogonal
# faces. dx, dy in board coords.
_CUBE_DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1)]


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


def best_line(bf, caster, length_cells: int, *, max_allies: int = 0,
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
        if len(allies) > max_allies:
            continue  # more allies than Sculpt can shield -> unacceptable
        if len(enemies) < min_enemies:
            continue
        if best is None or len(enemies) > len(best[0]):
            best = (enemies, foe.coord)
    return best


# -----------------------------------------------------------------------------
# Sphere (fireball, shatter) and cube (thunder wave)
# -----------------------------------------------------------------------------


def sphere_cells(board, center: tuple, radius_ft: int) -> set:
    """Cells whose center is within `radius_ft` (Euclidean, so the blast reads
    as a disc rather than a chebyshev square) of `center`, in bounds and not a
    wall. Walls only remove their own cell here — no corner-spread modeling."""
    cx, cy = center
    r = radius_ft / board.cell_feet
    rc = int(math.floor(r))
    out = set()
    for dy in range(-rc, rc + 1):
        for dx in range(-rc, rc + 1):
            if dx * dx + dy * dy > r * r:
                continue
            x, y = cx + dx, cy + dy
            if board.is_passable(x, y):
                out.add((x, y))
    return out


def cube_cells(board, origin: tuple, direction: tuple, size_cells: int) -> set:
    """A `size_cells` cube with its near face against `origin`, extending in
    `direction` (one of the four orthogonal faces). Passable cells only."""
    ox, oy = origin
    dx, dy = direction
    half = (size_cells - 1) // 2
    out = set()
    for step in range(1, size_cells + 1):          # depth away from the caster
        for lat in range(-half, half + 1):          # width across the face
            if dx:                                   # facing east/west
                x, y = ox + dx * step, oy + lat
            else:                                    # facing north/south
                x, y = ox + lat, oy + dy * step
            if board.is_passable(x, y):
                out.add((x, y))
    return out


def split_cells(bf, caster, cells: set) -> tuple[list, list]:
    """`(allies, enemies)` among the live creatures standing in `cells`
    (excluding the caster). The area version of get_targets."""
    allies, enemies = [], []
    for c in bf.creatures.values():
        if c is caster or c.is_down or c.coord not in cells:
            continue
        (allies if c.side == caster.side else enemies).append(c)
    return allies, enemies


def best_sphere(bf, caster, radius_ft: int, range_ft: int, *, max_allies: int = 0,
                min_enemies: int = 1) -> Optional[tuple[list, tuple]]:
    """Best sphere placement: `(enemies, center)`. Candidate centers are the live
    enemy cells within `range_ft` of the caster — centering on a foe inside a
    cluster catches the cluster, so no brute-force scan of the whole board."""
    if caster.coord is None:
        return None
    best: Optional[tuple[list, tuple]] = None
    for foe in bf.enemies_of(caster):
        if foe.coord is None or bf.board.distance_ft(caster.coord, foe.coord) > range_ft:
            continue
        allies, enemies = split_cells(bf, caster, sphere_cells(bf.board, foe.coord, radius_ft))
        if len(allies) > max_allies:
            continue
        if len(enemies) < min_enemies:
            continue
        if best is None or len(enemies) > len(best[0]):
            best = (enemies, foe.coord)
    return best


def best_cube(bf, caster, size_cells: int, *, max_allies: int = 0,
              min_enemies: int = 1) -> Optional[tuple[list, tuple]]:
    """Best of the four cube facings from the caster: `(enemies, direction)`."""
    if caster.coord is None:
        return None
    best: Optional[tuple[list, tuple]] = None
    for d in _CUBE_DIRS:
        allies, enemies = split_cells(bf, caster, cube_cells(bf.board, caster.coord, d, size_cells))
        if len(allies) > max_allies:
            continue
        if len(enemies) < min_enemies:
            continue
        if best is None or len(enemies) > len(best[0]):
            best = (enemies, d)
    return best


def best_area(bf, caster, area: dict, *, max_allies: int = 0,
              min_enemies: int = 1) -> Optional[tuple[list, tuple]]:
    """Dispatch to the right shape. Returns `(enemies, aim)` or None. `aim` is a
    cell for line/sphere and a direction for cube (opaque to the caller — only
    the enemy list is used for damage)."""
    shape = area.get("shape")
    if shape == "line":
        length_cells = bf.board.feet_to_cells(area["length_ft"])
        return best_line(bf, caster, length_cells, max_allies=max_allies, min_enemies=min_enemies)
    if shape == "sphere":
        return best_sphere(bf, caster, area["radius_ft"], area["range_ft"],
                           max_allies=max_allies, min_enemies=min_enemies)
    if shape == "cube":
        size_cells = bf.board.feet_to_cells(area["size_ft"])
        return best_cube(bf, caster, size_cells, max_allies=max_allies, min_enemies=min_enemies)
    raise ValueError(f"unknown area shape {shape!r}")


def sculpt_limit(caster, area: dict) -> int:
    """Sculpt Spells (evoker, 6th level): the caster can shield `1 + spell level`
    allies caught in one of its evocation areas (they auto-succeed, take no
    damage). Returns that many — the max allies a placement may include — or 0
    without the `sculpt_spells` tag or a known spell `level` on the area. All of
    the L6 evoker's area spells are evocations, so the tag is sufficient here;
    a school field would be needed if a non-evocation area spell were added."""
    if "level" in area and caster.has_tag("sculpt_spells"):
        return 1 + int(area["level"])
    return 0
