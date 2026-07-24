"""Frozen dataclasses a creature TOML file parses into (design doc 01 section
1). Nothing here does file I/O or validation — that's `loader.py`. All
mutation of per-trial state lives in `creature.py`; everything here is
immutable and shared read-only across every trial of a run.

Phase 4 update: `MultiattackOption.when`, `Ability.target_filter`, and
`TargetingRule.when` hold **compiled `expressions.Node` ASTs**, not raw
strings — `loader.py` parses and validates them once at load time
(`expressions.parse_and_validate`), so `behavior.py` never re-parses an
expression on the hot path of evaluating it every turn.

Phase 5 update: `[conditions.*]` (custom conditions, `ConditionDef` below) and
`[reactions.*]` (`Reaction.when` now also a compiled `Node`, matching the
others) are implemented — design doc 03 section 3 / doc 04 section 4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .expressions import Node

# Ability kinds (closed set, design doc 01 section 1.4).
ABILITY_KINDS = frozenset({"attack", "save", "heal", "utility"})

# Movement tactics implemented so far (design doc 06); `hunt_light` and
# `guard` are named in the full design doc 01 vocabulary but not implemented
# until later phases — the loader rejects them for now.
KNOWN_TACTICS = frozenset({"engage", "kite", "hold"})

# Targeting order modes (design doc 04 section 3).
TARGETING_ORDERS = frozenset({"nearest", "random", "focus"})


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

    # attack, conditional
    advantage_when: Optional["Node"] = None   # e.g. Pack Tactics — advantage if this holds

    # targeting
    targets: Optional[str] = None
    target_filter: Optional["Node"] = None
    # Area of effect (Lightning Bolt's line, etc.): a `{shape, ...}` dict. When
    # present, targeting is geometric — the caster aims to catch the most
    # enemies, and every enemy in the area is a target (each rolls the save).
    area: Optional[dict] = None
    # Whether the default (no explicit `targets`) enemy pool is filtered to
    # what the actor can SEE. Spells that require sight keep the default True;
    # mundane weapons set it False (you can swing at an unseen foe). This is the
    # correct way to skip the sight requirement for a SINGLE-target attack — the
    # old `targets = "enemies"` trick also switched to set-mode, so a single
    # weapon swing hit *every* enemy (harmless with one enemy, a big bug with a
    # pack).
    requires_sight: bool = True
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
    when: Optional["Node"] = None
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
    when: Optional["Node"] = None
    effects: tuple[EffectCall, ...] = ()
    uses_reaction: bool = False
    uses_bonus_action: bool = False
    priority: int = 0


@dataclass(frozen=True)
class ConditionDef:
    """A `[conditions.<name>]` custom condition definition (design doc 03
    section 3): mechanics live as data (a `grants` list of grant-context
    effect calls, folded generically by `actions.py` — the engine never
    tests condition names), not engine code. Distinct from `creature.
    ConditionInstance` (the per-trial *attached* instance, which carries a
    `source` and copies `expires`/`unless` from here at attach time) — this
    is the immutable, shared definition every instance of the name refers
    back to. Defined once per introducing creature file, but collected
    workspace-wide (`system.py` scans every roster member's `conditions`
    dict) since the condition may be *attached* to a creature whose own file
    never defines it (e.g. the Bruiser's Mark, attached to party members)."""

    name: str
    grants: tuple[EffectCall, ...] = ()
    exclusive: Optional[str] = None       # "per_source" | "per_target" | None
    ends_with_source: bool = True
    expires: Optional[str] = None         # a clock keyword (conditions.CLOCK_KEYWORDS), or None
    unless: Optional[str] = None          # a registered predicate name (conditions.UNLESS_PREDICATES)
    # Only for a `save_ends_*` clock (conditions.SAVE_ENDS_CLOCKS): which save
    # the bearer rolls, against what DC, to shake the condition off.
    save_ability: Optional[str] = None
    save_dc: Optional[int] = None


@dataclass(frozen=True)
class Resource:
    name: str
    uses: int
    recharge: Optional[str] = None  # e.g. "5-6"
    per: Optional[str] = None       # "day" | "encounter"


@dataclass(frozen=True)
class TargetingRule:
    """One `[[behavior.targeting]]` entry (design doc 04 section 3). `when`
    is None for the catch-all fallback rule (matches every pool member)."""

    when: Optional["Node"] = None
    priority: int = 0
    order: str = "nearest"


@dataclass(frozen=True)
class Behavior:
    tactic: str = "engage"
    action_priority: tuple[str, ...] = ()
    targeting: tuple[TargetingRule, ...] = ()
    custom: Optional[str] = None  # "python:module.Class" escape hatch (design doc 04 section 5)


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
    # Intrinsic tags (from the creature file's top-level `tags`). Merged with the
    # per-combatant tags at has_tag time — a capability like "sculpt_spells" or a
    # role like "breaker" belongs on the statblock; scenario-only tags go on the
    # combatant entry.
    tags: tuple[str, ...] = ()
    # Agent-scoped target reservation: if non-empty, ONLY agents carrying one of
    # these tags may target this creature, and those agents *prioritize* it.
    # Everyone else ignores it. (The confessio seal is `engaged_by = ["breaker"]`
    # so the melee run it down and ranged PCs leave it alone.)
    engaged_by: tuple[str, ...] = ()
    abilities: dict = field(default_factory=dict)       # name -> Ability
    multiattack: dict = field(default_factory=dict)     # name -> MultiattackOption
    traits: dict = field(default_factory=dict)          # name -> Trait
    reactions: dict = field(default_factory=dict)       # name -> Reaction
    resources: dict = field(default_factory=dict)       # name -> Resource
    conditions: dict = field(default_factory=dict)      # name -> ConditionDef
    behavior: Behavior = field(default_factory=Behavior)

    @property
    def challenge_or_level(self):
        return self.classification.get("cr", self.classification.get("level"))
