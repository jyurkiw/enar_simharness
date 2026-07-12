"""Sides, grapple graph, and focus over a `dnd_board.Board` (design doc 03
section 5). Board is constructor-required — decision D5 deleted every
`board is None` abstract-mode fallback the old `Battlefield` facade had.
Pure movement (approach/kite/hold) lives in `movement.py`, which calls this
module's query methods; this module never mutates a creature's position.

The grapple graph is a `dict[str, list[str]]`, not `dict[str, set[str]]` —
**this is a deliberate fix for a real bug found in Phase 0** (design doc 06's
Global Gotcha 7a): the old engine's `_grapples: dict[str, set[str]]` made
`grabbed_targets()` return names in hash-randomized order, so which grappled
target a multiattack-selecting creature bit/slammed first varied between
processes even with an identical dice seed. Using an insertion-ordered list
here closes that hole for good — see test_battlefield.py's determinism test.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional

from dnd_board import Board

from . import vision as _vision
from .creature import Creature


class Battlefield:
    def __init__(self, creatures: Iterable[Creature], *, board: Board) -> None:
        self.creatures: dict[str, Creature] = {c.instance_name: c for c in creatures}
        self.board = board
        self._grapples: dict[str, list[str]] = defaultdict(list)   # grappler -> [grappled, ...]
        self._grappled_by: dict[str, str] = {}                     # grappled -> grappler
        self.focus: dict[str, str] = {}                            # side -> enemy instance_name

    # ---- rosters ------------------------------------------------------------

    def side_of(self, name: str) -> str:
        return self.creatures[name].side

    def members(self, side: str) -> list[Creature]:
        return [c for c in self.creatures.values() if c.side == side]

    def enemies_of(self, actor: Creature) -> list[Creature]:
        """Live (not Down) enemies. Use `members()` for downed ones too."""
        return [c for c in self.creatures.values() if c.side != actor.side and not c.is_down]

    def allies_of(self, actor: Creature) -> list[Creature]:
        return [c for c in self.creatures.values()
                if c.side == actor.side and c.instance_name != actor.instance_name and not c.is_down]

    def primary_enemy(self, actor: Creature) -> Optional[Creature]:
        """Who this actor's side attacks: the side's focus if visible;
        otherwise the nearest visible enemy; otherwise the focus blindly, else
        the first live enemy."""
        enemies = self.enemies_of(actor)
        if not enemies:
            return None
        focus_name = self.focus.get(actor.side)
        focus = self.creatures.get(focus_name) if focus_name else None
        if focus is not None and focus.is_down:
            focus = None
        if focus is not None and self.can_see(actor, focus):
            return focus
        visible = [e for e in enemies if self.can_see(actor, e)]
        if visible:
            if actor.coord is not None:
                big = 1 << 30
                return min(visible, key=lambda e: self.board.distance_ft(actor.coord, e.coord)
                           if e.coord is not None else big)
            return visible[0]
        return focus if focus is not None else enemies[0]

    def preferred_target(self, actor: Creature) -> Optional[Creature]:
        """A melee attacker always fights whatever is grappling it (adjacent,
        no disadvantage); otherwise falls back to `primary_enemy`."""
        grappler = self.grappled_by(actor.instance_name)
        if grappler is not None:
            held_by = self.creatures.get(grappler)
            if held_by is not None and not held_by.is_down:
                return held_by
        return self.primary_enemy(actor)

    def nearest_enemy(self, actor: Creature) -> Optional[Creature]:
        enemies = self.enemies_of(actor)
        if not enemies:
            return None
        if actor.coord is None:
            return enemies[0]
        big = 1 << 30
        return min(enemies, key=lambda e: self.board.distance_ft(actor.coord, e.coord)
                   if e.coord is not None else big)

    def visible_enemies(self, actor: Creature) -> list[Creature]:
        return [e for e in self.enemies_of(actor) if self.line_of_sight(actor, e)]

    # ---- geometry -------------------------------------------------------------

    def occupied_cells(self, exclude: Iterable[str] = ()) -> set[tuple[int, int]]:
        ex = set(exclude)
        cells: set[tuple[int, int]] = set()
        for c in self.creatures.values():
            if c.instance_name in ex or c.is_down:
                continue
            if c.coord is not None:
                cells.add(c.coord)
        return cells

    def distance_ft(self, actor: Creature, target: Creature) -> Optional[int]:
        if actor.coord is None or target.coord is None:
            return None
        return self.board.distance_ft(actor.coord, target.coord)

    def in_reach(self, actor: Creature, target: Creature) -> bool:
        if actor.coord is None or target.coord is None:
            return False
        return self.board.distance_ft(actor.coord, target.coord) <= actor.reach_ft

    def line_of_sight(self, actor: Creature, target: Creature) -> bool:
        if actor.coord is None or target.coord is None:
            return False
        return _vision.line_of_sight(self.board, actor.coord, target.coord)

    def can_see(self, observer: Creature, target: Creature) -> bool:
        """Phase 3: equivalent to `line_of_sight` (no obscurement/darkvision
        yet — see vision.py's module docstring)."""
        return self.line_of_sight(observer, target)

    def cover_ac_bonus(self, actor: Creature, target: Creature) -> int:
        if actor.coord is None or target.coord is None:
            return 0
        return _vision.cover_ac_bonus(self.board, actor.coord, target.coord)

    def has_full_cover(self, actor: Creature, target: Creature) -> bool:
        if actor.coord is None or target.coord is None:
            return False
        return _vision.has_full_cover(self.board, actor.coord, target.coord)

    # ---- grapple graph ----------------------------------------------------------

    def grapple(self, grappler: str, target: str) -> None:
        """A creature can be held by only one grappler at a time; a new
        grapple supersedes any prior one."""
        prior = self._grappled_by.get(target)
        if prior and prior != grappler:
            self._detach(prior, target)
        bucket = self._grapples[grappler]
        if target not in bucket:
            bucket.append(target)
        self._grappled_by[target] = grappler

    def release(self, grappler: str, target: Optional[str] = None) -> None:
        if target is None:
            for t in list(self._grapples.get(grappler, ())):
                self._grappled_by.pop(t, None)
            self._grapples[grappler] = []
        else:
            self._detach(grappler, target)

    def _detach(self, grappler: str, target: str) -> None:
        bucket = self._grapples.get(grappler)
        if bucket and target in bucket:
            bucket.remove(target)
        if self._grappled_by.get(target) == grappler:
            self._grappled_by.pop(target, None)

    def grappled_by(self, name: str) -> Optional[str]:
        return self._grappled_by.get(name)

    def grabbed_targets(self, grappler: str) -> list[str]:
        """Insertion order, deterministic across processes/seeds (see this
        module's docstring — this is the Gotcha 7a fix)."""
        return list(self._grapples.get(grappler, ()))

    def is_grappling(self, grappler: str) -> bool:
        return bool(self._grapples.get(grappler))

    def clear_grapples(self) -> None:
        self._grapples = defaultdict(list)
        self._grappled_by = {}
