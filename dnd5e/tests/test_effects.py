import pytest

from dnd5e.effects import EffectScope, apply_effect, apply_effects, validate_effect_name
from dnd5e.statblock import EffectCall


class FakeCtx:
    def __init__(self, save_result=True):
        self.calls = []
        self._save_result = save_result

    def apply_condition(self, target, condition, *, source, escape_dc=None):
        self.calls.append(("apply_condition", target, condition, source, escape_dc))

    def remove_condition(self, target, condition):
        self.calls.append(("remove_condition", target, condition))

    def saving_throw(self, target, ability, dc):
        self.calls.append(("saving_throw", target, ability, dc))
        return self._save_result


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


def test_apply_effect_unregistered_name_raises_at_call_time_too():
    # Belt-and-suspenders: even if a bad name slipped past load-time validation.
    ctx = FakeCtx()
    scope = EffectScope(ctx=ctx, source="a", target="b")
    with pytest.raises(ValueError, match="unknown effect"):
        apply_effect(EffectCall(effect="teleport", args={}), scope)
