"""`Creature`: the mutable per-trial state wrapping an immutable `Statblock`
(design doc 03 section 1). One `Creature` instance persists across every
trial of a run (constructed once at roster build time); `reset_state()` is
called at the start of each trial, mirroring `dnd5e_combat.combatant.Combatant`
but split from its own frozen data (that's `Statblock` now).

Phase 5 update: `ConditionInstance` gains `expires`/`unless`, copied from the
attached condition's `ConditionDef` at attach time (`actions.apply_condition`)
so `system.py`'s clock-tick steps don't need to re-look up the definition —
see `conditions.py`'s module docstring for the clock-keyword/predicate
registries this drives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .dice import Resolver
from .statblock import Statblock


@dataclass
class ConditionInstance:
    name: str
    source: Optional[str] = None       # the source creature's instance_name
    escape_dc: Optional[int] = None
    expires: Optional[str] = None      # a clock keyword, copied from ConditionDef at attach time
    unless: Optional[str] = None       # a predicate name, copied from ConditionDef at attach time


@dataclass
class Creature:
    statblock: Statblock
    instance_name: str      # roster-unique name (creature TOML `name` unless count>1 auto-suffixes it)
    side: str
    tags: tuple[str, ...] = ()
    start_x: Optional[int] = None
    start_y: Optional[int] = None

    # ---- mutable per-trial state (reset by reset_state()) --------------------
    hp: int = field(default=1, init=False)
    current_damage: int = field(default=0, init=False)
    damage_total: int = field(default=0, init=False)
    conditions: list = field(default_factory=list, init=False)
    resources: dict = field(default_factory=dict, init=False)
    death_save_successes: int = field(default=0, init=False)
    death_save_failures: int = field(default=0, init=False)
    x: Optional[int] = field(default=None, init=False)
    y: Optional[int] = field(default=None, init=False)
    trial_scratch: dict = field(default_factory=dict, init=False)
    round_scratch: dict = field(default_factory=dict, init=False)
    turn_scratch: dict = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.x = self.start_x
        self.y = self.start_y
        self.hp = self.statblock.stats.hp_average

    # ---- board position --------------------------------------------------

    @property
    def coord(self) -> Optional[tuple[int, int]]:
        if self.x is None or self.y is None:
            return None
        return (self.x, self.y)

    def place(self, x: int, y: int) -> None:
        self.start_x = self.x = x
        self.start_y = self.y = y

    @property
    def speed_ft(self) -> int:
        return self.statblock.stats.speed

    @property
    def reach_ft(self) -> int:
        return self.statblock.stats.reach

    # ---- HP / death state --------------------------------------------------

    @property
    def hp_remaining(self) -> int:
        return max(self.hp - self.current_damage, 0)

    @property
    def is_bloodied(self) -> bool:
        return self.hp_remaining * 2 <= self.hp

    @property
    def is_down(self) -> bool:
        return self.hp_remaining <= 0

    @property
    def is_dead(self) -> bool:
        return self.death_save_failures >= 3

    @property
    def is_stabilized(self) -> bool:
        return self.death_save_successes >= 3 and not self.is_dead

    def roll_hp(self, resolver: Resolver, *, mode: str) -> None:
        """`mode` is the simulation's `hp_mode`: "average" (default, uses
        `stats.hp_average`) or "rolled" (rolls `stats.hit_dice`, minimum 1)."""
        if mode == "rolled" and self.statblock.stats.hit_dice:
            self.hp = max(1, resolver.roll(self.statblock.stats.hit_dice))
        else:
            self.hp = self.statblock.stats.hp_average

    # ---- abilities / saves --------------------------------------------------

    def save_mod(self, ability: str) -> int:
        return self.statblock.stats.save_mod(ability)

    def has_tag(self, tag: str) -> bool:
        # Union of intrinsic (statblock) and per-combatant tags.
        return tag in self.tags or tag in self.statblock.tags

    # ---- conditions -----------------------------------------------------------

    def has_condition(self, name: str) -> bool:
        return any(c.name == name for c in self.conditions)

    def condition(self, name: str) -> Optional[ConditionInstance]:
        return next((c for c in self.conditions if c.name == name), None)

    def add_condition(self, instance: ConditionInstance) -> None:
        if not self.has_condition(instance.name):
            self.conditions.append(instance)

    def remove_condition(self, name: str) -> None:
        self.conditions = [c for c in self.conditions if c.name != name]

    # ---- lifecycle -----------------------------------------------------------

    def reset_state(self) -> None:
        self.current_damage = 0
        self.damage_total = 0
        self.conditions = []
        self.death_save_successes = 0
        self.death_save_failures = 0
        self.x = self.start_x
        self.y = self.start_y
        self.trial_scratch = {}
        self.round_scratch = {}
        self.turn_scratch = {}
        for name, resource in self.statblock.resources.items():
            self.resources[name] = resource.uses
