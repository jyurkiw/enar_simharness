# otyugh-cr5-compare

Runs the standard party and the vanguard party against a single CR5 Otyugh and prints a side-by-side comparison.

## Running

From the repository root (`simulations/`):

**PowerShell**
```powershell
cd dnd\otyugh\otyugh_cr5_compare
uv run python src\simulation.py
```

**Bash**
```bash
cd dnd/otyugh/otyugh_cr5_compare
uv run python src/simulation.py
```

The first run triggers `uv sync` automatically (it installs the `dnd5e-combat`
engine from the local editable path in `pyproject.toml`). Results print to the
console; summary charts (`.png`) are written to this directory.
