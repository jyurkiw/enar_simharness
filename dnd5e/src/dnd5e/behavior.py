"""Declarative behavior: multiattack selection (design doc 04 section 2) and
targeting (section 3), driven by `expressions.py` against `ConcreteScope` —
this module's implementation of the `expressions.Scope` protocol, wrapping
`Battlefield`/`Creature` state into the queries the expression language needs.

Escape-hatch dispatch (`behavior.custom`, section 5): `select_multiattack`/
`select_targets` check `actor.statblock.behavior.custom` first and call into
`escape_hatch.resolve(...)`'s handler; a hook returning `None` falls through
to the declarative logic below it in the same function, unchanged from
Phase 4's pre-hatch behavior.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from . import aoe, escape_hatch, expressions
from .battlefield import Battlefield
from .creature import Creature
from .dice import Resolver
from .flags import FlagBag
from .statblock import Ability, MultiattackOption

logger = logging.getLogger(__name__)

# Selectors that resolve to a creature SET (vs. a single creature or None).
# Design doc 04 section 3: a `targets` selector that resolves to one of these
# skips target_filter/[[behavior.targeting]]/ordering — the set IS the list.
SET_SELECTORS = frozenset({"enemies", "allies", "enemies_grappled_by_self"})


@dataclass
class BehaviorContext:
    """Everything a turn's behavior decisions need beyond the AST itself."""

    battlefield: Battlefield
    round_index: int
    turn_order: list
    flags: FlagBag
    resolver: Resolver


class ConcreteScope:
    """`expressions.Scope` over live `Battlefield`/`Creature` state."""

    def __init__(self, ctx: BehaviorContext, self_creature: Creature, *,
                 target: Optional[Creature] = None, it: Optional[Creature] = None,
                 event: Optional[dict] = None) -> None:
        self._ctx = ctx
        self._self = self_creature
        self._target = target
        self._it = it
        self._event = event or {}

    @property
    def battlefield(self) -> Battlefield:
        """Escape-hatch access (design doc 04 section 5): a hatch's
        `plan_movement` needs board/occupancy queries the expression-function
        vocabulary doesn't cover (e.g. "farthest reachable cell from X")."""
        return self._ctx.battlefield

    @property
    def resolver(self):
        """The trial's seeded dice, for a hatch that makes a *random* decision
        (e.g. the evoker's per-round chance to spend a Lightning Bolt slot).
        Always the trial stream — never Python's `random`."""
        return self._ctx.resolver

    @property
    def round_index(self) -> int:
        return self._ctx.round_index

    # ---- single-creature selectors -----------------------------------------

    def self_creature(self):
        return self._self

    def target_creature(self):
        return self._target

    def it_creature(self):
        return self._it

    def event_field(self, name: str):
        return self._event.get(name)

    # ---- creature-set selectors ---------------------------------------------

    def enemies(self):
        return self._ctx.battlefield.enemies_of(self._self)

    def allies(self):
        return self._ctx.battlefield.allies_of(self._self)

    def enemies_grappled_by_self(self):
        bf = self._ctx.battlefield
        names = bf.grabbed_targets(self._self.instance_name)
        enemy_names = {e.instance_name for e in self.enemies()}
        return [bf.creatures[n] for n in names if n in enemy_names]

    def downed_allies(self):
        """Same-side creatures that are Down — the healer's triage pool.
        `allies()` can't serve this: `battlefield.allies_of` filters the Down
        out (correctly, so buffs/most targeting skip them), which would make
        `any(allies, is_down(it))` permanently false."""
        bf = self._ctx.battlefield
        return [c for c in bf.members(self._self.side)
                if c.is_down and c.instance_name != self._self.instance_name]

    def enemies_within(self, ft: float):
        bf = self._ctx.battlefield
        return [e for e in self.enemies() if (bf.distance_ft(self._self, e) or 0) <= ft]

    def allies_within(self, ft: float):
        bf = self._ctx.battlefield
        return [a for a in self.allies() if (bf.distance_ft(self._self, a) or 0) <= ft]

    def enemies_tagged(self, tag: str):
        return [e for e in self.enemies() if e.has_tag(tag)]

    def allies_tagged(self, tag: str):
        return [a for a in self.allies() if a.has_tag(tag)]

    def enemies_within_of(self, who, ft: float):
        bf = self._ctx.battlefield
        return [e for e in self.enemies() if (bf.distance_ft(who, e) or 0) <= ft]

    def allies_within_of(self, who, ft: float):
        # Living allies (excludes self and the Down) within `ft` of `who` — the
        # Werewolf's Pack Tactics asks "is another pack member next to my target".
        bf = self._ctx.battlefield
        return [a for a in self.allies() if (bf.distance_ft(who, a) or 0) <= ft]

    def nearest_enemy(self):
        return self._ctx.battlefield.nearest_enemy(self._self)

    def ally_lowest_hp(self):
        allies = self.allies()
        return min(allies, key=lambda a: a.hp_remaining) if allies else None

    # ---- functions --------------------------------------------------------------

    def nearest(self, creatures):
        if not creatures:
            return None
        big = 1 << 30
        return min(creatures, key=lambda c: self._ctx.battlefield.distance_ft(self._self, c) or big)

    def farthest(self, creatures):
        if not creatures:
            return None
        return max(creatures, key=lambda c: self._ctx.battlefield.distance_ft(self._self, c) or -1)

    def has_condition(self, who, name: str) -> bool:
        return who.has_condition(name)

    def has_tag(self, who, tag: str) -> bool:
        return who.has_tag(tag)

    def hp(self, who) -> float:
        return who.hp_remaining

    def hp_pct(self, who) -> float:
        return who.hp_remaining / who.hp if who.hp else 0.0

    def is_bloodied(self, who) -> bool:
        return who.is_bloodied

    def is_down(self, who) -> bool:
        return who.is_down

    def distance(self, a, b) -> float:
        return self._ctx.battlefield.distance_ft(a, b) or 0.0

    def can_see(self, a, b) -> bool:
        return self._ctx.battlefield.can_see(a, b)

    def in_reach(self, a, b) -> bool:
        return self._ctx.battlefield.in_reach(a, b)

    def is_grappling(self, a, b) -> bool:
        return self._ctx.battlefield.grappled_by(b.instance_name) == a.instance_name

    def is_grappled_by(self, a, b) -> bool:
        return self._ctx.battlefield.grappled_by(a.instance_name) == b.instance_name

    def is_grappled(self, who) -> bool:
        return self._ctx.battlefield.grappled_by(who.instance_name) is not None

    def resource_available(self, name: str) -> bool:
        return self._self.resources.get(name, 0) > 0

    def aoe_targets(self, ability_name: str) -> int:
        """How many enemies this creature's area ability would catch RIGHT NOW,
        aimed optimally from its current cell along a line that hits no allies.
        Lets a `when` gate a spell on "is it worth a slot?" — e.g.
        `aoe_targets('lightning_bolt') >= 2`. Returns 0 for an unknown or
        non-area ability (so the gate simply never fires)."""
        ability = self._self.statblock.abilities.get(ability_name)
        if ability is None or ability.area is None:
            return 0
        return len(_area_targets(self._self, ability, self._ctx))

    def round_number(self) -> int:
        return self._ctx.round_index

    def has_flag(self, name: str) -> bool:
        return self._ctx.flags.has(name)

    def turn_marked(self, key: str) -> bool:
        """Read a once-per-turn toggle the `mark_turn` effect set on the
        acting creature's `turn_scratch` (Sneak Attack's first-hit gate).
        `self` here is always the effect's source — the creature whose turn it
        is — because effect `when` scopes bind `self` to the acting creature."""
        return bool(self._self.turn_scratch.get(key, False))

    def any_yet_to_act(self, creatures) -> bool:
        order = self._ctx.turn_order
        self_idx = order.index(self._self.instance_name) if self._self.instance_name in order else -1
        for c in creatures:
            if c.instance_name in order and order.index(c.instance_name) > self_idx:
                return True
        return False

    def side_of(self, who) -> str:
        return who.side

    def with_it(self, creature) -> "ConcreteScope":
        return ConcreteScope(self._ctx, self._self, target=self._target, it=creature, event=self._event)

    def eval(self, source: str):
        """Escape-hatch convenience (design doc 04 section 5): evaluate a
        `when`-language expression string against this same scope, so a
        `behavior.custom` handler can lean on the declarative vocabulary
        instead of re-deriving a query by hand."""
        return expressions.evaluate(expressions.parse_and_validate(source, where="escape_hatch"), self)


# =============================================================================
# Multiattack selection (design doc 04 section 2)
# =============================================================================


def select_multiattack(actor: Creature, ctx: BehaviorContext) -> Optional[MultiattackOption]:
    options = list(actor.statblock.multiattack.values())
    if not options:
        priority = actor.statblock.behavior.action_priority
        if priority:
            return MultiattackOption(name="_implicit", actions=(priority[0],), priority=0)
        return None

    scope = ConcreteScope(ctx, actor)

    custom = actor.statblock.behavior.custom
    if custom is not None:
        chosen_name = escape_hatch.resolve(custom).choose_multiattack(actor, scope)
        if chosen_name is not None:
            return actor.statblock.multiattack[chosen_name]

    eligible = []
    for opt in options:
        if not _costs_available(opt, actor):
            continue
        if opt.when is not None and not expressions.evaluate(opt.when, scope):
            continue
        eligible.append(opt)

    if eligible:
        return max(eligible, key=lambda o: o.priority)

    # Nothing eligible: fall back to the lowest-priority option and warn
    # (design doc 04 section 2 point 4) — a monster should never stand idle
    # because of a data bug.
    fallback = min(options, key=lambda o: o.priority)
    logger.warning("no eligible multiattack option for %s; falling back to %r",
                   actor.instance_name, fallback.name)
    return fallback


def _costs_available(option: MultiattackOption, actor: Creature) -> bool:
    for action_name in option.actions:
        ability = actor.statblock.abilities[action_name]
        if ability.costs:
            resource_name = ability.costs.get("resource")
            amount = ability.costs.get("amount", 1)
            if resource_name and actor.resources.get(resource_name, 0) < amount:
                return False
    return True


# =============================================================================
# Targeting (design doc 04 section 3)
# =============================================================================


def select_targets(actor: Creature, ability: Ability, ctx: BehaviorContext) -> list:
    if ability.area is not None:
        # Geometric area of effect (Lightning Bolt's line, etc.): the caster
        # aims to catch the most enemies, and *every* enemy in the shape is a
        # target — the save (`kind = "save"`) is then rolled once per target by
        # actions.resolve_ability's per-target loop, exactly like the RAW "each
        # creature in the line makes a Dexterity save".
        return _area_targets(actor, ability, ctx)

    scope = ConcreteScope(ctx, actor)
    pool = _resolve_targets_selector(ability.targets, scope, ctx, requires_sight=ability.requires_sight)
    is_set_selector = ability.targets in SET_SELECTORS

    if ability.target_filter is not None:
        pool = [c for c in pool
                if expressions.evaluate(ability.target_filter, ConcreteScope(ctx, actor, target=c))]

    if is_set_selector:
        # design doc 04 section 3: set selectors skip filter-rule/order steps,
        # and (unlike the ordered path below) an unset `max_targets` means
        # "the whole set", not "just one" — the set selector already picked
        # exactly the members that matter (e.g. every current grapple
        # captive), so there's no implicit single-target default to fall
        # back to.
        ordered = pool
    else:
        order = "nearest"
        for rule in sorted(actor.statblock.behavior.targeting, key=lambda r: -r.priority):
            if rule.when is None:
                matching = pool
            else:
                matching = [c for c in pool
                           if expressions.evaluate(rule.when, ConcreteScope(ctx, actor, target=c))]
            if matching:
                pool = matching
                order = rule.order
                break
        ordered = _order_pool(pool, order, actor, ctx)

    custom = actor.statblock.behavior.custom
    if custom is not None and ordered:
        # The hatch picks (or confirms) only the *primary* target; any
        # remaining slots (multi-target abilities) keep the declarative
        # order behind it (design doc 04 section 5: override only what the
        # hatch must).
        chosen = escape_hatch.resolve(custom).choose_target(actor, ability, ordered, scope)
        if chosen is not None:
            ordered = [chosen] + [c for c in ordered if c is not chosen]

    if is_set_selector:
        return ordered[:ability.max_targets] if ability.max_targets else ordered
    return ordered[:ability.max_targets or 1]


# -----------------------------------------------------------------------------
# Area-of-effect targeting (design doc 04 — geometric shapes)
# -----------------------------------------------------------------------------
#
# The geometry lives in `aoe.py`; here we just pick the best clean line. A
# 5-ft-wide line on a 5-ft grid is one cell wide, so it's a single ray from the
# caster, aimed (smartly, toward an enemy) to clip the most foes. Lines that
# would also catch an ally are rejected — a 5th-level evoker has no Sculpt
# Spells, so a PC in the line eats the bolt too. This slightly under-counts vs a
# tabletop (a foe one cell off the ray isn't caught) but captures the thing that
# matters: a clustered pack lets one bolt hit several bodies without frying the
# party, a mixed scrum doesn't.


def _area_targets(actor: Creature, ability: Ability, ctx: BehaviorContext) -> list:
    choice = aoe.best_area(ctx.battlefield, actor, ability.area, allow_allies=False, min_enemies=1)
    return choice[0] if choice is not None else []


def _resolve_targets_selector(targets_name: Optional[str], scope: ConcreteScope,
                              ctx: BehaviorContext, *, requires_sight: bool = True) -> list:
    if targets_name is None:
        # The default single-target enemy pool. Sight-filtered unless the
        # ability opted out (`requires_sight = false` — a mundane weapon).
        actor = scope.self_creature()
        enemies = ctx.battlefield.enemies_of(actor)
        if requires_sight:
            enemies = [e for e in enemies if ctx.battlefield.can_see(actor, e)]
        return enemies
    node = expressions.Selector((targets_name,))
    result = expressions.evaluate(node, scope)
    if result is None:
        return []
    if isinstance(result, (list, tuple)):
        return list(result)
    return [result]


def _order_pool(pool: list, order: str, actor: Creature, ctx: BehaviorContext) -> list:
    if order == "nearest":
        big = 1 << 30
        # Stable sort: `pool` is already in roster order, so equal-distance
        # ties keep it (design doc 04 section 3: "ties by roster order").
        return sorted(pool, key=lambda c: ctx.battlefield.distance_ft(actor, c) or big)
    if order == "focus":
        focus_name = ctx.battlefield.focus.get(actor.side)
        if focus_name:
            focused = [c for c in pool if c.instance_name == focus_name]
            if focused:
                rest = [c for c in pool if c.instance_name != focus_name]
                return focused + rest
        return list(pool)
    if order == "random":
        # Drawn from the trial's own seeded stream (design doc 04 section 3)
        # — never Python's `random` module.
        remaining = list(pool)
        picked = []
        while remaining:
            idx = ctx.resolver.roll(f"1d{len(remaining)}") - 1
            picked.append(remaining.pop(idx))
        return picked
    raise ValueError(f"unknown targeting order {order!r}")  # pragma: no cover (validated at load)
