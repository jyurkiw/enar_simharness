import tomllib

import pytest

from simharness.config import (
    closed_vocab,
    deep_merge,
    get_path,
    load_toml,
    require_keys,
    set_path,
)


def test_load_toml(tmp_path):
    p = tmp_path / "x.toml"
    p.write_text('name = "otyugh"\n[stats]\nhp = 104\n')
    cfg = load_toml(p)
    assert cfg == {"name": "otyugh", "stats": {"hp": 104}}


def test_deep_merge_nested_tables_merge():
    base = {"stats": {"hp": 104, "ac": 14}, "name": "otyugh"}
    override = {"stats": {"hp": 120}}
    out = deep_merge(base, override)
    assert out == {"stats": {"hp": 120, "ac": 14}, "name": "otyugh"}
    # base is untouched
    assert base["stats"]["hp"] == 104


def test_deep_merge_lists_replace_wholesale():
    base = {"tags": ["tank", "slow"]}
    override = {"tags": ["striker"]}
    out = deep_merge(base, override)
    assert out["tags"] == ["striker"]


def test_deep_merge_scalar_replaces_dict_and_vice_versa():
    base = {"x": {"a": 1}}
    override = {"x": 5}
    assert deep_merge(base, override) == {"x": 5}

    base2 = {"x": 5}
    override2 = {"x": {"a": 1}}
    assert deep_merge(base2, override2) == {"x": {"a": 1}}


def test_get_path_success():
    d = {"a": {"b": {"c": 42}}}
    assert get_path(d, "a.b.c") == 42


def test_get_path_missing_names_exact_segment():
    d = {"a": {"b": {}}}
    with pytest.raises(KeyError) as exc:
        get_path(d, "a.b.c")
    assert "a.b.c" in str(exc.value)


def test_set_path_creates_intermediate_tables():
    d = {}
    set_path(d, "overrides.otyugh.stats.hp", 120)
    assert d == {"overrides": {"otyugh": {"stats": {"hp": 120}}}}


def test_set_path_overwrites_existing_leaf():
    d = {"simulation": {"seed": 1}}
    set_path(d, "simulation.seed", 2)
    assert d["simulation"]["seed"] == 2


def test_set_path_rejects_descending_into_scalar():
    d = {"x": 5}
    with pytest.raises(TypeError):
        set_path(d, "x.y", 1)


def test_require_keys_lists_all_missing():
    with pytest.raises(ValueError) as exc:
        require_keys({"a": 1}, ["a", "b", "c"], where="otyugh.toml [abilities.bite]")
    msg = str(exc.value)
    assert "b" in msg and "c" in msg
    assert "otyugh.toml [abilities.bite]" in msg


def test_require_keys_passes_when_all_present():
    require_keys({"a": 1, "b": 2}, ["a", "b"], where="x")


def test_closed_vocab_rejects_unknown():
    with pytest.raises(ValueError) as exc:
        closed_vocab("teleport", ("attack", "save", "heal", "utility"), where="abilities.bite.kind")
    msg = str(exc.value)
    assert "teleport" in msg
    assert "abilities.bite.kind" in msg


def test_closed_vocab_accepts_known():
    closed_vocab("attack", ("attack", "save", "heal", "utility"), where="x")
