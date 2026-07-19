# otyugh_shadow_pair

An encounter experiment: the CR7 Shadow Otyugh plus a normal CR5 Otyugh vs the
Beaumont playtest party, on the `arena` board with the geometric photophage
darkness (see [`otyugh_shadow_board`](../otyugh_shadow_board) for the model).

A lone Shadow Otyugh (2,900 XP) is a trivial fight for five level-5 PCs. The
question here: does a second, ordinary Otyugh make it a real attrition threat —
and does the darkness help the pair? Both otyughs have **darkvision**, so the
normal one can lurk *inside* the Shadow's darkness: it sees out and attacks while
the party (no darkvision) can't see in to target it with spells or arrows. Only
the fighter's torch reveals either monster.

```sh
uv sync
uv run python src/simulation.py
```
