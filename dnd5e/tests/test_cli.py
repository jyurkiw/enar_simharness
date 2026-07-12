import json

import pytest

from dnd5e.cli import main

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

SIMPLE_ABILITY = '[abilities.hit]\nkind = "attack"\nto_hit = 5\ndamage = "1d6"\n[multiattack.standard]\nactions = ["hit"]\n'

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


def make_sim(tmp_path, *, trials=50, max_rounds=5, seed=1):
    sim_dir = tmp_path / "sim"
    (sim_dir / "creatures").mkdir(parents=True)
    (sim_dir / "boards").mkdir(parents=True)
    (sim_dir / "boards" / "test.toml").write_text(BOARD_WITH_SPAWNS)
    for name in ("fighter", "otyugh"):
        (sim_dir / "creatures" / f"{name}.toml").write_text(
            f'name = "{name}"\n{MINIMAL_STATS}\n{SIMPLE_ABILITY}')
    sim_toml = sim_dir / "simulation.toml"
    sim_toml.write_text(f'''
name = "test_sim"
board = "boards/test.toml"
[simulation]
trials = {trials}
max_rounds = {max_rounds}
seed = {seed}
[[combatants]]
creature = "fighter"
side = "party"
spawn = "party"
[[combatants]]
creature = "otyugh"
side = "monsters"
spawn = "monsters"
[output]
report = ["totals"]
''')
    return sim_dir, sim_toml


def test_validate_single_creature_file(tmp_path, capsys):
    p = tmp_path / "otyugh.toml"
    p.write_text(f'name = "otyugh"\n{MINIMAL_STATS}')
    code = main(["validate", str(p)])
    assert code == 0
    assert "OK" in capsys.readouterr().out


def test_validate_single_board_file(tmp_path, capsys):
    p = tmp_path / "board.toml"
    p.write_text(BOARD_WITH_SPAWNS)
    code = main(["validate", str(p)])
    assert code == 0
    assert "OK" in capsys.readouterr().out


def test_validate_single_simulation_file(tmp_path, capsys):
    sim_dir, sim_toml = make_sim(tmp_path)
    code = main(["validate", str(sim_toml)])
    assert code == 0
    assert "OK" in capsys.readouterr().out


def test_validate_invalid_creature_reports_failure(tmp_path, capsys):
    p = tmp_path / "bad.toml"
    p.write_text('name = "wrong_name_not_matching_stem"\n[stats]\nstrength=10\n')
    code = main(["validate", str(p)])
    assert code == 1
    assert "FAIL" in capsys.readouterr().out


def test_validate_unclassifiable_file_reports_failure(tmp_path, capsys):
    p = tmp_path / "mystery.toml"
    p.write_text('foo = "bar"\n')
    code = main(["validate", str(p)])
    assert code == 1
    out = capsys.readouterr().out
    assert "FAIL" in out and "cannot determine file type" in out


def test_validate_directory_scans_all_toml_files(tmp_path, capsys):
    sim_dir, sim_toml = make_sim(tmp_path)
    code = main(["validate", str(sim_dir)])
    out = capsys.readouterr().out
    assert code == 0
    assert "all" in out and "file(s) valid" in out
    # board + 2 creatures + 1 simulation = 4 files
    assert out.count("OK") == 4


def test_validate_directory_with_one_bad_file_returns_nonzero(tmp_path, capsys):
    sim_dir, sim_toml = make_sim(tmp_path)
    (sim_dir / "creatures" / "broken.toml").write_text('name = "mismatch"\n[stats]\nstrength=10\n')
    code = main(["validate", str(sim_dir)])
    captured = capsys.readouterr()
    assert code == 1
    assert "FAIL" in captured.out
    assert "failure(s)" in captured.err


def test_run_executes_and_prints_report(tmp_path, capsys):
    sim_dir, sim_toml = make_sim(tmp_path, trials=20)
    code = main(["run", str(sim_toml)])
    assert code == 0
    out = capsys.readouterr().out
    assert "totals" in out


def test_run_trials_override(tmp_path, capsys):
    sim_dir, sim_toml = make_sim(tmp_path, trials=20)
    code = main(["run", str(sim_toml), "--trials", "5"])
    assert code == 0  # just proving the override path doesn't error


def test_run_baseline_compare_passes_against_itself(tmp_path, capsys):
    sim_dir, sim_toml = make_sim(tmp_path, trials=200, seed=777)
    # First run: capture rows via a direct run to build a "baseline".
    from dnd5e.cli import _build_system_and_runner
    from dnd5e.loader import load_simulation
    spec = load_simulation(sim_toml)
    runner, trials = _build_system_and_runner(spec)
    ledger = runner.run(trials=200)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(ledger.rows))

    code = main(["run", str(sim_toml), "--trials", "200", "--baseline", str(baseline_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "PASS" in out


def test_run_baseline_compare_fails_against_a_different_baseline(tmp_path, capsys):
    sim_dir, sim_toml = make_sim(tmp_path, trials=200, seed=777)
    # A fabricated baseline with wildly different numbers guarantees a fail.
    fake_rows = [{"dealt_fighter": 9999, "taken_fighter": 9999, "dealt_otyugh": 9999,
                 "taken_otyugh": 9999, "side_dealt_party": 9999, "side_dealt_monsters": 9999}
                for _ in range(200)]
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(fake_rows))

    code = main(["run", str(sim_toml), "--trials", "200", "--baseline", str(baseline_path)])
    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL" in out


def test_validate_missing_path_reports_no_files(tmp_path, capsys):
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    code = main(["validate", str(empty_dir)])
    assert code == 1
