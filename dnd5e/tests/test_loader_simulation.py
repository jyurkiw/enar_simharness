import pytest

from dnd5e.loader import NotYetSupportedError, load_simulation

MINIMAL_STATS = """
[stats]
strength = 16
dexterity = 11
constitution = 19
intelligence = 6
wisdom = 13
charisma = 6
ac = 14
speed = 30
"""

BOARD_WITH_SPAWNS = '''
name = "test_board"
map = """
P.......M
P.......M
"""
[meta]
cell_feet = 5
[glyph.'P']
spawn = "party"
[glyph.'M']
spawn = "monsters"
'''

SIMPLE_ABILITY = '[abilities.hit]\nkind = "attack"\nto_hit = 5\ndamage = "1d6"\n[multiattack.standard]\nactions = ["hit"]\n'


def make_sim_dir(tmp_path):
    sim_dir = tmp_path / "sim"
    (sim_dir / "creatures").mkdir(parents=True)
    (sim_dir / "boards").mkdir(parents=True)
    (sim_dir / "boards" / "test.toml").write_text(BOARD_WITH_SPAWNS)
    return sim_dir


def write_creature(sim_dir, name, extra=""):
    body = f'name = "{name}"\n{MINIMAL_STATS}\n{extra}'
    (sim_dir / "creatures" / f"{name}.toml").write_text(body)


def sim_toml(sim_dir, *, name="x", board='"boards/test.toml"', extra_top="",
             trials=1, max_rounds=1, seed=1, hp_mode=None, tables=""):
    """Compose a valid simulation.toml: every top-level scalar (name, board,
    sources, ...) is written before the first [table] header — see design
    doc 01 section 3's note on why that ordering is mandatory in TOML."""
    hp_line = f'hp_mode = "{hp_mode}"\n' if hp_mode else ""
    text = (
        f'name = "{name}"\n'
        f'board = {board}\n'
        f'{extra_top}'
        f'[simulation]\n'
        f'trials = {trials}\n'
        f'max_rounds = {max_rounds}\n'
        f'seed = {seed}\n'
        f'{hp_line}'
        f'{tables}'
    )
    p = sim_dir / "simulation.toml"
    p.write_text(text)
    return p


def test_load_minimal_simulation(tmp_path):
    sim_dir = make_sim_dir(tmp_path)
    write_creature(sim_dir, "fighter", SIMPLE_ABILITY)
    write_creature(sim_dir, "otyugh", SIMPLE_ABILITY)
    path = sim_toml(sim_dir, name="test_sim", trials=100, max_rounds=5, seed=42, tables='''
[[combatants]]
creature = "fighter"
side = "party"
spawn = "party"
[[combatants]]
creature = "otyugh"
side = "monsters"
spawn = "monsters"
''')
    spec = load_simulation(path)
    assert spec.name == "test_sim"
    assert spec.trials == 100
    assert spec.max_rounds == 5
    assert spec.seed == 42
    assert spec.hp_mode == "average"
    assert len(spec.roster) == 2
    names = {slot.instance_name for slot in spec.roster}
    assert names == {"fighter", "otyugh"}


def test_missing_simulation_keys_raises(tmp_path):
    sim_dir = make_sim_dir(tmp_path)
    p = sim_dir / "simulation.toml"
    p.write_text('name = "x"\nboard = "boards/test.toml"\n[simulation]\ntrials = 100\n')
    with pytest.raises(ValueError, match="missing required key"):
        load_simulation(p)


def test_missing_board_key_raises(tmp_path):
    sim_dir = make_sim_dir(tmp_path)
    p = sim_dir / "simulation.toml"
    p.write_text('name = "x"\n[simulation]\ntrials=1\nmax_rounds=1\nseed=1\n')
    with pytest.raises(ValueError, match="missing required 'board'"):
        load_simulation(p)


def test_no_combatants_raises(tmp_path):
    sim_dir = make_sim_dir(tmp_path)
    path = sim_toml(sim_dir)
    with pytest.raises(ValueError, match=r"no \[\[combatants\]\]"):
        load_simulation(path)


def test_creature_resolution_prefers_sim_local_creatures_dir(tmp_path):
    sim_dir = make_sim_dir(tmp_path)
    write_creature(sim_dir, "otyugh", SIMPLE_ABILITY)  # sim-local, shadows any library copy
    path = sim_toml(sim_dir, tables='''
[[combatants]]
creature = "otyugh"
side = "monsters"
spawn = "monsters"
''')
    spec = load_simulation(path)
    assert spec.roster[0].statblock.name == "otyugh"


def test_creature_not_found_anywhere_raises(tmp_path):
    sim_dir = make_sim_dir(tmp_path)
    path = sim_toml(sim_dir, tables='''
[[combatants]]
creature = "nonexistent_creature_xyz"
side = "monsters"
spawn = "monsters"
''')
    with pytest.raises(ValueError, match="not found"):
        load_simulation(path)


def test_count_greater_than_one_auto_suffixes_instance_names(tmp_path):
    sim_dir = make_sim_dir(tmp_path)
    write_creature(sim_dir, "otyugh", SIMPLE_ABILITY)
    path = sim_toml(sim_dir, tables='''
[[combatants]]
creature = "otyugh"
side = "monsters"
spawn = "monsters"
count = 2
''')
    spec = load_simulation(path)
    names = {slot.instance_name for slot in spec.roster}
    assert names == {"otyugh_1", "otyugh_2"}


def test_spawn_round_robin_assigns_distinct_cells(tmp_path):
    sim_dir = make_sim_dir(tmp_path)
    write_creature(sim_dir, "otyugh", SIMPLE_ABILITY)
    path = sim_toml(sim_dir, tables='''
[[combatants]]
creature = "otyugh"
side = "monsters"
spawn = "monsters"
count = 2
''')
    spec = load_simulation(path)
    starts = {slot.start for slot in spec.roster}
    assert len(starts) == 2  # both got distinct cells, not the same one twice


def test_explicit_start_overrides_spawn_label(tmp_path):
    sim_dir = make_sim_dir(tmp_path)
    write_creature(sim_dir, "otyugh", SIMPLE_ABILITY)
    path = sim_toml(sim_dir, tables='''
[[combatants]]
creature = "otyugh"
side = "monsters"
start = [3, 1]
''')
    spec = load_simulation(path)
    assert spec.roster[0].start == (3, 1)


def test_missing_spawn_and_start_raises(tmp_path):
    sim_dir = make_sim_dir(tmp_path)
    write_creature(sim_dir, "otyugh", SIMPLE_ABILITY)
    path = sim_toml(sim_dir, tables='''
[[combatants]]
creature = "otyugh"
side = "monsters"
''')
    with pytest.raises(ValueError, match="needs a 'spawn' label or explicit 'start'"):
        load_simulation(path)


def test_unknown_spawn_label_raises(tmp_path):
    sim_dir = make_sim_dir(tmp_path)
    write_creature(sim_dir, "otyugh", SIMPLE_ABILITY)
    path = sim_toml(sim_dir, tables='''
[[combatants]]
creature = "otyugh"
side = "monsters"
spawn = "nonexistent_label"
''')
    with pytest.raises(ValueError, match="spawn label"):
        load_simulation(path)


def test_overrides_applied_to_named_creature(tmp_path):
    sim_dir = make_sim_dir(tmp_path)
    write_creature(sim_dir, "otyugh", SIMPLE_ABILITY)
    path = sim_toml(sim_dir, tables='''
[[combatants]]
creature = "otyugh"
side = "monsters"
spawn = "monsters"
[overrides.otyugh]
stats.ac = 99
''')
    spec = load_simulation(path)
    assert spec.roster[0].statblock.stats.ac == 99


def test_environment_focus_maps_to_party_side(tmp_path):
    sim_dir = make_sim_dir(tmp_path)
    write_creature(sim_dir, "otyugh", SIMPLE_ABILITY)
    path = sim_toml(sim_dir, tables='''
[[combatants]]
creature = "otyugh"
side = "monsters"
spawn = "monsters"
[environment]
focus = "otyugh"
''')
    spec = load_simulation(path)
    assert spec.focus == {"party": "otyugh"}


def test_environment_obscurement_raises_not_yet_supported(tmp_path):
    sim_dir = make_sim_dir(tmp_path)
    write_creature(sim_dir, "otyugh", SIMPLE_ABILITY)
    path = sim_toml(sim_dir, tables='''
[[combatants]]
creature = "otyugh"
side = "monsters"
spawn = "monsters"
[[environment.obscurement]]
kind = "darkness"
radius = 30
''')
    with pytest.raises(NotYetSupportedError, match="Phase 4"):
        load_simulation(path)


def test_hp_mode_rolled_accepted(tmp_path):
    sim_dir = make_sim_dir(tmp_path)
    write_creature(sim_dir, "otyugh", SIMPLE_ABILITY)
    path = sim_toml(sim_dir, hp_mode="rolled", tables='''
[[combatants]]
creature = "otyugh"
side = "monsters"
spawn = "monsters"
''')
    spec = load_simulation(path)
    assert spec.hp_mode == "rolled"


def test_hp_mode_invalid_raises(tmp_path):
    sim_dir = make_sim_dir(tmp_path)
    write_creature(sim_dir, "otyugh", SIMPLE_ABILITY)
    path = sim_toml(sim_dir, hp_mode="bogus", tables='''
[[combatants]]
creature = "otyugh"
side = "monsters"
spawn = "monsters"
''')
    with pytest.raises(ValueError, match="not one of"):
        load_simulation(path)


def test_lib_board_reference_resolves_to_dnd5e_data(tmp_path):
    sim_dir = make_sim_dir(tmp_path)
    write_creature(sim_dir, "otyugh", SIMPLE_ABILITY)
    write_creature(sim_dir, "fighter", SIMPLE_ABILITY)
    path = sim_toml(sim_dir, board='"lib:plain_room"', tables='''
[[combatants]]
creature = "fighter"
side = "party"
spawn = "party"
[[combatants]]
creature = "otyugh"
side = "monsters"
spawn = "monsters"
''')
    spec = load_simulation(path)
    assert spec.board.meta["name"] == "plain_room"
