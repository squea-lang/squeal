"""Промежуточное представление squeal.

Соответствует слою ``TypedExpr``/``TypedModule`` у Gleam, но без типов
(см. architecture.md). Узлы несут строку ``.ee``, которую бэкенд кладёт в
аннотацию Erlang-формы.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# --- выражения ---


@dataclass(frozen=True)
class Int:
    value: int
    line: int


@dataclass(frozen=True)
class Float:
    value: float
    line: int


@dataclass(frozen=True)
class String:
    value: str
    line: int


@dataclass(frozen=True)
class AtomLit:
    name: str
    line: int


@dataclass(frozen=True)
class Bool:
    value: bool
    line: int


@dataclass(frozen=True)
class Nil:
    line: int


@dataclass(frozen=True)
class Var:
    name: str
    line: int


@dataclass(frozen=True)
class Tuple:
    items: tuple
    line: int


@dataclass(frozen=True)
class List:
    items: tuple
    line: int


@dataclass(frozen=True)
class Dict:
    items: tuple  # ((key, value), ...)
    line: int


@dataclass(frozen=True)
class UnaryOp:
    op: str  # USub | UAdd | Not
    operand: object
    line: int


@dataclass(frozen=True)
class BinOp:
    op: str  # Add|Sub|Mult|Div|FloorDiv|Mod|Pow|Eq|NotEq|Lt|LtE|Gt|GtE
    left: object
    right: object
    line: int


@dataclass(frozen=True)
class BoolOp:
    op: str  # And | Or
    operands: tuple
    line: int


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple
    line: int


@dataclass(frozen=True)
class FunRef:
    """Голое name в позиции декоратора → `fun name/1`."""

    name: str
    line: int


@dataclass(frozen=True)
class RemoteFunRef:
    """`mod.name` в позиции декоратора → `fun mod:name/1`."""

    module: str
    name: str
    line: int


@dataclass(frozen=True)
class RemoteCall:
    """`mod.name(args)` — прямой вызов Erlang-модуля (декораторы)."""

    module: str
    name: str
    args: tuple
    line: int


@dataclass(frozen=True)
class Merge:
    """``m |= d`` — слияние map."""

    left: object
    right: object
    line: int


# --- образцы ветвлений ---


@dataclass(frozen=True)
class Wildcard:
    line: int


@dataclass(frozen=True)
class OrPattern:
    patterns: tuple
    line: int


@dataclass(frozen=True)
class PMap:
    items: tuple  # ((key_expr, subpattern), ...)
    line: int


@dataclass(frozen=True)
class If:
    condition: object
    then_body: tuple  # операторы
    else_body: tuple
    line: int


@dataclass(frozen=True)
class Case:
    pattern: object
    guard: object  # выражение или None
    body: tuple
    line: int


@dataclass(frozen=True)
class Match:
    subject: object
    cases: tuple  # (Case, ...)
    line: int


# --- лямбды и включения ---


@dataclass(frozen=True)
class Lambda:
    params: tuple
    body: object
    line: int


@dataclass(frozen=True)
class Def:
    """`def f(x): …` в shell-режиме → fun-значение `F`."""

    name: str
    params: tuple
    statements: tuple  # тело (операторы)
    line: int
    decorators: tuple = ()


@dataclass(frozen=True)
class NestedDef:
    """`def f(x): …` внутри тела — вложенная функция: fun, привязанный к имени."""

    name: str
    params: tuple
    statements: tuple
    line: int
    decorators: tuple = ()


@dataclass(frozen=True)
class Print:
    """``print(x)`` — встроенная печать в stdout, возвращает nil."""

    value: object
    line: int


@dataclass(frozen=True)
class Method:
    """Вызов метода стандартной библиотеки: `recv.name(args)`."""

    receiver: object
    name: str
    args: tuple
    line: int


@dataclass(frozen=True)
class Gen:
    target: object  # образец
    iter: object
    line: int


@dataclass(frozen=True)
class MapGen:
    """``for k, v in m.items()`` — map-генератор ``K := V <- M``."""

    key: object
    value: object
    map: object
    line: int


@dataclass(frozen=True)
class Filter:
    expr: object
    line: int


@dataclass(frozen=True)
class ListComp:
    element: object
    qualifiers: tuple  # (Gen | MapGen | Filter, ...)
    line: int


@dataclass(frozen=True)
class DictComp:
    key: object
    value: object
    qualifiers: tuple
    line: int


# --- образцы присваивания ---


@dataclass(frozen=True)
class PName:
    name: str
    line: int


@dataclass(frozen=True)
class PStar:
    name: str
    line: int


@dataclass(frozen=True)
class PList:
    items: tuple  # PName | PStar (звезда — только последняя)
    line: int


@dataclass(frozen=True)
class PTuple:
    items: tuple  # PName
    line: int


# --- операторы ---


@dataclass(frozen=True)
class Assign:
    target: object  # PName | PList | PTuple
    value: object
    line: int


@dataclass(frozen=True)
class Expr:
    """Выражение-оператор: значение последнего — результат функции."""

    value: object
    line: int


@dataclass(frozen=True)
class Function:
    name: str
    params: tuple
    statements: tuple  # (Assign | Expr, ...)
    line: int
    decorators: tuple = ()


@dataclass(frozen=True)
class Module:
    name: str
    path: str
    functions: tuple
    imports: dict = field(default_factory=dict)
