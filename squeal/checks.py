"""Проверки: семантика, которой нет в синтаксисе (см. architecture.md)."""

from __future__ import annotations

from .errors import SquealError
from .ir import Module


def check(module: Module) -> None:
    seen = set()
    for function in module.functions:
        if function.name in seen:
            raise SquealError(f"повторное определение функции {function.name}")
        seen.add(function.name)
