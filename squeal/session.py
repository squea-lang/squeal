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
        source = frontend.rewrite_lets(source)
        toks = frontend._token_chars(source)
        tree = ast.parse(source)
        forms = []
        last_is_definition = False
        seen_classes: set[str] = set()
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                forms.append(self._gen.stmt_form(self._def(node, toks)))
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
                    forms.append(self._gen.stmt_form(stmt))
                    last_is_definition = False
        return forms, last_is_definition

    def _def(self, node: ast.FunctionDef, toks: dict) -> ir.Def:
        a = node.args
        if a.posonlyargs or a.kwonlyargs or a.vararg or a.kwarg or a.defaults:
            raise SquealError(f"{node.lineno}: параметры со значениями/vararg не поддержаны")
        params = tuple(arg.arg for arg in a.args)
        body = frontend._statements(node.body, toks, self.classes)
        if not body:
            raise SquealError(f"{node.lineno}: функция {node.name} без значения")
        return ir.Def(name=node.name, params=params, statements=body, line=node.lineno)

    def _class(self, node: ast.ClassDef, seen: set[str]) -> None:
        fields = frontend._class_fields(node)
        base = frontend._base_name(node)
        if base != "StartingWithAtom":
            raise SquealError(
                f"{node.lineno}: базовый класс {base!r} — поддержан только StartingWithAtom"
            )
        if node.name in seen:
            raise SquealError(
                f"{node.lineno}: повторное определение класса {node.name} в одной ячейке"
            )
        seen.add(node.name)
        # переопределение между ячейками разрешено: повторный запуск клетки — не ошибка
        self.classes[node.name] = fields

    def _import(self, node: ast.stmt) -> None:
        if isinstance(node, ast.Import):
            raise SquealError(f"{node.lineno}: import X — только from X import …")
        if node.level != 0:
            raise SquealError(f"{node.lineno}: относительные импорты не поддержаны")
        if not node.module:
            raise SquealError(f"{node.lineno}: безымянный import")
        for alias in node.names:
            if alias.name == "*":
                raise SquealError(f"{node.lineno}: import * не поддержан")
            self.imports[alias.asname or alias.name] = (
                node.module.replace(".", "@"),
                alias.name,
            )


def compile_cell(source: str, session: Session) -> tuple[list, bool]:
    return session.compile(source)
