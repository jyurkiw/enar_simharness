import pytest
from dieroller import Dice
from dnd_board import load_board_toml
from simharness.ledger import Ledger
from simharness.plugin import TrialContext
from simharness.runner import TrialRunner

from dnd5e import conditions
from dnd5e.creature import ConditionInstance
from dnd5e.statblock import (Ability, Behavior, ConditionDef, EffectCall, MultiattackOption, Reaction,
                             Statblock, Stats)
from dnd5e.system import Dnd5eSystem, RosterSlot

OPEN_BOARD = '''
name = "open"
map = """
..........
..........
"""
[meta]
cell_feet = 5
'''


class ScriptedDice:
    def __init__(self, values):
        self._values = list(values)

    def roll(self, code):
        return self._values.pop(0)

    def spawn(self, n):
        return [self]  # not used by direct system.py tests


def make_board(tmp_path):
    p = tmp_path / "board.toml"
    p.write_text(OPEN_BOARD)
    return load_board_toml(p)


def make_stats(**overrides):
    base = dict(strength=16, dexterity=11, constitution=19, intelligence=6, wisdom=13,
               charisma=6, ac=14, speed=30, initiative_bonus=0, proficiency=3,
               crit_range=20, reach=5, hit_dice="2d10+4", hp_average=20)
    base.update(overrides)
    return Stats(**base)


def attacker_statblock(name, *, to_hit=6, damage="1d8+3", multiattack_actions=("hit",),
                       action_priority=(), **stat_overrides):
    abilities = {"hit": Ability(name="hit", kind="attack", to_hit=to_hit, damage=damage,
                                damage_type="slashing")}
    multiattack = {}
    if multiattack_actions:
        multiattack["standard"] = MultiattackOption(name="standard", actions=multiattack_actions, priority=0)
    return Statblock(name=name, display_name=name, classification={}, stats=make_stats(**stat_overrides),
                     abilities=abilities, multiattack=multiattack,
                     behavior=Behavior(action_priority=action_priority))


def make_ctx(dice_values, trials=1, max_rounds=5):
    return TrialContext(dice=ScriptedDice(dice_values), ledger=Ledger(names=[], side_of={}),
                        trial_index=0, max_rounds=max_rounds)


def build_system(board, *, max_rounds=5, hp_mode="average"):
    fighter = RosterSlot(statblock=attacker_statblock("fighter", hp_average=30), instance_name="fighter",
                         side="party", start=(0, 0))
    otyugh = RosterSlot(statblock=attacker_statblock("otyugh", hp_average=20, to_hit=6, damage="1d8+3"),
                        instance_name="otyugh", side="monsters", start=(1, 0))
    return Dnd5eSystem(board=board, roster=[fighter, otyugh], max_rounds=max_rounds, hp_mode=hp_mode)


def test_setup_trial_places_creatures_rolls_hp_and_initiative(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    # 2 creatures: initiative rolls (1d20 each), no hp rolling in average mode.
    ctx = make_ctx([15, 10])  # fighter rolls 15, otyugh rolls 10 -> fighter first
    system.setup_trial(ctx)
    assert set(ctx.game.creatures) == {"fighter", "otyugh"}
    assert ctx.game.turn_order == ["fighter", "otyugh"]
    assert ctx.game.creatures["fighter"].hp == 30  # average mode
    assert ctx.game.creatures["fighter"].coord == (0, 0)
    assert ctx.game.creatures["otyugh"].coord == (1, 0)


def test_initiative_ties_keep_roster_order(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([10, 10])  # tie
    system.setup_trial(ctx)
    assert ctx.game.turn_order == ["fighter", "otyugh"]  # roster order preserved


def test_hp_mode_rolled_uses_hit_dice(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board, hp_mode="rolled")
    # setup_trial rolls HP before initiative (roster order), so: 2 hp rolls
    # (fighter, otyugh) then 2 initiative rolls.
    ctx = make_ctx([9, 8, 15, 10])
    system.setup_trial(ctx)
    assert ctx.game.creatures["fighter"].hp == 9
    assert ctx.game.creatures["otyugh"].hp == 8


def test_turn_order_returns_static_initiative_order(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    assert system.turn_order(ctx) == ["fighter", "otyugh"]


def test_take_turn_resolves_attack_against_preferred_target(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([15, 10, 12, 5])  # init x2, then attack roll(12) + damage(5)
    system.setup_trial(ctx)
    system.take_turn(ctx, "fighter")
    otyugh = ctx.game.creatures["otyugh"]
    assert otyugh.current_damage == 5  # 12+6=18 >= ac14 -> hit for 5


def test_take_turn_down_creature_rolls_death_save_instead_of_acting(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    fighter = ctx.game.creatures["fighter"]
    fighter.current_damage = 999  # down
    ctx.game.combat_ctx.resolver.dice._values = [15]  # death save roll: 15 -> success
    system.take_turn(ctx, "fighter")
    assert fighter.death_save_successes == 1
    assert fighter.death_save_failures == 0


def test_death_save_natural_20_revives_to_one_hp(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    fighter = ctx.game.creatures["fighter"]
    fighter.current_damage = 999
    ctx.game.combat_ctx.resolver.dice._values = [20]
    system.take_turn(ctx, "fighter")
    assert fighter.hp_remaining == 1
    assert not fighter.is_down


def test_death_save_natural_1_counts_as_two_failures(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    fighter = ctx.game.creatures["fighter"]
    fighter.current_damage = 999
    ctx.game.combat_ctx.resolver.dice._values = [1]
    system.take_turn(ctx, "fighter")
    assert fighter.death_save_failures == 2


def test_death_save_stops_at_dead_or_stabilized(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    fighter = ctx.game.creatures["fighter"]
    fighter.current_damage = 999
    fighter.death_save_failures = 3  # already dead
    ctx.game.combat_ctx.resolver.dice._values = []  # no roll consumed
    system.take_turn(ctx, "fighter")  # must not raise (no dice to pop)
    assert fighter.is_dead


def test_take_turn_skipped_while_stunned(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    fighter = ctx.game.creatures["fighter"]
    fighter.add_condition(ConditionInstance(name=conditions.STUNNED))
    otyugh = ctx.game.creatures["otyugh"]
    system.take_turn(ctx, "fighter")
    assert otyugh.current_damage == 0  # no attack happened


def test_multiattack_priority_selects_highest(tmp_path):
    board = make_board(tmp_path)
    sb = Statblock(
        name="x", display_name="x", classification={}, stats=make_stats(),
        abilities={
            "a": Ability(name="a", kind="attack", to_hit=99, damage="1d4"),
            "b": Ability(name="b", kind="attack", to_hit=99, damage="1d4"),
        },
        multiattack={
            "low": MultiattackOption(name="low", actions=("a",), priority=0),
            "high": MultiattackOption(name="high", actions=("b", "b"), priority=10),
        },
    )
    slot = RosterSlot(statblock=sb, instance_name="x", side="party", start=(0, 0))
    target_slot = RosterSlot(statblock=attacker_statblock("otyugh", hp_average=999),
                             instance_name="otyugh", side="monsters", start=(1, 0))
    system = Dnd5eSystem(board=board, roster=[slot, target_slot], max_rounds=1)
    ctx = make_ctx([15, 10, 20, 1, 20, 1])  # init x2, then 2 attacks (b, b) each hit+dmg
    system.setup_trial(ctx)
    system.take_turn(ctx, "x")
    otyugh = ctx.game.creatures["otyugh"]
    assert otyugh.current_damage == 2  # two "b" attacks (the high-priority option), 1 dmg each


def test_no_multiattack_falls_back_to_first_action_priority(tmp_path):
    board = make_board(tmp_path)
    sb = Statblock(
        name="x", display_name="x", classification={}, stats=make_stats(),
        abilities={"a": Ability(name="a", kind="attack", to_hit=99, damage="1d4")},
        multiattack={},
        behavior=Behavior(action_priority=("a",)),
    )
    slot = RosterSlot(statblock=sb, instance_name="x", side="party", start=(0, 0))
    target_slot = RosterSlot(statblock=attacker_statblock("otyugh", hp_average=999),
                             instance_name="otyugh", side="monsters", start=(1, 0))
    system = Dnd5eSystem(board=board, roster=[slot, target_slot], max_rounds=1)
    ctx = make_ctx([15, 10, 20, 3])
    system.setup_trial(ctx)
    system.take_turn(ctx, "x")
    assert ctx.game.creatures["otyugh"].current_damage == 3


def test_is_over_when_a_side_is_wiped(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    assert system.is_over(ctx) is False
    ctx.game.creatures["otyugh"].current_damage = 999
    assert system.is_over(ctx) is True


def test_finalize_trial_outcome_columns(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    ctx.game.creatures["otyugh"].current_damage = 999
    outcome = system.finalize_trial(ctx)
    assert outcome["down_otyugh"] == 1
    assert outcome["dead_otyugh"] == 0
    assert outcome["hp_remaining_otyugh"] == 0
    assert outcome["wiped_monsters"] == 1
    assert outcome["wiped_party"] == 0
    assert outcome["any_dead_monsters"] == 0
    assert outcome["poisoned_otyugh"] == 0
    assert outcome["any_poisoned_monsters"] == 0


def test_finalize_trial_reports_real_poisoned_state(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    ctx.game.creatures["fighter"].add_condition(ConditionInstance(name=conditions.POISONED))
    outcome = system.finalize_trial(ctx)
    assert outcome["poisoned_fighter"] == 1
    assert outcome["any_poisoned_party"] == 1
    assert outcome["any_poisoned_monsters"] == 0


def test_full_trial_via_trial_runner_end_to_end(tmp_path):
    """Integration proof: the whole pipeline (TrialRunner -> Dnd5eSystem ->
    Battlefield/CombatContext) runs to completion via the real GameSystem
    protocol with a real seeded Dice, not scripted values."""
    board = make_board(tmp_path)
    system = build_system(board, max_rounds=10)
    runner = TrialRunner(system, seed=20260711, max_rounds=10, names=["fighter", "otyugh"],
                         side_of={"fighter": "party", "otyugh": "monsters"})
    ledger = runner.run(trials=200)
    assert len(ledger.rows) == 200
    for row in ledger.rows:
        assert "wiped_party" in row and "wiped_monsters" in row
        assert row["hp_remaining_fighter"] >= 0
        assert row["hp_remaining_otyugh"] >= 0
    # With both sides attacking each other every round for up to 10 rounds,
    # at least one side should be wiped in the overwhelming majority of trials.
    any_wipe = sum(1 for r in ledger.rows if r["wiped_party"] or r["wiped_monsters"])
    assert any_wipe > 150


def test_set_flag_on_hit_is_visible_same_round_and_gates_a_multiattack_option(tmp_path):
    """A hit sets a round-scoped flag; the target's own multiattack `when`
    (has_flag) picks a different option once it's set — proves set_flag/
    has_flag round-trip end to end through system.py's real turn pipeline."""
    board = make_board(tmp_path)
    from dnd5e import expressions
    from dnd5e.statblock import EffectCall

    poker = Statblock(
        name="poker", display_name="poker", classification={}, stats=make_stats(),
        abilities={"poke": Ability(name="poke", kind="attack", to_hit=99, damage="1d4",
                                   damage_type="slashing",
                                   on_hit=(EffectCall(effect="set_flag",
                                                      args={"flag": "landed_hit", "scope": "round"}),))},
        multiattack={"standard": MultiattackOption(name="standard", actions=("poke",), priority=0)},
    )
    reactor = Statblock(
        name="reactor", display_name="reactor", classification={}, stats=make_stats(),
        abilities={"basic": Ability(name="basic", kind="attack", to_hit=6, damage="1d4",
                                    damage_type="slashing")},
        multiattack={
            "excited": MultiattackOption(name="excited", actions=("basic",),
                                         when=expressions.parse_and_validate("has_flag('landed_hit')", where="t"),
                                         priority=10),
            "calm": MultiattackOption(name="calm", actions=("basic",), priority=0),
        },
    )
    poker_slot = RosterSlot(statblock=poker, instance_name="poker", side="party", start=(0, 0))
    reactor_slot = RosterSlot(statblock=reactor, instance_name="reactor", side="monsters", start=(1, 0))
    system = Dnd5eSystem(board=board, roster=[poker_slot, reactor_slot], max_rounds=5)

    ctx = make_ctx([15, 10])  # initiative: poker first
    system.setup_trial(ctx)
    assert not ctx.game.flags.has("landed_hit")

    # poke's attack roll (natural 10) + damage roll (3): to_hit=99 guarantees a hit.
    ctx.game.combat_ctx.resolver.dice._values = [10, 3]
    system.take_turn(ctx, "poker")
    assert ctx.game.flags.has("landed_hit")

    from dnd5e.behavior import BehaviorContext
    behavior_ctx = BehaviorContext(battlefield=ctx.game.battlefield, round_index=ctx.round_index,
                                   turn_order=ctx.game.turn_order, flags=ctx.game.flags,
                                   resolver=ctx.game.combat_ctx.resolver)
    from dnd5e.behavior import select_multiattack
    option = select_multiattack(ctx.game.creatures["reactor"], behavior_ctx)
    assert option.name == "excited"

    # Next round: turn_order() is the begin-round hook that clears round flags.
    ctx.round_index += 1
    system.turn_order(ctx)
    assert not ctx.game.flags.has("landed_hit")
    option = select_multiattack(ctx.game.creatures["reactor"], behavior_ctx)
    assert option.name == "calm"


def test_end_trial_effect_ends_the_trial_early_and_merges_outcome(tmp_path):
    board = make_board(tmp_path)
    from dnd5e.statblock import EffectCall

    fleeing = Statblock(
        name="fleeing", display_name="fleeing", classification={}, stats=make_stats(),
        abilities={"flee": Ability(name="flee", kind="attack", to_hit=99, damage="1d4",
                                   damage_type="slashing",
                                   on_hit=(EffectCall(effect="end_trial",
                                                      args={"outcome": {"retreated": 1}}),))},
        multiattack={"standard": MultiattackOption(name="standard", actions=("flee",), priority=0)},
    )
    fighter_slot = RosterSlot(statblock=attacker_statblock("fighter"), instance_name="fighter",
                              side="party", start=(0, 0))
    fleeing_slot = RosterSlot(statblock=fleeing, instance_name="fleeing", side="monsters", start=(1, 0))
    system = Dnd5eSystem(board=board, roster=[fighter_slot, fleeing_slot], max_rounds=5)

    ctx = make_ctx([10, 15])  # initiative: fleeing goes first
    system.setup_trial(ctx)
    assert not system.is_over(ctx)

    ctx.game.combat_ctx.resolver.dice._values = [10, 3]  # flee's attack + damage roll
    system.take_turn(ctx, "fleeing")
    assert system.is_over(ctx)

    outcome = system.finalize_trial(ctx)
    assert outcome["retreated"] == 1
    # The standard outcome columns are still present alongside the merged one.
    assert "down_fighter" in outcome and "wiped_party" in outcome


def test_darkness_aura_blinds_the_non_immune_party_and_light_plan_clears_it(tmp_path):
    """End-to-end: [[environment.obscurement]] follows the otyugh (a
    darkvision-immune photophage darkness) and blinds the fighter each round;
    `light_plan` fires on the fighter's own turn, clears the party's
    obscurement-Blinded, marks the fighter LIGHT_SOURCE, and costs its action
    (no attack is resolved that turn — proven by not scripting any attack-
    roll dice for it)."""
    board = make_board(tmp_path)
    from dnd5e.loader import LightPlanSpec, ObscurementSpec
    from dnd5e.statblock import EffectCall, Trait

    otyugh = Statblock(
        name="otyugh", display_name="otyugh", classification={}, stats=make_stats(),
        abilities={"basic": Ability(name="basic", kind="attack", to_hit=6, damage="1d4",
                                    damage_type="slashing")},
        multiattack={"standard": MultiattackOption(name="standard", actions=("basic",), priority=0)},
        traits={"photophage": Trait(name="photophage", effects=(
            EffectCall(effect="darkvision_immunity", args={}),))},
    )
    fighter_slot = RosterSlot(statblock=attacker_statblock("fighter"), instance_name="fighter",
                              side="party", start=(0, 0))
    otyugh_slot = RosterSlot(statblock=otyugh, instance_name="otyugh", side="monsters", start=(2, 0))
    system = Dnd5eSystem(
        board=board, roster=[fighter_slot, otyugh_slot], max_rounds=5,
        obscurement=(ObscurementSpec(kind="darkness", radius_ft=30, follows="otyugh"),),
        light_plan=LightPlanSpec(source="fighter", round=1, costs_action=True),
    )

    ctx = make_ctx([15, 10])  # initiative: fighter first
    system.setup_trial(ctx)
    assert ctx.game.battlefield.obscurement is not None

    ctx.round_index = 1
    system.turn_order(ctx)  # the begin-round sync hook
    fighter = ctx.game.creatures["fighter"]
    otyugh_c = ctx.game.creatures["otyugh"]
    assert fighter.has_condition(conditions.BLINDED)
    assert fighter.condition(conditions.BLINDED).source == conditions.OBSCUREMENT_SOURCE
    assert not otyugh_c.has_condition(conditions.BLINDED)  # darkvision-immune

    # No attack-roll dice scripted: if light_plan's action-cost gate failed
    # to short-circuit take_turn, the normal attack pipeline would pop from
    # an empty ScriptedDice and raise, failing this test loudly.
    system.take_turn(ctx, "fighter")
    assert not fighter.has_condition(conditions.BLINDED)
    assert fighter.has_condition(conditions.LIGHT_SOURCE)
    assert otyugh_c.current_damage == 0  # no attack landed — the action was spent on light

    # Fires at most once per trial: a second call on a later round is a no-op.
    ctx.round_index = 2
    fighter.remove_condition(conditions.LIGHT_SOURCE)
    system.take_turn(ctx, "fighter")
    assert not fighter.has_condition(conditions.LIGHT_SOURCE)


def test_escape_hatch_plan_movement_overrides_the_tactic(tmp_path):
    """A custom `plan_movement` hook sends the actor to an explicit cell
    instead of engaging its target — proving system.py's take_turn calls
    `movement.move_to_cell` when the hook returns a destination, not
    `movement.apply_tactic`."""
    board = make_board(tmp_path)
    from dnd5e import escape_hatch

    escape_hatch.clear_cache()

    class _FleeToOrigin:
        def choose_multiattack(self, me, view):
            return None

        def choose_target(self, me, ability, pool, view):
            return None

        def plan_movement(self, me, view):
            return (0, 0)

    escape_hatch._CACHE["python:test.FleeToOrigin"] = _FleeToOrigin()

    actor_sb = attacker_statblock("actor")
    actor_sb = Statblock(name=actor_sb.name, display_name=actor_sb.display_name,
                         classification=actor_sb.classification, stats=actor_sb.stats,
                         abilities=actor_sb.abilities, multiattack=actor_sb.multiattack,
                         behavior=Behavior(custom="python:test.FleeToOrigin"))
    actor_slot = RosterSlot(statblock=actor_sb, instance_name="actor", side="party", start=(5, 0))
    target_slot = RosterSlot(statblock=attacker_statblock("target"), instance_name="target",
                             side="monsters", start=(9, 0))
    system = Dnd5eSystem(board=board, roster=[actor_slot, target_slot], max_rounds=5)

    ctx = make_ctx([15, 10])  # initiative: actor first
    system.setup_trial(ctx)
    ctx.game.combat_ctx.resolver.dice._values = [1]  # attack roll: natural 1, guaranteed miss
    system.take_turn(ctx, "actor")

    # engage would have moved toward (9, 0) (into reach, i.e. x=8); the
    # custom plan_movement instead sent it to (0, 0).
    assert ctx.game.creatures["actor"].coord == (0, 0)

    escape_hatch.clear_cache()


# ---- Phase 5: condition clocks, unless-predicates, turn_start reactions -------------

MARKED_DEF = ConditionDef(
    name="marked", grants=(EffectCall(effect="impose_disadvantage_except_source", args={}),),
    exclusive="per_source", expires="end_of_bearer_turn", unless="attacked_other_than_source_this_turn",
)


def _bruiser_statblock():
    return Statblock(
        name="bruiser", display_name="bruiser", classification={}, stats=make_stats(),
        abilities={"brand": Ability(name="brand", kind="attack", to_hit=99, damage="1d4", damage_type="bludgeoning",
                                    on_hit=(EffectCall(effect="attach_condition", args={"condition": "marked"}),))},
        multiattack={"standard": MultiattackOption(name="standard", actions=("brand",), priority=0)},
        conditions={"marked": MARKED_DEF},
    )


def _swinger_statblock(name):
    return Statblock(
        name=name, display_name=name, classification={}, stats=make_stats(),
        abilities={"swing": Ability(name="swing", kind="attack", to_hit=99, damage="1d4", damage_type="slashing")},
        multiattack={"standard": MultiattackOption(name="standard", actions=("swing",), priority=0)},
    )


def test_marked_condition_expires_at_end_of_bearer_turn_when_no_other_target_attacked(tmp_path):
    """The Bruiser Mark's clock/unless-predicate lifecycle: attached via
    `attach_condition`, `end_of_bearer_turn` ticks at the end of the marked
    creature's own turn (`system.py`'s `_tick_end_of_turn`, run from `take_
    turn`'s `finally`) — and expires here because the bearer's only enemy
    *is* the mark's source, so it never set the unless-predicate's keep-alive
    flag."""
    board = make_board(tmp_path)
    bruiser_slot = RosterSlot(statblock=_bruiser_statblock(), instance_name="bruiser", side="monsters",
                              start=(0, 0))
    fighter_slot = RosterSlot(statblock=_swinger_statblock("fighterB"), instance_name="fighterB", side="party",
                              start=(1, 0))
    system = Dnd5eSystem(board=board, roster=[bruiser_slot, fighter_slot], max_rounds=5)

    ctx = make_ctx([15, 10])  # initiative: bruiser first
    system.setup_trial(ctx)
    ctx.game.combat_ctx.resolver.dice._values = [10, 2]  # brand: attack roll (guaranteed hit) + damage
    system.take_turn(ctx, "bruiser")
    fighter = ctx.game.creatures["fighterB"]
    assert fighter.has_condition("marked")

    ctx.game.combat_ctx.resolver.dice._values = [10, 2]  # swing: no disadvantage (only enemy is the source)
    system.take_turn(ctx, "fighterB")  # fighterB's only enemy is bruiser -> attacks the mark's own source
    assert not fighter.has_condition("marked")  # expired: didn't attack anyone other than the source


def test_marked_condition_survives_end_of_turn_if_bearer_attacked_someone_else(tmp_path):
    """Same lifecycle, but the bearer has a second enemy (nearer than the
    mark's source) to attack instead: `impose_disadvantage_except_source`
    fires (disadvantage on that attack, `turn_scratch["attacked_other_than_
    source"]` stamped), and the `unless` predicate reads that stamp at the
    end-of-turn tick to keep the mark alive."""
    board = make_board(tmp_path)
    # The bruiser starts 2 cells out and closes to reach on its own turn — a
    # melee weapon can't resolve against a target outside its reach (see
    # `actions.attack`), so "far from fighterB" has to mean "one move away",
    # not "across the board". Roster order puts the grunt first so it wins the
    # equal-distance tie for fighterB's target (design doc 04 section 3: ties
    # break by roster order), which is what makes fighterB swing at someone
    # other than the mark's source.
    grunt_slot = RosterSlot(statblock=Statblock(name="grunt", display_name="grunt", classification={},
                                                stats=make_stats()),
                            instance_name="grunt", side="monsters", start=(1, 0))  # adjacent to fighterB
    fighter_slot = RosterSlot(statblock=_swinger_statblock("fighterB"), instance_name="fighterB", side="party",
                              start=(0, 0))
    bruiser_slot = RosterSlot(statblock=_bruiser_statblock(), instance_name="bruiser", side="monsters",
                              start=(2, 1))
    system = Dnd5eSystem(board=board, roster=[grunt_slot, fighter_slot, bruiser_slot], max_rounds=5)

    ctx = make_ctx([20, 15, 10])  # initiative: grunt, fighterB, bruiser
    system.setup_trial(ctx)
    ctx.game.combat_ctx.resolver.dice._values = [10, 2]  # brand hits fighterB
    system.take_turn(ctx, "bruiser")
    fighter = ctx.game.creatures["fighterB"]
    assert fighter.has_condition("marked")

    # fighterB's nearest enemy is grunt (adjacent), not bruiser (far) -> attacks
    # someone other than the source: disadvantage (2 d20, keep lower) + damage.
    ctx.game.combat_ctx.resolver.dice._values = [15, 12, 2]
    system.take_turn(ctx, "fighterB")
    assert fighter.turn_scratch.get("attacked_other_than_source") is True
    assert fighter.has_condition("marked")  # unless-predicate kept it alive


def test_start_of_source_next_turn_clock_expires_when_source_next_acts(tmp_path):
    """`start_of_source_next_turn` ticks in `_tick_start_of_turn`, called
    *before* the incapacity gates on the source's own next turn — not on any
    other creature's turn in between."""
    board = make_board(tmp_path)
    system = build_system(board)  # fighter (party) vs otyugh (monsters)
    ctx = make_ctx([15, 10])  # fighter first
    system.setup_trial(ctx)
    fighter = ctx.game.creatures["fighter"]
    fighter.add_condition(ConditionInstance(name="dazed", source="otyugh", expires="start_of_source_next_turn"))

    ctx.game.combat_ctx.resolver.dice._values = [1]  # fighter's own attack roll: natural 1, auto-miss
    system.take_turn(ctx, "fighter")
    assert fighter.has_condition("dazed")  # unaffected by fighter's own turn ticking

    ctx.game.combat_ctx.resolver.dice._values = [1]  # otyugh's own attack roll: natural 1, auto-miss
    system.take_turn(ctx, "otyugh")  # otyugh's turn starting is exactly this clock's expiry point
    assert not fighter.has_condition("dazed")


def test_turn_start_reaction_fires_on_own_turn_via_when_self_check(tmp_path):
    """The Masked Bruiser's Sleight of Crowd publish point: `turn_start` is
    broadcast to every creature each turn (`_offer_turn_start_reactions`,
    called right after the incapacity/light_plan gates, before multiattack
    selection); a `when = "self == event.actor"` clause is how a reaction
    restricts itself to its own turn starting, not anyone else's."""
    board = make_board(tmp_path)
    from dnd5e import expressions

    bruiser = Statblock(
        name="bruiser", display_name="bruiser", classification={}, stats=make_stats(),
        reactions={"sleight": Reaction(
            name="sleight", trigger="turn_start",
            when=expressions.parse_and_validate("self == event.actor", where="test"),
            effects=(EffectCall(effect="set_flag", args={"flag": "sleight_used", "scope": "round"}),))},
    )
    ally = Statblock(name="ally", display_name="ally", classification={}, stats=make_stats())
    bruiser_slot = RosterSlot(statblock=bruiser, instance_name="bruiser", side="monsters", start=(0, 0))
    ally_slot = RosterSlot(statblock=ally, instance_name="ally", side="monsters", start=(1, 0))
    system = Dnd5eSystem(board=board, roster=[bruiser_slot, ally_slot], max_rounds=5)

    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    assert not ctx.game.flags.has("sleight_used")

    system.take_turn(ctx, "ally")
    assert not ctx.game.flags.has("sleight_used")  # not bruiser's own turn -> when clause blocks it

    system.take_turn(ctx, "bruiser")
    assert ctx.game.flags.has("sleight_used")


# ---- Opportunity attacks (design doc 07): enemy_left_reach + make_attack ----

def _oa_guard_statblock():
    oa = Reaction(name="opportunity_attack", trigger="enemy_left_reach", uses_reaction=True,
                  effects=(EffectCall(effect="make_attack", args={"ability": "poke"}),))
    return Statblock(
        name="guard", display_name="guard", classification={}, stats=make_stats(),
        abilities={"poke": Ability(name="poke", kind="attack", to_hit=99, damage="1d6",
                                   damage_type="piercing")},
        reactions={"opportunity_attack": oa},
    )


def test_opportunity_attack_fires_when_a_creature_leaves_reach(tmp_path):
    board = make_board(tmp_path)
    guard = RosterSlot(statblock=_oa_guard_statblock(), instance_name="guard",
                       side="party", start=(0, 0))
    mover = RosterSlot(statblock=attacker_statblock("mover", hp_average=99),
                       instance_name="mover", side="monsters", start=(1, 0))
    system = Dnd5eSystem(board=board, roster=[guard, mover], max_rounds=3)
    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    m = ctx.game.creatures["mover"]

    # Walk out of the guard's 5 ft reach: (1,0) -> (5,0). Dice: attack roll, damage.
    ctx.game.combat_ctx.resolver.dice._values = [12, 4]
    system._offer_opportunity_attacks(m, (1, 0), (5, 0), ctx.game, ctx)
    assert m.current_damage == 4
    assert ctx.game.creatures["guard"].round_scratch.get("reaction_used") is True


def test_no_opportunity_attack_when_still_in_reach_or_not_moving(tmp_path):
    board = make_board(tmp_path)
    guard = RosterSlot(statblock=_oa_guard_statblock(), instance_name="guard",
                       side="party", start=(0, 0))
    mover = RosterSlot(statblock=attacker_statblock("mover", hp_average=99),
                       instance_name="mover", side="monsters", start=(1, 0))
    system = Dnd5eSystem(board=board, roster=[guard, mover], max_rounds=3)
    ctx = make_ctx([15, 10])
    system.setup_trial(ctx)
    m = ctx.game.creatures["mover"]
    ctx.game.combat_ctx.resolver.dice._values = []      # any roll would raise

    system._offer_opportunity_attacks(m, (1, 0), (1, 0), ctx.game, ctx)   # didn't move
    system._offer_opportunity_attacks(m, (1, 0), (1, 1), ctx.game, ctx)   # still adjacent
    assert m.current_damage == 0


def test_prone_creature_stands_up_at_the_start_of_its_turn(tmp_path):
    board = make_board(tmp_path)
    system = build_system(board)
    ctx = make_ctx([15, 10, 12, 5])
    system.setup_trial(ctx)
    fighter = ctx.game.creatures["fighter"]
    fighter.add_condition(ConditionInstance(name=conditions.PRONE))
    system.take_turn(ctx, "fighter")
    assert not fighter.has_condition(conditions.PRONE)   # stood up before acting
