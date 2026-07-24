"""Creature TOML -> validated `Statblock` (design doc 03 section 1, design doc
01 section 1). Simulation-file loading (source resolution, overrides,
placement) is added here in Phase 4+ once creature loading is solid.

Phase 4: `target_filter`, multiattack `when`, and `[[behavior.targeting]]` are
parsed and validated via `expressions.py` (`parse_and_validate` — syntax AND
identifier checks happen at load time, so a typo in a `when` clause fails
loudly here, never mid-trial). `behavior.custom` (the escape hatch) is
accepted structurally (design doc 04 section 5) — this module only stores the
`"python:module.Class"` string; resolving and instantiating it is
`escape_hatch.resolve`'s job.

Phase 5 adds `[conditions.*]` (custom conditions, design doc 03 section 3) and
`[reactions.*]` (design doc 04 section 4), plus a `when` gate on an individual
effect call (parsed the same way as any other `when`, evaluated by
`effects.apply_effect` at dispatch time against the acting creature/target/
event — doc01's masked_bruiser example uses this throughout). `[conditions.*]`
must be parsed before abilities/reactions so `attach_condition` can validate
against RAW conditions *plus* this file's own custom-condition names.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import dnd5e_data
from dnd_board import load_board_toml
from simharness.config import closed_vocab, deep_merge, require_keys

from . import conditions as conditions_module
from . import expressions
from .effects import validate_effect_name
from .statblock import (
    ABILITY_KINDS,
    KNOWN_TACTICS,
    TARGETING_ORDERS,
    Ability,
    Behavior,
    ConditionDef,
    EffectCall,
    MultiattackOption,
    Reaction,
    Resource,
    Statblock,
    Stats,
    TargetingRule,
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


# Effect-call arguments that name a *creature* (see effects._resolve_ref).
_EFFECT_TARGET_KEYS = ("target", "to", "with", "actor")
_EFFECT_TARGET_REFS = ("self", "target")  # or "event.<field>" / "expr:<expression>"


def _compile_target_ref(value, *, where: str):
    """Compile an effect-call creature reference. Four forms:
    `"self"` / `"target"` / `"event.<field>"` (fixed lookups resolved directly
    by `effects._resolve_ref`), and `"expr:<expression>"` — an escape into the
    normal expression language for references the fixed forms can't name (e.g.
    the Masked Bruiser's Sleight of Crowd swapping with a *Poet ally*, which is
    neither self, the target, nor an event field). The expr form is parsed and
    validated here, at load time, like every other expression in this loader,
    and stored as a compiled `Node`; a non-str value is already compiled."""
    if not isinstance(value, str):
        return value
    if value.startswith("expr:"):
        return expressions.parse_and_validate(value[len("expr:"):], where=f"{where} (expr:)")
    if value in _EFFECT_TARGET_REFS or value.startswith("event."):
        return value
    raise ValueError(f"{where}: {value!r} is not a valid target reference (expected 'self', "
                     f"'target', 'event.<field>', or 'expr:<expression>')")


def _validate_target_ref(ref, *, where: str) -> None:
    """Presence/shape check for refs already run through `_compile_target_ref`
    (a compiled Node passes trivially)."""
    _compile_target_ref(ref, where=where)


def _build_effect_calls(raw_list: Optional[list], *, where: str,
                        known_conditions: frozenset = frozenset()) -> tuple[EffectCall, ...]:
    calls = []
    for i, d in enumerate(raw_list or []):
        item_where = f"{where}[{i}]"
        raw = dict(d)
        effect_name = raw.get("effect")
        validate_effect_name(effect_name, where=item_where)
        # `when` (design doc 03 section 4's `attach_condition` arg, but legal
        # on any effect call per doc01's masked_bruiser example): compiled at
        # load time like every other `when`, evaluated by
        # `effects.apply_effect` against the acting creature/target/event.
        if "when" in raw:
            raw["when"] = expressions.parse_and_validate(raw["when"], where=f"{item_where}.when")
        # Creature-reference args (`target`/`to`/`with`) are compiled here, so an
        # `expr:` form is parsed+validated once at load time rather than per hit.
        for key in _EFFECT_TARGET_KEYS:
            if key in raw:
                raw[key] = _compile_target_ref(raw[key], where=f"{item_where}.{key}")
        call = EffectCall.from_dict(raw)
        _validate_effect_args(call, where=item_where, known_conditions=known_conditions)
        calls.append(call)
    return tuple(calls)


def _validate_effect_args(call: EffectCall, *, where: str, known_conditions: frozenset) -> None:
    if call.effect == "attach_condition":
        condition = call.args.get("condition")
        allowed = conditions_module.ATTACHABLE_CONDITIONS | known_conditions
        if condition not in allowed:
            raise ValueError(
                f"{where}: attach_condition condition {condition!r} is not a RAW condition "
                f"or one this file defines under [conditions.*]; known: {sorted(allowed)}"
            )
        if "expires" in call.args and not conditions_module.is_known_clock(call.args["expires"]):
            raise ValueError(
                f"{where}.expires: unknown clock {call.args['expires']!r}; "
                f"known: {sorted(conditions_module.CLOCK_KEYWORDS)} or 'rounds:<n>'")
    elif call.effect == "require_save":
        require_keys(call.args, ["ability", "dc"], where=where)
        for key in ("on_fail", "on_success"):
            for j, sub in enumerate(call.args.get(key, [])):
                sub_call = EffectCall.from_dict(sub)
                sub_where = f"{where}.{key}[{j}]"
                validate_effect_name(sub_call.effect, where=sub_where)
                _validate_effect_args(sub_call, where=sub_where, known_conditions=known_conditions)
    elif call.effect == "set_flag":
        require_keys(call.args, ["flag"], where=where)
        closed_vocab(call.args.get("scope", "round"), ("round", "trial"), where=f"{where}.scope")
    elif call.effect == "end_trial":
        if "outcome" in call.args and not isinstance(call.args["outcome"], dict):
            raise ValueError(f"{where}.outcome: must be a table, got {type(call.args['outcome']).__name__}")
    elif call.effect == "emit_light":
        require_keys(call.args, ["radius"], where=where)
    elif call.effect == "redirect_attack":
        require_keys(call.args, ["to"], where=where)
        _validate_target_ref(call.args["to"], where=f"{where}.to")
    elif call.effect == "swap_positions":
        require_keys(call.args, ["with"], where=where)
        _validate_target_ref(call.args["with"], where=f"{where}.with")
    elif call.effect == "damage_rider":
        require_keys(call.args, ["damage"], where=where)
    elif call.effect == "reduce_damage":
        require_keys(call.args, ["factor"], where=where)
    elif call.effect == "mark_turn":
        require_keys(call.args, ["key"], where=where)
    elif call.effect == "make_attack":
        require_keys(call.args, ["ability"], where=where)
        if "actor" in call.args:
            _validate_target_ref(call.args["actor"], where=f"{where}.actor")
    elif call.effect == "spend_resource":
        require_keys(call.args, ["resource"], where=where)
    elif call.effect == "grant_temp_hp":
        require_keys(call.args, ["amount"], where=where)


# Area-of-effect shapes the engine can target geometrically (aoe.py): a line
# (Lightning Bolt), a sphere (Fireball, Shatter), and a caster-origin cube
# (Thunder Wave). A cone would join here.
AREA_SHAPES = frozenset({"line", "sphere", "cube"})
_AREA_REQUIRED = {"line": ["length_ft"], "sphere": ["radius_ft", "range_ft"], "cube": ["size_ft"]}


def _validate_area(area: dict, *, where: str) -> None:
    if not isinstance(area, dict):
        raise ValueError(f"{where}: expected an inline table, got {type(area).__name__}")
    shape = area.get("shape")
    closed_vocab(shape, AREA_SHAPES, where=f"{where}.shape")
    require_keys(area, _AREA_REQUIRED[shape], where=where)


def _build_ability(name: str, spec: dict, *, where: str, known_conditions: frozenset) -> Ability:
    kind = spec.get("kind")
    closed_vocab(kind, ABILITY_KINDS, where=f"{where}.kind")
    if "targets" in spec:
        closed_vocab(spec["targets"], expressions.SELECTOR_NAMES, where=f"{where}.targets")
    target_filter = None
    if "target_filter" in spec:
        target_filter = expressions.parse_and_validate(spec["target_filter"], where=f"{where}.target_filter")
    advantage_when = None
    if "advantage_when" in spec:
        advantage_when = expressions.parse_and_validate(spec["advantage_when"], where=f"{where}.advantage_when")
    area = spec.get("area")
    if area is not None:
        _validate_area(area, where=f"{where}.area")
    return Ability(
        name=name, kind=kind,
        to_hit=spec.get("to_hit"), damage=spec.get("damage"), damage_type=spec.get("damage_type"),
        crit_range=spec.get("crit_range", 20), reach=spec.get("reach"),
        range_normal=spec.get("range_normal"), range_long=spec.get("range_long"),
        advantage_when=advantage_when,
        ability=spec.get("ability"), dc=spec.get("dc"), half_on_save=spec.get("half_on_save", False),
        targets=spec.get("targets"), target_filter=target_filter, max_targets=spec.get("max_targets"),
        area=area,
        requires_sight=spec.get("requires_sight", True),
        amount=spec.get("amount"), range=spec.get("range"),
        costs=spec.get("costs"), uses_bonus_action=spec.get("uses_bonus_action", False),
        description=spec.get("description"),
        on_hit=_build_effect_calls(spec.get("on_hit"), where=f"{where}.on_hit", known_conditions=known_conditions),
        on_fail=_build_effect_calls(spec.get("on_fail"), where=f"{where}.on_fail", known_conditions=known_conditions),
        on_crit=_build_effect_calls(spec.get("on_crit"), where=f"{where}.on_crit", known_conditions=known_conditions),
        on_success=_build_effect_calls(spec.get("on_success"), where=f"{where}.on_success",
                                       known_conditions=known_conditions),
        on_all_saved=_build_effect_calls(spec.get("on_all_saved"), where=f"{where}.on_all_saved",
                                         known_conditions=known_conditions),
        effects=_build_effect_calls(spec.get("effects"), where=f"{where}.effects", known_conditions=known_conditions),
    )


def _build_multiattack(name: str, spec: dict, *, where: str) -> MultiattackOption:
    when = None
    if "when" in spec:
        when = expressions.parse_and_validate(spec["when"], where=f"{where}.when")
    actions = tuple(spec.get("actions", ()))
    if not actions:
        raise ValueError(f"{where}: multiattack option has no actions")
    return MultiattackOption(name=name, actions=actions, when=when, priority=spec.get("priority", 0))


def _build_trait(name: str, spec: dict, *, where: str, known_conditions: frozenset) -> Trait:
    return Trait(name=name, description=spec.get("description"),
                effects=_build_effect_calls(spec.get("effects"), where=f"{where}.effects",
                                            known_conditions=known_conditions))


def _build_resource(name: str, spec: dict, *, where: str) -> Resource:
    require_keys(spec, ["uses"], where=where)
    return Resource(name=name, uses=spec["uses"], recharge=spec.get("recharge"), per=spec.get("per"))


def _build_targeting_rule(spec: dict, *, where: str) -> TargetingRule:
    when = None
    if "when" in spec:
        when = expressions.parse_and_validate(spec["when"], where=f"{where}.when")
    order = spec.get("order", "nearest")
    closed_vocab(order, TARGETING_ORDERS, where=f"{where}.order")
    return TargetingRule(when=when, priority=spec.get("priority", 0), order=order)


def _build_condition_def(name: str, spec: dict, *, where: str) -> ConditionDef:
    grants = []
    for i, d in enumerate(spec.get("grants", [])):
        item_where = f"{where}.grants[{i}]"
        call = EffectCall.from_dict(d)
        if call.effect not in conditions_module.GRANT_EFFECTS:
            raise ValueError(
                f"{item_where}: unknown grant-context effect {call.effect!r}; "
                f"known: {sorted(conditions_module.GRANT_EFFECTS)}")
        grants.append(call)
    exclusive = spec.get("exclusive")
    if exclusive is not None:
        closed_vocab(exclusive, ("per_source", "per_target"), where=f"{where}.exclusive")
    expires = spec.get("expires")
    if expires is not None and not conditions_module.is_known_clock(expires):
        raise ValueError(f"{where}.expires: unknown clock {expires!r}; "
                         f"known: {sorted(conditions_module.CLOCK_KEYWORDS)} or 'rounds:<n>'")
    unless = spec.get("unless")
    if unless is not None:
        closed_vocab(unless, conditions_module.UNLESS_PREDICATES, where=f"{where}.unless")
    save_ability, save_dc = spec.get("save_ability"), spec.get("save_dc")
    if expires in conditions_module.SAVE_ENDS_CLOCKS:
        require_keys(spec, ["save_ability", "save_dc"], where=where)
        closed_vocab(save_ability, ABILITY_SCORE_KEYS, where=f"{where}.save_ability")
    elif save_ability is not None or save_dc is not None:
        raise ValueError(f"{where}: save_ability/save_dc only apply to a save-ends clock "
                         f"({sorted(conditions_module.SAVE_ENDS_CLOCKS)}), not expires={expires!r}")
    return ConditionDef(name=name, grants=tuple(grants), exclusive=exclusive,
                        ends_with_source=spec.get("ends_with_source", True),
                        expires=expires, unless=unless,
                        save_ability=save_ability, save_dc=save_dc)


def _build_reaction(name: str, spec: dict, *, where: str, known_conditions: frozenset) -> Reaction:
    require_keys(spec, ["trigger"], where=where)
    trigger = spec["trigger"]
    closed_vocab(trigger, conditions_module.REACTION_TRIGGERS, where=f"{where}.trigger")
    when = None
    if "when" in spec:
        when = expressions.parse_and_validate(spec["when"], where=f"{where}.when")
    return Reaction(
        name=name, trigger=trigger, when=when,
        effects=_build_effect_calls(spec.get("effects"), where=f"{where}.effects",
                                    known_conditions=known_conditions),
        uses_reaction=spec.get("uses_reaction", False), uses_bonus_action=spec.get("uses_bonus_action", False),
        priority=spec.get("priority", 0),
    )


def _build_behavior(spec: dict, *, where: str) -> Behavior:
    tactic = spec.get("tactic", "engage")
    closed_vocab(tactic, KNOWN_TACTICS, where=f"{where}.tactic")
    targeting = tuple(
        _build_targeting_rule(rule, where=f"{where}.targeting[{i}]")
        for i, rule in enumerate(spec.get("targeting", []))
    )
    custom = spec.get("custom", {}).get("handler") if "custom" in spec else None
    if custom is not None and not custom.startswith("python:"):
        raise ValueError(f"{where}.custom.handler: must start with 'python:', got {custom!r}")
    return Behavior(tactic=tactic, action_priority=tuple(spec.get("action_priority", ())),
                    targeting=targeting, custom=custom)


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

    # Parsed first: `attach_condition` (in abilities/traits/reactions below)
    # validates against RAW conditions *plus* whatever this file defines here.
    condition_defs = {n: _build_condition_def(n, spec, where=f"{source} [conditions.{n}]")
                      for n, spec in cfg.get("conditions", {}).items()}
    known_conditions = frozenset(condition_defs)

    abilities = {n: _build_ability(n, spec, where=f"{source} [abilities.{n}]", known_conditions=known_conditions)
                for n, spec in cfg.get("abilities", {}).items()}
    multiattack = {n: _build_multiattack(n, spec, where=f"{source} [multiattack.{n}]")
                   for n, spec in cfg.get("multiattack", {}).items()}
    traits = {n: _build_trait(n, spec, where=f"{source} [traits.{n}]", known_conditions=known_conditions)
             for n, spec in cfg.get("traits", {}).items()}
    reactions = {n: _build_reaction(n, spec, where=f"{source} [reactions.{n}]", known_conditions=known_conditions)
                for n, spec in cfg.get("reactions", {}).items()}
    resources = {n: _build_resource(n, spec, where=f"{source} [resources.{n}]")
                for n, spec in cfg.get("resources", {}).items()}
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
    # Design doc 04 section 2: "ties are a load-time error." Enforced across
    # ALL options, not just ones that could be simultaneously eligible at
    # runtime — deciding whether two `when` clauses can ever both be true is
    # a satisfiability question this loader doesn't attempt; requiring every
    # option to have a distinct priority is the simple, always-correct rule
    # that "forces the author to be explicit" (the doc's own rationale).
    priorities = [opt.priority for opt in multiattack.values()]
    if len(set(priorities)) != len(priorities):
        raise ValueError(
            f"{source} [multiattack]: duplicate priority value(s) among "
            f"{sorted(multiattack.keys())} — every option must have a distinct priority"
        )

    return Statblock(
        name=name,
        display_name=cfg.get("display_name", name.replace("_", " ").title()),
        classification=dict(cfg.get("classification", {})),
        stats=stats,
        tags=tuple(cfg.get("tags", ())),
        engaged_by=tuple(cfg.get("engaged_by", ())),
        abilities=abilities,
        multiattack=multiattack,
        traits=traits,
        reactions=reactions,
        resources=resources,
        conditions=condition_defs,
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


OBSCUREMENT_KINDS = ("fog", "darkness", "magical_darkness", "light")


@dataclass(frozen=True)
class ObscurementSpec:
    """One `[[environment.obscurement]]` entry (design doc 01 section 3): a
    fog/darkness/magical_darkness/light region, either static (`center`) or
    bound to a combatant (`follows`, re-centered on it every round — see
    `battlefield.Aura`)."""

    kind: str
    radius_ft: float
    follows: Optional[str] = None          # instance_name, or...
    center: Optional[tuple] = None         # ...a fixed (x, y)
    start_round: int = 1


@dataclass(frozen=True)
class LightPlanSpec:
    """`[environment.light_plan]` (design doc 01 section 3): a scripted
    "someone lights a torch" moment — `source` clears its side's obscurement-
    blindness once, at `round`, optionally spending its action to do so."""

    source: str
    round: int
    costs_action: bool = True


@dataclass(frozen=True)
class ExtractionSpec:
    """`[extraction]` (a smash-and-grab objective): the party breaks the
    `objective` creature, then RETREATS toward `exit`, fights `cover_rounds`
    rounds, and the trial ends — success (`extracted`) = objective secured AND
    nobody on `party_side` is down. Turns a stand-and-die fight into "grab it and
    get out"."""

    objective: str
    exit: tuple           # (x, y) cell the party flees toward
    cover_rounds: int = 1
    party_side: str = "party"


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
    obscurement: tuple = ()               # tuple[ObscurementSpec, ...]
    light_plan: Optional[LightPlanSpec] = None
    reinforcements: tuple = ()            # tuple[(round_index, tuple[RosterSlot]), ...]
    extraction: Optional["ExtractionSpec"] = None
    # `[simulation] grapple_escape`: model RAW 2024's "escaping costs your
    # action" (system._try_escape_grapple). Opt-in — see that method for why.
    grapple_escape: bool = False


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
    cfg = load_toml_file(path)
    return build_simulation(cfg, sim_dir=path.parent, name_fallback=path.stem, where=str(path))


def build_simulation(cfg: dict, *, sim_dir: Path, name_fallback: str,
                     where: Optional[str] = None) -> SimulationSpec:
    """The dict-driven half of `load_simulation`, split out so `sweep.expand`'s
    in-memory config variants (design doc 02 section 6) can be built into a
    `SimulationSpec` without a round-trip through disk. `sim_dir` anchors
    relative `sources`/board/creature paths exactly as the sim file's own
    directory would; `name_fallback` is the sim's name when `cfg` has none
    (matching `load_simulation`'s use of the file's stem); `where` labels error
    messages (the real file path for `load_simulation`, `sim_dir` itself for a
    sweep variant that was never written to disk)."""
    path = where if where is not None else str(sim_dir)

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
    focus = {}
    if "focus" in environment:
        # Matches the old engine's scenario.py: a bare `focus` name is always
        # the *party's* focus-fire target (monsters don't get scripted focus
        # in these sims).
        focus["party"] = environment["focus"]

    obscurement = []
    for i, spec in enumerate(environment.get("obscurement", [])):
        where = f"{path} [[environment.obscurement]][{i}]"
        require_keys(spec, ["kind", "radius"], where=where)
        closed_vocab(spec["kind"], OBSCUREMENT_KINDS, where=f"{where}.kind")
        follows, center = spec.get("follows"), spec.get("center")
        if follows is None and center is None:
            raise ValueError(f"{where}: needs 'follows' (a combatant instance_name) or 'center' ([x, y])")
        obscurement.append(ObscurementSpec(
            kind=spec["kind"], radius_ft=spec["radius"], follows=follows,
            center=tuple(center) if center is not None else None,
            start_round=spec.get("start_round", 1),
        ))

    light_plan = None
    if "light_plan" in environment:
        lp = environment["light_plan"]
        where = f"{path} [environment.light_plan]"
        require_keys(lp, ["source", "round"], where=where)
        light_plan = LightPlanSpec(source=lp["source"], round=lp["round"],
                                   costs_action=lp.get("costs_action", True))

    # Reinforcement waves (mid-trial arrivals). Each rule spawns `combatants`
    # at `spawn` starting `first_round`, repeating every `interval` rounds up to
    # max_rounds. Pre-expanded to concrete (round, [RosterSlot]) waves here so
    # the system only has to place them.
    reinforcements = []
    for ri, rule in enumerate(cfg.get("reinforcements", [])):
        where = f"{path} [[reinforcements]][{ri}]"
        require_keys(rule, ["first_round", "spawn", "combatants"], where=where)
        spawn_label = rule["spawn"]
        cells = board.spawns.get(spawn_label)
        if not cells:
            raise ValueError(f"{where}: spawn label {spawn_label!r} not found on board")
        interval = rule.get("interval", 0)
        rounds = [rule["first_round"]]
        if interval > 0:
            r = rule["first_round"] + interval
            while r <= sim["max_rounds"]:
                rounds.append(r)
                r += interval
        cursor = 0
        for wr in rounds:
            slots = []
            for wc in rule["combatants"]:
                require_keys(wc, ["creature"], where=f"{where}.combatants")
                cn, cnt, wside = wc["creature"], wc.get("count", 1), wc.get("side", "monsters")
                cpath = _resolve_creature_path(cn, sim_dir=sim_dir, sources=sources)
                for i in range(cnt):
                    start = cells[cursor % len(cells)]
                    cursor += 1
                    slots.append(RosterSlot(statblock=load_creature(cpath),
                                            instance_name=f"{cn}_r{wr}_{i + 1}",
                                            side=wside, start=start, tags=()))
            reinforcements.append((wr, tuple(slots)))

    extraction = None
    if "extraction" in cfg:
        ex = cfg["extraction"]
        require_keys(ex, ["objective", "exit"], where=f"{path} [extraction]")
        extraction = ExtractionSpec(objective=ex["objective"], exit=tuple(ex["exit"]),
                                    cover_rounds=ex.get("cover_rounds", 1),
                                    party_side=ex.get("party_side", "party"))

    return SimulationSpec(
        name=cfg.get("name", name_fallback), board=board, roster=roster,
        trials=sim["trials"], max_rounds=sim["max_rounds"], seed=sim["seed"],
        hp_mode=hp_mode, focus=focus, output=cfg.get("output", {}),
        obscurement=tuple(obscurement), light_plan=light_plan,
        reinforcements=tuple(reinforcements), extraction=extraction,
        grapple_escape=bool(sim.get("grapple_escape", False)),
    )
