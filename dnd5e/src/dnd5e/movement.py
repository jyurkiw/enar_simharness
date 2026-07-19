"""Named movement tactics (design doc 03 section 5). **Phase 3 scope: engage,
kite, hold only** — `hunt_light` and `guard` are Phase 4/5, once environment
light/obscurement data exists to make them meaningful (design doc 06's build
order). Each tactic mutates the actor's `x`/`y` in place; `battlefield.py`
itself never mutates position (see its docstring) — this module is the only
place that does. Ported from `dnd5e_combat.battlefield.Battlefield.approach/
kite/move_toward`, adapted to the new `Battlefield`/`Creature` split.
"""

from __future__ import annotations

from typing import Optional

from dnd_board import pathing as _bpath

from . import vision as _vision
from .battlefield import Battlefield
from .creature import Creature

PHASE3_TACTICS = ("engage", "kite", "hold")


def apply_tactic(tactic: str, actor: Creature, target: Optional[Creature],
                  battlefield: Battlefield, *, max_range_ft: Optional[int] = None) -> None:
    if tactic == "engage":
        engage(actor, target, battlefield)
    elif tactic == "kite":
        kite(actor, target, battlefield, max_range_ft=max_range_ft)
    elif tactic == "hold":
        hold(actor, target, battlefield)
    else:
        raise ValueError(f"unknown movement tactic {tactic!r} (Phase 3 supports {PHASE3_TACTICS})")


def hold(actor: Creature, target: Optional[Creature], battlefield: Battlefield) -> None:
    """Stand still. No movement at all — a deliberate turtle tactic."""
    return


def move_to_cell(actor: Creature, dest: Optional[tuple[int, int]], battlefield: Battlefield) -> None:
    """Move as far toward an explicit destination cell as speed allows — the
    escape hatch's `plan_movement` hook (design doc 04 section 5), for
    bespoke movement no named tactic captures (e.g. dragging a captive away
    from a light source). Unlike `_move_toward`, this has no notion of a
    target creature to stop short of or move into reach of; it just spends
    up to `actor.speed_ft` pathing toward `dest`, routing around other living
    creatures, and drags along anyone it's grappling."""
    if actor.coord is None or dest is None:
        return
    board = battlefield.board
    start = actor.coord
    occ = battlefield.occupied_cells(exclude=(actor.instance_name,))
    route = _bpath.path(board, start, dest, blocked=occ)
    if len(route) <= 1:
        return
    budget = board.feet_to_cells(actor.speed_ft)
    cost = board.move_cost_grid()
    for (ox, oy) in occ:
        cost[oy, ox] = 0
    spent = 0
    new_pos = start
    for cell in route[1:]:
        cx, cy = cell
        spent += int(cost[cy, cx])
        if spent > budget:
            break
        new_pos = cell
    actor.x, actor.y = new_pos
    if battlefield.is_grappling(actor.instance_name):
        _settle_captives(actor, start, battlefield)


def engage(actor: Creature, target: Optional[Creature], battlefield: Battlefield) -> None:
    """Move into melee reach of `target` if not already there. No-op if
    already in reach, unplaced, or there's no target."""
    if actor.coord is None or target is None or target.coord is None:
        return
    if battlefield.in_reach(actor, target):
        return
    _move_toward(actor, target, battlefield, into_reach=True)


def kite(actor: Creature, target: Optional[Creature], battlefield: Battlefield, *,
         max_range_ft: Optional[int] = None) -> None:
    """Stand as far from `target` as possible while staying within
    `max_range_ft` and keeping line of sight, re-evaluated fresh every turn
    (never cached). If no reachable in-range cell can see the target, advance
    toward it instead of holding a blind position (`_advance_to_los`)."""
    if actor.coord is None or target is None or target.coord is None:
        return
    board = battlefield.board
    start = actor.coord
    occ = battlefield.occupied_cells(exclude=(actor.instance_name, target.instance_name))
    candidates = _bpath.reachable(board, start, actor.speed_ft, blocked=occ)
    candidates.add(start)  # standing still is always an option
    goal = target.coord
    # Farthest-first: usually finds an in-range, sight-clear cell in a
    # handful of checks rather than scanning the whole reachable set.
    for cell in sorted(candidates, key=lambda c: board.distance_ft(c, goal), reverse=True):
        if max_range_ft is not None and board.distance_ft(cell, goal) > max_range_ft:
            continue
        if _vision.line_of_sight(board, cell, goal):
            actor.x, actor.y = cell
            if battlefield.is_grappling(actor.instance_name):
                _settle_captives(actor, start, battlefield)
            return
    _advance_to_los(actor, target, battlefield, occ)


def _move_toward(actor: Creature, target: Creature, battlefield: Battlefield, *,
                  into_reach: bool) -> tuple[int, int]:
    """Path `actor` toward `target`, spending up to its speed and routing
    around other living creatures. Stops one cell short (never steps onto the
    target's own cell) and, when `into_reach`, as soon as it's within reach."""
    board = battlefield.board
    start, goal = actor.coord, target.coord
    occ = battlefield.occupied_cells(exclude=(actor.instance_name, target.instance_name))
    route = _bpath.path(board, start, goal, blocked=occ)
    if len(route) <= 1:
        return actor.coord
    budget = board.feet_to_cells(actor.speed_ft)
    cost = board.move_cost_grid()
    for (ox, oy) in occ:
        cost[oy, ox] = 0
    spent = 0
    dest = start
    for cell in route[1:]:
        if cell == goal:
            break  # never step onto the target's own cell
        cx, cy = cell
        spent += int(cost[cy, cx])
        if spent > budget:
            break
        dest = cell
        if into_reach and board.distance_ft(dest, goal) <= actor.reach_ft:
            break
    actor.x, actor.y = dest
    if battlefield.is_grappling(actor.instance_name):
        _settle_captives(actor, start, battlefield)
    return dest


def _advance_to_los(actor: Creature, target: Creature, battlefield: Battlefield, occ: set) -> None:
    """Kite's fallback: step toward `target` along the shortest path, stopping
    as soon as a sight line opens up, and never closing into melee reach (a
    kiter that can't see forgoes the shot rather than charging in)."""
    board = battlefield.board
    start, goal = actor.coord, target.coord
    route = _bpath.path(board, start, goal, blocked=occ)
    if len(route) <= 1:
        return
    budget = board.feet_to_cells(actor.speed_ft)
    cost = board.move_cost_grid()
    for (ox, oy) in occ:
        cost[oy, ox] = 0
    spent = 0
    dest = start
    for cell in route[1:]:
        if cell == goal or board.distance_ft(cell, goal) <= actor.reach_ft:
            break  # don't walk into melee reach while kiting
        cx, cy = cell
        spent += int(cost[cy, cx])
        if spent > budget:
            break
        dest = cell
        if _vision.line_of_sight(board, dest, goal):
            break  # regained a sight line — hold here
    actor.x, actor.y = dest


def _settle_captives(actor: Creature, old_coord: tuple[int, int], battlefield: Battlefield) -> None:
    """Drag the actor's grappled captives to free cells next to its new
    position (preferring the cell it just vacated), so a grapple stays
    adjacent as the grappler moves."""
    captives = battlefield.grabbed_targets(actor.instance_name)
    occupied = battlefield.occupied_cells(exclude=(actor.instance_name, *captives))
    occupied.add(actor.coord)
    for name in captives:
        cap = battlefield.creatures.get(name)
        if cap is None or cap.is_down or cap.coord is None:
            continue
        spot = _free_adjacent(battlefield.board, actor.coord, occupied, prefer=old_coord)
        if spot is not None:
            cap.x, cap.y = spot
            occupied.add(spot)


def _free_adjacent(board, center: tuple[int, int], occupied: set,
                    prefer: Optional[tuple[int, int]] = None) -> Optional[tuple[int, int]]:
    cx, cy = center
    neighbors = [(cx + dx, cy + dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dx, dy) != (0, 0)]
    if prefer is not None and prefer in neighbors:
        neighbors = [prefer] + [n for n in neighbors if n != prefer]
    for (x, y) in neighbors:
        if board.is_passable(x, y) and (x, y) not in occupied:
            return (x, y)
    return None
