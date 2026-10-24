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
import keyword
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

# Встроенные конструкторы (прелюдия как у Gleam): Result = Ok(a) | Error(e).
BUILTIN_CLASSES = {"Ok": ("value",), "Error": ("value",)}

# Маркер присваивания с образцом: `Ctor(args) = expr` переписывается в
# `__pattern_match__(Ctor(args), expr)`, потому что CPython не принимает call-цель.
PATTERN_MARKER = "__pattern_match__"


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
    source = rewrite_pattern_assignments(source)
    toks = _source_chars(source)
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
                f"{path}:{node.lineno}: only def/class/from…import are allowed at the top level"
            )
    return ir.Module(name=name, path=path, functions=tuple(functions), imports=imports)


def _collect_imports(tree: ast.Module) -> dict:
    """`from a.b.c import f, g` → {f: 'a@b@c', g: 'a@b@c'}."""
    imports = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if node.level != 0:
                raise SquealError(f"{node.lineno}: relative imports are not supported")
            if not node.module:
                raise SquealError(f"{node.lineno}: import without a module name")
            for alias in node.names:
                if alias.name == "*":
                    raise SquealError(f"{node.lineno}: import * is not supported")
                imports[alias.asname or alias.name] = (
                    node.module.replace(".", "@"),
                    alias.name,
                )
        elif isinstance(node, ast.Import):
            raise SquealError(f"{node.lineno}: plain import X is not supported — use from X import …")
    return imports


def _collect_classes(tree: ast.Module) -> dict:
    classes = dict(BUILTIN_CLASSES)
    tags = {snake_case(name): name for name in BUILTIN_CLASSES}
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if node.decorator_list:
                raise SquealError(
                f"{node.lineno}: decorators are only supported on functions"
            )
            fields = _class_fields(node)
            base = _base_name(node)
            if base != "StartingWithAtom":
                raise SquealError(
                    f"{node.lineno}: base class {base!r} is not supported — only "
                    "StartingWithAtom (NativeRecord/Map come later)"
                )
            if node.name in classes:
                raise SquealError(f"{node.lineno}: duplicate definition of class {node.name}")
            tag = snake_case(node.name)
            if tag in tags and tags[tag] != node.name:
                raise SquealError(
                    f"{node.lineno}: classes {node.name} and {tags[tag]} produce the same tag {tag!r}"
                )
            tags[tag] = node.name
            classes[node.name] = fields
    return classes


def _class_fields(node: ast.ClassDef) -> tuple:
    fields = []
    for stmt in node.body:
        if isinstance(stmt, ast.AnnAssign):
            if stmt.value is not None:
                raise SquealError(f"{stmt.lineno}: a class field must be an annotation without a value")
            if not isinstance(stmt.target, ast.Name):
                raise SquealError(f"{stmt.lineno}: a class field must be a name")
            fields.append(stmt.target.id)
        else:
            raise SquealError(
                f"{stmt.lineno}: class body allows only field annotations "
                f"(not {type(stmt).__name__})"
            )
    return tuple(fields)


def _base_name(node: ast.ClassDef) -> str:
    if not node.bases:
        raise SquealError(f"{node.lineno}: a class needs a base class (StartingWithAtom)")
    if len(node.bases) != 1 or not isinstance(node.bases[0], ast.Name):
        raise SquealError(f"{node.lineno}: exactly one base class name")
    return node.bases[0].id


def rewrite_pattern_assignments(source: str) -> str:
    """`Ctor(args) = expr` → `__pattern_match__(Ctor(args), expr)`.

    CPython не принимает call-цель присваивания, поэтому образцы в позиции
    присваивания переписываются в вызов-маркер. Число строк сохраняется.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError):
        return source

    lines = source.splitlines(keepends=True)
    starts, acc = [], 0
    for line in lines:
        starts.append(acc)
        acc += len(line)

    def offset(pos):
        row, col = pos
        return (starts[row - 1] if 0 < row <= len(starts) else len(source)) + col

    def ranges():
        start = 0
        for i, t in enumerate(tokens):
            if t.type == tokenize.NEWLINE:
                yield start, i
                start = i + 1
        yield start, len(tokens)

    edits = []
    for beg, end in ranges():
        stmt = [t for t in tokens[beg:end] if t.type not in (
            tokenize.NL, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT)]
        if len(stmt) < 5 or stmt[0].type != tokenize.NAME:
            continue
        if keyword.iskeyword(stmt[0].string) or stmt[1].string != "(":
            continue
        depth, close = 0, None
        for j in range(1, len(stmt)):
            if stmt[j].string in "([{":
                depth += 1
            elif stmt[j].string in ")]}":
                depth -= 1
                if depth == 0:
                    close = j
                    break
        if close is None or close + 1 >= len(stmt) or stmt[close + 1].string != "=":
            continue
        start_off = offset(stmt[0].start)
        end_off = offset(stmt[-1].end)
        eq_off = offset(stmt[close + 1].start)
        lhs = source[start_off:eq_off].rstrip()
        rhs = source[eq_off + 1:end_off].strip()
        edits.append((start_off, end_off, f"{PATTERN_MARKER}({lhs}, {rhs})"))

    for start_off, end_off, replacement in reversed(edits):
        source = source[:start_off] + replacement + source[end_off:]
    return source


def _as_pattern_assign(node: ast.AST, toks: dict, classes: dict):
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == PATTERN_MARKER
        and len(node.args) == 2
        and not node.keywords
    ):
        return None
    target = _expr_to_pattern(node.args[0], toks, classes)
    _check_pattern_names(target)
    return ir.Assign(
        target=target,
        value=_expr(node.args[1], toks, classes),
        line=node.lineno,
    )


def _check_pattern_names(pat, seen=None) -> set:
    """Повтор имени в одном образце — ошибка (иначе Erlang молча сравнил бы разные переменные)."""
    if seen is None:
        seen = set()
    if isinstance(pat, (ir.PName, ir.PStar)):
        if pat.name in seen:
            raise SquealError(f"{pat.line}: duplicate name {pat.name!r} in a pattern")
        seen.add(pat.name)
    elif isinstance(pat, (ir.PList, ir.PTuple)):
        for item in pat.items:
            _check_pattern_names(item, seen)
    elif isinstance(pat, ir.PMap):
        for _, sub in pat.items:
            _check_pattern_names(sub, seen)
    return seen


def _expr_to_pattern(node: ast.AST, toks: dict, classes: dict):
    if isinstance(node, ast.Name):
        return ir.Wildcard(node.lineno) if node.id == "_" else ir.PName(node.id, node.lineno)
    if isinstance(node, ast.Starred):
        if not isinstance(node.value, ast.Name):
            raise SquealError(f"{node.lineno}: star is only allowed for a name")
        return ir.PStar(node.value.id, node.lineno)
    if isinstance(node, ast.Tuple):
        return ir.PTuple(
            tuple(_expr_to_pattern(e, toks, classes) for e in node.elts), node.lineno
        )
    if isinstance(node, ast.List):
        return ir.PList(
            tuple(_expr_to_pattern(e, toks, classes) for e in node.elts), node.lineno
        )
    if isinstance(node, ast.Constant):
        return _expr(node, toks, classes)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in classes:
            raise SquealError(
                f"{node.lineno}: a pattern in a call assignment must be a squeal class constructor"
            )
        if node.keywords:
            raise SquealError(f"{node.lineno}: named fields in a pattern are not supported")
        fields = classes[node.func.id]
        if len(node.args) != len(fields):
            raise SquealError(
                f"{node.lineno}: constructor {node.func.id} expects {len(fields)} arguments, "
                f"got {len(node.args)}"
            )
        tag = snake_case(node.func.id)
        return ir.PTuple(
            (ir.AtomLit(tag, node.lineno),)
            + tuple(_expr_to_pattern(a, toks, classes) for a in node.args),
            node.lineno,
        )
    raise SquealError(f"{node.lineno}: unsupported assignment pattern: {type(node).__name__}")


class _SourceChars:
    """Символ исходника в позиции узла: кавычка строки (`'`/`"`) или скобка (`[`/`(`/`{`).

    Позиция AST (`col_offset`) — байтовое смещение UTF-8, поэтому индекс берём по байтам.
    """

    def __init__(self, source: str):
        self.lines = source.splitlines(keepends=True)

    def get(self, pos, default=None):
        row, col = pos
        if not 0 < row <= len(self.lines):
            return default
        line = self.lines[row - 1].encode("utf-8")
        return chr(line[col]) if 0 <= col < len(line) else default


def _source_chars(source: str) -> _SourceChars:
    return _SourceChars(source)


def _decorators(node: ast.FunctionDef, toks: dict, classes: dict) -> tuple:
    return tuple(_decorator(dec, toks, classes) for dec in node.decorator_list)


def _decorator(node: ast.AST, toks: dict, classes: dict):
    """Выражение в позиции декоратора: `dec`, `mod.dec`, `dec(args)`, `mod.dec(args)`."""
    if isinstance(node, ast.Name):
        return ir.FunRef(name=node.id, line=node.lineno)
    if isinstance(node, ast.Attribute):
        if not isinstance(node.value, ast.Name):
            raise SquealError(f"{node.lineno}: decorator must be a name or module.function")
        return ir.RemoteFunRef(module=node.value.id, name=node.attr, line=node.lineno)
    if isinstance(node, ast.Call):
        if node.keywords:
            raise SquealError(f"{node.lineno}: named decorator arguments are not supported")
        args = tuple(_expr(a, toks, classes) for a in node.args)
        func = node.func
        if isinstance(func, ast.Name):
            return ir.Call(name=func.id, args=args, line=node.lineno)
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            return ir.RemoteCall(
                module=func.value.id, name=func.attr, args=args, line=node.lineno
            )
    raise SquealError(
        f"{node.lineno}: decorator must be a name, module.function or a call of them"
    )


def _function(node: ast.FunctionDef, toks: dict, classes: dict) -> ir.Function:
    decorators = _decorators(node, toks, classes)
    a = node.args
    if a.posonlyargs or a.kwonlyargs or a.vararg or a.kwarg or a.defaults:
        raise SquealError(
            f"{node.lineno}: parameters with defaults/vararg are not supported yet"
        )
    params = tuple(arg.arg for arg in a.args)
    statements = _statements(node.body, toks, classes)
    if not statements:
        raise SquealError(f"{node.lineno}: function {node.name} has no value")
    return ir.Function(
        name=node.name,
        params=params,
        statements=statements,
        line=node.lineno,
        decorators=decorators,
    )


def _builtin_call(node: ast.Call, toks: dict, classes: dict):
    """`zip(a, b)` и `enumerate(xs[, start])` — встроенные функции стандартной библиотеки."""
    name = node.func.id
    if node.keywords:
        raise SquealError(f"{node.lineno}: {name} takes positional arguments only")
    args = [_expr(a, toks, classes) for a in node.args]
    if name == "zip":
        if len(args) != 2:
            raise SquealError(
                f"{node.lineno}: zip takes exactly two lists, got {len(args)}"
            )
        return ir.Zip(left=args[0], right=args[1], line=node.lineno)
    if len(args) not in (1, 2):
        raise SquealError(
            f"{node.lineno}: enumerate takes one or two arguments, got {len(args)}"
        )
    return ir.Enumerate(
        value=args[0], start=args[1] if len(args) == 2 else None, line=node.lineno
    )


def _nested_def(node: ast.FunctionDef, toks: dict, classes: dict) -> ir.NestedDef:
    """`def` в теле функции: замыкание-значение, а не функция модуля."""
    a = node.args
    if a.posonlyargs or a.kwonlyargs or a.vararg or a.kwarg or a.defaults:
        raise SquealError(
            f"{node.lineno}: parameters with defaults/vararg are not supported yet"
        )
    statements = _statements(node.body, toks, classes)
    if not statements:
        raise SquealError(f"{node.lineno}: function {node.name} has no value")
    return ir.NestedDef(
        name=node.name,
        params=tuple(arg.arg for arg in a.args),
        statements=statements,
        line=node.lineno,
        decorators=_decorators(node, toks, classes),
    )


def _statements(body: list, toks: dict, classes: dict) -> tuple:
    out = []
    for stmt in body:
        s = _statement(stmt, toks, classes)
        if s is not None:
            out.append(s)
    return tuple(out)


def _statement(node: ast.stmt, toks: dict, classes: dict):
    if isinstance(node, ast.FunctionDef):
        return _nested_def(node, toks, classes)
    if isinstance(node, ast.Assign):
        if len(node.targets) != 1:
            raise SquealError(f"{node.lineno}: chained assignment a = b = … is not supported")
        return ir.Assign(
            target=_target(node.targets[0]),
            value=_expr(node.value, toks, classes),
            line=node.lineno,
        )
    if isinstance(node, ast.AnnAssign):
        if node.value is None:
            raise SquealError(f"{node.lineno}: annotation without a value is not supported")
        if not isinstance(node.target, ast.Name):
            raise SquealError(f"{node.lineno}: annotation is only allowed on a name")
        return ir.Assign(
            target=ir.PName(node.target.id, node.target.lineno),
            value=_expr(node.value, toks, classes),
            line=node.lineno,
        )
    if isinstance(node, ast.AugAssign):
        if isinstance(node.op, ast.BitOr):
            if not isinstance(node.target, ast.Name):
                raise SquealError(f"{node.lineno}: |= is only allowed on a name")
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
            f"{node.lineno}: mutating assignment {type(node.op).__name__} is not supported"
        )
    if isinstance(node, ast.Expr):
        assign = _as_pattern_assign(node.value, toks, classes)
        if assign is not None:
            return assign
        return ir.Expr(value=_expr(node.value, toks, classes), line=node.lineno)
    if isinstance(node, ast.Return):
        value = ir.Nil(node.lineno) if node.value is None else _expr(node.value, toks, classes)
        return ir.Expr(value=value, line=node.lineno)
    if isinstance(node, ast.Pass):
        return None
    if isinstance(node, ast.If):
        else_body = _statements(node.orelse, toks, classes)
        if not else_body:
            raise SquealError(f"{node.lineno}: if without else has no value on the false path")
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
        raise SquealError(f"{node.lineno}: loop {type(node).__name__} is forbidden — squeal has no mutation")
    if isinstance(node, ast.Delete):
        raise SquealError(f"{node.lineno}: del is forbidden")
    raise SquealError(f"{node.lineno}: operator {type(node).__name__} is not supported")


def _target(node: ast.AST) -> object:
    if isinstance(node, ast.Name):
        return ir.PName(node.id, node.lineno)
    if isinstance(node, ast.Tuple):
        items = tuple(_target_elt(e) for e in node.elts)
    elif isinstance(node, ast.List):
        items = tuple(_target_elt(e) for e in node.elts)
    else:
        raise SquealError(f"{node.lineno}: unsupported assignment target (index/attribute)")

    stars = [i for i, it in enumerate(items) if isinstance(it, ir.PStar)]
    if stars:
        if len(stars) != 1 or stars[0] != len(items) - 1:
            raise SquealError(f"{node.lineno}: only one star, and at the end of the pattern")
        return ir.PList(items=items, line=node.lineno)
    if isinstance(node, ast.Tuple):
        return ir.PTuple(items=items, line=node.lineno)
    return ir.PList(items=items, line=node.lineno)


def _target_elt(node: ast.AST) -> object:
    if isinstance(node, ast.Starred):
        if not isinstance(node.value, ast.Name):
            raise SquealError(f"{node.lineno}: star is only allowed for a name")
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
            raise SquealError(f"{node.lineno}: as-pattern is not supported")
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
            raise SquealError(f"{node.lineno}: class pattern is only allowed for squeal classes")
        if node.kwd_patterns:
            raise SquealError(f"{node.lineno}: named fields in a class pattern are not supported")
        fields = classes[node.cls.id]
        if len(node.patterns) != len(fields):
            raise SquealError(
                f"{node.lineno}: pattern {node.cls.id} expects {len(fields)} fields, "
                f"got {len(node.patterns)}"
            )
        tag = snake_case(node.cls.id)
        items = (ir.AtomLit(tag, node.lineno),) + tuple(
            _match_pattern(p, toks, classes) for p in node.patterns
        )
        return ir.PTuple(items=items, line=node.lineno)
    raise SquealError(f"{node.lineno}: pattern {type(node).__name__} is not supported")


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
        raise SquealError(f"{node.lineno}: unsupported literal {v!r}")

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
            raise SquealError(f"{node.lineno}: operator {type(node.op).__name__} is not supported")
        return ir.UnaryOp(
            op=op, operand=_expr(node.operand, toks, classes), line=node.lineno
        )

    if isinstance(node, ast.BinOp):
        op = _BINOP.get(type(node.op))
        if op is None:
            raise SquealError(
                f"{node.lineno}: operator {type(node.op).__name__} is not supported"
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
            raise SquealError(f"{node.lineno}: boolean operator is not supported")
        return ir.BoolOp(
            op=op,
            operands=tuple(_expr(v, toks, classes) for v in node.values),
            line=node.lineno,
        )

    if isinstance(node, ast.Compare):
        if len(node.ops) != 1:
            raise SquealError(f"{node.lineno}: comparison chains are not supported yet")
        op = _CMP.get(type(node.ops[0]))
        if op is None:
            raise SquealError(f"{node.lineno}: comparison operator (is/in/…) is not supported")
        return ir.BinOp(
            op=op,
            left=_expr(node.left, toks, classes),
            right=_expr(node.comparators[0], toks, classes),
            line=node.lineno,
        )

    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute):
            if node.keywords:
                raise SquealError(
                    f"{node.lineno}: named method arguments are not supported"
                )
            return ir.Method(
                receiver=_expr(node.func.value, toks, classes),
                name=node.func.attr,
                args=tuple(_expr(a, toks, classes) for a in node.args),
                line=node.lineno,
            )
        if isinstance(node.func, ast.Name) and node.func.id in ("zip", "enumerate"):
            return _builtin_call(node, toks, classes)
        if isinstance(node.func, ast.Name) and node.func.id == "print":
            if node.keywords:
                raise SquealError(
                    f"{node.lineno}: print takes a single positional argument (print(x))"
                )
            if len(node.args) != 1:
                raise SquealError(
                    f"{node.lineno}: print takes exactly one argument, "
                    f"got {len(node.args)}"
                )
            return ir.Print(value=_expr(node.args[0], toks, classes), line=node.lineno)
        if isinstance(node.func, ast.Name) and node.func.id in classes:
            if node.keywords:
                raise SquealError(f"{node.lineno}: named constructor arguments are not supported")
            fields = classes[node.func.id]
            if len(node.args) != len(fields):
                raise SquealError(
                    f"{node.lineno}: constructor {node.func.id} expects {len(fields)} arguments, "
                    f"got {len(node.args)}"
                )
            tag = snake_case(node.func.id)
            return ir.Tuple(
                items=(ir.AtomLit(tag, node.lineno),)
                + tuple(_expr(a, toks, classes) for a in node.args),
                line=node.lineno,
            )
        if not isinstance(node.func, ast.Name):
            raise SquealError(f"{node.lineno}: call through an attribute is not supported")
        if node.keywords:
            raise SquealError(f"{node.lineno}: named arguments are not supported")
        return ir.Call(
            name=node.func.id,
            args=tuple(_expr(a, toks, classes) for a in node.args),
            line=node.lineno,
        )

    if isinstance(node, ast.Lambda):
        a = node.args
        if a.posonlyargs or a.kwonlyargs or a.vararg or a.kwarg or a.defaults:
            raise SquealError(f"{node.lineno}: lambda parameters with defaults are not supported")
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
        raise SquealError(f"{node.lineno}: squeal has no sets — set comprehension is not supported")
    if isinstance(node, ast.GeneratorExp):
        raise SquealError(f"{node.lineno}: generator expressions are not supported yet")

    raise SquealError(f"{node.lineno}: unsupported expression {type(node).__name__}")


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
            raise SquealError(f"{c.target.lineno}: async generator is not supported")
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
