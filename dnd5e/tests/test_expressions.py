import pytest

from dnd5e.expressions import (
    BinOp,
    Bool,
    Call,
    Compare,
    ExpressionError,
    Number,
    Selector,
    String,
    UnaryOp,
    evaluate,
    parse,
    parse_and_validate,
    validate,
)


# ---- a minimal but complete Scope for evaluation tests -----------------------

class Creature:
    def __init__(self, name, *, hp=20, max_hp=20, tags=(), conditions=(), side="party"):
        self.name = name
        self.hp_val = hp
        self.max_hp = max_hp
        self.tags = set(tags)
        self.conditions = set(conditions)
        self.side = side

    def __repr__(self):
        return f"Creature({self.name!r})"


class FakeScope:
    def __init__(self, *, self_c=None, target=None, it=None, enemies=(), allies=(),
                grappled=(), flags=(), resources=(), round_index=1, event=None):
        self._self = self_c
        self._target = target
        self._it = it
        self._enemies = list(enemies)
        self._allies = list(allies)
        self._grappled = list(grappled)
        self._flags = set(flags)
        self._resources = set(resources)
        self._round = round_index
        self._event = event or {}

    def self_creature(self):
        return self._self

    def target_creature(self):
        return self._target

    def it_creature(self):
        return self._it

    def event_field(self, name):
        return self._event.get(name)

    def enemies(self):
        return self._enemies

    def allies(self):
        return self._allies

    def enemies_grappled_by_self(self):
        return self._grappled

    def enemies_within(self, ft):
        return self._enemies

    def allies_within(self, ft):
        return self._allies

    def enemies_tagged(self, tag):
        return [e for e in self._enemies if tag in e.tags]

    def allies_tagged(self, tag):
        return [a for a in self._allies if tag in a.tags]

    def enemies_within_of(self, who, ft):
        return self._enemies

    def nearest_enemy(self):
        return self._enemies[0] if self._enemies else None

    def ally_lowest_hp(self):
        return min(self._allies, key=lambda a: a.hp_val) if self._allies else None

    def nearest(self, creatures):
        return creatures[0] if creatures else None

    def farthest(self, creatures):
        return creatures[-1] if creatures else None

    def has_condition(self, who, name):
        return name in who.conditions

    def has_tag(self, who, tag):
        return tag in who.tags

    def hp(self, who):
        return who.hp_val

    def hp_pct(self, who):
        return who.hp_val / who.max_hp

    def is_bloodied(self, who):
        return who.hp_val * 2 <= who.max_hp

    def is_down(self, who):
        return who.hp_val <= 0

    def distance(self, a, b):
        return 10  # fixed, controlled value — no hash-randomization dependence

    def can_see(self, a, b):
        return True

    def in_reach(self, a, b):
        return True

    def is_grappling(self, a, b):
        return b in self._grappled and a is self._self

    def is_grappled_by(self, a, b):
        return a in self._grappled and b is self._self

    def is_grappled(self, who):
        return who in self._grappled

    def resource_available(self, name):
        return name in self._resources

    def round_number(self):
        return self._round

    def has_flag(self, name):
        return name in self._flags

    def any_yet_to_act(self, creatures):
        return len(creatures) > 0

    def side_of(self, who):
        return who.side

    def with_it(self, creature):
        return FakeScope(self_c=self._self, target=self._target, it=creature,
                         enemies=self._enemies, allies=self._allies, grappled=self._grappled,
                         flags=self._flags, resources=self._resources, round_index=self._round,
                         event=self._event)


# ---- parsing -------------------------------------------------------------------

def test_parse_number():
    assert parse("42") == Number(42.0)
    assert parse("3.5") == Number(3.5)


def test_parse_string_single_and_double_quotes():
    assert parse("'tank'") == String("tank")
    assert parse('"tank"') == String("tank")


def test_parse_bool():
    assert parse("true") == Bool(True)
    assert parse("false") == Bool(False)


def test_parse_bare_selector():
    assert parse("self") == Selector(("self",))


def test_parse_dotted_selector():
    assert parse("event.attacker") == Selector(("event", "attacker"))


def test_parse_call_no_args():
    assert parse("round()") == Call("round", ())


def test_parse_call_multiple_args():
    node = parse("distance(self, target)")
    assert node == Call("distance", (Selector(("self",)), Selector(("target",))))


def test_parse_parentheses_grouping():
    node = parse("(1 + 2) * 3")
    assert node == BinOp("*", BinOp("+", Number(1), Number(2)), Number(3))


def test_parse_unmatched_paren_raises():
    with pytest.raises(ExpressionError):
        parse("(1 + 2")


def test_parse_unknown_token_raises():
    with pytest.raises(ExpressionError):
        parse("1 & 2")


# ---- precedence -----------------------------------------------------------------

def test_precedence_multiplication_before_addition():
    assert evaluate(parse("1 + 2 * 3"), FakeScope()) == 7


def test_precedence_and_before_or():
    # false or (true and false) == false
    assert evaluate(parse("false or true and false"), FakeScope()) is False
    # true or (false and false) == true
    assert evaluate(parse("true or false and false"), FakeScope()) is True


def test_precedence_not_binds_tighter_than_and():
    # (not true) and false == false; if not bound looser it'd be not(true and false) = true
    assert evaluate(parse("not true and false"), FakeScope()) is False


def test_precedence_comparison_below_sum():
    assert evaluate(parse("1 + 1 == 2"), FakeScope()) is True


def test_explicit_parentheses_override_precedence():
    assert evaluate(parse("(1 + 2) * 3"), FakeScope()) == 9
    assert evaluate(parse("1 + 2 * 3"), FakeScope()) == 7


# ---- validation ------------------------------------------------------------------

def test_validate_accepts_known_selector():
    validate(parse("self"), where="x")
    validate(parse("enemies"), where="x")


def test_validate_rejects_unknown_selector():
    with pytest.raises(ExpressionError, match="unknown selector"):
        validate(parse("bogus"), where="abilities.bite.target_filter")


def test_validate_accepts_event_dotted_selector():
    validate(parse("event.attacker"), where="x")  # structurally valid (Phase 5 semantics)


def test_validate_rejects_unknown_dotted_root():
    with pytest.raises(ExpressionError, match="unknown selector root"):
        validate(parse("bogus.field"), where="x")


def test_validate_accepts_known_function():
    validate(parse("count(enemies)"), where="x")
    validate(parse("has_tag(self, 'tank')"), where="x")


def test_validate_rejects_unknown_function():
    with pytest.raises(ExpressionError, match="unknown function"):
        validate(parse("teleport(self)"), where="x")


def test_validate_recurses_into_nested_expressions():
    with pytest.raises(ExpressionError, match="unknown function"):
        validate(parse("1 + teleport(self)"), where="x")


def test_validate_recurses_into_call_args():
    with pytest.raises(ExpressionError, match="unknown selector"):
        validate(parse("count(bogus)"), where="x")


def test_parse_and_validate_convenience():
    node = parse_and_validate("count(enemies) >= 2", where="x")
    assert isinstance(node, Compare)


def test_parse_and_validate_propagates_validation_error():
    with pytest.raises(ExpressionError):
        parse_and_validate("teleport(self)", where="x")


# ---- evaluation: selectors --------------------------------------------------------

def test_eval_self_and_target_selectors():
    a, b = Creature("otyugh"), Creature("fighter")
    scope = FakeScope(self_c=a, target=b)
    assert evaluate(parse("self"), scope) is a
    assert evaluate(parse("target"), scope) is b


def test_eval_enemies_allies_selectors():
    e1, e2 = Creature("e1"), Creature("e2")
    scope = FakeScope(enemies=[e1, e2])
    assert evaluate(parse("count(enemies)"), scope) == 2


# ---- evaluation: functions ---------------------------------------------------------

def test_eval_count():
    scope = FakeScope(enemies=[Creature("a"), Creature("b")])
    assert evaluate(parse("count(enemies)"), scope) == 2


def test_eval_has_condition_and_has_tag():
    a = Creature("a", tags=["tank"], conditions=["grappled"])
    scope = FakeScope(self_c=a)
    assert evaluate(parse("has_tag(self, 'tank')"), scope) is True
    assert evaluate(parse("has_tag(self, 'skirmisher')"), scope) is False
    assert evaluate(parse("has_condition(self, 'grappled')"), scope) is True


def test_eval_hp_and_hp_pct_and_is_bloodied():
    a = Creature("a", hp=5, max_hp=20)
    scope = FakeScope(self_c=a)
    assert evaluate(parse("hp(self)"), scope) == 5
    assert evaluate(parse("hp_pct(self)"), scope) == pytest.approx(0.25)
    assert evaluate(parse("is_bloodied(self)"), scope) is True


def test_eval_is_down():
    dead = Creature("d", hp=0)
    scope = FakeScope(self_c=dead)
    assert evaluate(parse("is_down(self)"), scope) is True


def test_eval_is_grappling_family():
    otyugh = Creature("otyugh")
    fighter = Creature("fighter")
    scope = FakeScope(self_c=otyugh, target=fighter, grappled=[fighter])
    assert evaluate(parse("is_grappling(self, target)"), scope) is True
    assert evaluate(parse("is_grappled(target)"), scope) is True


def test_eval_resource_available():
    scope = FakeScope(resources=["ki"])
    assert evaluate(parse("resource_available('ki')"), scope) is True
    assert evaluate(parse("resource_available('smite_1')"), scope) is False


def test_eval_round_and_has_flag():
    scope = FakeScope(round_index=3, flags=["enemy_crit"])
    assert evaluate(parse("round()"), scope) == 3
    assert evaluate(parse("has_flag('enemy_crit')"), scope) is True
    assert evaluate(parse("has_flag('nope')"), scope) is False


def test_eval_side_of():
    a = Creature("a", side="monsters")
    scope = FakeScope(self_c=a)
    assert evaluate(parse("side_of(self)"), scope) == "monsters"


def test_eval_within():
    # FakeScope.distance is a fixed 10 for any pair; `within` measures
    # distance from self to the given creature.
    a, b = Creature("a"), Creature("b")
    scope = FakeScope(self_c=a, target=b)
    assert evaluate(parse("within(target, 10)"), scope) is True   # exactly at the limit
    assert evaluate(parse("within(target, 9)"), scope) is False   # just short of it


# ---- evaluation: any/all with `it` binding -----------------------------------------

def test_eval_any_true_when_one_element_matches():
    tank = Creature("tank", tags=["tank"])
    other = Creature("other", tags=[])
    scope = FakeScope(enemies=[other, tank])
    assert evaluate(parse("any(enemies, has_tag(it, 'tank'))"), scope) is True


def test_eval_any_false_when_no_element_matches():
    scope = FakeScope(enemies=[Creature("a"), Creature("b")])
    assert evaluate(parse("any(enemies, has_tag(it, 'tank'))"), scope) is False


def test_eval_all_true_when_every_element_matches():
    a = Creature("a", tags=["tank"])
    b = Creature("b", tags=["tank"])
    scope = FakeScope(enemies=[a, b])
    assert evaluate(parse("all(enemies, has_tag(it, 'tank'))"), scope) is True


def test_eval_all_false_when_one_element_fails():
    a = Creature("a", tags=["tank"])
    b = Creature("b", tags=[])
    scope = FakeScope(enemies=[a, b])
    assert evaluate(parse("all(enemies, has_tag(it, 'tank'))"), scope) is False


def test_eval_any_on_empty_set_is_false():
    scope = FakeScope(enemies=[])
    assert evaluate(parse("any(enemies, has_tag(it, 'tank'))"), scope) is False


def test_eval_all_on_empty_set_is_true():
    scope = FakeScope(enemies=[])
    assert evaluate(parse("all(enemies, has_tag(it, 'tank'))"), scope) is True


def test_eval_it_does_not_leak_outside_any_all():
    # `it` in the outer scope is None; only the predicate's child scope binds it.
    scope = FakeScope(enemies=[Creature("a")])
    assert scope.it_creature() is None
    evaluate(parse("any(enemies, has_tag(it, 'tank'))"), scope)
    assert scope.it_creature() is None  # outer scope untouched


# ---- evaluation: and/or short circuit + not ------------------------------------------

def test_and_short_circuits():
    calls = []

    class RecordingScope(FakeScope):
        def has_flag(self, name):
            calls.append(name)
            return False

    scope = RecordingScope(flags=[])
    # left side false -> right side's has_flag('b') should never be called
    evaluate(parse("has_flag('a') and has_flag('b')"), scope)
    assert calls == ["a"]


def test_or_short_circuits():
    calls = []

    class RecordingScope(FakeScope):
        def has_flag(self, name):
            calls.append(name)
            return True

    scope = RecordingScope(flags=["a"])
    evaluate(parse("has_flag('a') or has_flag('b')"), scope)
    assert calls == ["a"]


def test_not_negates():
    assert evaluate(parse("not true"), FakeScope()) is False
    assert evaluate(parse("not false"), FakeScope()) is True


def test_comparison_operators():
    scope = FakeScope()
    assert evaluate(parse("1 < 2"), scope) is True
    assert evaluate(parse("2 <= 2"), scope) is True
    assert evaluate(parse("3 > 2"), scope) is True
    assert evaluate(parse("2 >= 3"), scope) is False
    assert evaluate(parse("1 == 1"), scope) is True
    assert evaluate(parse("1 != 2"), scope) is True


def test_arithmetic_operators():
    scope = FakeScope()
    assert evaluate(parse("2 + 3"), scope) == 5
    assert evaluate(parse("5 - 2"), scope) == 3
    assert evaluate(parse("2 * 3"), scope) == 6
    assert evaluate(parse("6 / 2"), scope) == 3


def test_string_equality():
    scope = FakeScope()
    assert evaluate(parse("'a' == 'a'"), scope) is True
    assert evaluate(parse("'a' == 'b'"), scope) is False


# ---- real acid-test expressions from the otyugh multiattack (design doc 01 section 1.11) --

def test_otyugh_multiattack_when_clauses():
    otyugh = Creature("otyugh")
    grappled_two = [Creature("a"), Creature("b")]
    scope = FakeScope(self_c=otyugh, grappled=grappled_two)
    assert evaluate(parse("count(enemies_grappled_by_self) >= 2"), scope) is True

    grappled_one = [Creature("a")]
    scope1 = FakeScope(self_c=otyugh, grappled=grappled_one)
    assert evaluate(parse("count(enemies_grappled_by_self) == 1"), scope1) is True
    assert evaluate(parse("count(enemies_grappled_by_self) >= 2"), scope1) is False

    scope0 = FakeScope(self_c=otyugh, grappled=[])
    assert evaluate(parse("count(enemies_grappled_by_self) == 0"), scope0) is True
