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

from . import escape_hatch, expressions
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

    def round_number(self) -> int:
        return self._ctx.round_index

    def has_flag(self, name: str) -> bool:
        return self._ctx.flags.has(name)

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
    scope = ConcreteScope(ctx, actor)
    pool = _resolve_targets_selector(ability.targets, scope, ctx)
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


def _resolve_targets_selector(targets_name: Optional[str], scope: ConcreteScope,
                              ctx: BehaviorContext) -> list:
    if targets_name is None:
        actor = scope.self_creature()
        return [e for e in ctx.battlefield.enemies_of(actor) if ctx.battlefield.can_see(actor, e)]
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
