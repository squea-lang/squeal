"""Проверки: семантика, которой нет в синтаксисе (см. architecture.md)."""

from __future__ import annotations

from .backend import RESERVED_NAMES
from .errors import SquealError
from .ir import Module


def check(module: Module) -> None:
    """Дубли определяются по паре (имя, арность): как в Erlang/Gleam,
    `fib/1` и `fib/3` — разные функции. Имена хелперов зарезервированы."""
    seen = set()
    for function in module.functions:
        if function.name in RESERVED_NAMES:
            raise SquealError(f"имя {function.name!r} зарезервировано компилятором")
        key = (function.name, len(function.params))
        if key in seen:
            raise SquealError(
                f"повторное определение функции {function.name}/{len(function.params)}"
            )
        seen.add(key)
