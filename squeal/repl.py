"""Persistent Erlang-REPL: подпроцесс escript, обмен абстрактными формами."""

from __future__ import annotations

import pathlib
import subprocess

from .term import term_to_erlang

ESCRIPT = pathlib.Path(__file__).parent / "repl.escript"


class ErlangRepl:
    def __init__(self):
        self.proc = subprocess.Popen(
            ["escript", str(ESCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )

    def eval_forms(self, forms: list) -> tuple[str, str]:
        """Отправляет список форм, возвращает ("ok" | "error", текст значения/ошибки)."""
        self.proc.stdin.write(term_to_erlang(forms) + ".\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise RuntimeError("repl завершился")
        line = line.rstrip("\n")
        if line.startswith("OK "):
            return "ok", line[3:]
        if line.startswith("ERR "):
            return "error", line[4:]
        raise RuntimeError(f"неожиданный ответ repl: {line!r}")

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        self.proc.wait(timeout=5)
