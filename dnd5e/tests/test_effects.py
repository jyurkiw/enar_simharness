import pytest

from dnd5e.effects import EffectScope, apply_effect, apply_effects, validate_effect_name
from dnd5e.statblock import EffectCall


class FakeCtx:
    def __init__(self, save_result=True):
        self.calls = []
        self._save_result = save_result
        self.condition_defs = {}

    def apply_condition(self, target, condition, *, source, escape_dc=None):
        self.calls.append(("apply_condition", target, condition, source, escape_dc))

    def remove_condition(self, target, condition):
        self.calls.append(("remove_condition", target, condition))

    def saving_throw(self, target, ability, dc):
        self.calls.append(("saving_throw", target, ability, dc))
        return self._save_result

    def set_flag(self, name, *, scope):
        self.calls.append(("set_flag", name, scope))

    def end_trial(self, *, outcome=None):
        self.calls.append(("end_trial", outcome))

    def set_pending_redirect(self, to):
        self.calls.append(("set_pending_redirect", to))

    def swap_positions(self, a, b):
        self.calls.append(("swap_positions", a, b))

    def roll(self, code, *, crit=False):
        self.calls.append(("roll", code, crit))
        return 99

    def deal(self, source, target, amount, name, damage_type=None):
        self.calls.append(("deal", source, target, amount, name, damage_type))


def test_validate_effect_name_accepts_known():
    validate_effect_name("attach_condition", where="x")


def test_validate_effect_name_rejects_unknown():
    with pytest.raises(ValueError, match="unknown effect"):
        validate_effect_name("teleport", where="abilities.bite.on_hit")


def test_attach_condition_calls_ctx_with_source_and_escape_dc():
    ctx = FakeCtx()
    scope = EffectScope(ctx=ctx, source="otyugh", target="fighter")
    apply_effect(EffectCall(effect="attach_condition", args={"condition": "grappled", "escape_dc": 13}), scope)
    assert ctx.calls == [("apply_condition", "fighter", "grappled", "otyugh", 13)]


def test_attach_condition_escape_dc_defaults_to_none():
    ctx = FakeCtx()
    scope = EffectScope(ctx=ctx, source="otyugh", target="fighter")
    apply_effect(EffectCall(effect="attach_condition", args={"condition": "stunned"}), scope)
    assert ctx.calls == [("apply_condition", "fighter", "stunned", "otyugh", None)]


def test_redirect_attack_sets_pending_redirect_to_the_resolved_ref():
    ctx = FakeCtx()
    scope = EffectScope(ctx=ctx, source="protector", target="fighter")
    apply_effect(EffectCall(effect="redirect_attack", args={"to": "self"}), scope)
    assert ctx.calls == [("set_pending_redirect", "protector")]


def test_swap_positions_calls_ctx_with_source_and_the_resolved_ref():
    ctx = FakeCtx()
    scope = EffectScope(ctx=ctx, source="rogue", target="fighter", event={"attacker": "otyugh"})
    apply_effect(EffectCall(effect="swap_positions", args={"with": "event.attacker"}), scope)
    assert ctx.calls == [("swap_positions", "rogue", "otyugh")]


def test_damage_rider_rolls_and_deals_separately_from_the_base_hit():
    ctx = FakeCtx()
    scope = EffectScope(ctx=ctx, source="hector", target="fighter", event={"crit": True})
    apply_effect(EffectCall(effect="damage_rider", args={"damage": "2d6", "name": "mark_rider"}), scope)
    assert ctx.calls == [("roll", "2d6", True), ("deal", "hector", "fighter", 99, "mark_rider", None)]


def test_remove_condition():
    ctx = FakeCtx()
    scope = EffectScope(ctx=ctx, source="cleric", target="fighter")
    apply_effect(EffectCall(effect="remove_condition", args={"condition": "poisoned"}), scope)
    assert ctx.calls == [("remove_condition", "fighter", "poisoned")]


def test_require_save_dispatches_on_fail_when_save_fails():
    ctx = FakeCtx(save_result=False)
    scope = EffectScope(ctx=ctx, source="otyugh", target="fighter")
    call = EffectCall(effect="require_save", args={
        "ability": "con", "dc": 15,
        "on_fail": [{"effect": "attach_condition", "condition": "diseased"}],
    })
    apply_effect(call, scope)
    assert ("saving_throw", "fighter", "con", 15) in ctx.calls
    assert ("apply_condition", "fighter", "diseased", "otyugh", None) in ctx.calls


def test_require_save_dispatches_on_success_when_save_succeeds():
    ctx = FakeCtx(save_result=True)
    scope = EffectScope(ctx=ctx, source="cleric", target="rogue")
    call = EffectCall(effect="require_save", args={
        "ability": "wis", "dc": 14,
        "on_fail": [{"effect": "attach_condition", "condition": "stunned"}],
        "on_success": [{"effect": "remove_condition", "condition": "poisoned"}],
    })
    apply_effect(call, scope)
    assert ("remove_condition", "rogue", "poisoned") in ctx.calls
    assert not any(c[0] == "apply_condition" for c in ctx.calls)


def test_require_save_with_no_matching_branch_is_a_noop():
    ctx = FakeCtx(save_result=True)
    scope = EffectScope(ctx=ctx, source="otyugh", target="fighter")
    call = EffectCall(effect="require_save", args={"ability": "con", "dc": 15,
                                                    "on_fail": [{"effect": "attach_condition", "condition": "diseased"}]})
    apply_effect(call, scope)  # saved, no on_success given -> nothing extra happens
    assert ("saving_throw", "fighter", "con", 15) in ctx.calls
    assert not any(c[0] == "apply_condition" for c in ctx.calls)


def test_apply_effects_runs_every_call_in_order():
    ctx = FakeCtx()
    scope = EffectScope(ctx=ctx, source="a", target="b")
    calls = (
        EffectCall(effect="attach_condition", args={"condition": "grappled"}),
        EffectCall(effect="remove_condition", args={"condition": "prone"}),
    )
    apply_effects(calls, scope)
    assert [c[0] for c in ctx.calls] == ["apply_condition", "remove_condition"]


def test_set_flag_defaults_to_round_scope():
    ctx = FakeCtx()
    scope = EffectScope(ctx=ctx, source="otyugh", target="fighter")
    apply_effect(EffectCall(effect="set_flag", args={"flag": "enemy_crit"}), scope)
    assert ctx.calls == [("set_flag", "enemy_crit", "round")]


def test_set_flag_explicit_trial_scope():
    ctx = FakeCtx()
    scope = EffectScope(ctx=ctx, source="otyugh", target="fighter")
    apply_effect(EffectCall(effect="set_flag", args={"flag": "boss_enraged", "scope": "trial"}), scope)
    assert ctx.calls == [("set_flag", "boss_enraged", "trial")]


class FakeBattlefield:
    def __init__(self):
        self.auras = []


class FakeCreature:
    def __init__(self, instance_name):
        self.instance_name = instance_name
        self.trial_scratch = {}


class FakeCtxWithBattlefield(FakeCtx):
    def __init__(self, save_result=True):
        super().__init__(save_result)
        self.battlefield = FakeBattlefield()


def test_emit_light_appends_a_following_aura_for_the_target():
    from dnd5e.battlefield import Aura

    ctx = FakeCtxWithBattlefield()
    target = FakeCreature("torchbearer")
    scope = EffectScope(ctx=ctx, source=target, target=target)
    apply_effect(EffectCall(effect="emit_light", args={"radius": 20}), scope)
    assert ctx.battlefield.auras == [Aura(source="torchbearer", kind="light", radius_ft=20, start_round=1)]


def test_emit_light_explicit_start_round():
    from dnd5e.battlefield import Aura

    ctx = FakeCtxWithBattlefield()
    target = FakeCreature("lamp")
    scope = EffectScope(ctx=ctx, source=target, target=target)
    apply_effect(EffectCall(effect="emit_light", args={"radius": 15, "start_round": 3}), scope)
    assert ctx.battlefield.auras == [Aura(source="lamp", kind="light", radius_ft=15, start_round=3)]


def test_limited_darkvision_sets_default_range():
    ctx = FakeCtx()
    target = FakeCreature("shadow_otyugh")
    scope = EffectScope(ctx=ctx, source=target, target=target)
    apply_effect(EffectCall(effect="limited_darkvision", args={}), scope)
    assert target.trial_scratch["limited_darkvision_ft"] == 30


def test_limited_darkvision_explicit_range():
    ctx = FakeCtx()
    target = FakeCreature("owl")
    scope = EffectScope(ctx=ctx, source=target, target=target)
    apply_effect(EffectCall(effect="limited_darkvision", args={"range": 60}), scope)
    assert target.trial_scratch["limited_darkvision_ft"] == 60


def test_darkvision_immunity_sets_marker():
    ctx = FakeCtx()
    target = FakeCreature("otyugh")
    scope = EffectScope(ctx=ctx, source=target, target=target)
    apply_effect(EffectCall(effect="darkvision_immunity", args={}), scope)
    assert target.trial_scratch["darkvision_immune"] is True


def test_end_trial_with_no_outcome():
    ctx = FakeCtx()
    scope = EffectScope(ctx=ctx, source="otyugh", target="otyugh")
    apply_effect(EffectCall(effect="end_trial", args={}), scope)
    assert ctx.calls == [("end_trial", None)]


def test_end_trial_with_outcome_dict():
    ctx = FakeCtx()
    scope = EffectScope(ctx=ctx, source="otyugh", target="otyugh")
    apply_effect(EffectCall(effect="end_trial", args={"outcome": {"retreated": 1}}), scope)
    assert ctx.calls == [("end_trial", {"retreated": 1})]


def test_apply_effect_unregistered_name_raises_at_call_time_too():
    # Belt-and-suspenders: even if a bad name slipped past load-time validation.
    ctx = FakeCtx()
    scope = EffectScope(ctx=ctx, source="a", target="b")
    with pytest.raises(ValueError, match="unknown effect"):
        apply_effect(EffectCall(effect="teleport", args={}), scope)
