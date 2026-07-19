"""Quick smoke test: build a minimal shadow_otyugh vs. one fighter scenario
in-memory and run a handful of trials, to prove the escape hatch resolves and
executes end to end before building the real shadow sims."""

from __future__ import annotations

from pathlib import Path

from dnd_board import load_board_toml

from dnd5e.cli import _build_system_and_runner
from dnd5e.loader import ObscurementSpec, load_creature
from dnd5e.system import Dnd5eSystem, RosterSlot

import dnd5e_data

board = load_board_toml(dnd5e_data.data_path("boards", "plain_room.toml"))

fighter_sb = load_creature(dnd5e_data.data_path("characters", "champion_fighter.toml"))
shadow_sb = load_creature(dnd5e_data.data_path("monsters", "shadow_otyugh.toml"))

fighter_slot = RosterSlot(statblock=fighter_sb, instance_name="champion_fighter", side="party", start=(2, 2))
shadow_slot = RosterSlot(statblock=shadow_sb, instance_name="shadow_otyugh", side="monsters", start=(8, 2))

system = Dnd5eSystem(
    board=board, roster=[fighter_slot, shadow_slot], max_rounds=6,
    obscurement=(ObscurementSpec(kind="magical_darkness", radius_ft=30, follows="shadow_otyugh"),),
)

names = [fighter_slot.instance_name, shadow_slot.instance_name]
side_of = {fighter_slot.instance_name: "party", shadow_slot.instance_name: "monsters"}
from simharness.runner import TrialRunner
runner = TrialRunner(system, seed=42, max_rounds=6, names=names, side_of=side_of)
ledger = runner.run(trials=300)

print("trials:", len(ledger.rows))
sample = ledger.rows[0]
for k in sorted(sample):
    print(f"  {k}: {sample[k]}")

retreated = sum(r.get("retreated", 0) for r in ledger.rows)
print("retreated count:", retreated, "/", len(ledger.rows))
