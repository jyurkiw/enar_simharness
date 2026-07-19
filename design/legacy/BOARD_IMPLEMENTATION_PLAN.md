# Board, Movement & Line-of-Sight for the D&D Sims

## Context

The Monte Carlo sims under `E:\Repos\simulations` currently model position **abstractly**.
`Battlefield` (`dnd5e_combat/src/dnd5e_combat/battlefield.py`) tracks only *sides*, a
*grapple graph*, and a per-side *focus* target. The only spatial signal that reaches
behavior code is `Combatant.position = "front" | "back"` plus `attack_style =
"melee" | "ranged"`. There is no grid, no distance, no line of sight; light/darkness is a
crude one-source/one-round switch (`CombatContext.light_config`) that just toggles the
`BLINDED` condition for everyone.

We want real tactical geometry: a fixed-size battle grid, A* movement over weighted
terrain, line of sight for ranged attacks, cover, and distance-based light/obscurement
(fog cloud, darkness). Crucially, `Battlefield`'s own docstring already anticipates this:
*"a real grid can replace the internals later without changing any behavior code."* That
makes a clean, backward-compatible layering possible.

### Decisions locked
- **Standard board: 30×30 cells @ 5 ft = 150 ft square.**
- **Library: `tcod` (python-tcod)** — one dependency covers A* pathfinding, Bresenham
  line-of-sight, and field-of-view for light/darkness/fog.
- **Authoring format: ASCII text map + TOML palette**, compiled to a fast-loading `.npz`.
- Diagonals: **Chebyshev (5 ft per diagonal, D&D 2024 default)**; 5-10-5 offered as a flag.
- Terrain weights: **open / difficult / impassable**. Cover tracked as a **second layer**
  (none / half / three-quarters / full).

---

## Architecture: a new sibling project `dnd_board`

Create `E:\Repos\simulations\dnd_board`, a **combat-agnostic** geometry package, sibling to
`dnd5e_combat` and `sim_template`. It knows nothing about combatants or D&D rules — just
grids, terrain, paths, visibility, and file IO — so `snss` and future sims can reuse it.
`dnd5e_combat` imports it and grows a thin, **optional** integration layer; individual sims
keep importing only `dnd5e_combat`.

```
dnd_board/
  pyproject.toml            # uv + hatchling; deps: tcod, numpy, rich (viewer), matplotlib
  README.md
  src/dnd_board/
    __init__.py             # public API surface
    terrain.py              # Terrain & Cover enums + numeric costs / AC bonuses
    grid.py                 # Board: aligned numpy layers + cell queries + distance
    pathing.py              # A* (tcod.path) with dynamic occupancy cost grid
    vision.py               # LOS (tcod.los.bresenham), cover_between, FOV (tcod.map)
    obscurement.py          # ObscurementField: dynamic fog/darkness/light overlays
    palette.py              # glyph <-> cell mapping loaded from TOML
    fileio.py               # ASCII+palette -> Board; Board <-> .npz round-trip
    boardtool.py            # CLI: package / view / validate
    data/
      palettes/default.toml
      boards/<name>.txt     # human-authored source maps
      compiled/<name>.npz   # packaged output the sims load
  tests/                    # pytest: distance, A*, LOS, cover, FOV, file round-trip
```

Mirror the existing packaging conventions from `dnd5e_combat/pyproject.toml`: `src/` layout,
`requires-python = ">=3.13"`, hatchling wheel target, git-sourced shared deps if any.

---

## Board model (`grid.py`, `terrain.py`)

`Board` holds aligned `numpy` arrays, all shape `(H, W)` (standard 30×30):
- `terrain`: `0=open (cost 1)`, `1=difficult (cost 2)`, `2=impassable (blocks move)`.
- `cover`: `0=none`, `1=half (+2 AC)`, `2=three-quarters (+5 AC)`, `3=full (untargetable)`.
- `blocks_los`: bool — obstacle stops sight/ranged effects (a high wall).
- `blocks_light`: bool — obstacle stops light propagation (usually == blocks_los).

`Terrain`/`Cover` are `IntEnum`s in `terrain.py` with lookup tables for movement cost and
AC bonus, so the mapping lives in exactly one place.

Cells are 5 ft. `Board.distance_ft(a, b)` uses **Chebyshev × 5** by default; a
`diagonal="5-10-5"` construction flag switches to alternating cost. `Board.meta` carries
`cell_feet` and `name` (read from the palette `[meta]`).

Cover is deliberately **a property of the obstacle cell**, not of the creature: a low wall
or pillar occupies a cell that is `impassable` terrain **and** grants `three_quarters`
cover to a creature on the far side. Cover *experienced* by a target is computed
per-attack from the line the shot travels (see `vision.py`), never stored on the target.

---

## Authoring format: ASCII + TOML palette (`palette.py`, `fileio.py`)

`data/boards/<name>.txt` — one glyph per cell, 30 rows × 30 columns:
```
..............................
..######............~~~~......
..#....#.....o................
..#....#.....o.......@........
..######......................
...
```

`data/palettes/default.toml` — maps each glyph to a fully-specified cell:
```toml
[meta]
name = "default"
cell_feet = 5

[glyph.'.']              # open floor
terrain = "open"
cover   = "none"

[glyph.'~']              # rubble / difficult terrain
terrain = "difficult"
cover   = "none"

[glyph.'#']              # full wall: blocks move, sight, and light; full cover
terrain = "impassable"
cover   = "full"
blocks_los   = true
blocks_light = true

[glyph.'o']              # pillar / crate: blocks move + 3/4 cover, light passes over
terrain = "impassable"
cover   = "three_quarters"
blocks_los   = false
blocks_light = false

[glyph.'@']              # spawn marker (terrain=open); collected as a named spawn cell
terrain = "open"
spawn   = "party"
```
Unspecified keys default to `terrain=open, cover=none, blocks_los=false, blocks_light=false`.
`@`/spawn glyphs let a board declare where sides start (returned as `Board.spawns:
dict[str, list[(x,y)]]`), so scenarios can place combatants without hard-coding coords.

`fileio.parse_ascii(path, palette)` validates dimensions (must equal the standard size),
rejects unknown glyphs with a clear error, and emits a `Board`. `fileio.save_npz` /
`load_npz` give a fast binary round-trip so sims never re-parse text at runtime.

---

## Packaging & viewing CLI (`boardtool.py`)

A single script, runnable via `uv run python -m dnd_board.boardtool ...`:
- `package <board.txt> [--palette default] [-o compiled/<name>.npz]` — parse + validate +
  write `.npz`. Fails loudly on wrong dimensions or unknown glyphs.
- `view <board.txt | .npz>` — render to the terminal with `rich` (colored cells per
  terrain/cover); `--png <file>` also dumps a `matplotlib` image (same dep already used by
  `dnd5e_combat/report.py`).
- `validate <board.txt>` — dimension + glyph checks **plus** connectivity (flood-fill from
  each spawn zone so no side starts walled off from the enemy).

This satisfies the "package or view boards" requirement and keeps board data as
diff-friendly text checked into `data/boards/`, compiled artifacts alongside.

---

## Pathfinding & movement (`pathing.py`)

- Static cost grid comes from `terrain` (open=1, difficult=2, impassable=0 → wall in tcod).
- `path(board, start, goal, *, blocked=set())` builds a `tcod.path.AStar` (or
  `SimpleGraph`/`Dijkstra`) over `cost` with `blocked` cells (occupied by other creatures)
  stamped impassable, and returns the cell list.
- `reachable(board, start, budget_ft, blocked)` — cells within a movement budget (BFS over
  cost), used to decide how far a creature actually gets this turn.
- Occupancy is dynamic: the integration layer stamps every *other* living combatant's cell
  as blocked before pathing, and a creature stops at the last cell it can afford.

---

## Vision, cover & FOV (`vision.py`)

- `line_of_sight(board, a, b, obscurement=None)` — walk `tcod.los.bresenham(a, b)`; blocked
  if any intermediate cell has `blocks_los`, `cover == full`, or lies inside a
  heavily-obscured region. Endpoints excluded.
- `cover_between(board, a, b)` — trace the line; return the **max** cover value among
  obstacle cells adjacent to it (D&D corner rule, simplified to line-crossing). Feeds the
  attacker's to-hit as a target-AC bonus, or "untargetable" on full cover.
- `field_of_view(board, source, radius_ft, obscurement=None)` — `tcod.map.compute_fov`
  from a light source, honoring `blocks_light`; returns the illuminated cell mask. Powers
  "which cells a torch/Light spell lights up" and "who can see whom".

---

## Dynamic light & obscurement (`obscurement.py`)

`ObscurementField` holds a list of circular regions `{center, radius_ft, kind}` where kind ∈
`{fog, darkness, magical_darkness, light}`:
- A cell is **heavily obscured** if inside a `fog`/`darkness` region and not carved out by a
  `light` region (magical darkness ignores non-magical light).
- Queried by `vision` (blocks LOS beyond entry) and by the combat layer (a creature in a
  heavily-obscured cell is effectively **blinded** — attacks against it get advantage, its
  attacks get disadvantage, reusing the *existing* `conditions.BLINDED` logic in
  `engine.py:116-119`).
- Regions are added/removed by policies over the fight (Fog Cloud cast, Darkness dropped,
  Light lit), which **replaces** the crude `CombatContext.light_config` mechanism with a
  real geometric model that still resolves to the same condition effects.

---

## Integration into `dnd5e_combat` (optional, backward-compatible)

The board must be **opt-in** so the existing abstract sims keep running untouched. Every new
method falls back to the current behavior when `board is None`.

1. **Dependency** — add `dnd-board` to `dnd5e_combat/pyproject.toml` (via
   `[tool.uv.sources] dnd-board = { path = "../dnd_board", editable = true }`, mirroring how
   `looper`/`py-die-roller` are wired). Sims still import only `dnd5e_combat`.

2. **`combatant.py`** — add optional fields `x: int|None = None`, `y: int|None = None`,
   `speed_ft: int = 30`, `reach_ft: int = 5`. Keep `position`/`attack_style` for the
   abstract path. Register the new keys in the loader `_KNOWN` set
   (`loader.py:15-18`) and pass them through `_combatant_from_entry` (`loader.py:71-89`).

3. **`battlefield.py`** — `Battlefield(__init__)` gains `board: Board|None = None` and an
   `obscurement: ObscurementField`. Add methods (all no-op / abstract-fallback when no
   board):
   - `distance_ft(a, b)`, `in_reach(actor, target)` (uses `reach_ft`),
   - `line_of_sight(a, b)`, `cover_between(a, b)`,
   - `move_toward(actor, target, *, into_reach=True)` — path with live-combatant occupancy,
     spend up to `speed_ft`, update `(x, y)`; records melee engagers so the existing
     opportunity-attack path (`engine.py:107-110`) still fires,
   - `visible_enemies(actor)`, `is_obscured(cell)`.
   The existing `enemies_of`/`allies_of`/`primary_enemy`/grapple API is unchanged.

4. **`engine.py` `CombatContext.attack`** — optional cover: when a board is present, add
   `field.cover_between(attacker, target)`'s AC bonus and treat full cover as an automatic
   miss / disallowed target. Gate ranged attacks on `field.line_of_sight`. Kept behind the
   board check so current policies are byte-for-byte unaffected. Retire `light_config` /
   `_produce_light` in favor of `obscurement` overlays (leave a shim for one release).

5. **Policies** — the one real leak, `Otyugh` filtering `e.position == "front"`
   (`monsters/otyugh/__init__.py:42`), becomes `field.in_reach(actor, e)` when a board
   exists, `position`-based otherwise. Provide a `Battlefield.in_reach` shim that reproduces
   the front/back semantics with no board so nothing else changes. Movement-aware policies
   (e.g. a ranger kiting, the Shadow Otyugh hunting the light source) call
   `field.move_toward` at the top of their turn.

6. **`scenario.py`** — `[encounter] board = "<name>"` loads
   `dnd_board.data.compiled/<name>.npz`; combatants take `start = [x, y]` overrides or are
   auto-placed from the board's `spawns` zones. Assemble `ObscurementField` from any
   `[[encounter.obscurement]]` entries. When no `board` key is present, behavior is exactly
   as today.

---

## Critical files

**New (`dnd_board`):** `grid.py`, `terrain.py`, `pathing.py`, `vision.py`,
`obscurement.py`, `palette.py`, `fileio.py`, `boardtool.py`, `data/palettes/default.toml`,
one sample `data/boards/*.txt`, `pyproject.toml`, `tests/`.

**Modified (`dnd5e_combat`):**
- `pyproject.toml` — add `dnd-board` source.
- `src/dnd5e_combat/combatant.py` — coords + speed/reach fields.
- `src/dnd5e_combat/loader.py` — `_KNOWN` + `_combatant_from_entry` pass-through.
- `src/dnd5e_combat/battlefield.py` — board handle + geometry methods.
- `src/dnd5e_combat/engine.py` — optional cover/LOS in `attack`; replace `light_config`.
- `src/dnd5e_combat/scenario.py` — load board + placement + obscurement.
- `src/dnd5e_combat/monsters/otyugh/__init__.py` (+ `shadow_otyugh`) — `in_reach`/move calls.

Reuse rather than rebuild: `deep_merge`/`load_*` in `loader.py`, the `Resolver` in
`dice.py`, the `BLINDED` advantage/disadvantage machinery in `engine.py:116-119`, and
`matplotlib` (already a dep) for the PNG board viewer.

---

## Verification

1. **`dnd_board` unit tests** (`uv run pytest` in `dnd_board`):
   - distance: Chebyshev 5 ft and 5-10-5 diagonal cases;
   - A* routes around `impassable`, and prefers `open` over `difficult` when cheaper;
   - `reachable` respects a movement budget over mixed terrain;
   - LOS blocked by a `#` wall, open across floor, cover value correct for a `o` pillar;
   - FOV radius + `blocks_light`; fog region marks cells heavily obscured;
   - file round-trip: `parse_ascii → save_npz → load_npz` equals the original board.
2. **CLI smoke test:** `boardtool.py package` the sample map, then `view` it (terminal +
   `--png`) and eyeball terrain/cover colors.
3. **Regression:** run an existing sim unchanged —
   `cd dnd\otyugh\otyugh_cr5_dps && uv run python src\simulation.py` — and confirm identical
   output when no `board` key is present (board path is fully opt-in).
4. **End-to-end board sim:** add `board = "<sample>"` + spawns to a copy of the otyugh
   scenario, run it, and confirm movement/LOS/cover produce sane, finite fights (no infinite
   pathing, ranged attackers respect LOS, cover shifts hit rates in the expected direction).

## Rollout order
1. Stand up `dnd_board` (grid/terrain/fileio/palette + tests) and the `boardtool` CLI.
2. Add pathing, vision, obscurement (+ tests).
3. Wire the optional board layer into `dnd5e_combat` (coords, Battlefield methods, loader).
4. Add cover/LOS to `attack` and migrate light → obscurement.
5. Update the Otyugh policies to geometry; ship one board-based demo scenario.
