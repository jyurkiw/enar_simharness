"""Sides, grapple graph, focus, and obscurement/auras over a `dnd_board.Board`
(design doc 03 section 5). Board is constructor-required — decision D5
deleted every `board is None` abstract-mode fallback the old `Battlefield`
facade had. Pure movement (approach/kite/hold) lives in `movement.py`, which
calls this module's query methods; this module never mutates a creature's
position.

The grapple graph is a `dict[str, list[str]]`, not `dict[str, set[str]]` —
**this is a deliberate fix for a real bug found in Phase 0** (design doc 06's
Global Gotcha 7a): the old engine's `_grapples: dict[str, set[str]]` made
`grabbed_targets()` return names in hash-randomized order, so which grappled
target a multiattack-selecting creature bit/slammed first varied between
processes even with an identical dice seed. Using an insertion-ordered list
here closes that hole for good — see test_battlefield.py's determinism test.

Obscurement/auras (Phase 4, design doc 01 section 3's `[[environment.
obscurement]]`) is a straight port of `dnd5e_combat.battlefield.Battlefield`'s
`Aura`/`refresh_auras`/`obscurement_immune`/`not_blinded_by_obscurement`/
`can_see` — see each method's docstring for the old-engine cross-reference.
`limited_darkvision`/`darkvision_immunity` are per-creature markers written
by `effects.py`'s trait effects into `Creature.trial_scratch` (there's no
custom-condition mechanism yet — Phase 5 — for a passive innate trait to hang
off of), read here rather than off `Statblock` directly so overrides/traits
resolve exactly once, at trial setup.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Optional

from dnd_board import Board, ObscurementField, Region

from . import conditions as _conditions
from . import vision as _vision
from .creature import Creature
from .hazards import HazardField

# A creature with `limited_darkvision` set can see *into* heavy obscurement up
# to this range (but not past it), instead of being fully blocked — matching
# `dnd5e_combat.battlefield.LIMITED_DARKVISION_RANGE_FT` (a standard 60 ft
# darkvision halved by the photophage darkness that's the only source of this
# trait so far).
LIMITED_DARKVISION_RANGE_FT = 30

# Obscurement kinds a darkness-family aura source is immune to at any range —
# matches `dnd_board.obscurement.OBSCURING_KINDS`'s darkness members (not
# "fog", which nothing is innately immune to).
_DARKNESS_KINDS = frozenset({"darkness", "magical_darkness"})


@dataclass
class Aura:
    """A light/obscurement region bound to a creature: it re-centers on that
    creature's cell every round and switches off while the source is down —
    port of `dnd5e_combat.battlefield.Aura`."""

    source: str        # instance_name
    kind: str           # "darkness" | "magical_darkness" | "fog" | "light"
    radius_ft: float
    start_round: int = 1


class Battlefield:
    def __init__(self, creatures: Iterable[Creature], *, board: Board,
                 obscurement: Optional[ObscurementField] = None,
                 auras: Optional[Iterable[Aura]] = None,
                 condition_defs: Optional[dict] = None) -> None:
        self.creatures: dict[str, Creature] = {c.instance_name: c for c in creatures}
        self.board = board
        # The workspace-wide `dict[str, statblock.ConditionDef]` registry
        # `system.py` builds. Carried here so `movement.py` can fold a
        # `grant_speed_zero` condition (the Slinger's Low Bolo) without needing
        # its own handle on the system — every movement call already has the
        # Battlefield.
        self.condition_defs: dict = condition_defs if condition_defs is not None else {}
        self._grapples: dict[str, list[str]] = defaultdict(list)   # grappler -> [grappled, ...]
        self._grappled_by: dict[str, str] = {}                     # grappled -> grappler
        self.focus: dict[str, str] = {}                            # side -> enemy instance_name
        self.obscurement = obscurement
        self.auras: list[Aura] = list(auras) if auras else []
        # Persistent damaging regions — the fire field (see hazards.py). Fresh
        # (empty) per trial; a sim or the Pyre Elemental driver fills it.
        self.hazards = HazardField(board)
        # Obscurement regions that don't move (the scenario's static
        # `[[environment.obscurement]]` entries without `follows`);
        # creature-bound auras are layered on top of these each round by
        # `refresh_auras`.
        self._static_regions: list[Region] = list(obscurement.regions) if obscurement is not None else []

    # ---- rosters ------------------------------------------------------------

    def side_of(self, name: str) -> str:
        return self.creatures[name].side

    def members(self, side: str) -> list[Creature]:
        return [c for c in self.creatures.values() if c.side == side]

    def enemies_of(self, actor: Creature) -> list[Creature]:
        """Live (not Down) enemies that are still in the fight. Excludes anyone
        carrying a `neutralizes` condition (a manacled, bound-and-helpless PC) —
        the guards leave them and move on. Use `members()` for everyone."""
        return [c for c in self.creatures.values()
                if c.side != actor.side and not c.is_down
                and not _conditions.is_neutralized(c, condition_defs=self.condition_defs)]

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
        return _vision.line_of_sight(self.board, actor.coord, target.coord, self.obscurement)

    def _cell_sees(self, cell: tuple[int, int], target_coord: tuple[int, int], *,
                   darkvision_ft: int = 0) -> bool:
        """Whether a non-immune observer on `cell` can see `target_coord`:
        neither end is in heavy obscurement, and the sight line itself is
        clear. `darkvision_ft` lets the observer see *into* obscurement (but
        not past it) within that range instead of being fully blocked. Port
        of `dnd5e_combat.battlefield.Battlefield._cell_sees`."""
        obsc = self.obscurement
        obscured = obsc is not None and (obsc.is_heavily_obscured(*cell)
                                         or obsc.is_heavily_obscured(*target_coord))
        if obscured and darkvision_ft and self.board.distance_ft(cell, target_coord) <= darkvision_ft:
            # Within limited-darkvision range: the sight line itself must skip
            # the obscurement check too (passing `obsc` blocks on ANY obscured
            # cell it crosses, not just the two endpoints) — walls/terrain
            # (checked via `board` regardless) still block.
            return _vision.line_of_sight(self.board, cell, target_coord, None)
        if obscured:
            return False
        return _vision.line_of_sight(self.board, cell, target_coord, obsc)

    def _limited_darkvision_ft(self, observer: Creature) -> int:
        return observer.trial_scratch.get("limited_darkvision_ft", 0)

    def can_see(self, observer: Creature, target: Creature) -> bool:
        """Line of sight plus obscurement: a target in heavy obscurement can't
        be seen, and a non-immune observer standing in it can't see anything
        — unless the observer is immune (`obscurement_immune`) or has
        `limited_darkvision`, which caps rather than fully blocks. Port of
        `dnd5e_combat.battlefield.Battlefield.can_see`."""
        if observer.coord is None or target.coord is None:
            return False
        if observer.instance_name in self.obscurement_immune():
            return _vision.line_of_sight(self.board, observer.coord, target.coord, None)
        return self._cell_sees(observer.coord, target.coord,
                               darkvision_ft=self._limited_darkvision_ft(observer))

    def cover_ac_bonus(self, actor: Creature, target: Creature) -> int:
        if actor.coord is None or target.coord is None:
            return 0
        return _vision.cover_ac_bonus(self.board, actor.coord, target.coord)

    def has_full_cover(self, actor: Creature, target: Creature) -> bool:
        if actor.coord is None or target.coord is None:
            return False
        return _vision.has_full_cover(self.board, actor.coord, target.coord)

    # ---- obscurement / auras -----------------------------------------------------

    def refresh_auras(self, round_index: int) -> None:
        """Rebuild the obscurement layer for this moment: the static scenario
        regions plus one region per active aura, centered on its source's
        current cell. An aura is skipped before its `start_round` or while its
        source is down or unplaced. Call once per round (design doc 03
        section 2's "sync environment" turn-pipeline step) — port of
        `dnd5e_combat.battlefield.Battlefield.refresh_auras`."""
        if self.obscurement is None:
            return
        regions = list(self._static_regions)
        for aura in self.auras:
            if round_index < aura.start_round:
                continue
            source = self.creatures.get(aura.source)
            if source is None or source.is_down or source.coord is None:
                continue
            regions.append(Region(center=source.coord, radius_ft=aura.radius_ft, kind=aura.kind))
        self.obscurement.regions = regions

    def obscurement_immune(self) -> set[str]:
        """Instance names that ignore heavy obscurement at any range: the
        source of a darkness/magical_darkness aura (sees through its own
        photophage) and anything with the `darkvision_immunity` trait. A
        `limited_darkvision`-only creature is NOT included — see `can_see`,
        which caps its sight range into obscurement instead. Port of
        `dnd5e_combat.battlefield.Battlefield.obscurement_immune`."""
        immune = {a.source for a in self.auras if a.kind in _DARKNESS_KINDS}
        immune |= {c.instance_name for c in self.creatures.values()
                  if c.trial_scratch.get("darkvision_immune")}
        return immune

    def not_blinded_by_obscurement(self) -> set[str]:
        """Instance names exempt from the blanket Blinded that standing in
        heavy obscurement otherwise imposes: everyone in `obscurement_immune`
        plus anyone with `limited_darkvision` (capped range, not full
        immunity, still isn't flatly blind for standing in the dark — see
        `can_see` for where the shorter range actually bites). Port of
        `dnd5e_combat.battlefield.Battlefield.not_blinded_by_obscurement`."""
        immune = self.obscurement_immune()
        immune |= {c.instance_name for c in self.creatures.values()
                  if c.trial_scratch.get("limited_darkvision_ft", 0) > 0}
        return immune

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
