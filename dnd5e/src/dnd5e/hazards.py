"""Persistent damaging board regions — fire (the burning opera house), and any
future "stand here and it hurts" hazard.

Distinct from the two things it resembles:
  * Obscurement (`ObscurementField`) *blinds*; a hazard *burns*.
  * An ability's one-shot AoE resolves once and is gone; a hazard STAYS on the
    board and ticks damage on whoever is in it at the start of their turn.

The Pyre Elemental's Falling Debris drops these; the spreading fire field is the
real "monster" of the burning-building phase (see sims/opera_house/PLAN.md, P0).
Hazard damage is environmental — no attacker — so it is always LETHAL: the
`subduing_side` mercy only spares a foe from a killer that *chose* to subdue, and
fire chooses nothing (`CombatContext.environmental_damage`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import aoe


@dataclass
class Hazard:
    """One damaging region: a sphere of `radius_ft` around `center`, dealing
    `damage` (dice) of `damage_type` to anyone starting their turn inside it,
    active until `expires_round` (inclusive; None = permanent). `cells` is the
    footprint, computed once when the hazard is placed."""

    center: tuple                 # (x, y)
    radius_ft: float
    damage: str                   # dice code, e.g. "2d6"
    damage_type: str = "fire"
    expires_round: Optional[int] = None
    tag: str = "fire"             # ledger label / source name
    cells: frozenset = field(default_factory=frozenset)


class HazardField:
    """The board's active hazards. Fresh per trial (built in setup_trial), so a
    trial always starts with a clean board unless the sim seeds one."""

    def __init__(self, board) -> None:
        self.board = board
        self.hazards: list[Hazard] = []

    def add(self, hazard: Hazard) -> None:
        if not hazard.cells:
            hazard.cells = frozenset(aoe.sphere_cells(self.board, hazard.center, hazard.radius_ft))
        self.hazards.append(hazard)

    def active(self, round_index: int) -> list[Hazard]:
        return [h for h in self.hazards
                if h.expires_round is None or round_index <= h.expires_round]

    def prune(self, round_index: int) -> None:
        """Drop expired hazards — cheap housekeeping so the list stays bounded on
        a long burning-building trial."""
        self.hazards = self.active(round_index)

    def covering(self, coord: Optional[tuple], round_index: int) -> list[Hazard]:
        """Active hazards whose footprint covers `coord` (empty if unplaced)."""
        if coord is None:
            return []
        return [h for h in self.active(round_index) if coord in h.cells]
