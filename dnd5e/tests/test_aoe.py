"""Line AoE geometry (`aoe.py`) and the Evoker's bolt-slot brain."""

from dnd_board import load_board_toml

from dnd5e import aoe
from dnd5e.battlefield import Battlefield
from dnd5e.behavior import BehaviorContext, ConcreteScope
from dnd5e.creature import Creature
from dnd5e.dice import Resolver
from dnd5e.flags import FlagBag
from dnd5e.statblock import Ability, Behavior, MultiattackOption, Resource, Statblock, Stats
from dnd5e_behaviors.evoker_wizard import EvokerBrain

BOARD = 'name="o"\nmap="""\n' + "\n".join("." * 12 for _ in range(8)) + '\n"""\n[meta]\ncell_feet=5\n'


class Dice:
    """Fixed d100 roll, so the per-round chance is deterministic in tests."""

    def __init__(self, d100=1):
        self._d100 = d100

    def roll(self, code):
        return self._d100 if code == "1d100" else 5


def board(tmp_path):
    p = tmp_path / "b.toml"
    p.write_text(BOARD)
    return load_board_toml(p)


def stats():
    return Stats(strength=10, dexterity=10, constitution=10, intelligence=16, wisdom=10, charisma=10,
                 ac=12, speed=30, initiative_bonus=1, proficiency=3, crit_range=20, reach=5,
                 hit_dice=None, hp_average=32)


def creature(name, side, x, y, sb=None):
    c = Creature(statblock=sb or Statblock(name=name, display_name=name, classification={}, stats=stats()),
                 instance_name=name, side=side)
    c.place(x, y)
    return c


def wizard_sb():
    bolt = Ability(name="lightning_bolt", kind="save", ability="dexterity", dc=14, damage="8d6",
                   damage_type="lightning", half_on_save=True, area={"shape": "line", "length_ft": 100},
                   costs={"resource": "leveled_slots", "amount": 1})
    fire = Ability(name="fire_bolt", kind="attack", to_hit=7, damage="2d10", damage_type="fire")
    return Statblock(name="evoker_wizard", display_name="wiz", classification={}, stats=stats(),
                     abilities={"lightning_bolt": bolt, "fire_bolt": fire},
                     multiattack={"blast": MultiattackOption(name="blast", actions=("lightning_bolt",), priority=10),
                                  "standard": MultiattackOption(name="standard", actions=("fire_bolt",), priority=0)},
                     resources={"leveled_slots": Resource(name="leveled_slots", uses=2)},
                     behavior=Behavior(tactic="kite"))


# ---- get_targets: the friend/enemy split primitive ------------------------

def test_get_targets_splits_friendly_and_enemy(tmp_path):
    b = board(tmp_path)
    wiz = creature("wiz", "party", 0, 0)
    ally = creature("ally", "party", 2, 0)      # in the eastward line
    foe1 = creature("f1", "monsters", 4, 0)
    foe2 = creature("f2", "monsters", 6, 0)
    bf = Battlefield([wiz, ally, foe1, foe2], board=b)
    allies, enemies = aoe.get_targets(bf, wiz, (4, 0), length_cells=20)
    assert {a.instance_name for a in allies} == {"ally"}
    assert {e.instance_name for e in enemies} == {"f1", "f2"}


# ---- best_line: no friendly fire ------------------------------------------

def test_best_line_avoids_a_line_through_an_ally(tmp_path):
    b = board(tmp_path)
    wiz = creature("wiz", "party", 0, 0)
    ally = creature("ally", "party", 1, 0)      # blocks the eastward row
    east1 = creature("e1", "monsters", 2, 0)
    east2 = creature("e2", "monsters", 3, 0)    # 2 foes east, but the ally is in the way
    south = creature("s", "monsters", 0, 2)     # a lone clean foe due south
    bf = Battlefield([wiz, ally, east1, east2, south], board=b)
    # 2+ enemies only exist on the east row, which is fouled by the ally:
    assert aoe.best_line(bf, wiz, 20, allow_allies=False, min_enemies=2) is None
    # a clean solo line still exists (south):
    choice = aoe.best_line(bf, wiz, 20, allow_allies=False, min_enemies=1)
    assert choice is not None and {e.instance_name for e in choice[0]} == {"s"}


def test_best_line_with_sculpt_allows_the_ally_line(tmp_path):
    """Future Sculpt Spells: allow_allies=True re-opens the fouled 2-enemy row."""
    b = board(tmp_path)
    wiz = creature("wiz", "party", 0, 0)
    ally = creature("ally", "party", 1, 0)
    east1 = creature("e1", "monsters", 2, 0)
    east2 = creature("e2", "monsters", 3, 0)
    bf = Battlefield([wiz, ally, east1, east2], board=b)
    choice = aoe.best_line(bf, wiz, 20, allow_allies=True, min_enemies=2)
    assert choice is not None and {e.instance_name for e in choice[0]} == {"e1", "e2"}


# ---- EvokerBrain decision --------------------------------------------------

def _view(bf, rnd, d100=1):
    ctx = BehaviorContext(battlefield=bf, round_index=rnd, turn_order=[], flags=FlagBag(),
                          resolver=Resolver(Dice(d100)))
    return ctx


def test_brain_fires_on_a_clean_cluster(tmp_path):
    b = board(tmp_path)
    wiz = creature("wiz", "party", 0, 0, sb=wizard_sb()); wiz.reset_state()
    foes = [creature(f"f{i}", "monsters", x, 0) for i, x in enumerate((2, 4, 6))]
    bf = Battlefield([wiz, *foes], board=b)
    ctx = _view(bf, rnd=1, d100=1)               # roll 1 -> passes any chance
    assert EvokerBrain().choose_multiattack(wiz, ConcreteScope(ctx, wiz)) == "blast"


def test_brain_holds_a_solo_early_but_nukes_by_round_three(tmp_path):
    b = board(tmp_path)
    wiz = creature("wiz", "party", 0, 0, sb=wizard_sb()); wiz.reset_state()
    lone = creature("f", "monsters", 3, 0)
    bf = Battlefield([wiz, lone], board=b)
    brain = EvokerBrain()
    # Round 1 solo chance is 0.70; a max roll (100) fails it -> hold this beat.
    assert brain.choose_multiattack(wiz, ConcreteScope(_view(bf, 1, d100=100), wiz)) == "standard"
    # Round 3 solo chance defaults to 1.0 -> always nuke (a slot is never hoarded).
    assert brain.choose_multiattack(wiz, ConcreteScope(_view(bf, 3, d100=100), wiz)) == "blast"


def test_brain_out_of_slots_uses_cantrip(tmp_path):
    b = board(tmp_path)
    wiz = creature("wiz", "party", 0, 0, sb=wizard_sb()); wiz.reset_state()
    wiz.resources["leveled_slots"] = 0
    foes = [creature(f"f{i}", "monsters", x, 0) for i, x in enumerate((2, 4))]
    bf = Battlefield([wiz, *foes], board=b)
    assert EvokerBrain().choose_multiattack(wiz, ConcreteScope(_view(bf, 1), wiz)) == "standard"


def test_brain_will_not_fry_a_teammate(tmp_path):
    b = board(tmp_path)
    wiz = creature("wiz", "party", 0, 0, sb=wizard_sb()); wiz.reset_state()
    ally = creature("ally", "party", 1, 0)       # directly in the only foe-line
    foes = [creature(f"f{i}", "monsters", x, 0) for i, x in enumerate((2, 3))]
    bf = Battlefield([wiz, ally, *foes], board=b)
    # The only 2-foe line is fouled by the ally, and the foes sit behind it, so
    # there's no clean solo line either -> holds rather than frying the teammate.
    assert EvokerBrain().choose_multiattack(wiz, ConcreteScope(_view(bf, 1, d100=100), wiz)) == "standard"
