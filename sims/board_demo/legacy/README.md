# board_demo

A minimal board-based encounter that exercises the `dnd_board` integration: a
melee-heavy party spawns on the west edge of the `arena` map and closes on a lone
Otyugh spawned on the east edge, with an archer firing across the central wall's
gap. It demonstrates A* movement (the melee combatants must path into reach),
line of sight (the archer needs a clear line), and reach-based melee vs. ranged
attack resolution.

```sh
uv sync
uv run python src/simulation.py
```

The encounter is entirely config-driven — see `src/scenario.toml`. The board is
loaded by name (`board = "arena"`) from the compiled maps packaged in
`dnd_board`; combatants take explicit `start = [x, y]` cells or are auto-placed
from the board's spawn zones.
