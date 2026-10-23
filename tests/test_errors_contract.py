"""Контракт ошибок: ошибки линта Erlang выходят как `путь:строка: текст`, без дампа."""

from __future__ import annotations

import pathlib
import subprocess
import tempfile

from squeal.term import Atom, term_to_erlang

ROOT = pathlib.Path(__file__).resolve().parent.parent
ESCRIPT = ROOT / "squeal" / "squeal_compile.escript"


def test_lint_error_is_clean():
    tmp = pathlib.Path(tempfile.mkdtemp())
    # формы с вызовом несуществующей локальной функции — такую форму линт отвергает
    forms = [
        (Atom("attribute"), 0, Atom("module"), Atom("t")),
        (Atom("attribute"), 0, Atom("export"), [(Atom("m"), 0)]),
        (Atom("attribute"), 0, Atom("file"), ("src/t.ee", 0)),
        (Atom("function"), 2, Atom("m"), 0, [
            (Atom("clause"), 2, [], [],
             [(Atom("call"), 3, (Atom("atom"), 3, Atom("nope")), [])]),
        ]),
    ]
    abstr = tmp / "t.abstr"
    abstr.write_text("".join(term_to_erlang(f) + ".\n" for f in forms))
    jobs = tmp / "_jobs.term"
    jobs.write_text(term_to_erlang((str(abstr), str(tmp / "t"), "src/t.ee")) + ".\n")
    run = subprocess.run(
        ["escript", str(ESCRIPT), str(jobs)], capture_output=True, text=True
    )
    assert run.returncode != 0
    assert run.stderr.strip() == "src/t.ee:3: function nope/0 is not defined"
