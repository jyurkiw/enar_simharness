# otyugh-cr5-x2

Two CR5 Otyughs vs the standard level-5 party.

## Running

From the repository root (`simulations/`):

**PowerShell**
```powershell
cd dnd\otyugh\otyugh_cr5_x2
uv run python src\simulation.py
```

**Bash**
```bash
cd dnd/otyugh/otyugh_cr5_x2
uv run python src/simulation.py
```

The first run triggers `uv sync` automatically (it installs the `dnd5e-combat`
engine from the local editable path in `pyproject.toml`). Results print to the
console; summary charts (`.png`) are written to this directory.
