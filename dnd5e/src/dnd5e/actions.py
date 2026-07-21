"""Attack / save / heal / utility resolution — the API a creature's turn calls
into (design doc 06's "semantics to preserve exactly" list, sourced from
`dnd5e_combat/engine.py`'s `attack`/`saving_throw`/`deal`/`heal`/`apply`/
`cure`/`simple_attack`). `CombatContext` is this engine's equivalent of the
old `CombatContext` — constructed fresh each trial by `system.py`.

Ranged gating and HP/death-save/grapple-release sync are preserved exactly.
Phase 4 added Bane/Bless d20 bonus/penalty dice — `attack`/`saving_throw`
consult `conditions.d20_dice` on top of any caller-supplied advantage/
disadvantage. Phase 5 adds reaction interception (`attack` offers `ally_
targeted_by_attack`/`self_targeted_by_attack` to the reaction bus *before*
any roll, design doc 04 section 4's ordering invariant — a `redirect_attack`
effect can change who the attack resolves against, `swap_positions` can
change where either combatant stands, both complete before advantage/
disadvantage/reach/cover/range are computed) and custom-condition grants
(folded generically via `conditions.grants_for`, alongside the RAW-condition
checks that already existed — the Bruiser's Mark's `impose_disadvantage_
except_source` is exactly this, target-conditional so it can't be a blanket
condition check).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import conditions
from .battlefield import Battlefield
from .creature import ConditionInstance, Creature
from .dice import Resolver
from .effects import EffectScope, apply_effects
from .flags import FlagBag
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

    def __init__(self, resolver: Resolver, battlefield: Battlefield, ledger, *,
                 flags: Optional[FlagBag] = None, condition_defs: Optional[dict] = None) -> None:
        self.resolver = resolver
        self.battlefield = battlefield
        self.ledger = ledger
        self.flags = flags if flags is not None else FlagBag()
        # Workspace-wide `dict[str, statblock.ConditionDef]` (design doc 03
        # section 3) — `system.py` builds this once from every roster
        # member's `[conditions.*]`; a condition's *definition* lives on
        # whichever creature file introduces it, but may be *attached* to a
        # creature whose own file never defines it (the Bruiser's Mark,
        # attached to party members).
        self.condition_defs: dict = condition_defs if condition_defs is not None else {}
        # `round_index`/`turn_order`: kept in sync by `system.py.take_turn`
        # each call (cheap — just two attribute writes) so `attack()` can
        # build a `behavior.BehaviorContext` for reaction `when` evaluation
        # without every caller threading them through `resolve_ability`.
        self.round_index = 0
        self.turn_order: list = []
        # `end_trial` state (design doc 03 section 4's `outcome?` primitive,
        # the shadow-otyugh retreat's `force_trial_end` equivalent):
        # `trial_ending` short-circuits `Dnd5eSystem.is_over`; `trial_outcome`
        # accumulates any extra outcome keys to merge into `finalize_trial`'s
        # result (e.g. `{"retreated": 1}`).
        self.trial_ending = False
        self.trial_outcome: dict = {}
        # Reaction-effect side channel (design doc 04 section 4):
        # `redirect_attack`/`swap_positions` write here; `attack()` reads it
        # back immediately after offering the pre-roll reactions.
        self._pending_redirect: Optional[Creature] = None
        # Damage-reduction side channel (design doc 07, Bug A): the
        # `reduce_damage` effect (Uncanny Dodge) multiplies this; `_resolve_
        # attack` resets it before offering `taking_damage` and reads it back
        # before dealing.
        self._pending_damage_reduction: float = 1.0

    def roll(self, code: str, *, crit: bool = False) -> int:
        return self.resolver.damage(code, crit=crit)

    def set_flag(self, name: str, *, scope: str) -> None:
        self.flags.set(name, scope=scope)

    def end_trial(self, *, outcome: Optional[dict] = None) -> None:
        self.trial_ending = True
        if outcome:
            self.trial_outcome.update(outcome)

    def set_pending_redirect(self, to: Creature) -> None:
        self._pending_redirect = to

    def reduce_pending_damage(self, factor: float) -> None:
        self._pending_damage_reduction *= factor

    def offer_taking_damage(self, defender: Creature, amount: int, *, attacker: Creature,
                            ability) -> int:
        """Design doc 04 section 4's `taking_damage` trigger, published for
        *attack* damage only (Uncanny Dodge and Rage resistance both react to
        attacks, not save effects — so `_resolve_save` never calls this).
        Offers the reaction to the defender, then returns the (possibly
        reduced) amount. A no-op fast-path for the overwhelming majority of
        creatures, which declare no reactions at all, so it never perturbs a
        sim without a damage-reducing reactor."""
        if amount <= 0 or not defender.statblock.reactions:
            return amount
        from . import reactions
        from .behavior import BehaviorContext

        self._pending_damage_reduction = 1.0
        behavior_ctx = BehaviorContext(battlefield=self.battlefield, round_index=self.round_index,
                                       turn_order=self.turn_order, flags=self.flags, resolver=self.resolver)
        event = {"attacker": attacker, "target": defender, "ability": ability, "amount": amount}
        reactions.offer("taking_damage", event, candidates=[defender],
                        behavior_ctx=behavior_ctx, combat_ctx=self)
        return round(amount * self._pending_damage_reduction)

    def swap_positions(self, a: Creature, b: Creature) -> None:
        if a.coord is not None and b.coord is not None:
            a.x, a.y, b.x, b.y = b.x, b.y, a.x, a.y

    def _offer_pre_attack_reactions(self, attacker: Creature, target: Creature, ability) -> Creature:
        """Design doc 04 section 4's ordering invariant: `ally_targeted_by_
        attack`/`self_targeted_by_attack` fire — and any redirect/swap they
        cause completes — before any roll math. Returns the (possibly
        redirected) target. A no-op with no matching reaction, so every sim
        without a guardian draws the same dice as before."""
        from . import reactions
        from .behavior import BehaviorContext

        self._pending_redirect = None
        behavior_ctx = BehaviorContext(battlefield=self.battlefield, round_index=self.round_index,
                                       turn_order=self.turn_order, flags=self.flags, resolver=self.resolver)
        event = {"attacker": attacker, "target": target, "ability": ability}
        allies = [c for c in self.battlefield.members(target.side) if c.instance_name != target.instance_name]
        reactions.offer("ally_targeted_by_attack", event, candidates=allies,
                        behavior_ctx=behavior_ctx, combat_ctx=self)
        if self._pending_redirect is None:
            reactions.offer("self_targeted_by_attack", event, candidates=[target],
                            behavior_ctx=behavior_ctx, combat_ctx=self)
        return self._pending_redirect if self._pending_redirect is not None else target

    def attack(self, attacker: Creature, target: Creature, *, bonus: int, damage: str,
               crit_range: int = 20, advantage: bool = False, disadvantage: bool = False,
               normal_range: Optional[int] = None, long_range: Optional[int] = None,
               ability: Optional[Ability] = None) -> AttackOutcome:
        bf = self.battlefield
        target = self._offer_pre_attack_reactions(attacker, target, ability)
        # A condition on the target can hand every attacker advantage; a
        # condition on the attacker can impose disadvantage on it. Advantage
        # and disadvantage still cancel in the resolver.
        if any(c.name in conditions.GRANTS_ATTACKERS_ADVANTAGE for c in target.conditions):
            advantage = True
        if any(c.name in conditions.IMPOSES_ATTACK_DISADVANTAGE for c in attacker.conditions):
            disadvantage = True
        if conditions.grants_for(target, "grant_advantage_to_attackers", condition_defs=self.condition_defs):
            advantage = True
        # A condition on the attacker can hand it advantage on its own attacks
        # (the Barbarian's Reckless Attack).
        if conditions.grants_for(attacker, "grant_self_advantage", condition_defs=self.condition_defs):
            advantage = True
        # Per-attack conditional advantage (the Werewolf's Pack Tactics): an
        # `advantage_when` expression evaluated against the *final* target (post-
        # redirect), with the attacker as `self`. Kept on the ability rather than
        # a condition because it depends on live board state at swing time, not
        # on a flag the attacker carries.
        if ability is not None and ability.advantage_when is not None:
            from . import expressions
            from .behavior import BehaviorContext, ConcreteScope
            adv_ctx = BehaviorContext(battlefield=bf, round_index=self.round_index,
                                      turn_order=self.turn_order, flags=self.flags, resolver=self.resolver)
            if expressions.evaluate(ability.advantage_when, ConcreteScope(adv_ctx, attacker, target=target)):
                advantage = True
        if conditions.grants_for(attacker, "impose_disadvantage", condition_defs=self.condition_defs):
            disadvantage = True
        # Target-conditional (can't be a blanket condition check): the
        # Bruiser's Mark imposes disadvantage on the bearer's attacks against
        # anyone *other* than the mark's source — attacking the source itself
        # is penalty-free. Ends the moment the source is down (`ends_with_
        # source`); attacking someone else stamps the generic marker the
        # `attacked_other_than_source_this_turn` unless-predicate reads.
        for instance in conditions.grants_for(attacker, "impose_disadvantage_except_source",
                                              condition_defs=self.condition_defs):
            source = self.battlefield.creatures.get(instance.source) if instance.source else None
            if source is None or source.is_down:
                attacker.remove_condition(instance.name)
                continue
            if target.instance_name != instance.source:
                disadvantage = True
                attacker.turn_scratch["attacked_other_than_source"] = True
        in_reach = bf.in_reach(attacker, target)
        # Prone (the Wolf's knockdown): a prone TARGET is easy meat in melee
        # (advantage for an attacker in reach) but hard to hit at range
        # (disadvantage); a prone ATTACKER swings at disadvantage. RAW. A prone
        # attacker striking a prone target in melee cancels to a straight roll,
        # which the resolver handles.
        if attacker.has_condition(conditions.PRONE):
            disadvantage = True
        if target.has_condition(conditions.PRONE):
            if in_reach:
                advantage = True
            else:
                disadvantage = True
        # Outside melee reach, this is a ranged attack: subject to cover and
        # gated by range bands.
        #
        # An UNSEEN target is disadvantage, NOT an automatic miss (design doc 07,
        # shadow-sim fix) — the same RAW principle doc 06's Gotcha #6 already
        # applied to the *targeting* pool ("Blinded imposes disadvantage, not an
        # inability to attack"), which had never been carried through to attack
        # *resolution*. Auto-missing here silently reduced the ranger to ~15% of
        # its damage in the darkness sims: it kites outside the dark, shoots into
        # it, and every shot was discarded before a roll. Abilities that genuinely
        # require sight (spells) never reach this point — the sight-gated default
        # targeting pool already excludes an unseen target, so only weapons that
        # opted into `targets = "enemies"` can shoot blind.
        # Full cover remains an auto-miss: there is no line to the target at all.
        cover_bonus = 0
        if not in_reach:
            if bf.has_full_cover(attacker, target):
                return AttackOutcome(hit=False, crit=False, damage=0, target=target)
            if not bf.can_see(attacker, target):
                disadvantage = True
            cover_bonus = bf.cover_ac_bonus(attacker, target)
            if normal_range is not None:
                dist = bf.distance_ft(attacker, target)
                if dist is not None:
                    limit = long_range if long_range is not None else normal_range
                    if dist > limit:
                        return AttackOutcome(hit=False, crit=False, damage=0, target=target)
                    if dist > normal_range:
                        disadvantage = True
        # A temporary AC bonus from a condition on the target (Shield's +5).
        ac_bonus = conditions.ac_bonus_for(target, condition_defs=self.condition_defs)
        bonus_dice, penalty_dice = conditions.d20_dice(c.name for c in attacker.conditions)
        roll = self.resolver.attack(
            bonus, target.statblock.stats.ac + cover_bonus + ac_bonus, crit_range=crit_range,
            advantage=advantage, disadvantage=disadvantage,
            bonus_dice=bonus_dice, penalty_dice=penalty_dice,
        )
        base = self.resolver.damage(damage, crit=roll.crit) if (roll.hit and damage) else 0
        return AttackOutcome(hit=roll.hit, crit=roll.crit, damage=base, target=target,
                             advantaged=advantage and not disadvantage)

    def saving_throw(self, creature: Creature, ability: str, dc: int, *,
                     advantage: bool = False, disadvantage: bool = False) -> bool:
        bonus_dice, penalty_dice = conditions.d20_dice(c.name for c in creature.conditions)
        return self.resolver.save(creature.save_mod(ability), dc,
                                  advantage=advantage, disadvantage=disadvantage,
                                  bonus_dice=bonus_dice, penalty_dice=penalty_dice)

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
        _resolve_utility(ctx, actor, ability, targets)
    else:  # pragma: no cover - loader already enforces the closed kind vocab
        raise ValueError(f"unresolvable ability kind {ability.kind!r}")


def _resolve_attack(ctx: CombatContext, actor: Creature, ability: Ability, target: Creature) -> AttackOutcome:
    out = ctx.attack(actor, target, bonus=ability.to_hit or 0, damage=ability.damage or "",
                     crit_range=ability.crit_range, normal_range=ability.range_normal,
                     long_range=ability.range_long, ability=ability)
    defender = out.target or target
    if out.hit:
        # `taking_damage` reaction (design doc 07, Bug A): Uncanny Dodge can
        # halve the base hit before it lands. Offered for attack damage only,
        # a no-op for defenders with no reactions. on_hit riders below are
        # dealt separately and are NOT reduced (matches the split-`deal`
        # model — a documented limitation for cross-rider cases).
        dealt = ctx.offer_taking_damage(defender, out.damage, attacker=actor, ability=ability)
        ctx.deal(actor, defender, dealt, ability.name, ability.damage_type)
        # `event["crit"]`/`["advantaged"]`: on_hit effects (e.g. the Masked
        # Hector's `damage_rider`) key their own dice off whether *this* hit
        # was a crit/had advantage, same as the base damage did.
        scope = EffectScope(ctx=ctx, source=actor, target=defender,
                            event={"crit": out.crit, "advantaged": out.advantaged})
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


def _resolve_utility(ctx: CombatContext, actor: Creature, ability: Ability, targets: list) -> None:
    """Apply `ability.effects` to each of `targets` (e.g. a party-wide buff
    with `targets = "allies"`), or to the actor itself if the ability
    resolved no targets (e.g. a self-only buff with no `targets` override)."""
    for target in (targets or [actor]):
        scope = EffectScope(ctx=ctx, source=actor, target=target)
        apply_effects(ability.effects, scope)
