"""dnd5e_data: shared TOML creature/board library.

Data only — no code beyond this file. `characters/`, `monsters/`, and
`boards/` hold the reusable creature and board definitions consumed by
simulation files, resolved through `dnd5e`'s creature/board source chain
(design doc 01) via `importlib.resources`.
"""

from pathlib import Path

_ROOT = Path(__file__).parent


def data_path(*parts: str) -> Path:
    """Absolute path into this package's data directories."""
    return _ROOT.joinpath(*parts)
