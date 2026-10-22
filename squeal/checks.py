"""Проверки: семантика, которой нет в синтаксисе (см. architecture.md)."""

from __future__ import annotations

from .errors import SquealError
from .ir import Module


def check(module: Module) -> None:
    """Дубли определяются по паре (имя, арность): как в Erlang/Gleam,
    `fib/1` и `fib/3` — разные функции."""
    seen = set()
    for function in module.functions:
        key = (function.name, len(function.params))
        if key in seen:
            raise SquealError(
                f"повторное определение функции {function.name}/{len(function.params)}"
            )
        seen.add(key)
