# otyugh-cr5-monk

Isolates the Ranger's contribution: the standard party vs. the same party with
the Ranger swapped for an unarmed Monk, run against 1x and 2x CR5 Otyugh.

## Running

From the repository root (`simulations/`):

**PowerShell**
```powershell
cd dnd\otyugh\otyugh_cr5_monk
uv run python src\simulation.py
```

**Bash**
```bash
cd dnd/otyugh/otyugh_cr5_monk
uv run python src/simulation.py
```

The first run triggers `uv sync` automatically (it installs the `dnd5e-combat`
engine from the local editable path in `pyproject.toml`). Results print to the
console; summary charts (`.png`) are written to this directory.
