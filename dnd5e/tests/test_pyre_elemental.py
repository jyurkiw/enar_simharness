"""P3 — the Pyre Elemental as a `[[hazard_actors]]` driver: a bodiless force
with an initiative slot. See sims/opera_house/PLAN.md."""

import pytest
from dnd_board import load_board_toml
from simharness.ledger import Ledger
from simharness.plugin import TrialContext

from dnd5e.loader import HazardActorSpec
from dnd5e.statblock import Ability, Behavior, MultiattackOption, Statblock, Stats
from dnd5e.system import Dnd5eSystem, RosterSlot

BOARD = '''
name = "hall"
map = """
....................
....................
....................
....................
....................
"""
[meta]
cell_feet = 5
'''

HANDLER = "python:dnd5e_behaviors.pyre_elemental.PyreElementalDriver"


class ScriptedDice:
    """Deterministic-ish: pops scripted values, then falls back to `default`
    forever (the elemental rolls a lot of dice per turn)."""
    def __init__(self, values, default=10):
        self._values = list(values)
        self.default = default
        self.rolled = []

    def roll(self, code):
        self.rolled.append(code)
        return self._values.pop(0) if self._values else self.default

    def spawn(self, n):
        return [self]


def board(tmp_path):
    p = tmp_path / "hall.toml"; p.write_text(BOARD)
    return load_board_toml(p)


def pc(name, hp=45):
    hit = Ability(name="hit", kind="attack", to_hit=6, damage="1d8+3", requires_sight=False)
    return Statblock(name=name, display_name=name, classification={"level": 6},
                     stats=Stats(strength=14, dexterity=14, constitution=14, intelligence=10,
                                 wisdom=12, charisma=10, ac=16, speed=30, initiative_bonus=2,
                                 proficiency=3, crit_range=20, reach=5, hit_dice=None, hp_average=hp),
                     abilities={"hit": hit},
                     multiattack={"m": MultiattackOption(name="m", actions=("hit",))},
                     behavior=Behavior(tactic="hold"))


def build(tmp_path, *, start_round=1, n_pcs=3, config=None, dice=()):
    spec = HazardActorSpec(name="pyre", handler=HANDLER, initiative=99,
                           start_round=start_round, config=config or {})
    roster = [RosterSlot(statblock=pc(f"pc{i}"), instance_name=f"pc{i}", side="party",
                         start=(4 + i, 2)) for i in range(n_pcs)]
    system = Dnd5eSystem(board=board(tmp_path), roster=roster, max_rounds=5, hazard_actors=(spec,))
    ctx = TrialContext(dice=ScriptedDice(list(dice)), ledger=Ledger(names=[], side_of={}),
                       trial_index=0, max_rounds=5)
    ctx.round_index = 1
    system.setup_trial(ctx)
    return system, ctx


def test_hazard_actor_takes_an_initiative_slot_but_is_not_a_creature(tmp_path):
    system, ctx = build(tmp_path)
    assert "pyre" in ctx.game.turn_order          # it acts...
    assert "pyre" not in ctx.game.creatures       # ...but has no body
    # ...so it can't be targeted or keep a side alive.
    assert all(c.side != "monsters" for c in ctx.game.battlefield.creatures.values())


def test_its_turn_damages_pcs_and_leaves_fire_behind(tmp_path):
    system, ctx = build(tmp_path)
    system.take_turn(ctx, "pyre")

    assert any(ctx.game.creatures[f"pc{i}"].current_damage > 0 for i in range(3))
    assert len(ctx.game.battlefield.hazards.hazards) >= 1     # debris left fires


def test_it_does_not_act_before_its_start_round(tmp_path):
    # The fire starts on round 2 (Mathieu's lantern) — round 1 must be untouched.
    system, ctx = build(tmp_path, start_round=2)
    system.take_turn(ctx, "pyre")

    assert all(ctx.game.creatures[f"pc{i}"].current_damage == 0 for i in range(3))
    assert ctx.game.battlefield.hazards.hazards == []


def test_it_ignores_the_unconscious(tmp_path):
    """"has no interest in anyone who is unconscious" — the hinge the phase-2
    hand-off swings on: a subdued party can lie there while it burns elsewhere."""
    system, ctx = build(tmp_path, n_pcs=2)
    downed, up = ctx.game.creatures["pc0"], ctx.game.creatures["pc1"]
    downed.current_damage = downed.hp                      # unconscious
    downed.death_save_successes = 3                        # stable, subdued
    # Park them far apart so an aim at one can't splash the other.
    downed.place(1, 1)
    up.place(18, 4)

    system.take_turn(ctx, "pyre")

    assert downed.current_damage == downed.hp              # untouched
    assert up.current_damage > 0                           # the standing one burns


def test_legendary_actions_are_offered_after_another_creatures_turn(tmp_path):
    system, ctx = build(tmp_path, n_pcs=2)
    system.take_turn(ctx, "pyre")                          # sets legendary_left = 3
    before = sum(ctx.game.creatures[f"pc{i}"].current_damage for i in range(2))
    left_before = ctx.game.hazard_scratch["pyre"]["legendary_left"]

    system.take_turn(ctx, "pc0")                           # a creature acts...

    after = sum(ctx.game.creatures[f"pc{i}"].current_damage for i in range(2))
    left_after = ctx.game.hazard_scratch["pyre"]["legendary_left"]
    assert left_after < left_before                        # ...it spent a legendary
    assert after >= before


def test_smolder_mode_stops_bombing_but_still_seeds_weirds(tmp_path):
    """The escape phase: "the Pyre Elemental will stop attacking anyone in the
    front of the house... It will, however, spawn three Pyre Weirds." At full
    aggression it drops a standing party in ~3 rounds, so this mode is what
    makes the escape a fight against the weirds rather than an execution."""
    system, ctx = build(tmp_path, n_pcs=2, config={"mode": "smolder"})
    # Seed a fire for the weirds to rise from (normally left by phase-1 debris).
    ctx.game.battlefield.hazards.hazards.clear()
    system.take_turn(ctx, "pyre")
    from dnd5e.hazards import Hazard
    ctx.game.battlefield.hazards.add(Hazard(center=(10, 2), radius_ft=10, damage="2d6",
                                            damage_type="fire"))

    # No debris damage from its turn...
    system.take_turn(ctx, "pyre")
    assert all(ctx.game.creatures[f"pc{i}"].current_damage == 0 for i in range(2))

    # ...but legendary actions still put weirds on the board.
    for _ in range(6):
        ctx.game.hazard_scratch["pyre"]["legendary_left"] = 3
        system._offer_legendary(ctx, ctx.game, after=ctx.game.creatures["pc0"])
    assert any(c.has_tag("weird") for c in ctx.game.creatures.values())


def test_it_summons_a_weird_into_its_fire_up_to_the_cap(tmp_path):
    system, ctx = build(tmp_path, n_pcs=2)
    system.take_turn(ctx, "pyre")                          # lays fire + refreshes actions

    # Give it plenty of legendary budget and let it summon repeatedly.
    for _ in range(8):
        ctx.game.hazard_scratch["pyre"]["legendary_left"] = 3
        ctx.game.hazard_scratch["pyre"].pop("enflamed_this_turn", None)
        system._offer_legendary(ctx, ctx.game, after=ctx.game.creatures["pc0"])

    weirds = [c for c in ctx.game.creatures.values() if c.has_tag("weird")]
    assert 1 <= len(weirds) <= 2                           # summons, and caps at 2
    assert all(c.side == "monsters" for c in weirds)
    assert all(n in ctx.game.turn_order for n in (c.instance_name for c in weirds))
