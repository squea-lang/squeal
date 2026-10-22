"""Jupyter-интеграция squeal без кастомного kernel.

Подключается как IPython-расширение (``c.InteractiveShellApp.extensions =
['squeal.notebook']`` в ``ipython_config.py``). Ячейка остаётся Python-текстом —
автокомплит/линт даёт Python-LSP; выполнение перехватывается: Python выполняет
``pass``, а исходник компилируется squeal'ом и исполняется в persistent Erlang-REPL.
"""

from __future__ import annotations

import ast
import sys


def load_ipython_extension(ipython) -> None:
    from .errors import SquealError
    from .repl import ErlangRepl
    from .session import Session

    state = {"session": Session(), "repl": None, "raw_cell": None}

    class _NoopTransformer(ast.NodeTransformer):
        """Заменяет тело ячейки на pass — Python ничего не выполняет."""

        def visit_Module(self, node):  # noqa: N802
            node.body = [ast.Pass()]
            return node

    def pre_run_cell(info) -> None:
        state["raw_cell"] = info.raw_cell

    def post_run_cell(result) -> None:
        source = state["raw_cell"]
        if source is None or result.error_in_exec is not None:
            return
        try:
            if state["repl"] is None:
                state["repl"] = ErlangRepl()
            forms, suppress = state["session"].compile(source)
            if not forms:
                return
            status, value = state["repl"].eval_forms(forms)
            if status == "ok":
                if not suppress:
                    print(value)
            else:
                sys.stderr.write(f"squeal runtime error: {value}\n")
        except SquealError as exc:
            sys.stderr.write(f"squeal: {exc}\n")

    ipython.events.register("pre_run_cell", pre_run_cell)
    ipython.events.register("post_run_cell", post_run_cell)
    ipython.ast_transformers.append(_NoopTransformer())


def unload_ipython_extension(ipython) -> None:
    # Упрощённо: перезапуск ядра сбрасывает всё состояние.
    pass
