"""Capture parity baselines for the masks sim's 6 party x strategy variants.

Design ref: 06-implementation-guide.md Phase 0. masks/src/simulation.py's `run()`
mutates cfg["encounter"]["party"] and cfg["encounter"]["focus"] per variant (on top
of the standard apply_stats(monster, stats) merge every other sim does) - reproduced
here exactly, verified against dnd/masks/src/simulation.py's PARTIES/STRATEGIES maps
and its `run()` function.

Usage (run with masks' own venv active):
    PYTHONHASHSEED=0 uv run --project <repo>/dnd/masks python <path-to-this-script>.py <masks/src dir>

IMPORTANT - PYTHONHASHSEED must be set before the interpreter starts. See
capture_baseline.py's docstring for why (hash-randomized set iteration in
dnd5e_combat.battlefield.Battlefield._grapples makes reruns non-reproducible for
any grapple-capable monster). masks has no grappler, so this sim is not known to be
affected, but the requirement is enforced uniformly for safety and consistency.
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
WORKSPACE_ROOT = Path(__file__).resolve().parents[1]

# Mirrors dnd/masks/src/simulation.py PARTIES / STRATEGIES exactly.
PARTIES = {
    "adventurers": "adventurers",
    "beaumont_playtest": "beaumont_playtest",
}
STRATEGIES = {
    "natural": "hector_a",
    "break_generator": "poet_a",
    "break_mark": "bruiser",
}


def main() -> None:
    if "PYTHONHASHSEED" not in os.environ:
        print("ERROR: PYTHONHASHSEED must be set (e.g. PYTHONHASHSEED=0) before "
              "running this script - see the module docstring.", file=sys.stderr)
        raise SystemExit(2)
    masks_src = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if masks_src is None:
        print(__doc__)
        raise SystemExit(2)
    scenario = (masks_src / "scenario.toml").resolve()
    sys.path.insert(0, str(masks_src))
    from tuning import apply_stats

    for party_label, party in PARTIES.items():
        for strat_label, focus in STRATEGIES.items():
            cfg = load_toml(scenario)
            cfg["simulation"]["trials"] = TRIALS
            cfg["encounter"]["party"] = party
            cfg["encounter"]["focus"] = focus
            cfg["encounter"]["monster"] = apply_stats(
                cfg["encounter"]["monster"], cfg.get("stats", {})
            )
            ctx = assemble(cfg)
            build_engine(ctx).run()

            label = f"masks/{party_label}_{strat_label}"
            out = WORKSPACE_ROOT / "sims" / label / "baseline"
            out.mkdir(parents=True, exist_ok=True)
            (out / "rows.json").write_text(json.dumps(ctx.ledger.rows))
            (out / "meta.json").write_text(json.dumps({
                "scenario": str(scenario),
                "trials": TRIALS,
                "seed": cfg["simulation"].get("seed"),
                "party": party,
                "focus": focus,
                "pythonhashseed": os.environ["PYTHONHASHSEED"],
            }))
            print(f"captured {len(ctx.ledger.rows)} rows -> {out}")


if __name__ == "__main__":
    main()
