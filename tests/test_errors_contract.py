"""Error contract: Erlang lint errors surface as `path:line: text`, never as a term dump."""

from __future__ import annotations

import pathlib
import subprocess
import tempfile

from squeal.term import Atom, term_to_erlang

ROOT = pathlib.Path(__file__).resolve().parent.parent
ESCRIPT = ROOT / "squeal" / "squeal_compile.escript"


def test_lint_error_is_clean():
    tmp = pathlib.Path(tempfile.mkdtemp())
    # a form calling a missing local function — the linter rejects it
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


def test_reserved_name_reports_the_line(tmp_path=None):
    import pytest
    from squeal.compiler import compile_source
    from squeal.errors import SquealError

    with pytest.raises(SquealError, match=r"^src/m\.ee:4: name 'squeal_iter'"):
        compile_source("def ok(x):\n    x\n\ndef squeal_iter(x):\n    x\n", "src/m.ee", "m")
    with pytest.raises(SquealError, match=r"^src/m\.ee:4: duplicate definition of function f/1"):
        compile_source("def f(x):\n    x\n\ndef f(x):\n    x\n", "src/m.ee", "m")
