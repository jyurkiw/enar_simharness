import pytest

from simharness.ledger import Ledger


SIDES = {"fighter": "party", "rogue": "party", "otyugh": "monsters"}


def make_ledger():
    return Ledger(names=["fighter", "rogue", "otyugh"], side_of=SIDES)


def test_record_accumulates_and_finalize_produces_uniform_row():
    ledger = make_ledger()
    ledger.record("fighter", "otyugh", "longsword", 10)
    ledger.record("fighter", "otyugh", "longsword", 7)
    ledger.record("otyugh", "fighter", "bite", 12)
    ledger.finalize_trial()

    row = ledger.rows[0]
    assert row["dealt_fighter"] == 17
    assert row["taken_otyugh"] == 17
    assert row["dealt_otyugh"] == 12
    assert row["taken_fighter"] == 12
    # rogue had zero events this trial but still gets uniform columns
    assert row["dealt_rogue"] == 0
    assert row["taken_rogue"] == 0
    assert row["side_dealt_party"] == 17
    assert row["side_dealt_monsters"] == 12


def test_non_positive_amounts_are_noops():
    ledger = make_ledger()
    ledger.record("fighter", "otyugh", "longsword", 0)
    ledger.record("fighter", "otyugh", "longsword", -5)
    ledger.finalize_trial()
    row = ledger.rows[0]
    assert row["dealt_fighter"] == 0
    assert row["side_dealt_party"] == 0


def test_outcome_dict_merges_and_can_override_ledger_columns():
    ledger = make_ledger()
    ledger.record("fighter", "otyugh", "longsword", 10)
    ledger.finalize_trial({"wiped_monsters": 1, "dealt_fighter": 999})
    row = ledger.rows[0]
    assert row["wiped_monsters"] == 1
    assert row["dealt_fighter"] == 999  # outcome wins over the ledger's own tally


def test_accumulator_resets_between_trials():
    ledger = make_ledger()
    ledger.record("fighter", "otyugh", "longsword", 10)
    ledger.finalize_trial()
    ledger.record("fighter", "otyugh", "longsword", 3)
    ledger.finalize_trial()
    assert len(ledger.rows) == 2
    assert ledger.rows[0]["dealt_fighter"] == 10
    assert ledger.rows[1]["dealt_fighter"] == 3


def test_combatants_on_filters_by_side():
    ledger = make_ledger()
    assert ledger.combatants_on("party") == ["fighter", "rogue"]
    assert ledger.combatants_on("monsters") == ["otyugh"]


def test_side_of_accepts_callable_not_just_mapping():
    def side_of(name: str) -> str:
        return "monsters" if name == "otyugh" else "party"

    ledger = Ledger(names=["fighter", "otyugh"], side_of=side_of)
    ledger.record("fighter", "otyugh", "longsword", 5)
    ledger.finalize_trial()
    row = ledger.rows[0]
    assert row["side_dealt_party"] == 5
    assert row["side_dealt_monsters"] == 0


def test_multiple_events_same_triple_sum():
    ledger = make_ledger()
    ledger.record("fighter", "otyugh", "longsword", 5)
    ledger.record("fighter", "otyugh", "longsword", 5)
    ledger.record("fighter", "otyugh", "longsword", 5)
    ledger.finalize_trial()
    assert ledger.rows[0]["dealt_fighter"] == 15
