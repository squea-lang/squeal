"""Фронтенд: Python AST → IR.

Стоковый ``ast.parse`` из CPython 3.15; ``compile()`` не вызывается, чтобы
питоновские проверки не мешали семантике squeal (см. architecture.md).

Атомы и строки различаются по кавычкам исходника: ``'ok'`` (одинарные) — атом,
``"ok"`` (двойные) — строка. Списки и кортежи в match-образцах различаются по
скобкам. ``ast`` ни то, ни другое не хранит, поэтому фронтенд снимает их токенизатором.
"""

from __future__ import annotations

import ast
import io
import tokenize

from . import ir
from .errors import SquealError

_BINOP = {
    ast.Add: "Add",
    ast.Sub: "Sub",
    ast.Mult: "Mult",
    ast.Div: "Div",
    ast.FloorDiv: "FloorDiv",
    ast.Mod: "Mod",
    ast.Pow: "Pow",
}
_CMP = {
    ast.Eq: "Eq",
    ast.NotEq: "NotEq",
    ast.Lt: "Lt",
    ast.LtE: "LtE",
    ast.Gt: "Gt",
    ast.GtE: "GtE",
}
_BOOL = {ast.And: "And", ast.Or: "Or"}
_UNARY = {ast.USub: "USub", ast.UAdd: "UAdd", ast.Not: "Not"}


def snake_case(name: str) -> str:
    """Точный порт ``to_snake_case`` у Gleam: ``CustomType`` → ``custom_type``."""
    out = []
    boundary = True
    for ch in name:
        if ch in "_ ":
            boundary = True
            continue
        if ch.isupper():
            boundary = True
        if boundary:
            if out:
                out.append("_")
            boundary = False
        out.append(ch.lower())
    return "".join(out)


def parse_module(source: str, path: str, name: str) -> ir.Module:
    toks = _token_chars(source)
    tree = ast.parse(source)
    classes = _collect_classes(tree)
    imports = _collect_imports(tree)

    functions = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            functions.append(_function(node, toks, classes))
        elif isinstance(node, (ast.ClassDef, ast.Import, ast.ImportFrom)):
            continue  # класс/импорт — только резолвинг имён
        else:
            raise SquealError(
                f"{path}:{node.lineno}: на верхнем уровне допустимы def/class/from…import"
            )
    return ir.Module(name=name, path=path, functions=tuple(functions), imports=imports)


def _collect_imports(tree: ast.Module) -> dict:
    """`from a.b.c import f, g` → {f: 'a@b@c', g: 'a@b@c'}."""
    imports = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if node.level != 0:
                raise SquealError(f"{node.lineno}: относительные импорты не поддержаны")
            if not node.module:
                raise SquealError(f"{node.lineno}: безымянный import")
            for alias in node.names:
                if alias.name == "*":
                    raise SquealError(f"{node.lineno}: import * не поддержан")
                imports[alias.asname or alias.name] = (
                    node.module.replace(".", "@"),
                    alias.name,
                )
        elif isinstance(node, ast.Import):
            raise SquealError(f"{node.lineno}: import X — только from X import …")
    return imports


def _collect_classes(tree: ast.Module) -> dict:
    classes = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            fields = _class_fields(node)
            base = _base_name(node)
            if base != "StartingWithAtom":
                raise SquealError(
                    f"{node.lineno}: базовый класс {base!r} — поддержан только "
                    "StartingWithAtom (NativeRecord/Map — позже)"
                )
            if node.name in classes:
                raise SquealError(f"{node.lineno}: повторное определение класса {node.name}")
            classes[node.name] = fields
    return classes


def _class_fields(node: ast.ClassDef) -> tuple:
    fields = []
    for stmt in node.body:
        if isinstance(stmt, ast.AnnAssign):
            if stmt.value is not None:
                raise SquealError(f"{stmt.lineno}: поле класса — только аннотация без значения")
            if not isinstance(stmt.target, ast.Name):
                raise SquealError(f"{stmt.lineno}: поле класса — только имя")
            fields.append(stmt.target.id)
        else:
            raise SquealError(
                f"{stmt.lineno}: в теле класса — только аннотации полей "
                f"(не {type(stmt).__name__})"
            )
    return tuple(fields)


def _base_name(node: ast.ClassDef) -> str:
    if not node.bases:
        raise SquealError(f"{node.lineno}: классу нужен базовый класс (StartingWithAtom)")
    if len(node.bases) != 1 or not isinstance(node.bases[0], ast.Name):
        raise SquealError(f"{node.lineno}: ровно один базовый класс-имя")
    return node.bases[0].id


def _token_chars(source: str) -> dict:
    """(строка, колонка) → символ: кавычка строки ('/\") или скобка ([/(/{)."""
    chars = {}
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.STRING:
            s = tok.string
            i = 0
            while i < len(s) and s[i] in "rRbBuUfF":
                i += 1
            if i < len(s):
                chars[(tok.start[0], tok.start[1])] = s[i]
        elif tok.type == tokenize.OP and tok.string in "([{":
            chars[(tok.start[0], tok.start[1])] = tok.string
    return chars


def _function(node: ast.FunctionDef, toks: dict, classes: dict) -> ir.Function:
    a = node.args
    if a.posonlyargs or a.kwonlyargs or a.vararg or a.kwarg or a.defaults:
        raise SquealError(
            f"{node.lineno}: параметры со значениями/vararg пока не поддерживаются"
        )
    params = tuple(arg.arg for arg in a.args)
    statements = _statements(node.body, toks, classes)
    if not statements:
        raise SquealError(f"{node.lineno}: функция {node.name} без значения")
    return ir.Function(name=node.name, params=params, statements=statements, line=node.lineno)


def _statements(body: list, toks: dict, classes: dict) -> tuple:
    out = []
    for stmt in body:
        s = _statement(stmt, toks, classes)
        if s is not None:
            out.append(s)
    return tuple(out)


def _statement(node: ast.stmt, toks: dict, classes: dict):
    if isinstance(node, ast.Assign):
        if len(node.targets) != 1:
            raise SquealError(f"{node.lineno}: цепочное присваивание a = b = … не поддержано")
        return ir.Assign(
            target=_target(node.targets[0]),
            value=_expr(node.value, toks, classes),
            line=node.lineno,
        )
    if isinstance(node, ast.AnnAssign):
        if node.value is None:
            raise SquealError(f"{node.lineno}: аннотация без значения не поддержана")
        if not isinstance(node.target, ast.Name):
            raise SquealError(f"{node.lineno}: аннотация только для имени")
        return ir.Assign(
            target=ir.PName(node.target.id, node.target.lineno),
            value=_expr(node.value, toks, classes),
            line=node.lineno,
        )
    if isinstance(node, ast.AugAssign):
        if isinstance(node.op, ast.BitOr):
            if not isinstance(node.target, ast.Name):
                raise SquealError(f"{node.lineno}: |= только для имени")
            return ir.Assign(
                target=ir.PName(node.target.id, node.target.lineno),
                value=ir.Merge(
                    left=ir.Var(node.target.id, node.target.lineno),
                    right=_expr(node.value, toks, classes),
                    line=node.lineno,
                ),
                line=node.lineno,
            )
        raise SquealError(
            f"{node.lineno}: мутирующее присваивание {type(node.op).__name__} не поддержано"
        )
    if isinstance(node, ast.Expr):
        return ir.Expr(value=_expr(node.value, toks, classes), line=node.lineno)
    if isinstance(node, ast.Return):
        return ir.Expr(value=_expr(node.value, toks, classes), line=node.lineno)
    if isinstance(node, ast.Pass):
        return None
    if isinstance(node, ast.If):
        else_body = _statements(node.orelse, toks, classes)
        if not else_body:
            raise SquealError(f"{node.lineno}: if без else — нет значения на ложном пути")
        return ir.If(
            condition=_expr(node.test, toks, classes),
            then_body=_statements(node.body, toks, classes),
            else_body=else_body,
            line=node.lineno,
        )
    if isinstance(node, ast.Match):
        cases = []
        for c in node.cases:
            cases.append(
                ir.Case(
                    pattern=_match_pattern(c.pattern, toks, classes),
                    guard=_expr(c.guard, toks, classes) if c.guard else None,
                    body=_statements(c.body, toks, classes),
                    line=c.pattern.lineno,
                )
            )
        return ir.Match(
            subject=_expr(node.subject, toks, classes),
            cases=tuple(cases),
            line=node.lineno,
        )
    if isinstance(node, (ast.For, ast.While)):
        raise SquealError(f"{node.lineno}: цикл {type(node).__name__} запрещён — squeal без мутаций")
    if isinstance(node, ast.Delete):
        raise SquealError(f"{node.lineno}: del запрещён")
    raise SquealError(f"{node.lineno}: оператор {type(node).__name__} не поддержан")


def _target(node: ast.AST) -> object:
    if isinstance(node, ast.Name):
        return ir.PName(node.id, node.lineno)
    if isinstance(node, ast.Tuple):
        items = tuple(_target_elt(e) for e in node.elts)
    elif isinstance(node, ast.List):
        items = tuple(_target_elt(e) for e in node.elts)
    else:
        raise SquealError(f"{node.lineno}: цель присваивания не поддержана (индекс/атрибут)")

    stars = [i for i, it in enumerate(items) if isinstance(it, ir.PStar)]
    if stars:
        if len(stars) != 1 or stars[0] != len(items) - 1:
            raise SquealError(f"{node.lineno}: звезда только одна и в конце образца")
        return ir.PList(items=items, line=node.lineno)
    if isinstance(node, ast.Tuple):
        return ir.PTuple(items=items, line=node.lineno)
    return ir.PList(items=items, line=node.lineno)


def _target_elt(node: ast.AST) -> object:
    if isinstance(node, ast.Starred):
        if not isinstance(node.value, ast.Name):
            raise SquealError(f"{node.lineno}: звезда только для имени")
        return ir.PStar(node.value.id, node.lineno)
    return _target(node)


def _match_pattern(node: ast.AST, toks: dict, classes: dict) -> object:
    if isinstance(node, ast.MatchValue):
        return _expr(node.value, toks, classes)
    if isinstance(node, ast.MatchSingleton):
        if node.value is None:
            return ir.Nil(node.lineno)
        return ir.Bool(value=node.value, line=node.lineno)
    if isinstance(node, ast.MatchAs):
        if node.name is None:
            return ir.Wildcard(node.lineno)
        if node.pattern is not None:
            raise SquealError(f"{node.lineno}: as-образец не поддержан")
        return ir.PName(node.name, node.lineno)
    if isinstance(node, ast.MatchStar):
        return ir.PStar(node.name, node.lineno)
    if isinstance(node, ast.MatchOr):
        return ir.OrPattern(
            patterns=tuple(_match_pattern(p, toks, classes) for p in node.patterns),
            line=node.lineno,
        )
    if isinstance(node, ast.MatchSequence):
        bracket = toks.get((node.lineno, node.col_offset), "(")  # `1, 2` — кортеж
        items = tuple(_match_pattern(p, toks, classes) for p in node.patterns)
        if bracket == "[":
            return ir.PList(items=items, line=node.lineno)
        return ir.PTuple(items=items, line=node.lineno)
    if isinstance(node, ast.MatchMapping):
        keys = tuple(_expr(k, toks, classes) for k in node.keys)
        pats = tuple(_match_pattern(p, toks, classes) for p in node.patterns)
        return ir.PMap(items=tuple(zip(keys, pats)), line=node.lineno)
    if isinstance(node, ast.MatchClass):
        if not isinstance(node.cls, ast.Name) or node.cls.id not in classes:
            raise SquealError(f"{node.lineno}: класс-образец только для классов squeal")
        if node.kwd_patterns:
            raise SquealError(f"{node.lineno}: именованные поля в класс-образце не поддержаны")
        fields = classes[node.cls.id]
        if len(node.patterns) != len(fields):
            raise SquealError(
                f"{node.lineno}: образец {node.cls.id} ожидает {len(fields)} полей, "
                f"получено {len(node.patterns)}"
            )
        tag = snake_case(node.cls.id)
        items = (ir.AtomLit(tag, node.lineno),) + tuple(
            _match_pattern(p, toks, classes) for p in node.patterns
        )
        return ir.PTuple(items=items, line=node.lineno)
    raise SquealError(f"{node.lineno}: образец {type(node).__name__} не поддержан")


def _expr(node: ast.AST, toks: dict, classes: dict) -> object:
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bool):
            return ir.Bool(value=v, line=node.lineno)
        if isinstance(v, int):
            return ir.Int(value=v, line=node.lineno)
        if isinstance(v, float):
            return ir.Float(value=v, line=node.lineno)
        if v is None:
            return ir.Nil(line=node.lineno)
        if isinstance(v, str):
            q = toks.get((node.lineno, node.col_offset), '"')
            if q == "'":
                return ir.AtomLit(name=v, line=node.lineno)
            return ir.String(value=v, line=node.lineno)
        raise SquealError(f"{node.lineno}: неподдерживаемый литерал {v!r}")

    if isinstance(node, ast.Name):
        return ir.Var(name=node.id, line=node.lineno)
    if isinstance(node, ast.Tuple):
        return ir.Tuple(
            items=tuple(_expr(e, toks, classes) for e in node.elts), line=node.lineno
        )
    if isinstance(node, ast.List):
        return ir.List(
            items=tuple(_expr(e, toks, classes) for e in node.elts), line=node.lineno
        )
    if isinstance(node, ast.Dict):
        keys = tuple(_expr(k, toks, classes) for k in node.keys)
        values = tuple(_expr(v, toks, classes) for v in node.values)
        return ir.Dict(items=tuple(zip(keys, values)), line=node.lineno)

    if isinstance(node, ast.UnaryOp):
        op = _UNARY.get(type(node.op))
        if op is None:
            raise SquealError(f"{node.lineno}: оператор {type(node.op).__name__} не поддержан")
        return ir.UnaryOp(
            op=op, operand=_expr(node.operand, toks, classes), line=node.lineno
        )

    if isinstance(node, ast.BinOp):
        op = _BINOP.get(type(node.op))
        if op is None:
            raise SquealError(
                f"{node.lineno}: оператор {type(node.op).__name__} не поддержан"
            )
        return ir.BinOp(
            op=op,
            left=_expr(node.left, toks, classes),
            right=_expr(node.right, toks, classes),
            line=node.lineno,
        )

    if isinstance(node, ast.BoolOp):
        op = _BOOL.get(type(node.op))
        if op is None:
            raise SquealError(f"{node.lineno}: логический оператор не поддержан")
        return ir.BoolOp(
            op=op,
            operands=tuple(_expr(v, toks, classes) for v in node.values),
            line=node.lineno,
        )

    if isinstance(node, ast.Compare):
        if len(node.ops) != 1:
            raise SquealError(f"{node.lineno}: цепочки сравнений пока не поддержаны")
        op = _CMP.get(type(node.ops[0]))
        if op is None:
            raise SquealError(f"{node.lineno}: оператор сравнения (is/in/…) не поддержан")
        return ir.BinOp(
            op=op,
            left=_expr(node.left, toks, classes),
            right=_expr(node.comparators[0], toks, classes),
            line=node.lineno,
        )

    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute):
            if node.func.attr != "items" or node.args or node.keywords:
                raise SquealError(
                    f"{node.lineno}: метод {node.func.attr!r} не поддержан (только .items())"
                )
            return ir.Items(
                receiver=_expr(node.func.value, toks, classes), line=node.lineno
            )
        if isinstance(node.func, ast.Name) and node.func.id in classes:
            if node.keywords:
                raise SquealError(f"{node.lineno}: именованные аргументы конструктора не поддержаны")
            fields = classes[node.func.id]
            if len(node.args) != len(fields):
                raise SquealError(
                    f"{node.lineno}: конструктор {node.func.id} ожидает {len(fields)} аргументов, "
                    f"получено {len(node.args)}"
                )
            tag = snake_case(node.func.id)
            return ir.Tuple(
                items=(ir.AtomLit(tag, node.lineno),)
                + tuple(_expr(a, toks, classes) for a in node.args),
                line=node.lineno,
            )
        if not isinstance(node.func, ast.Name):
            raise SquealError(f"{node.lineno}: вызов по атрибуту не поддержан")
        if node.keywords:
            raise SquealError(f"{node.lineno}: именованные аргументы не поддержаны")
        return ir.Call(
            name=node.func.id,
            args=tuple(_expr(a, toks, classes) for a in node.args),
            line=node.lineno,
        )

    if isinstance(node, ast.Lambda):
        a = node.args
        if a.posonlyargs or a.kwonlyargs or a.vararg or a.kwarg or a.defaults:
            raise SquealError(f"{node.lineno}: параметры лямбды со значениями не поддержаны")
        return ir.Lambda(
            params=tuple(arg.arg for arg in a.args),
            body=_expr(node.body, toks, classes),
            line=node.lineno,
        )

    if isinstance(node, ast.ListComp):
        return ir.ListComp(
            element=_expr(node.elt, toks, classes),
            qualifiers=_comprehensions(node.generators, toks, classes),
            line=node.lineno,
        )
    if isinstance(node, ast.DictComp):
        return ir.DictComp(
            key=_expr(node.key, toks, classes),
            value=_expr(node.value, toks, classes),
            qualifiers=_comprehensions(node.generators, toks, classes),
            line=node.lineno,
        )
    if isinstance(node, ast.SetComp):
        raise SquealError(f"{node.lineno}: множеств в squeal нет — set comprehension не поддержан")
    if isinstance(node, ast.GeneratorExp):
        raise SquealError(f"{node.lineno}: generator-выражения позже")

    raise SquealError(f"{node.lineno}: неподдерживаемое выражение {type(node).__name__}")


def _is_items_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "items"
        and not node.args
        and not node.keywords
    )


def _comprehensions(generators: list, toks: dict, classes: dict) -> tuple:
    quals = []
    for c in generators:
        if c.is_async:
            raise SquealError(f"{c.target.lineno}: async-генератор не поддержан")
        target = _target(c.target)
        if (
            _is_items_call(c.iter)
            and isinstance(c.iter.func.value, ast.Name)
            and isinstance(target, ir.PTuple)
            and len(target.items) == 2
            and all(isinstance(i, ir.PName) for i in target.items)
        ):
            recv = c.iter.func.value
            quals.append(
                ir.MapGen(
                    key=target.items[0],
                    value=target.items[1],
                    map=ir.Var(recv.id, c.iter.lineno),
                    line=c.target.lineno,
                )
            )
        else:
            quals.append(
                ir.Gen(
                    target=target,
                    iter=_expr(c.iter, toks, classes),
                    line=c.target.lineno,
                )
            )
        for f in c.ifs:
            quals.append(ir.Filter(expr=_expr(f, toks, classes), line=f.lineno))
    return tuple(quals)
