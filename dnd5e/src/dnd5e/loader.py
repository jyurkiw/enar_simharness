"""Creature TOML -> validated `Statblock` (design doc 03 section 1, design doc
01 section 1). Simulation-file loading (source resolution, overrides,
placement) is added here in Phase 4+ once creature loading is solid.

Phase 3 explicitly does NOT implement: expressions (`when`/`target_filter`),
`[[behavior.targeting]]`, the `behavior.custom` escape hatch, `[reactions.*]`,
or `[conditions.*]` (custom conditions) — all real design-doc-01 schema
features, deferred to Phase 4/5 per design doc 06's build order. A creature
file using any of them fails to load with a `NotYetSupportedError` naming the
phase that adds it, not a silent no-op or a generic parse error. Every other
validation (closed vocab, referential integrity, name/stem match) is fully
enforced now.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import dnd5e_data
from dnd_board import load_board_toml
from simharness.config import closed_vocab, deep_merge, require_keys

from .conditions import ATTACHABLE_CONDITIONS
from .effects import validate_effect_name
from .statblock import (
    ABILITY_KINDS,
    PHASE3_TACTICS,
    Ability,
    Behavior,
    EffectCall,
    MultiattackOption,
    Resource,
    Statblock,
    Stats,
    Trait,
)
from .system import RosterSlot

ABILITY_SCORE_KEYS = ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma")


class NotYetSupportedError(ValueError):
    """A schema feature that's valid per design doc 01 but not implemented
    until a later phase. Distinct from ValueError-for-a-real-mistake so
    callers/tests can tell "not built yet" apart from "actually wrong"."""


def load_toml_file(path: str | Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def _build_effect_calls(raw_list: Optional[list], *, where: str) -> tuple[EffectCall, ...]:
    calls = []
    for i, d in enumerate(raw_list or []):
        call = EffectCall.from_dict(d)
        item_where = f"{where}[{i}]"
        validate_effect_name(call.effect, where=item_where)
        _validate_effect_args(call, where=item_where)
        calls.append(call)
    return tuple(calls)


def _validate_effect_args(call: EffectCall, *, where: str) -> None:
    if call.effect == "attach_condition":
        condition = call.args.get("condition")
        if condition not in ATTACHABLE_CONDITIONS:
            raise ValueError(
                f"{where}: attach_condition condition {condition!r} is not a RAW condition "
                f"(custom conditions are Phase 5); known: {sorted(ATTACHABLE_CONDITIONS)}"
            )
        if "when" in call.args:
            raise NotYetSupportedError(f"{where}: attach_condition 'when' requires expressions (Phase 4)")
    elif call.effect == "require_save":
        require_keys(call.args, ["ability", "dc"], where=where)
        for key in ("on_fail", "on_success"):
            for j, sub in enumerate(call.args.get(key, [])):
                sub_call = EffectCall.from_dict(sub)
                sub_where = f"{where}.{key}[{j}]"
                validate_effect_name(sub_call.effect, where=sub_where)
                _validate_effect_args(sub_call, where=sub_where)


def _build_ability(name: str, spec: dict, *, where: str) -> Ability:
    kind = spec.get("kind")
    closed_vocab(kind, ABILITY_KINDS, where=f"{where}.kind")
    if "target_filter" in spec:
        raise NotYetSupportedError(f"{where}: target_filter requires expressions (Phase 4)")
    return Ability(
        name=name, kind=kind,
        to_hit=spec.get("to_hit"), damage=spec.get("damage"), damage_type=spec.get("damage_type"),
        crit_range=spec.get("crit_range", 20), reach=spec.get("reach"),
        range_normal=spec.get("range_normal"), range_long=spec.get("range_long"),
        ability=spec.get("ability"), dc=spec.get("dc"), half_on_save=spec.get("half_on_save", False),
        targets=spec.get("targets"), target_filter=None, max_targets=spec.get("max_targets"),
        amount=spec.get("amount"), range=spec.get("range"),
        costs=spec.get("costs"), uses_bonus_action=spec.get("uses_bonus_action", False),
        description=spec.get("description"),
        on_hit=_build_effect_calls(spec.get("on_hit"), where=f"{where}.on_hit"),
        on_fail=_build_effect_calls(spec.get("on_fail"), where=f"{where}.on_fail"),
        on_crit=_build_effect_calls(spec.get("on_crit"), where=f"{where}.on_crit"),
        on_success=_build_effect_calls(spec.get("on_success"), where=f"{where}.on_success"),
        on_all_saved=_build_effect_calls(spec.get("on_all_saved"), where=f"{where}.on_all_saved"),
        effects=_build_effect_calls(spec.get("effects"), where=f"{where}.effects"),
    )


def _build_multiattack(name: str, spec: dict, *, where: str) -> MultiattackOption:
    if "when" in spec:
        raise NotYetSupportedError(f"{where}: multiattack 'when' requires expressions (Phase 4)")
    actions = tuple(spec.get("actions", ()))
    if not actions:
        raise ValueError(f"{where}: multiattack option has no actions")
    return MultiattackOption(name=name, actions=actions, when=None, priority=spec.get("priority", 0))


def _build_trait(name: str, spec: dict, *, where: str) -> Trait:
    return Trait(name=name, description=spec.get("description"),
                effects=_build_effect_calls(spec.get("effects"), where=f"{where}.effects"))


def _build_resource(name: str, spec: dict, *, where: str) -> Resource:
    require_keys(spec, ["uses"], where=where)
    return Resource(name=name, uses=spec["uses"], recharge=spec.get("recharge"), per=spec.get("per"))


def _build_behavior(spec: dict, *, where: str) -> Behavior:
    tactic = spec.get("tactic", "engage")
    closed_vocab(tactic, PHASE3_TACTICS, where=f"{where}.tactic")
    if "targeting" in spec:
        raise NotYetSupportedError(f"{where}: [[behavior.targeting]] requires expressions (Phase 4)")
    if "custom" in spec:
        raise NotYetSupportedError(f"{where}: behavior.custom (the escape hatch) is Phase 4")
    return Behavior(tactic=tactic, action_priority=tuple(spec.get("action_priority", ())))


def _default_proficiency(cfg: dict) -> int:
    classification = cfg.get("classification", {})
    challenge = classification.get("cr", classification.get("level", 1))
    if challenge < 5:
        return 2
    if challenge < 9:
        return 3
    if challenge < 13:
        return 4
    if challenge < 17:
        return 5
    return 6


def _build_stats(cfg: dict, *, where: str) -> Stats:
    stats = cfg.get("stats", {})
    require_keys(stats, ABILITY_SCORE_KEYS, where=f"{where} [stats]")
    require_keys(stats, ["ac", "speed"], where=f"{where} [stats]")
    health = stats.get("health", {})
    senses = stats.get("senses", {})
    dex_mod = (stats["dexterity"] - 10) // 2
    return Stats(
        strength=stats["strength"], dexterity=stats["dexterity"], constitution=stats["constitution"],
        intelligence=stats["intelligence"], wisdom=stats["wisdom"], charisma=stats["charisma"],
        ac=stats["ac"], speed=stats["speed"],
        initiative_bonus=stats.get("initiative_bonus", dex_mod),
        proficiency=stats.get("proficiency", _default_proficiency(cfg)),
        crit_range=stats.get("crit_range", 20), reach=stats.get("reach", 5),
        hit_dice=health.get("hit_dice"), hp_average=health.get("average", 1),
        saves=dict(stats.get("saves", {})), skills=dict(stats.get("skills", {})),
        darkvision=senses.get("darkvision", 0), passive_perception=senses.get("passive_perception", 10),
    )


def build_statblock(cfg: dict, *, source: str) -> Statblock:
    name = cfg.get("name")
    if not name:
        raise ValueError(f"{source}: missing required top-level 'name'")
    stem = Path(source).stem
    if name != stem:
        raise ValueError(f"{source}: name {name!r} does not match file stem {stem!r}")

    stats = _build_stats(cfg, where=source)

    abilities = {n: _build_ability(n, spec, where=f"{source} [abilities.{n}]")
                for n, spec in cfg.get("abilities", {}).items()}
    multiattack = {n: _build_multiattack(n, spec, where=f"{source} [multiattack.{n}]")
                   for n, spec in cfg.get("multiattack", {}).items()}
    traits = {n: _build_trait(n, spec, where=f"{source} [traits.{n}]")
             for n, spec in cfg.get("traits", {}).items()}
    if cfg.get("reactions"):
        raise NotYetSupportedError(f"{source}: [reactions.*] requires the trigger bus (Phase 5)")
    resources = {n: _build_resource(n, spec, where=f"{source} [resources.{n}]")
                for n, spec in cfg.get("resources", {}).items()}
    if "conditions" in cfg:
        raise NotYetSupportedError(f"{source}: [conditions.*] (custom conditions) is Phase 5")
    behavior = _build_behavior(cfg.get("behavior", {}), where=f"{source} [behavior]")

    # Referential validation (design doc 03 section 1).
    for opt in multiattack.values():
        missing = [a for a in opt.actions if a not in abilities]
        if missing:
            raise ValueError(f"{source} [multiattack.{opt.name}]: references unknown action(s) {missing}")
    for action_name in behavior.action_priority:
        if action_name not in abilities:
            raise ValueError(f"{source} [behavior].action_priority: unknown action {action_name!r}")
    for ability in abilities.values():
        if ability.costs:
            resource_name = ability.costs.get("resource")
            if resource_name and resource_name not in resources:
                raise ValueError(
                    f"{source} [abilities.{ability.name}].costs: unknown resource {resource_name!r}")
    # Phase 3 has no `when` gating, so every multiattack option is always
    # eligible — a priority tie among ALL options (not just a runtime-eligible
    # subset, which doesn't exist yet) is unresolvable and must be caught now.
    priorities = [opt.priority for opt in multiattack.values()]
    if len(set(priorities)) != len(priorities):
        raise ValueError(
            f"{source} [multiattack]: duplicate priority value(s) among "
            f"{sorted(multiattack.keys())} — with no `when` gating every option is always "
            f"eligible, so ties must be broken explicitly"
        )

    return Statblock(
        name=name,
        display_name=cfg.get("display_name", name.replace("_", " ").title()),
        classification=dict(cfg.get("classification", {})),
        stats=stats,
        abilities=abilities,
        multiattack=multiattack,
        traits=traits,
        reactions={},
        resources=resources,
        behavior=behavior,
    )


def load_creature(path: str | Path, *, overrides: Optional[dict] = None) -> Statblock:
    cfg = load_toml_file(path)
    if overrides:
        cfg = deep_merge(cfg, overrides)
    return build_statblock(cfg, source=str(path))


# =============================================================================
# Simulation-file loading (design doc 01 section 3).
#
# Creature resolution order for a `creature = "<name>"` reference (first hit
# wins, so a sim-local file shadows the shared library):
#   1. each directory in `sources`, relative to the simulation file
#   2. the simulation directory's own `creatures/`
#   3. `dnd5e_data` — `characters/` then `monsters/`
#
# Phase 3 scope: `[environment.obscurement]`/`[environment.light_plan]`
# (Phase 4, needs vision traits + auras) and `[sweep]` (not wired into the
# CLI yet, task 37) are not implemented — the former raises
# NotYetSupportedError; the latter is simply ignored by `run`.
# =============================================================================


@dataclass(frozen=True)
class SimulationSpec:
    name: str
    board: object  # dnd_board.Board
    roster: list   # list[RosterSlot]
    trials: int
    max_rounds: int
    seed: int
    hp_mode: str
    focus: dict = field(default_factory=dict)
    output: dict = field(default_factory=dict)


def _resolve_creature_path(name: str, *, sim_dir: Path, sources: list) -> Path:
    candidates = [sim_dir / src / f"{name}.toml" for src in sources]
    candidates.append(sim_dir / "creatures" / f"{name}.toml")
    candidates.append(dnd5e_data.data_path("characters", f"{name}.toml"))
    candidates.append(dnd5e_data.data_path("monsters", f"{name}.toml"))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise ValueError(f"creature {name!r} not found; looked in: {[str(c) for c in candidates]}")


def _resolve_board_path(board_ref: str, *, sim_dir: Path) -> Path:
    if board_ref.startswith("lib:"):
        return dnd5e_data.data_path("boards", f"{board_ref[4:]}.toml")
    return sim_dir / board_ref


def load_simulation(path: str | Path) -> SimulationSpec:
    path = Path(path)
    sim_dir = path.parent
    cfg = load_toml_file(path)

    sim = cfg.get("simulation", {})
    require_keys(sim, ["trials", "max_rounds", "seed"], where=f"{path} [simulation]")
    hp_mode = sim.get("hp_mode", "average")
    closed_vocab(hp_mode, ("average", "rolled"), where=f"{path} [simulation].hp_mode")

    if "board" not in cfg:
        raise ValueError(f"{path}: missing required 'board'")
    board = load_board_toml(_resolve_board_path(cfg["board"], sim_dir=sim_dir))

    sources = list(cfg.get("sources", []))
    overrides_by_name = cfg.get("overrides", {})

    combatants_cfg = cfg.get("combatants", [])
    if not combatants_cfg:
        raise ValueError(f"{path}: no [[combatants]] entries")

    roster: list[RosterSlot] = []
    spawn_cursor: dict = {}
    for entry in combatants_cfg:
        require_keys(entry, ["creature", "side"], where=f"{path} [[combatants]]")
        creature_name = entry["creature"]
        side = entry["side"]
        count = entry.get("count", 1)
        tags = tuple(entry.get("tags", ()))
        spawn_label = entry.get("spawn")
        explicit_start = entry.get("start")
        if spawn_label is None and explicit_start is None:
            raise ValueError(
                f"{path} [[combatants]] {creature_name!r}: needs a 'spawn' label or explicit 'start'")

        creature_path = _resolve_creature_path(creature_name, sim_dir=sim_dir, sources=sources)

        for i in range(count):
            instance_name = creature_name if count == 1 else f"{creature_name}_{i + 1}"
            # Per-instance override wins wholesale over a base-name override
            # (not merged) — design doc 01 section 3.1.
            entry_overrides = overrides_by_name.get(instance_name, overrides_by_name.get(creature_name))
            statblock = load_creature(creature_path, overrides=entry_overrides)

            if explicit_start is not None:
                start = tuple(explicit_start)
            else:
                cells = board.spawns.get(spawn_label)
                if not cells:
                    raise ValueError(
                        f"{path}: spawn label {spawn_label!r} not found on board {board.meta.get('name')!r}")
                idx = spawn_cursor.get(spawn_label, 0)
                start = cells[idx % len(cells)]
                spawn_cursor[spawn_label] = idx + 1

            roster.append(RosterSlot(statblock=statblock, instance_name=instance_name, side=side,
                                     start=start, tags=tags))

    environment = cfg.get("environment", {})
    if "obscurement" in environment or "light_plan" in environment:
        raise NotYetSupportedError(
            f"{path}: [environment.obscurement]/[environment.light_plan] require vision traits (Phase 4)")
    focus = {}
    if "focus" in environment:
        # Matches the old engine's scenario.py: a bare `focus` name is always
        # the *party's* focus-fire target (monsters don't get scripted focus
        # in these sims).
        focus["party"] = environment["focus"]

    return SimulationSpec(
        name=cfg.get("name", path.stem), board=board, roster=roster,
        trials=sim["trials"], max_rounds=sim["max_rounds"], seed=sim["seed"],
        hp_mode=hp_mode, focus=focus, output=cfg.get("output", {}),
    )
