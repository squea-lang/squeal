"""Jupyter-интеграция squeal без кастомного kernel.

Подключается как IPython-расширение (``c.InteractiveShellApp.extensions =
['squeal.notebook']`` в ``ipython_config.py``). Ячейка остаётся Python-текстом —
автокомплит/линт даёт Python-LSP; выполнение перехватывается: Python выполняет
``pass``, а исходник компилируется squeal'ом и исполняется в persistent Erlang-REPL.
"""

from __future__ import annotations

import ast
import sys

from .term import Atom


def find_comprehensions(node, out=None) -> list:
    """Найти все формы включений (`lc`/`mc`) в списке форм клетки."""
    if out is None:
        out = []
    if isinstance(node, tuple):
        if node and isinstance(node[0], Atom) and node[0] in (Atom("lc"), Atom("mc")):
            out.append(node)
        for item in node:
            find_comprehensions(item, out)
    elif isinstance(node, list):
        for item in node:
            find_comprehensions(item, out)
    return out


def compact(source: str) -> str:
    """erl_pp переносит строки — сжимаем в одну для консоли."""
    s = " ".join(source.split())
    for a, b in (("[ ", "["), (" ]", "]"), ("#{ ", "#{"), (" }", "}")):
        s = s.replace(a, b)
    return s


def load_ipython_extension(ipython) -> None:
    if getattr(ipython, "_squeal_notebook", None) is not None:
        return  # уже загружено
    from . import frontend
    from .errors import SquealError
    from .repl import ErlangRepl
    from .session import Session

    state = {"session": Session(), "repl": None, "raw_cell": None}

    def let_cleanup(lines):
        """Переписывает `Ctor(args) = expr` до Python-парсера (иначе SyntaxError)."""
        return frontend.rewrite_pattern_assignments("".join(lines)).splitlines(keepends=True)

    class _NoopTransformer(ast.NodeTransformer):
        """Заменяет тело ячейки на pass — Python ничего не выполняет."""

        def visit_Module(self, node):  # noqa: N802
            node.body = [ast.Pass()]
            return node

    def pre_run_cell(info) -> None:
        state["raw_cell"] = info.raw_cell

    def post_run_cell(result) -> None:
        source = state["raw_cell"]
        if (
            source is None
            or result.error_before_exec is not None
            or result.error_in_exec is not None
        ):
            return  # Python уже показал ошибку (например, SyntaxError)
        try:
            if state["repl"] is None:
                state["repl"] = ErlangRepl()
            forms, suppress = state["session"].compile(source)
            if not forms:
                return
            if not suppress:
                for comp in find_comprehensions(forms):
                    print(f"erl: {compact(state['repl'].pp(comp))}")
            status, value = state["repl"].eval_forms(forms)
            if status == "ok":
                if not suppress and value != "nil":
                    print(value)
            else:
                sys.stderr.write(f"squeal runtime error: {value}\n")
        except SyntaxError:
            pass  # клетка — не валидный Python-синтаксис, это уже видно в выводе
        except SquealError as exc:
            sys.stderr.write(f"squeal: {exc}\n")

    transformer = _NoopTransformer()
    ipython.events.register("pre_run_cell", pre_run_cell)
    ipython.events.register("post_run_cell", post_run_cell)
    ipython.ast_transformers.append(transformer)
    ipython.input_transformers_cleanup.append(let_cleanup)
    ipython._squeal_notebook = {
        "state": state,
        "pre": pre_run_cell,
        "post": post_run_cell,
        "transformer": transformer,
        "cleanup": let_cleanup,
    }


def unload_ipython_extension(ipython) -> None:
    loaded = getattr(ipython, "_squeal_notebook", None)
    if loaded is None:
        return
    for name, callback in (("pre_run_cell", loaded["pre"]), ("post_run_cell", loaded["post"])):
        try:
            ipython.events.callbacks[name].remove(callback)
        except (KeyError, ValueError):
            pass
    for seq, item in (
        (ipython.ast_transformers, loaded["transformer"]),
        (ipython.input_transformers_cleanup, loaded["cleanup"]),
    ):
        try:
            seq.remove(item)
        except ValueError:
            pass
    repl = loaded["state"].get("repl")
    if repl is not None:
        repl.close()
    ipython._squeal_notebook = None
