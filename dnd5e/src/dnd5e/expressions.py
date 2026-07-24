"""The `when`/`target_filter` expression language (design doc 04 section 1).

A deliberately tiny, hand-rolled recursive-descent parser — **not Python
`eval`**: no attribute access, no arbitrary calls, no state mutation. An
expression is parsed once at load time (`parse` + `validate`, which checks
every identifier against the closed selector/function registries — an
unregistered name is a load-time error, never a runtime surprise) and
evaluated many times per trial via `evaluate(ast, scope)`.

This module knows nothing about `Creature`/`Battlefield` — it evaluates
against a `Scope` Protocol that `behavior.py` implements, keeping the
grammar/evaluator decoupled from the engine's concrete types (the same
pattern `effects.py` uses for its `EffectScope`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol, Sequence, runtime_checkable

# =============================================================================
# AST
# =============================================================================


@dataclass(frozen=True)
class Number:
    value: float


@dataclass(frozen=True)
class String:
    value: str


@dataclass(frozen=True)
class Bool:
    value: bool


@dataclass(frozen=True)
class Selector:
    parts: tuple[str, ...]  # ("self",) or ("event", "attacker")


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple["Node", ...]


@dataclass(frozen=True)
class UnaryOp:
    op: str  # "not" | "-"
    operand: "Node"


@dataclass(frozen=True)
class BinOp:
    op: str  # "and" | "or" | "+" | "-" | "*" | "/"
    left: "Node"
    right: "Node"


@dataclass(frozen=True)
class Compare:
    op: str  # "==" | "!=" | "<" | "<=" | ">" | ">="
    left: "Node"
    right: "Node"


Node = Number | String | Bool | Selector | Call | UnaryOp | BinOp | Compare


class ExpressionError(ValueError):
    """Raised for both parse errors and load-time validation failures, always
    naming the offending expression text."""


# =============================================================================
# Lexer
# =============================================================================

_TOKEN_RE = re.compile(r"""
      (?P<WS>\s+)
    | (?P<NUMBER>\d+\.\d+|\d+)
    | (?P<STRING>'[^']*'|"[^"]*")
    | (?P<OP><=|>=|==|!=|<|>|[()+\-*/,.])
    | (?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)
""", re.VERBOSE)

_KEYWORDS = {"and", "or", "not", "true", "false"}


@dataclass(frozen=True)
class _Token:
    kind: str  # NUMBER | STRING | OP | IDENT | keyword text | "EOF"
    text: str


def _tokenize(source: str) -> list[_Token]:
    tokens: list[_Token] = []
    pos = 0
    while pos < len(source):
        m = _TOKEN_RE.match(source, pos)
        if not m:
            raise ExpressionError(f"cannot tokenize {source!r} at position {pos} ({source[pos:pos + 10]!r}...)")
        pos = m.end()
        if m.lastgroup == "WS":
            continue
        kind = m.lastgroup
        text = m.group()
        if kind == "IDENT" and text in _KEYWORDS:
            kind = text  # keywords become their own token kind
        elif kind == "STRING":
            text = text[1:-1]
        tokens.append(_Token(kind=kind, text=text))
    tokens.append(_Token(kind="EOF", text=""))
    return tokens


# =============================================================================
# Parser (recursive descent, matching the EBNF in design doc 04 section 1)
# =============================================================================


class _Parser:
    def __init__(self, tokens: list[_Token], source: str) -> None:
        self._tokens = tokens
        self._pos = 0
        self._source = source

    def _peek(self) -> _Token:
        return self._tokens[self._pos]

    def _advance(self) -> _Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _expect(self, kind: str) -> _Token:
        tok = self._peek()
        if tok.kind != kind:
            raise ExpressionError(
                f"{self._source!r}: expected {kind!r} but found {tok.kind!r} ({tok.text!r})")
        return self._advance()

    def parse(self) -> Node:
        node = self._expr()
        self._expect("EOF")
        return node

    def _expr(self) -> Node:
        return self._or_expr()

    def _or_expr(self) -> Node:
        node = self._and_expr()
        while self._peek().kind == "or":
            self._advance()
            node = BinOp(op="or", left=node, right=self._and_expr())
        return node

    def _and_expr(self) -> Node:
        node = self._not_expr()
        while self._peek().kind == "and":
            self._advance()
            node = BinOp(op="and", left=node, right=self._not_expr())
        return node

    def _not_expr(self) -> Node:
        if self._peek().kind == "not":
            self._advance()
            return UnaryOp(op="not", operand=self._comparison())
        return self._comparison()

    def _comparison(self) -> Node:
        node = self._sum()
        if self._peek().text in ("==", "!=", "<", "<=", ">", ">="):
            op = self._advance().text
            node = Compare(op=op, left=node, right=self._sum())
        return node

    def _sum(self) -> Node:
        node = self._term()
        while self._peek().text in ("+", "-"):
            op = self._advance().text
            node = BinOp(op=op, left=node, right=self._term())
        return node

    def _term(self) -> Node:
        node = self._primary()
        while self._peek().text in ("*", "/"):
            op = self._advance().text
            node = BinOp(op=op, left=node, right=self._primary())
        return node

    def _primary(self) -> Node:
        tok = self._peek()
        if tok.kind == "NUMBER":
            self._advance()
            return Number(value=float(tok.text))
        if tok.kind == "STRING":
            self._advance()
            return String(value=tok.text)
        if tok.kind == "true":
            self._advance()
            return Bool(value=True)
        if tok.kind == "false":
            self._advance()
            return Bool(value=False)
        if tok.text == "(":
            self._advance()
            node = self._expr()
            if self._peek().text != ")":
                raise ExpressionError(f"{self._source!r}: unmatched '('")
            self._advance()
            return node
        if tok.text == "-":
            self._advance()
            return UnaryOp(op="-", operand=self._primary())
        if tok.kind == "IDENT":
            return self._call_or_selector()
        raise ExpressionError(f"{self._source!r}: unexpected token {tok.text!r}")

    def _call_or_selector(self) -> Node:
        name = self._advance().text
        if self._peek().text == "(":
            self._advance()
            args: list[Node] = []
            if self._peek().text != ")":
                args.append(self._expr())
                while self._peek().text == ",":
                    self._advance()
                    args.append(self._expr())
            if self._peek().text != ")":
                raise ExpressionError(f"{self._source!r}: unmatched '(' in call to {name!r}")
            self._advance()
            return Call(name=name, args=tuple(args))
        parts = [name]
        while self._peek().text == ".":
            self._advance()
            parts.append(self._expect("IDENT").text)
        return Selector(parts=tuple(parts))


def parse(source: str) -> Node:
    tokens = _tokenize(source)
    return _Parser(tokens, source).parse()


# =============================================================================
# Registries (design doc 04 section 1's tables — closed vocabularies)
# =============================================================================

# Bare-identifier selectors (no parens). "event" is intentionally absent —
# reaction scope (and event.* bindings) is Phase 5; referencing `event.x` in
# Phase 4 data fails validation like any other unknown selector, which is
# correct: Phase 4 genuinely has no scope that binds it.
SELECTOR_NAMES = frozenset({
    "self", "target", "it", "enemies", "allies",
    "enemies_grappled_by_self", "nearest_enemy", "ally_lowest_hp",
    # `allies` deliberately excludes the Down (battlefield.allies_of), so a
    # healer's "who needs raising" query needs its own selector.
    "downed_allies",
    # `enemies` likewise excludes the Down, so a "bind the helpless" ability
    # (the Guard Cartel Vise manacling a downed PC) needs its own.
    "downed_enemies",
})

# Call-syntax functions (design doc 04 section 1's function registry, v1).
FUNCTION_NAMES = frozenset({
    "count", "nearest", "farthest", "any", "all",
    "has_condition", "has_tag", "hp", "hp_pct", "is_bloodied", "is_down",
    "distance", "within", "can_see", "in_reach",
    "is_grappling", "is_grappled_by", "is_grappled",
    "resource_available", "round", "has_flag", "any_yet_to_act", "side_of",
    "enemies_within", "allies_within", "enemies_tagged", "allies_tagged",
    "enemies_within_of", "allies_within_of", "turn_marked", "aoe_targets",
    "temp_hp", "reaction_available", "is_source_of",
})


# =============================================================================
# Load-time validation
# =============================================================================


def validate(node: Node, *, where: str) -> None:
    """Walk the AST and confirm every selector/function name is registered.
    Raises ExpressionError naming `where` (the file/table the expression came
    from) on the first problem found."""
    if isinstance(node, (Number, String, Bool)):
        return
    if isinstance(node, Selector):
        root = node.parts[0]
        if len(node.parts) == 1:
            if root not in SELECTOR_NAMES:
                raise ExpressionError(f"{where}: unknown selector {root!r}")
        elif root != "event":
            raise ExpressionError(f"{where}: unknown selector root {root!r}")
        return
    if isinstance(node, Call):
        if node.name not in FUNCTION_NAMES:
            raise ExpressionError(f"{where}: unknown function {node.name!r}")
        for arg in node.args:
            validate(arg, where=where)
        return
    if isinstance(node, UnaryOp):
        validate(node.operand, where=where)
        return
    if isinstance(node, (BinOp, Compare)):
        validate(node.left, where=where)
        validate(node.right, where=where)
        return
    raise ExpressionError(f"{where}: unrecognized AST node {node!r}")  # pragma: no cover


def parse_and_validate(source: str, *, where: str) -> Node:
    node = parse(source)
    validate(node, where=where)
    return node


# =============================================================================
# Evaluation
# =============================================================================


@runtime_checkable
class Scope(Protocol):
    """What `behavior.py`'s concrete scope must provide. Creature values are
    opaque (`Any`) to this module — only the Scope interprets them."""

    def self_creature(self) -> Any: ...
    def target_creature(self) -> Optional[Any]: ...
    def it_creature(self) -> Optional[Any]: ...
    def event_field(self, name: str) -> Any: ...

    def enemies(self) -> Sequence[Any]: ...
    def allies(self) -> Sequence[Any]: ...
    def enemies_grappled_by_self(self) -> Sequence[Any]: ...
    def downed_allies(self) -> Sequence[Any]: ...
    def downed_enemies(self) -> Sequence[Any]: ...
    def enemies_within(self, ft: float) -> Sequence[Any]: ...
    def allies_within(self, ft: float) -> Sequence[Any]: ...
    def enemies_tagged(self, tag: str) -> Sequence[Any]: ...
    def allies_tagged(self, tag: str) -> Sequence[Any]: ...
    def enemies_within_of(self, who: Any, ft: float) -> Sequence[Any]: ...
    def allies_within_of(self, who: Any, ft: float) -> Sequence[Any]: ...
    def nearest_enemy(self) -> Optional[Any]: ...
    def ally_lowest_hp(self) -> Optional[Any]: ...

    def nearest(self, creatures: Sequence[Any]) -> Optional[Any]: ...
    def farthest(self, creatures: Sequence[Any]) -> Optional[Any]: ...
    def has_condition(self, who: Any, name: str) -> bool: ...
    def has_tag(self, who: Any, tag: str) -> bool: ...
    def hp(self, who: Any) -> float: ...
    def hp_pct(self, who: Any) -> float: ...
    def is_bloodied(self, who: Any) -> bool: ...
    def is_down(self, who: Any) -> bool: ...
    def distance(self, a: Any, b: Any) -> float: ...
    def can_see(self, a: Any, b: Any) -> bool: ...
    def in_reach(self, a: Any, b: Any) -> bool: ...
    def is_grappling(self, a: Any, b: Any) -> bool: ...
    def is_grappled_by(self, a: Any, b: Any) -> bool: ...
    def is_grappled(self, who: Any) -> bool: ...
    def resource_available(self, name: str) -> bool: ...
    def temp_hp(self, who: Any) -> float: ...
    def reaction_available(self, who: Any) -> bool: ...
    def is_source_of(self, condition: str) -> bool: ...
    def aoe_targets(self, ability_name: str) -> int: ...
    def round_number(self) -> int: ...
    def has_flag(self, name: str) -> bool: ...
    def turn_marked(self, key: str) -> bool: ...
    def any_yet_to_act(self, creatures: Sequence[Any]) -> bool: ...
    def side_of(self, who: Any) -> str: ...

    def with_it(self, creature: Any) -> "Scope":
        """Return a child scope with `it` rebound — used by any()/all()."""
        ...


def _truthy(value: Any) -> bool:
    if value is None:
        return False
    return bool(value)


def evaluate(node: Node, scope: Scope) -> Any:
    if isinstance(node, Number):
        return node.value
    if isinstance(node, String):
        return node.value
    if isinstance(node, Bool):
        return node.value
    if isinstance(node, Selector):
        return _eval_selector(node, scope)
    if isinstance(node, Call):
        return _eval_call(node, scope)
    if isinstance(node, UnaryOp):
        if node.op == "not":
            return not _truthy(evaluate(node.operand, scope))
        if node.op == "-":
            return -evaluate(node.operand, scope)
        raise ExpressionError(f"unknown unary operator {node.op!r}")  # pragma: no cover
    if isinstance(node, BinOp):
        return _eval_binop(node, scope)
    if isinstance(node, Compare):
        return _eval_compare(node, scope)
    raise ExpressionError(f"cannot evaluate node {node!r}")  # pragma: no cover


def _eval_selector(node: Selector, scope: Scope) -> Any:
    root = node.parts[0]
    if len(node.parts) > 1:
        if root != "event":
            raise ExpressionError(f"unknown selector root {root!r}")  # pragma: no cover (validated at load)
        return scope.event_field(node.parts[1])
    if root == "self":
        return scope.self_creature()
    if root == "target":
        return scope.target_creature()
    if root == "it":
        return scope.it_creature()
    if root == "enemies":
        return scope.enemies()
    if root == "allies":
        return scope.allies()
    if root == "enemies_grappled_by_self":
        return scope.enemies_grappled_by_self()
    if root == "downed_allies":
        return scope.downed_allies()
    if root == "downed_enemies":
        return scope.downed_enemies()
    if root == "nearest_enemy":
        return scope.nearest_enemy()
    if root == "ally_lowest_hp":
        return scope.ally_lowest_hp()
    raise ExpressionError(f"unknown selector {root!r}")  # pragma: no cover (validated at load)


def _eval_binop(node: BinOp, scope: Scope) -> Any:
    if node.op == "and":
        left = evaluate(node.left, scope)
        return left if not _truthy(left) else evaluate(node.right, scope)
    if node.op == "or":
        left = evaluate(node.left, scope)
        return left if _truthy(left) else evaluate(node.right, scope)
    left = evaluate(node.left, scope)
    right = evaluate(node.right, scope)
    if node.op == "+":
        return left + right
    if node.op == "-":
        return left - right
    if node.op == "*":
        return left * right
    if node.op == "/":
        return left / right
    raise ExpressionError(f"unknown binary operator {node.op!r}")  # pragma: no cover


def _eval_compare(node: Compare, scope: Scope) -> bool:
    left = evaluate(node.left, scope)
    right = evaluate(node.right, scope)
    if node.op == "==":
        return left == right
    if node.op == "!=":
        return left != right
    if node.op == "<":
        return left < right
    if node.op == "<=":
        return left <= right
    if node.op == ">":
        return left > right
    if node.op == ">=":
        return left >= right
    raise ExpressionError(f"unknown comparison operator {node.op!r}")  # pragma: no cover


def _eval_call(node: Call, scope: Scope) -> Any:
    # any()/all() are special: their 2nd argument is a predicate evaluated
    # once per element with `it` rebound, so it must NOT be eagerly evaluated
    # like every other function's arguments.
    if node.name in ("any", "all"):
        creatures = evaluate(node.args[0], scope)
        predicate = node.args[1]
        results = (_truthy(evaluate(predicate, scope.with_it(c))) for c in creatures)
        return any(results) if node.name == "any" else all(results)

    args = [evaluate(a, scope) for a in node.args]
    fn = _CALL_TABLE.get(node.name)
    if fn is None:
        raise ExpressionError(f"unknown function {node.name!r}")  # pragma: no cover (validated at load)
    return fn(scope, *args)


_CALL_TABLE: dict[str, Callable[..., Any]] = {
    "count": lambda scope, s: len(s),
    "nearest": lambda scope, s: scope.nearest(s),
    "farthest": lambda scope, s: scope.farthest(s),
    "has_condition": lambda scope, who, name: scope.has_condition(who, name),
    "has_tag": lambda scope, who, tag: scope.has_tag(who, tag),
    "hp": lambda scope, who: scope.hp(who),
    "hp_pct": lambda scope, who: scope.hp_pct(who),
    "is_bloodied": lambda scope, who: scope.is_bloodied(who),
    "is_down": lambda scope, who: scope.is_down(who),
    "temp_hp": lambda scope, who: scope.temp_hp(who),
    "reaction_available": lambda scope, who: scope.reaction_available(who),
    "is_source_of": lambda scope, name: scope.is_source_of(name),
    "distance": lambda scope, a, b: scope.distance(a, b),
    "within": lambda scope, who, ft: scope.distance(scope.self_creature(), who) <= ft,
    "can_see": lambda scope, a, b: scope.can_see(a, b),
    "in_reach": lambda scope, a, b: scope.in_reach(a, b),
    "is_grappling": lambda scope, a, b: scope.is_grappling(a, b),
    "is_grappled_by": lambda scope, a, b: scope.is_grappled_by(a, b),
    "is_grappled": lambda scope, who: scope.is_grappled(who),
    "resource_available": lambda scope, name: scope.resource_available(name),
    "aoe_targets": lambda scope, name: scope.aoe_targets(name),
    "round": lambda scope: scope.round_number(),
    "has_flag": lambda scope, name: scope.has_flag(name),
    "turn_marked": lambda scope, key: scope.turn_marked(key),
    "any_yet_to_act": lambda scope, s: scope.any_yet_to_act(s),
    "side_of": lambda scope, who: scope.side_of(who),
    "enemies_within": lambda scope, ft: scope.enemies_within(ft),
    "allies_within": lambda scope, ft: scope.allies_within(ft),
    "enemies_tagged": lambda scope, tag: scope.enemies_tagged(tag),
    "allies_tagged": lambda scope, tag: scope.allies_tagged(tag),
    "enemies_within_of": lambda scope, who, ft: scope.enemies_within_of(who, ft),
    "allies_within_of": lambda scope, who, ft: scope.allies_within_of(who, ft),
}
