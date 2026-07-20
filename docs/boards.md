# Board TOML

A board is an ASCII map plus a glyph palette. No compile step — the `.toml` is the source
of truth, loaded directly.

Boards live in `dnd5e_data/src/dnd5e_data/boards/` (referenced as `board = "lib:<name>"`)
or beside a simulation (referenced by relative path).

```toml
name = "plain_room"

map = """
##############
#............#
#PP.....MM...#
#PP.....MM...#
#PP.....MM...#
#............#
##############
"""

[meta]
cell_feet = 5
diagonal = "chebyshev"        # diagonal movement costs the same as orthogonal

[glyph.'#']
terrain = "impassable"
cover = "full"
blocks_los = true
blocks_light = true

[glyph.'P']
terrain = "open"
spawn = "party"

[glyph.'M']
terrain = "open"
spawn = "monsters"
```

> ⚠️ **`name` and `map` must come before the first `[table]` header** or they get silently
> nested into it. This has bitten the project more than once.

## Glyph properties

| Property | Values | Meaning |
|---|---|---|
| `terrain` | `open`, `difficult`, `impassable` | `difficult` costs double movement |
| `cover` | `half`, `three_quarters`, `full` | +2 / +5 AC; `full` blocks the attack entirely |
| `blocks_los` | bool | Blocks line of sight (so also targeting/ranged attacks) |
| `blocks_light` | bool | Blocks light propagation |
| `spawn` | any label | Marks a spawn cell for `[[combatants]].spawn` |

`.` is open floor by default and needs no entry.

## Spawns

Cells sharing a `spawn` label form a block, handed out round-robin as combatants are
created. Give a block at least as many cells as the largest group that uses it.

To pin an exact position instead, use `start = [x, y]` on the combatant. Coordinates are
`(x, y)` with the origin top-left, `x` increasing right and `y` increasing down.

## Board size matters more than you'd think

Distances are real, and tactics exploit them:

- **`plain_room`** is small on purpose (spawn blocks 30 ft apart) so melee closes in round
  one — it stands in for "abstract" fights with no meaningful geometry.
- **`arena`** is 30×30 with a dividing wall, pillars (three-quarters cover), low walls
  (half cover) and difficult terrain — real positioning.

On a large board a `kite` creature will hold maximum weapon range, which can put it
effectively out of the fight for melee monsters. That's legitimate — but it means **board
size is a balance lever**, not just set dressing. If a ranged attacker looks impossibly
strong, check whether anything on the map can actually reach it.

## Vision, cover and light

- **Line of sight** is blocked by `blocks_los` glyphs; `can_see()` also accounts for
  obscurement regions from `[[environment.obscurement]]`.
- **Cover** adds AC from the best intervening glyph; `full` cover is an automatic miss.
- **An unseen target imposes disadvantage**, not an automatic miss — you can shoot into the
  dark, badly. Abilities that require sight simply won't select an unseen target (that's
  the `targets` default; see [creatures.md](creatures.md#targeting)).
- **Light and darkness** are geometric. A creature in heavy obscurement is blinded;
  `darkvision_immunity` or `limited_darkvision` traits change what it can see out of.

## Checking a board

```bash
uv run --project dnd5e dnd5e-sim validate path/to/board.toml
```

`validate` auto-detects file type (a top-level `map` key means board), so it catches a
malformed palette or a spawn label no combatant references before you run 10,000 trials.
