# otyugh-shadow-solo

Solo Shadow Otyugh (CR7 retune candidate) vs the Beaumont playtest party. Models
the Photophage darkness aura, bite poison, light-source hunting, and the
Bloodied retreat. This is the sim used to tune the CR7 statblock — see
[`../CR7_TUNING_GUIDE.md`](../CR7_TUNING_GUIDE.md).

## Running

From the repository root (`simulations/`):

**PowerShell**
```powershell
cd dnd\otyugh\otyugh_shadow_solo
uv run python src\simulation.py
```

**Bash**
```bash
cd dnd/otyugh/otyugh_shadow_solo
uv run python src/simulation.py
```

The first run triggers `uv sync` automatically (it installs the `dnd5e-combat`
engine from the local editable path in `pyproject.toml`). Results print to the
console; summary charts (`.png`) are written to this directory. Tune the
statblock in `dnd5e_combat/.../monsters/shadow_otyugh/defaults.toml` and rerun.
