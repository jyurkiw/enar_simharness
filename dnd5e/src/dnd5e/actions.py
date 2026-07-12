"""Attack / save / heal / utility resolution — the API a creature's turn calls
into (design doc 06's "semantics to preserve exactly" list, sourced from
`dnd5e_combat/engine.py`'s `attack`/`saving_throw`/`deal`/`heal`/`apply`/
`cure`/`simple_attack`). `CombatContext` is this engine's equivalent of the
old `CombatContext` — constructed fresh each trial by `system.py`.

Phase 3 explicitly omits (all later-phase territory): reaction interception
(`_resolve_interception`, Phase 5), Bane/Bless d20 bonus/penalty dice
(no Phase 3 creature casts them), the Bruiser's Mark (Phase 5), opportunity
attacks (Phase 5). Ranged gating and HP/death-save/grapple-release sync are
preserved exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import conditions
from .battlefield import Battlefield
from .creature import ConditionInstance, Creature
from .dice import Resolver
from .effects import EffectScope, apply_effects
from .statblock import Ability


@dataclass(frozen=True)
class AttackOutcome:
    hit: bool
    crit: bool
    damage: int
    target: Optional[Creature] = None
    advantaged: bool = False


class CombatContext:
    """The resolution API a turn's ability resolution calls into. Owns no
    round/turn bookkeeping itself (that's `system.py`) — just attack/save/
    damage/condition mechanics, shared by every trial via a fresh instance."""

    def __init__(self, resolver: Resolver, battlefield: Battlefield, ledger) -> None:
        self.resolver = resolver
        self.battlefield = battlefield
        self.ledger = ledger

    def roll(self, code: str) -> int:
        return self.resolver.damage(code)

    def attack(self, attacker: Creature, target: Creature, *, bonus: int, damage: str,
               crit_range: int = 20, advantage: bool = False, disadvantage: bool = False,
               normal_range: Optional[int] = None, long_range: Optional[int] = None) -> AttackOutcome:
        bf = self.battlefield
        # A condition on the target can hand every attacker advantage; a
        # condition on the attacker can impose disadvantage on it. Advantage
        # and disadvantage still cancel in the resolver.
        if any(c.name in conditions.GRANTS_ATTACKERS_ADVANTAGE for c in target.conditions):
            advantage = True
        if any(c.name in conditions.IMPOSES_ATTACK_DISADVANTAGE for c in attacker.conditions):
            disadvantage = True
        # Outside melee reach, this is a ranged attack: needs line of sight,
        # subject to cover, gated by range bands.
        cover_bonus = 0
        if not bf.in_reach(attacker, target):
            if not bf.can_see(attacker, target) or bf.has_full_cover(attacker, target):
                return AttackOutcome(hit=False, crit=False, damage=0, target=target)
            cover_bonus = bf.cover_ac_bonus(attacker, target)
            if normal_range is not None:
                dist = bf.distance_ft(attacker, target)
                if dist is not None:
                    limit = long_range if long_range is not None else normal_range
                    if dist > limit:
                        return AttackOutcome(hit=False, crit=False, damage=0, target=target)
                    if dist > normal_range:
                        disadvantage = True
        roll = self.resolver.attack(
            bonus, target.statblock.stats.ac + cover_bonus, crit_range=crit_range,
            advantage=advantage, disadvantage=disadvantage,
        )
        base = self.resolver.damage(damage, crit=roll.crit) if (roll.hit and damage) else 0
        return AttackOutcome(hit=roll.hit, crit=roll.crit, damage=base, target=target,
                             advantaged=advantage and not disadvantage)

    def saving_throw(self, creature: Creature, ability: str, dc: int, *,
                     advantage: bool = False, disadvantage: bool = False) -> bool:
        return self.resolver.save(creature.save_mod(ability), dc,
                                  advantage=advantage, disadvantage=disadvantage)

    def deal(self, attacker: Creature, target: Creature, amount: int, action_name: str,
             damage_type: Optional[str] = None) -> int:
        if amount <= 0:
            return 0
        was_down = target.is_down
        self.ledger.record(attacker.instance_name, target.instance_name, action_name, amount, damage_type)
        target.damage_total += amount
        target.current_damage += amount
        self._sync_hp_conditions(target, was_down)
        return amount

    def heal(self, target: Creature, amount: int) -> int:
        if amount <= 0:
            return 0
        was_down = target.is_down
        healed = min(amount, target.current_damage)
        target.current_damage -= healed
        self._sync_hp_conditions(target, was_down)
        return healed

    def _sync_hp_conditions(self, target: Creature, was_down: bool) -> None:
        if target.is_down:
            if not was_down:
                # Newly dropped to 0: begin dying with a clean tally, unless
                # the overkill is massive (>= max HP): instant death.
                target.death_save_successes = 0
                target.death_save_failures = 0
                if target.current_damage - target.hp >= target.hp:
                    target.death_save_failures = 3
                # A grappler that drops releases whoever it was holding.
                for freed_name in self.battlefield.grabbed_targets(target.instance_name):
                    freed = self.battlefield.creatures.get(freed_name)
                    if freed is not None:
                        freed.remove_condition(conditions.GRAPPLED)
                self.battlefield.release(target.instance_name)
        elif was_down:
            # Healed back above 0: conscious again, death saves reset.
            target.death_save_successes = 0
            target.death_save_failures = 0

    def revive_to_one_hp(self, target: Creature) -> None:
        """Natural 20 on a death save: pop back to 1 HP, fully conscious."""
        was_down = target.is_down
        target.current_damage = target.hp - 1
        self._sync_hp_conditions(target, was_down)

    def apply_condition(self, target: Creature, condition: str, *, source: Optional[Creature] = None,
                        escape_dc: Optional[int] = None) -> None:
        if condition == conditions.GRAPPLED and source is not None:
            self.battlefield.grapple(source.instance_name, target.instance_name)
        target.add_condition(ConditionInstance(
            name=condition, source=source.instance_name if source is not None else None,
            escape_dc=escape_dc,
        ))

    def remove_condition(self, target: Creature, condition: str) -> None:
        if condition == conditions.GRAPPLED:
            grappler = self.battlefield.grappled_by(target.instance_name)
            if grappler:
                self.battlefield.release(grappler, target.instance_name)
        target.remove_condition(condition)


def resolve_ability(ctx: CombatContext, actor: Creature, ability: Ability, targets: list) -> None:
    """Resolve one ability against `targets` (usually a single-element list
    in Phase 3, since multi-target selectors are Phase 4)."""
    if ability.kind == "attack":
        for target in targets:
            _resolve_attack(ctx, actor, ability, target)
    elif ability.kind == "save":
        for target in targets:
            _resolve_save(ctx, actor, ability, target)
    elif ability.kind == "heal":
        for target in targets:
            _resolve_heal(ctx, actor, ability, target)
    elif ability.kind == "utility":
        _resolve_utility(ctx, actor, ability)
    else:  # pragma: no cover - loader already enforces the closed kind vocab
        raise ValueError(f"unresolvable ability kind {ability.kind!r}")


def _resolve_attack(ctx: CombatContext, actor: Creature, ability: Ability, target: Creature) -> AttackOutcome:
    out = ctx.attack(actor, target, bonus=ability.to_hit or 0, damage=ability.damage or "",
                     crit_range=ability.crit_range, normal_range=ability.range_normal,
                     long_range=ability.range_long)
    defender = out.target or target
    if out.hit:
        ctx.deal(actor, defender, out.damage, ability.name, ability.damage_type)
        scope = EffectScope(ctx=ctx, source=actor, target=defender)
        apply_effects(ability.on_hit, scope)
        if out.crit:
            apply_effects(ability.on_crit, scope)
    return out


def _resolve_save(ctx: CombatContext, actor: Creature, ability: Ability, target: Creature) -> bool:
    saved = ctx.saving_throw(target, ability.ability, ability.dc or 0)
    dmg = ctx.roll(ability.damage) if ability.damage else 0
    if saved:
        dmg = dmg // 2 if ability.half_on_save else 0
    if dmg:
        ctx.deal(actor, target, dmg, ability.name, ability.damage_type)
    scope = EffectScope(ctx=ctx, source=actor, target=target)
    apply_effects(ability.on_success if saved else ability.on_fail, scope)
    return saved


def _resolve_heal(ctx: CombatContext, actor: Creature, ability: Ability, target: Creature) -> int:
    amount = ctx.roll(ability.amount) if ability.amount else 0
    return ctx.heal(target, amount)


def _resolve_utility(ctx: CombatContext, actor: Creature, ability: Ability) -> None:
    scope = EffectScope(ctx=ctx, source=actor, target=actor)
    apply_effects(ability.effects, scope)
