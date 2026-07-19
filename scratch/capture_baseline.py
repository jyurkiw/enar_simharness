"""Capture a parity baseline from an OLD-engine (dnd5e_combat) sim.

**ARCHIVED, NOT RUNNABLE as of Phase 6 (design/05-migration-plan.md):** `dnd5e_combat`
and every old `dnd/*` sim project this script imported (via the old sim's own venv) were
deleted as part of retiring the old engine. Every baseline this script could capture
already has been — see `sims/*/baseline/{rows.json,meta.json}`, which is what actually
matters going forward (design/07-known-issues.md's parity backlog reads from those, not
by re-running this). Kept only as a record of exactly how those baselines were produced.

Design ref: E:\\Repos\\simulations\\simharness_v2\\design\\06-implementation-guide.md, Phase 0.

Every otyugh/board_demo sim's `main()` follows the identical pattern:
    cfg = load_toml(SCENARIO)
    cfg["encounter"]["monster"] = apply_stats(cfg["encounter"]["monster"], cfg.get("stats", {}))
    ctx = assemble(cfg)
    build_engine(ctx).run()
This script reproduces exactly that (verified against each sim's simulation.py before
use) and dumps ctx.ledger.rows instead of printing a report.

masks/simulation.py is NOT covered by this script — it also overrides
cfg["encounter"]["party"] and cfg["encounter"]["focus"] per variant. See
capture_masks_baseline.py for that sim.

Usage (run with the OLD sim's own venv active, so dnd5e_combat/tuning.py resolve):
    PYTHONHASHSEED=0 uv run --project <old-sim-dir> python <path-to-this-script>.py <scenario.toml> <label> [--stats]

<label> may contain "/" to nest (e.g. otyugh_cr5_compare/standard) - baseline output
lands at simharness_v2/sims/<label>/baseline/{rows.json,meta.json}.

--stats: pass when the scenario has a [stats.<archetype>] tuning block that
src/tuning.py::apply_stats merges onto cfg["encounter"]["monster"] (every otyugh sim
has this; board_demo does not).

IMPORTANT - PYTHONHASHSEED must be set before the interpreter starts (it cannot be
fixed from inside this script). Without it, dnd5e_combat.battlefield.Battlefield's
`_grapples: dict[str, set[str]]` iterates in hash-randomized order
(`grabbed_targets()` -> `list(self._grapples[grappler])`), which changes which
grappled target an Otyugh bites/slams first between runs even with the same dice
seed - two captures of the same scenario/seed then disagree starting at whichever
trial first involves a multi-target grapple, despite identical total damage. This
script refuses to run without PYTHONHASHSEED set so every baseline is reproducible.
See design/06-implementation-guide.md Global Gotchas and the Phase 0 write-up for
the investigation; this is also a hazard the new dnd5e grapple graph must avoid
(never let unordered set iteration influence targeting/turn-order decisions).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dnd5e_combat.engine import build_engine
from dnd5e_combat.loader import load_toml
from dnd5e_combat.scenario import assemble

TRIALS = 10_000
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]   # simharness_v2/


def main() -> None:
    if "PYTHONHASHSEED" not in os.environ:
        print("ERROR: PYTHONHASHSEED must be set (e.g. PYTHONHASHSEED=0) before "
              "running this script - see the module docstring.", file=sys.stderr)
        raise SystemExit(2)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    use_stats = "--stats" in sys.argv
    if len(args) != 2:
        print(__doc__)
        raise SystemExit(2)
    scenario_path, label = args
    scenario = Path(scenario_path).resolve()

    cfg = load_toml(scenario)
    cfg["simulation"]["trials"] = TRIALS   # keep the scenario's own seed; raise trial count

    if use_stats:
        sys.path.insert(0, str(scenario.parent))
        from tuning import apply_stats
        cfg["encounter"]["monster"] = apply_stats(
            cfg["encounter"]["monster"], cfg.get("stats", {})
        )

    ctx = assemble(cfg)
    build_engine(ctx).run()

    out = WORKSPACE_ROOT / "sims" / label / "baseline"
    out.mkdir(parents=True, exist_ok=True)
    (out / "rows.json").write_text(json.dumps(ctx.ledger.rows))
    (out / "meta.json").write_text(json.dumps({
        "scenario": str(scenario),
        "trials": TRIALS,
        "seed": cfg["simulation"].get("seed"),
        "used_stats_tuning": use_stats,
        "pythonhashseed": os.environ["PYTHONHASHSEED"],
    }))
    print(f"captured {len(ctx.ledger.rows)} rows -> {out}")


if __name__ == "__main__":
    main()
