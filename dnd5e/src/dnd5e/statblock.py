"""Frozen dataclasses a creature TOML file parses into (design doc 01 section
1). Nothing here does file I/O or validation — that's `loader.py`. All
mutation of per-trial state lives in `creature.py`; everything here is
immutable and shared read-only across every trial of a run.

Phase 3 scope (design doc 06): `EffectCall`/`Trait`/`Reaction`/`Resource` are
schema-complete (so `dnd5e_data`'s files can be authored fully forward), but
`when`/`target_filter` (expressions, Phase 4), `[[behavior.targeting]]`
(Phase 4), `behavior.custom` (the escape hatch, Phase 4), and `[conditions.*]`
(custom conditions, Phase 5) are parsed as absent/rejected by the loader — see
loader.py's phase-boundary checks. The fields exist here now so later phases
don't need to change this module's shape, only the loader's validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# Ability kinds (closed set, design doc 01 section 1.4).
ABILITY_KINDS = frozenset({"attack", "save", "heal", "utility"})

# Movement tactics implemented in Phase 3 (design doc 06); `hunt_light` and
# `guard` are named in the full design doc 01 vocabulary but not implemented
# until later phases — the loader rejects them for now.
PHASE3_TACTICS = frozenset({"engage", "kite", "hold"})


@dataclass(frozen=True)
class EffectCall:
    """One `{ effect = "...", ... }` table from an `on_hit`/`on_fail`/`effects`
    list. `args` is every key besides `effect`, passed through as a plain
    dict — effects.py's registry knows how to read its own arguments,
    including recursively nested effect lists (e.g. `require_save`'s
    `on_fail`)."""

    effect: str
    args: dict = field(default_factory=dict)

    @staticmethod
    def from_dict(d: dict) -> "EffectCall":
        return EffectCall(effect=d["effect"], args={k: v for k, v in d.items() if k != "effect"})


@dataclass(frozen=True)
class Ability:
    name: str
    kind: str  # attack | save | heal | utility

    # attack
    to_hit: Optional[int] = None
    damage: Optional[str] = None
    damage_type: Optional[str] = None
    crit_range: int = 20
    reach: Optional[int] = None
    range_normal: Optional[int] = None
    range_long: Optional[int] = None

    # save (target rolls)
    ability: Optional[str] = None
    dc: Optional[int] = None
    half_on_save: bool = False

    # targeting
    targets: Optional[str] = None
    target_filter: Optional[str] = None
    max_targets: Optional[int] = None

    # heal
    amount: Optional[str] = None
    range: Optional[int] = None

    # shared
    costs: Optional[dict] = None
    uses_bonus_action: bool = False
    description: Optional[str] = None

    on_hit: tuple[EffectCall, ...] = ()
    on_fail: tuple[EffectCall, ...] = ()
    on_crit: tuple[EffectCall, ...] = ()
    on_success: tuple[EffectCall, ...] = ()
    on_all_saved: tuple[EffectCall, ...] = ()
    effects: tuple[EffectCall, ...] = ()  # kind=utility


@dataclass(frozen=True)
class MultiattackOption:
    name: str
    actions: tuple[str, ...]
    when: Optional[str] = None
    priority: int = 0


@dataclass(frozen=True)
class Trait:
    name: str
    description: Optional[str] = None
    effects: tuple[EffectCall, ...] = ()


@dataclass(frozen=True)
class Reaction:
    name: str
    trigger: str
    when: Optional[str] = None
    effects: tuple[EffectCall, ...] = ()
    uses_reaction: bool = False
    uses_bonus_action: bool = False
    priority: int = 0


@dataclass(frozen=True)
class Resource:
    name: str
    uses: int
    recharge: Optional[str] = None  # e.g. "5-6"
    per: Optional[str] = None       # "day" | "encounter"


@dataclass(frozen=True)
class Behavior:
    tactic: str = "engage"
    action_priority: tuple[str, ...] = ()


@dataclass(frozen=True)
class Stats:
    strength: int
    dexterity: int
    constitution: int
    intelligence: int
    wisdom: int
    charisma: int
    ac: int
    speed: int
    initiative_bonus: int
    proficiency: int
    crit_range: int
    reach: int
    hit_dice: Optional[str]
    hp_average: int
    saves: dict = field(default_factory=dict)      # ability -> explicit save modifier
    skills: dict = field(default_factory=dict)
    darkvision: int = 0
    passive_perception: int = 10

    def modifier(self, ability: str) -> int:
        """Ability modifier derived from the raw score: floor((score-10)/2)."""
        score = getattr(self, ability)
        return (score - 10) // 2

    def save_mod(self, ability: str) -> int:
        """Explicit `[stats.saves]` entry wins; otherwise the bare ability
        modifier (design doc 01 section 1.3's derivation rule)."""
        if ability in self.saves:
            return self.saves[ability]
        return self.modifier(ability)


@dataclass(frozen=True)
class Statblock:
    name: str
    display_name: str
    classification: dict
    stats: Stats
    abilities: dict = field(default_factory=dict)       # name -> Ability
    multiattack: dict = field(default_factory=dict)     # name -> MultiattackOption
    traits: dict = field(default_factory=dict)          # name -> Trait
    reactions: dict = field(default_factory=dict)       # name -> Reaction
    resources: dict = field(default_factory=dict)       # name -> Resource
    behavior: Behavior = field(default_factory=Behavior)

    @property
    def challenge_or_level(self):
        return self.classification.get("cr", self.classification.get("level"))
