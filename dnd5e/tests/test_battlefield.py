import pytest
from dnd_board import ObscurementField, Region, load_board_toml

from dnd5e.battlefield import Aura, Battlefield
from dnd5e.creature import Creature
from dnd5e.statblock import Statblock, Stats

BOARD_TOML = '''
name = "test_board"

map = """
..........
..........
..#.......
..........
..........
"""

[meta]
cell_feet = 5

[glyph.'#']
terrain = "impassable"
cover = "full"
blocks_los = true
blocks_light = true
'''


@pytest.fixture
def board(tmp_path):
    p = tmp_path / "board.toml"
    p.write_text(BOARD_TOML)
    return load_board_toml(p)


def make_stats(**overrides):
    base = dict(strength=10, dexterity=10, constitution=10, intelligence=10, wisdom=10,
               charisma=10, ac=14, speed=30, initiative_bonus=0, proficiency=2,
               crit_range=20, reach=5, hit_dice=None, hp_average=20)
    base.update(overrides)
    return Stats(**base)


def make_creature(name, side, *, x=None, y=None, hp=None):
    sb = Statblock(name=name, display_name=name, classification={},
                   stats=make_stats(hp_average=hp or 20))
    c = Creature(statblock=sb, instance_name=name, side=side)
    if x is not None:
        c.place(x, y)
    return c


def test_enemies_of_excludes_own_side_and_downed(board):
    fighter = make_creature("fighter", "party", x=0, y=0)
    rogue = make_creature("rogue", "party", x=1, y=0)
    otyugh = make_creature("otyugh", "monsters", x=5, y=0)
    dead_otyugh = make_creature("otyugh2", "monsters", x=6, y=0)
    dead_otyugh.current_damage = 999  # is_down
    bf = Battlefield([fighter, rogue, otyugh, dead_otyugh], board=board)

    enemies = bf.enemies_of(fighter)
    assert {e.instance_name for e in enemies} == {"otyugh"}


def test_allies_of_excludes_self_and_downed(board):
    fighter = make_creature("fighter", "party", x=0, y=0)
    rogue = make_creature("rogue", "party", x=1, y=0)
    bf = Battlefield([fighter, rogue], board=board)
    assert {a.instance_name for a in bf.allies_of(fighter)} == {"rogue"}


def test_distance_ft_and_in_reach(board):
    fighter = make_creature("fighter", "party", x=0, y=0, hp=20)
    otyugh = make_creature("otyugh", "monsters", x=1, y=0, hp=20)
    bf = Battlefield([fighter, otyugh], board=board)
    assert bf.distance_ft(fighter, otyugh) == 5
    assert bf.in_reach(fighter, otyugh) is True  # reach 5, distance 5

    far = make_creature("far", "monsters", x=9, y=0)
    assert bf.in_reach(fighter, far) is False


def test_distance_ft_none_when_unplaced(board):
    fighter = make_creature("fighter", "party")  # never placed
    otyugh = make_creature("otyugh", "monsters", x=1, y=0)
    bf = Battlefield([fighter, otyugh], board=board)
    assert bf.distance_ft(fighter, otyugh) is None
    assert bf.in_reach(fighter, otyugh) is False


def test_nearest_enemy(board):
    fighter = make_creature("fighter", "party", x=0, y=0)
    near = make_creature("near", "monsters", x=2, y=0)
    far = make_creature("far", "monsters", x=8, y=0)
    bf = Battlefield([fighter, near, far], board=board)
    assert bf.nearest_enemy(fighter).instance_name == "near"


def test_primary_enemy_prefers_visible_focus(board):
    fighter = make_creature("fighter", "party", x=0, y=0)
    a = make_creature("a", "monsters", x=1, y=0)
    b = make_creature("b", "monsters", x=2, y=0)
    bf = Battlefield([fighter, a, b], board=board)
    bf.focus["party"] = "b"
    assert bf.primary_enemy(fighter).instance_name == "b"


def test_primary_enemy_falls_back_to_nearest_visible_when_focus_down(board):
    fighter = make_creature("fighter", "party", x=0, y=0)
    a = make_creature("a", "monsters", x=1, y=0)
    b = make_creature("b", "monsters", x=8, y=0)
    b.current_damage = 999
    bf = Battlefield([fighter, a, b], board=board)
    bf.focus["party"] = "b"
    assert bf.primary_enemy(fighter).instance_name == "a"


def test_preferred_target_is_own_grappler_when_grappled(board):
    fighter = make_creature("fighter", "party", x=0, y=0)
    otyugh = make_creature("otyugh", "monsters", x=1, y=0)
    other = make_creature("other", "monsters", x=8, y=0)
    bf = Battlefield([fighter, otyugh, other], board=board)
    bf.focus["party"] = "other"
    bf.grapple("otyugh", "fighter")
    assert bf.preferred_target(fighter).instance_name == "otyugh"


def test_line_of_sight_and_cover_delegate_to_vision(board):
    a = make_creature("a", "party", x=0, y=2)
    b = make_creature("b", "monsters", x=4, y=2)  # wall at (2,2) between them
    bf = Battlefield([a, b], board=board)
    assert bf.line_of_sight(a, b) is False
    assert bf.can_see(a, b) is False
    assert bf.has_full_cover(a, b) is True


def test_occupied_cells_excludes_downed_and_named_exclusions(board):
    a = make_creature("a", "party", x=0, y=0)
    b = make_creature("b", "party", x=1, y=0)
    c = make_creature("c", "monsters", x=2, y=0)
    c.current_damage = 999
    bf = Battlefield([a, b, c], board=board)
    assert bf.occupied_cells() == {(0, 0), (1, 0)}
    assert bf.occupied_cells(exclude=("a",)) == {(1, 0)}


# ---- grapple graph ---------------------------------------------------------

def test_grapple_and_release(board):
    bf = Battlefield([], board=board)
    bf.grapple("otyugh", "fighter")
    assert bf.grappled_by("fighter") == "otyugh"
    assert bf.grabbed_targets("otyugh") == ["fighter"]
    bf.release("otyugh", "fighter")
    assert bf.grappled_by("fighter") is None
    assert bf.grabbed_targets("otyugh") == []


def test_grapple_supersedes_prior_grappler(board):
    bf = Battlefield([], board=board)
    bf.grapple("otyugh1", "fighter")
    bf.grapple("otyugh2", "fighter")
    assert bf.grappled_by("fighter") == "otyugh2"
    assert bf.grabbed_targets("otyugh1") == []
    assert bf.grabbed_targets("otyugh2") == ["fighter"]


def test_release_all_targets_of_a_grappler(board):
    bf = Battlefield([], board=board)
    bf.grapple("otyugh", "fighter")
    bf.grapple("otyugh", "rogue")
    bf.release("otyugh")
    assert bf.grabbed_targets("otyugh") == []
    assert bf.grappled_by("fighter") is None
    assert bf.grappled_by("rogue") is None


def test_is_grappling(board):
    bf = Battlefield([], board=board)
    assert bf.is_grappling("otyugh") is False
    bf.grapple("otyugh", "fighter")
    assert bf.is_grappling("otyugh") is True


def test_clear_grapples(board):
    bf = Battlefield([], board=board)
    bf.grapple("otyugh", "fighter")
    bf.clear_grapples()
    assert bf.grabbed_targets("otyugh") == []
    assert bf.grappled_by("fighter") is None


def test_grabbed_targets_is_deterministic_insertion_order_not_hash_order(board):
    """Regression test for design doc 06 Global Gotcha 7a: the old engine's
    `_grapples: dict[str, set[str]]` returned grappled-target order dependent
    on Python's per-process hash randomization, so an Otyugh grappling two
    targets would bite/slam them in a different order across runs even with
    an identical dice seed. This asserts insertion order is preserved exactly
    — the actual guarantee that closes the hole (hash randomization can't
    perturb list order the way it perturbs set iteration order)."""
    bf = Battlefield([], board=board)
    # Grapple in a specific order; targets named so alphabetical/hash order
    # would very likely disagree with insertion order if a set were used.
    bf.grapple("otyugh", "zed")
    bf.grapple("otyugh", "alice")
    bf.grapple("otyugh", "mike")
    assert bf.grabbed_targets("otyugh") == ["zed", "alice", "mike"]
    # Re-querying repeatedly must be stable (proves it's not re-deriving from
    # a set each call).
    for _ in range(5):
        assert bf.grabbed_targets("otyugh") == ["zed", "alice", "mike"]


def test_grapple_target_not_duplicated_on_regrapple(board):
    bf = Battlefield([], board=board)
    bf.grapple("otyugh", "fighter")
    bf.grapple("otyugh", "fighter")  # re-grapple same target: no-op duplicate
    assert bf.grabbed_targets("otyugh") == ["fighter"]


# ---- obscurement / auras (row y=0, clear of the fixture's wall at (2,2)) -----

def test_can_see_blocked_when_target_is_heavily_obscured(board):
    a = make_creature("a", "party", x=0, y=0)
    b = make_creature("b", "monsters", x=5, y=0)
    obsc = ObscurementField(cell_feet=5, regions=[Region(center=(5, 0), radius_ft=10, kind="darkness")])
    bf = Battlefield([a, b], board=board, obscurement=obsc)
    assert bf.can_see(a, b) is False


def test_can_see_unblocked_outside_obscurement(board):
    a = make_creature("a", "party", x=0, y=0)
    b = make_creature("b", "monsters", x=5, y=0)
    obsc = ObscurementField(cell_feet=5, regions=[])
    bf = Battlefield([a, b], board=board, obscurement=obsc)
    assert bf.can_see(a, b) is True


def test_can_see_immune_observer_sees_through_own_darkness_aura(board):
    a = make_creature("a", "party", x=0, y=0)
    b = make_creature("b", "monsters", x=5, y=0)
    obsc = ObscurementField(cell_feet=5, regions=[Region(center=(5, 0), radius_ft=30, kind="darkness")])
    bf = Battlefield([a, b], board=board, obscurement=obsc,
                     auras=[Aura(source="b", kind="darkness", radius_ft=30)])
    # b is the darkness's own source -> immune -> sees a fine despite both
    # cells being inside the darkness region.
    assert bf.can_see(b, a) is True
    # a is not immune -> blocked (b's cell is obscured).
    assert bf.can_see(a, b) is False


def test_can_see_limited_darkvision_caps_range(board):
    a = make_creature("a", "party", x=0, y=0)
    a.trial_scratch["limited_darkvision_ft"] = 30
    near = make_creature("near", "monsters", x=5, y=0)   # 25 ft away
    far = make_creature("far", "monsters", x=9, y=0)      # 45 ft away
    obsc = ObscurementField(cell_feet=5, regions=[
        Region(center=(0, 0), radius_ft=50, kind="darkness"),  # covers the whole row
    ])
    bf = Battlefield([a, near, far], board=board, obscurement=obsc)
    assert bf.can_see(a, near) is True    # within the 30 ft darkvision cap
    assert bf.can_see(a, far) is False    # beyond it


def test_refresh_auras_follows_source_and_recenters(board):
    otyugh = make_creature("otyugh", "monsters", x=2, y=0)
    obsc = ObscurementField(cell_feet=5)
    bf = Battlefield([otyugh], board=board, obscurement=obsc,
                     auras=[Aura(source="otyugh", kind="darkness", radius_ft=30)])
    bf.refresh_auras(round_index=1)
    assert obsc.regions == [Region(center=(2, 0), radius_ft=30, kind="darkness")]

    otyugh.x, otyugh.y = 4, 0
    bf.refresh_auras(round_index=2)
    assert obsc.regions == [Region(center=(4, 0), radius_ft=30, kind="darkness")]


def test_refresh_auras_skips_before_start_round(board):
    otyugh = make_creature("otyugh", "monsters", x=2, y=0)
    obsc = ObscurementField(cell_feet=5)
    bf = Battlefield([otyugh], board=board, obscurement=obsc,
                     auras=[Aura(source="otyugh", kind="darkness", radius_ft=30, start_round=2)])
    bf.refresh_auras(round_index=1)
    assert obsc.regions == []
    bf.refresh_auras(round_index=2)
    assert len(obsc.regions) == 1


def test_refresh_auras_skips_down_source(board):
    otyugh = make_creature("otyugh", "monsters", x=2, y=0, hp=20)
    otyugh.current_damage = 999  # down
    obsc = ObscurementField(cell_feet=5)
    bf = Battlefield([otyugh], board=board, obscurement=obsc,
                     auras=[Aura(source="otyugh", kind="darkness", radius_ft=30)])
    bf.refresh_auras(round_index=1)
    assert obsc.regions == []


def test_refresh_auras_keeps_static_regions_alongside_auras(board):
    otyugh = make_creature("otyugh", "monsters", x=2, y=0)
    static_region = Region(center=(8, 8), radius_ft=15, kind="fog")
    obsc = ObscurementField(cell_feet=5, regions=[static_region])
    bf = Battlefield([otyugh], board=board, obscurement=obsc,
                     auras=[Aura(source="otyugh", kind="darkness", radius_ft=30)])
    bf.refresh_auras(round_index=1)
    assert static_region in obsc.regions
    assert Region(center=(2, 0), radius_ft=30, kind="darkness") in obsc.regions


def test_obscurement_immune_includes_darkness_aura_source_and_darkvision_trait(board):
    a = make_creature("a", "party", x=0, y=0)
    b = make_creature("b", "monsters", x=5, y=0)
    b.trial_scratch["darkvision_immune"] = True
    bf = Battlefield([a, b], board=board, obscurement=ObscurementField(cell_feet=5),
                     auras=[Aura(source="a", kind="magical_darkness", radius_ft=30)])
    assert bf.obscurement_immune() == {"a", "b"}


def test_not_blinded_by_obscurement_also_includes_limited_darkvision(board):
    a = make_creature("a", "party", x=0, y=0)
    a.trial_scratch["limited_darkvision_ft"] = 30
    bf = Battlefield([a], board=board, obscurement=ObscurementField(cell_feet=5))
    assert bf.obscurement_immune() == set()
    assert bf.not_blinded_by_obscurement() == {"a"}


def test_no_obscurement_field_means_no_crash_and_full_visibility(board):
    a = make_creature("a", "party", x=0, y=0)
    b = make_creature("b", "monsters", x=5, y=0)
    bf = Battlefield([a, b], board=board)  # obscurement=None (the default)
    assert bf.can_see(a, b) is True
    bf.refresh_auras(round_index=1)  # no-op, must not raise
