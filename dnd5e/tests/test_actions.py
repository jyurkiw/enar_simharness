import pytest
from dnd_board import load_board_toml
from simharness.ledger import Ledger

from dnd5e import conditions
from dnd5e.actions import CombatContext, resolve_ability
from dnd5e.battlefield import Battlefield
from dnd5e.creature import ConditionInstance, Creature
from dnd5e.dice import Resolver
from dnd5e.effects import EffectScope, apply_effect
from dnd5e.statblock import Ability, ConditionDef, EffectCall, Reaction, Statblock, Stats


class ScriptedDice:
    def __init__(self, values):
        self._values = list(values)

    def roll(self, code):
        return self._values.pop(0)


OPEN_BOARD = '''
name = "open"
map = """
..........
..........
"""
[meta]
cell_feet = 5
'''

RANGED_BOARD = '''
name = "ranged"
map = """
....................
....................
"""
[meta]
cell_feet = 5
'''

COVER_BOARD = '''
name = "cover"
map = """
....................
.........o..........
....................
"""
[meta]
cell_feet = 5
[glyph.'o']
terrain = "impassable"
cover = "three_quarters"
blocks_los = false
'''

WALL_BOARD = '''
name = "wall"
map = """
....................
.........#..........
....................
"""
[meta]
cell_feet = 5
[glyph.'#']
terrain = "impassable"
cover = "full"
blocks_los = true
blocks_light = true
'''


def make_board(tmp_path, text, name):
    p = tmp_path / f"{name}.toml"
    p.write_text(text)
    return load_board_toml(p)


def make_stats(**overrides):
    base = dict(strength=16, dexterity=11, constitution=19, intelligence=6, wisdom=13,
               charisma=6, ac=14, speed=30, initiative_bonus=0, proficiency=3,
               crit_range=20, reach=5, hit_dice="12d10+48", hp_average=40,
               saves={"constitution": 7})
    base.update(overrides)
    return Stats(**base)


def make_creature(name, side, x, y, **stat_overrides):
    sb = Statblock(name=name, display_name=name, classification={}, stats=make_stats(**stat_overrides))
    c = Creature(statblock=sb, instance_name=name, side=side)
    c.place(x, y)
    return c


def make_ctx(board, dice_values, creatures):
    bf = Battlefield(creatures, board=board)
    ledger = Ledger(names=[c.instance_name for c in creatures],
                    side_of={c.instance_name: c.side for c in creatures})
    ctx = CombatContext(Resolver(ScriptedDice(dice_values)), bf, ledger)
    return ctx, bf, ledger


# ---- attack(): basic hit/miss, advantage/disadvantage ------------------------

def test_attack_hits_when_total_meets_ac(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    a = make_creature("fighter", "party", 0, 0)
    b = make_creature("otyugh", "monsters", 1, 0)
    ctx, _, _ = make_ctx(board, [10, 7], [a, b])  # d20=10, damage=7
    out = ctx.attack(a, b, bonus=5, damage="1d8+4")  # total=15, ac=14
    assert out.hit is True
    assert out.damage == 7


def test_attack_misses_when_total_below_ac(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    a = make_creature("fighter", "party", 0, 0)
    b = make_creature("otyugh", "monsters", 1, 0)
    ctx, _, _ = make_ctx(board, [5], [a, b])  # d20=5, bonus=0 -> total=5 < ac 14
    out = ctx.attack(a, b, bonus=0, damage="1d8+4")
    assert out.hit is False
    assert out.damage == 0


def test_attack_target_blinded_grants_attacker_advantage(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    a = make_creature("fighter", "party", 0, 0)
    b = make_creature("otyugh", "monsters", 1, 0)
    b.add_condition(ConditionInstance(name=conditions.BLINDED))
    ctx, _, _ = make_ctx(board, [5, 18, 7], [a, b])  # advantage: rolls 5 and 18, keep 18
    out = ctx.attack(a, b, bonus=0, damage="1d8+4")
    assert out.hit is True  # 18 >= ac 14


def test_attack_attacker_blinded_imposes_disadvantage(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    a = make_creature("fighter", "party", 0, 0)
    a.add_condition(ConditionInstance(name=conditions.BLINDED))
    b = make_creature("otyugh", "monsters", 1, 0)
    ctx, _, _ = make_ctx(board, [18, 5], [a, b])  # disadvantage: rolls 18 and 5, keep 5
    out = ctx.attack(a, b, bonus=0, damage="1d8+4")
    assert out.hit is False  # 5 < ac 14


def test_natural_1_misses_regardless_of_bonus(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    a = make_creature("fighter", "party", 0, 0)
    b = make_creature("otyugh", "monsters", 1, 0)
    ctx, _, _ = make_ctx(board, [1], [a, b])
    out = ctx.attack(a, b, bonus=50, damage="1d8+4")
    assert out.hit is False


def test_natural_20_always_crits_and_hits(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    a = make_creature("fighter", "party", 0, 0)
    b = make_creature("otyugh", "monsters", 1, 0)
    ctx, _, _ = make_ctx(board, [20, 14], [a, b])  # d20=20 crit, damage rolled with crit_code doubling
    out = ctx.attack(a, b, bonus=-50, damage="1d8")
    assert out.hit is True and out.crit is True


# ---- attack(): ranged gating ---------------------------------------------------

def test_ranged_attack_beyond_long_range_auto_misses(tmp_path):
    board = make_board(tmp_path, RANGED_BOARD, "ranged")
    a = make_creature("archer", "party", 0, 0)
    b = make_creature("otyugh", "monsters", 19, 0)  # 95 ft away
    ctx, _, _ = make_ctx(board, [], [a, b])
    out = ctx.attack(a, b, bonus=7, damage="1d8+4", normal_range=30, long_range=60)
    assert out.hit is False


def test_ranged_attack_beyond_normal_within_long_imposes_disadvantage(tmp_path):
    board = make_board(tmp_path, RANGED_BOARD, "ranged")
    a = make_creature("archer", "party", 0, 0)
    b = make_creature("otyugh", "monsters", 10, 0)  # 50 ft: beyond normal(30), within long(60)
    ctx, _, _ = make_ctx(board, [18, 3], [a, b])  # disadvantage -> min(18,3)=3
    out = ctx.attack(a, b, bonus=7, damage="1d8+4", normal_range=30, long_range=60)
    assert out.hit is False  # 3+7=10 < ac 14


def test_ranged_attack_within_normal_range_no_penalty(tmp_path):
    board = make_board(tmp_path, RANGED_BOARD, "ranged")
    a = make_creature("archer", "party", 0, 0)
    b = make_creature("otyugh", "monsters", 4, 0)  # 20 ft, within normal(30)
    ctx, _, _ = make_ctx(board, [10, 7], [a, b])
    out = ctx.attack(a, b, bonus=7, damage="1d8+4", normal_range=30, long_range=60)
    assert out.hit is True  # 10+7=17 >= ac 14


def test_ranged_attack_no_long_range_uses_normal_as_hard_limit(tmp_path):
    board = make_board(tmp_path, RANGED_BOARD, "ranged")
    a = make_creature("archer", "party", 0, 0)
    b = make_creature("otyugh", "monsters", 10, 0)  # 50 ft, beyond normal(30), no long given
    ctx, _, _ = make_ctx(board, [], [a, b])
    out = ctx.attack(a, b, bonus=7, damage="1d8+4", normal_range=30, long_range=None)
    assert out.hit is False  # past the only limit given -> auto-miss


def test_full_cover_auto_misses(tmp_path):
    board = make_board(tmp_path, WALL_BOARD, "wall")
    a = make_creature("archer", "party", 0, 1)
    b = make_creature("otyugh", "monsters", 19, 1)  # wall directly between
    ctx, _, _ = make_ctx(board, [], [a, b])
    out = ctx.attack(a, b, bonus=7, damage="1d8+4", normal_range=150, long_range=600)
    assert out.hit is False


def test_three_quarters_cover_adds_ac_bonus(tmp_path):
    board = make_board(tmp_path, COVER_BOARD, "cover")
    a = make_creature("archer", "party", 0, 1)
    b = make_creature("otyugh", "monsters", 19, 1, ac=10)  # pillar between, +5 AC -> effective 15
    ctx, _, _ = make_ctx(board, [10], [a, b])  # bonus 4 -> total 14, would hit ac10 but not ac15
    out = ctx.attack(a, b, bonus=4, damage="1d8+4", normal_range=150, long_range=600)
    assert out.hit is False  # 14 < 10+5


def test_melee_attack_ignores_range_bands_when_in_reach(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    a = make_creature("fighter", "party", 0, 0)
    b = make_creature("otyugh", "monsters", 1, 0)  # adjacent, in reach
    ctx, _, _ = make_ctx(board, [10, 7], [a, b])  # d20=10 hits (15>=14), damage=7
    out = ctx.attack(a, b, bonus=5, damage="1d8+4")  # no range args at all
    assert out.hit is True
    assert out.damage == 7


# ---- attack(): reaction interception (design doc 04 section 4's ordering invariant) ----

def test_attack_ally_targeted_reaction_redirects_before_the_roll(tmp_path):
    """`ally_targeted_by_attack` fires and its `redirect_attack` completes
    *before* advantage/disadvantage/AC are read for the roll — proven by
    giving the redirect target a much higher AC than the original target: if
    the roll read the original target's AC, an 18 would hit; it doesn't,
    because the swap already happened before `resolver.attack` ran."""
    board = make_board(tmp_path, OPEN_BOARD, "open")
    a = make_creature("archer", "party", 0, 0)
    b = make_creature("fighter", "monsters", 1, 0, ac=14)
    protector_sb = Statblock(
        name="protector", display_name="protector", classification={}, stats=make_stats(ac=99),
        reactions={"intercept": Reaction(name="intercept", trigger="ally_targeted_by_attack",
                                         effects=(EffectCall(effect="redirect_attack", args={"to": "self"}),),
                                         uses_reaction=True)},
    )
    c = Creature(statblock=protector_sb, instance_name="protector", side="monsters")
    c.place(2, 0)
    ctx, _, _ = make_ctx(board, [12], [a, b, c])  # 12+6=18: would hit fighter's ac14, not protector's ac99
    out = ctx.attack(a, b, bonus=6, damage="1d8+3")
    assert out.hit is False
    assert out.target is c
    assert c.round_scratch.get("reaction_used") is True


def test_attack_with_no_matching_reaction_is_unaffected(tmp_path):
    """No candidate has a matching reaction: `_offer_pre_attack_reactions` is
    a no-op, and the attack resolves against the original target exactly as
    if reactions didn't exist."""
    board = make_board(tmp_path, OPEN_BOARD, "open")
    a = make_creature("fighter", "party", 0, 0)
    b = make_creature("otyugh", "monsters", 1, 0)
    ctx, _, _ = make_ctx(board, [10, 7], [a, b])
    out = ctx.attack(a, b, bonus=5, damage="1d8+4")
    assert out.hit is True
    assert out.target is b


# ---- saving_throw ---------------------------------------------------------------

def test_saving_throw_uses_creature_save_mod(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    a = make_creature("otyugh", "monsters", 0, 0)
    b = make_creature("fighter", "party", 1, 0, saves={"constitution": 2})
    ctx, _, _ = make_ctx(board, [10], [a, b])
    assert ctx.saving_throw(b, "constitution", 12) is True  # 10+2=12 >= dc12


def test_saving_throw_fails_below_dc(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    a = make_creature("otyugh", "monsters", 0, 0)
    b = make_creature("fighter", "party", 1, 0, saves={"constitution": 2})
    ctx, _, _ = make_ctx(board, [5], [a, b])
    assert ctx.saving_throw(b, "constitution", 12) is False  # 5+2=7 < dc12


# ---- deal / heal / hp sync -------------------------------------------------------

def test_deal_records_to_ledger_and_updates_damage(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    a = make_creature("fighter", "party", 0, 0)
    b = make_creature("otyugh", "monsters", 1, 0, hp_average=40)
    ctx, _, ledger = make_ctx(board, [], [a, b])
    ctx.deal(a, b, 10, "longsword", "slashing")
    assert b.current_damage == 10
    assert b.damage_total == 10
    ledger.finalize_trial()
    assert ledger.rows[0]["dealt_fighter"] == 10
    assert ledger.rows[0]["taken_otyugh"] == 10


def test_deal_non_positive_amount_is_noop(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    a = make_creature("fighter", "party", 0, 0)
    b = make_creature("otyugh", "monsters", 1, 0)
    ctx, _, _ = make_ctx(board, [], [a, b])
    assert ctx.deal(a, b, 0, "x") == 0
    assert b.current_damage == 0


def test_dropping_to_zero_begins_dying_with_clean_tally(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    a = make_creature("fighter", "party", 0, 0)
    b = make_creature("otyugh", "monsters", 1, 0, hp_average=20)
    ctx, _, _ = make_ctx(board, [], [a, b])
    b.death_save_failures = 2  # stale state from a prior down (shouldn't matter)
    ctx.deal(a, b, 20, "x")
    assert b.is_down
    assert b.death_save_failures == 0
    assert b.death_save_successes == 0


def test_massive_overkill_is_instant_death(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    a = make_creature("fighter", "party", 0, 0)
    b = make_creature("otyugh", "monsters", 1, 0, hp_average=20)
    ctx, _, _ = make_ctx(board, [], [a, b])
    ctx.deal(a, b, 40, "x")  # current_damage(40) - hp(20) = 20 >= hp(20) -> instant death
    assert b.is_dead


def test_moderate_overkill_is_not_instant_death(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    a = make_creature("fighter", "party", 0, 0)
    b = make_creature("otyugh", "monsters", 1, 0, hp_average=20)
    ctx, _, _ = make_ctx(board, [], [a, b])
    ctx.deal(a, b, 25, "x")  # overkill 5 < hp 20
    assert b.is_down
    assert not b.is_dead


def test_dropping_a_grappler_releases_its_captives(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    otyugh = make_creature("otyugh", "monsters", 0, 0, hp_average=20)
    fighter = make_creature("fighter", "party", 1, 0)
    ctx, bf, _ = make_ctx(board, [], [otyugh, fighter])
    bf.grapple("otyugh", "fighter")
    fighter.add_condition(ConditionInstance(name=conditions.GRAPPLED, source="otyugh"))

    ctx.deal(fighter, otyugh, 20, "x")  # otyugh drops

    assert otyugh.is_down
    assert bf.grappled_by("fighter") is None
    assert not fighter.has_condition(conditions.GRAPPLED)


def test_heal_reduces_current_damage_not_damage_total(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    a = make_creature("cleric", "party", 0, 0)
    b = make_creature("fighter", "party", 1, 0, hp_average=40)
    ctx, _, _ = make_ctx(board, [], [a, b])
    b.current_damage = 20
    b.damage_total = 20
    healed = ctx.heal(b, 8)
    assert healed == 8
    assert b.current_damage == 12
    assert b.damage_total == 20  # never decreases


def test_heal_clamps_to_current_damage_not_overhealing(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    a = make_creature("cleric", "party", 0, 0)
    b = make_creature("fighter", "party", 1, 0, hp_average=40)
    ctx, _, _ = make_ctx(board, [], [a, b])
    b.current_damage = 5
    healed = ctx.heal(b, 999)  # way more than the 5 damage present
    assert healed == 5
    assert b.current_damage == 0


def test_heal_non_positive_amount_is_noop(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    a = make_creature("cleric", "party", 0, 0)
    b = make_creature("fighter", "party", 1, 0, hp_average=40)
    ctx, _, _ = make_ctx(board, [], [a, b])
    b.current_damage = 5
    assert ctx.heal(b, 0) == 0
    assert b.current_damage == 5


def test_healing_from_down_resets_death_saves(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    a = make_creature("cleric", "party", 0, 0)
    b = make_creature("fighter", "party", 1, 0, hp_average=20)
    ctx, _, _ = make_ctx(board, [], [a, b])
    ctx.deal(a, b, 20, "x")  # oops, friendly fire test setup: just to get it down
    b.death_save_failures = 2
    ctx.heal(b, 5)
    assert not b.is_down
    assert b.death_save_failures == 0


def test_revive_to_one_hp_clears_down_and_resets_death_saves(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    a = make_creature("cleric", "party", 0, 0)
    b = make_creature("fighter", "party", 1, 0, hp_average=20)
    ctx, _, _ = make_ctx(board, [], [a, b])
    ctx.deal(a, b, 20, "x")  # drop to 0
    b.death_save_failures = 2
    ctx.revive_to_one_hp(b)
    assert b.hp_remaining == 1
    assert not b.is_down
    assert b.death_save_failures == 0


# ---- conditions -------------------------------------------------------------------

def test_apply_condition_grappled_wires_the_grapple_graph(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    otyugh = make_creature("otyugh", "monsters", 0, 0)
    fighter = make_creature("fighter", "party", 1, 0)
    ctx, bf, _ = make_ctx(board, [], [otyugh, fighter])
    ctx.apply_condition(fighter, conditions.GRAPPLED, source=otyugh, escape_dc=13)
    assert fighter.has_condition(conditions.GRAPPLED)
    assert fighter.condition(conditions.GRAPPLED).escape_dc == 13
    assert bf.grappled_by("fighter") == "otyugh"


def test_remove_condition_grappled_releases_the_grapple_graph(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    otyugh = make_creature("otyugh", "monsters", 0, 0)
    fighter = make_creature("fighter", "party", 1, 0)
    ctx, bf, _ = make_ctx(board, [], [otyugh, fighter])
    ctx.apply_condition(fighter, conditions.GRAPPLED, source=otyugh)
    ctx.remove_condition(fighter, conditions.GRAPPLED)
    assert not fighter.has_condition(conditions.GRAPPLED)
    assert bf.grappled_by("fighter") is None


def test_attach_condition_per_source_exclusive_moves_between_bearers(tmp_path):
    """The Bruiser's Mark's RAW "only one creature marked at a time":
    `exclusive = "per_source"` detaches the same source's existing instance
    from whoever else holds it when it's attached to a new bearer."""
    board = make_board(tmp_path, OPEN_BOARD, "open")
    bruiser = make_creature("bruiser", "monsters", 0, 0)
    fighter_a = make_creature("fighterA", "party", 1, 0)
    fighter_b = make_creature("fighterB", "party", 2, 0)
    ctx, _, _ = make_ctx(board, [], [bruiser, fighter_a, fighter_b])
    ctx.condition_defs = {"marked": ConditionDef(name="marked", exclusive="per_source")}

    apply_effect(EffectCall(effect="attach_condition", args={"condition": "marked"}),
                EffectScope(ctx=ctx, source=bruiser, target=fighter_a))
    assert fighter_a.has_condition("marked")

    apply_effect(EffectCall(effect="attach_condition", args={"condition": "marked"}),
                EffectScope(ctx=ctx, source=bruiser, target=fighter_b))
    assert fighter_b.has_condition("marked")
    assert not fighter_a.has_condition("marked")  # exclusivity moved it, didn't duplicate it


# ---- resolve_ability ----------------------------------------------------------------

def test_resolve_attack_ability_deals_damage_and_runs_on_hit(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    otyugh = make_creature("otyugh", "monsters", 0, 0)
    fighter = make_creature("fighter", "party", 1, 0, hp_average=40)
    ctx, _, ledger = make_ctx(board, [15, 5], [otyugh, fighter])
    ability = Ability(name="tentacle", kind="attack", to_hit=6, damage="1d8+3", damage_type="bludgeoning",
                      on_hit=(EffectCall(effect="attach_condition", args={"condition": "grappled", "escape_dc": 13}),))
    resolve_ability(ctx, otyugh, ability, [fighter])
    assert fighter.current_damage == 5
    assert fighter.has_condition(conditions.GRAPPLED)


def test_resolve_save_ability_halves_damage_on_success(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    otyugh = make_creature("otyugh", "monsters", 0, 0)
    fighter = make_creature("fighter", "party", 1, 0, hp_average=40, saves={"constitution": 10})
    ctx, _, _ = make_ctx(board, [15, 10], [otyugh, fighter])  # save total 25 >= dc14, then damage roll 10
    ability = Ability(name="tentacle_slam", kind="save", ability="constitution", dc=14,
                      damage="2d10+3", damage_type="bludgeoning", half_on_save=True)
    resolve_ability(ctx, otyugh, ability, [fighter])
    assert fighter.current_damage == 5  # 10 // 2


def test_resolve_save_ability_full_damage_and_on_fail_when_save_fails(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    otyugh = make_creature("otyugh", "monsters", 0, 0)
    fighter = make_creature("fighter", "party", 1, 0, hp_average=40, saves={"constitution": 0})
    ctx, _, _ = make_ctx(board, [1, 10], [otyugh, fighter])  # save total 1 < dc14, damage roll 10
    ability = Ability(name="tentacle_slam", kind="save", ability="constitution", dc=14,
                      damage="2d10+3", damage_type="bludgeoning", half_on_save=True,
                      on_fail=(EffectCall(effect="attach_condition", args={"condition": "stunned"}),))
    resolve_ability(ctx, otyugh, ability, [fighter])
    assert fighter.current_damage == 10  # full damage, not halved
    assert fighter.has_condition(conditions.STUNNED)


def test_resolve_heal_ability(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    cleric = make_creature("cleric", "party", 0, 0)
    fighter = make_creature("fighter", "party", 1, 0, hp_average=40)
    fighter.current_damage = 20
    ctx, _, _ = make_ctx(board, [12], [cleric, fighter])
    ability = Ability(name="cure_wounds", kind="heal", amount="1d8+7")
    resolve_ability(ctx, cleric, ability, [fighter])
    assert fighter.current_damage == 8


def test_resolve_utility_ability_runs_effects(tmp_path):
    board = make_board(tmp_path, OPEN_BOARD, "open")
    wizard = make_creature("wizard", "party", 0, 0)
    ctx, _, _ = make_ctx(board, [], [wizard])
    # utility abilities with unregistered effects (emit_light etc.) aren't
    # implemented until Phase 4 — this just proves the dispatch path itself
    # works with the effects Phase 3 does support.
    wizard.add_condition(ConditionInstance(name=conditions.PRONE))
    ability = Ability(name="stand_up", kind="utility",
                      effects=(EffectCall(effect="remove_condition", args={"condition": "prone"}),))
    resolve_ability(ctx, wizard, ability, [])
    assert not wizard.has_condition(conditions.PRONE)
