"""Shell-режим компилятора для Jupyter: клетка → Erlang-выражения (не модуль).

Клетка — последовательность операторов, как тело функции. Состояние (маппинг имён
`X@N`, классы, импорты) живёт между клетками в :class:`Session`.
"""

from __future__ import annotations

import ast

from . import backend, frontend, ir
from .errors import SquealError


class Session:
    def __init__(self):
        self.classes: dict[str, tuple] = dict(frontend.BUILTIN_CLASSES)
        self.imports: dict[str, tuple] = {}
        self._gen = backend._Gen()
        self._gen._shell_mode = True
        self._gen._imports = self.imports

    def compile(self, source: str) -> tuple[list, bool]:
        """Исходник клетки → (формы, подавлять_вывод).

        ``подавлять_вывод`` — True, когда клетка только определяет (def/class/import).
        """
        source = frontend.rewrite_pattern_assignments(source)
        toks = frontend._source_chars(source)
        tree = ast.parse(source)

        gen = self._gen
        saved = (dict(gen._scope), dict(gen._taken), dict(gen._defs))
        gen._later_defs = {
            (node.name, len(node.args.args))
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        }
        try:
            return self._compile_body(tree, toks)
        except Exception:
            gen._scope, gen._taken, gen._defs = saved
            raise

    def _compile_body(self, tree: ast.Module, toks: dict) -> tuple[list, bool]:
        stmts = []
        last_is_definition = False
        seen_classes: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                stmts.append(self._def(node, toks))
                last_is_definition = True
            elif isinstance(node, ast.ClassDef):
                self._class(node, seen_classes)
                last_is_definition = True
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                self._import(node)
                last_is_definition = True
            else:
                stmt = frontend._statement(node, toks, self.classes)
                if stmt is not None:
                    stmts.append(stmt)
                    last_is_definition = False

        forms = []
        for i, stmt in enumerate(stmts):
            if isinstance(stmt, ir.Def) and stmt.decorators:
                forms.extend(self._gen.decorated_def_forms(stmt))
            elif i == len(stmts) - 1:
                forms.append(self._gen.tail_stmt_form(stmt))
            else:
                forms.append(self._gen.stmt_form(stmt))
        return forms, last_is_definition

    def _def(self, node: ast.FunctionDef, toks: dict) -> ir.Def:
        if node.name in backend.RESERVED_NAMES:
            raise SquealError(
                f"{node.lineno}: name {node.name!r} is reserved by the compiler"
            )
        a = node.args
        if a.posonlyargs or a.kwonlyargs or a.vararg or a.kwarg or a.defaults:
            raise SquealError(f"{node.lineno}: parameters with defaults/vararg are not supported")
        params = tuple(arg.arg for arg in a.args)
        body = frontend._statements(node.body, toks, self.classes)
        if not body:
            raise SquealError(f"{node.lineno}: function {node.name} has no value")
        return ir.Def(
            name=node.name,
            params=params,
            statements=body,
            line=node.lineno,
            decorators=frontend._decorators(node, toks, self.classes),
        )

    def _class(self, node: ast.ClassDef, seen: set[str]) -> None:
        if node.decorator_list:
            raise SquealError(
                f"{node.lineno}: decorators are only supported on functions"
            )
        fields = frontend._class_fields(node)
        base = frontend._base_name(node)
        if base != "StartingWithAtom":
            raise SquealError(
                f"{node.lineno}: base class {base!r} is not supported — only StartingWithAtom"
            )
        if node.name in seen:
            raise SquealError(
                f"{node.lineno}: duplicate definition of class {node.name} in one cell"
            )
        tag = frontend.snake_case(node.name)
        for other in self.classes:
            if other != node.name and frontend.snake_case(other) == tag:
                raise SquealError(
                    f"{node.lineno}: classes {node.name} and {other} produce the same tag {tag!r}"
                )
        seen.add(node.name)
        # переопределение между ячейками разрешено: повторный запуск клетки — не ошибка
        self.classes[node.name] = fields

    def _import(self, node: ast.stmt) -> None:
        if isinstance(node, ast.Import):
            raise SquealError(f"{node.lineno}: plain import X is not supported — use from X import …")
        if node.level != 0:
            raise SquealError(f"{node.lineno}: relative imports are not supported")
        if not node.module:
            raise SquealError(f"{node.lineno}: import without a module name")
        for alias in node.names:
            if alias.name == "*":
                raise SquealError(f"{node.lineno}: import * is not supported")
            self.imports[alias.asname or alias.name] = (
                node.module.replace(".", "@"),
                alias.name,
            )


def compile_cell(source: str, session: Session) -> tuple[list, bool]:
    return session.compile(source)
