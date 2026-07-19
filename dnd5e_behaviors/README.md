# dnd5e-behaviors

Python escape-hatch `Behavior` classes (design doc 04 section 5) for creatures whose
behavior the declarative `when`/`target_filter` language genuinely can't express.
Referenced from a creature TOML's `[behavior.custom] handler = "python:dnd5e_behaviors.<module>.<Class>"`.

Kept as its own package, separate from both `dnd5e` (the generic engine — "no
creature-specific branches anywhere in this package") and `dnd5e_data` (data only, no
code). Classes here interact with `Creature`/`Battlefield` via duck typing, matching
`dnd5e.escape_hatch.Behavior`'s protocol — no import of `dnd5e` itself, to avoid a
circular workspace dependency (`dnd5e` depends on this package so its own environment
has hatch classes importable).
