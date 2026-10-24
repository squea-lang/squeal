"""Built-in range: Python semantics, eager list, helper and errors."""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile

import pytest

from squeal.compiler import compile_source
from squeal.errors import SquealError
from squeal.term import Atom

ERL = shutil.which("erl")
ROOT = pathlib.Path(__file__).resolve().parent.parent

ZERO = (Atom("integer"), 2, 0)
ONE = (Atom("integer"), 2, 1)


def _forms(source: str, name: str = "m") -> list:
    return compile_source(source, "src/m.ee", name)


def _body(source: str, name: str = "m"):
    forms = _forms(source, name)
    fn = next(f for f in forms if f[0] == Atom("function") and f[2] == Atom(name))
    return fn[4][0][4][0]


def _function_names(source: str, name: str = "m") -> list:
    return [f[2] for f in _forms(source, name) if f[0] == Atom("function")]


def test_range_arities_become_start_stop_step():
    body = _body("def m():\n    range(5)\n")
    assert body[2] == (Atom("atom"), 2, Atom("squeal_range"))
    assert body[3] == [ZERO, (Atom("integer"), 2, 5), ONE]

    body = _body("def m(a):\n    range(2, a)\n")
    assert body[3] == [(Atom("integer"), 2, 2), (Atom("var"), 2, Atom("A")), ONE]

    body = _body("def m(a):\n    range(0, a, 3)\n")
    assert body[3] == [ZERO, (Atom("var"), 2, Atom("A")), (Atom("integer"), 2, 3)]


def test_helper_emitted_on_demand():
    assert _function_names("def m():\n    range(3)\n")[1:] == [Atom("squeal_range")]
    assert _function_names("def m(x):\n    x\n") == [Atom("m")]


def test_arity_errors():
    for source in [
        "def m():\n    range()\n",
        "def m(a, b, c):\n    range(a, b, c, 1)\n",
    ]:
        with pytest.raises(SquealError, match="range takes"):
            compile_source(source, "src/m.ee", "m")


def test_semantics_in_erl():
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    src.mkdir()
    (src / "r.ee").write_text(
        "def a():\n    range(5)\n"
        "def b():\n    range(2, 5)\n"
        "def c():\n    range(0, 10, 3)\n"
        "def d():\n    range(10, 0, -3)\n"
        "def e():\n    range(5, 5)\n"
        "def f():\n    range(5, 0)\n"
        "def g():\n    range(0, 10, -1)\n"
        "def h():\n    range(-3)\n"
        "def i():\n    range(3, -1, -1)\n"
        "def squares():\n    [x * x for x in range(4)]\n"
        "def bad_step():\n    range(0, 10, 0)\n"
        "def bad_float():\n    range(1.5)\n"
    )
    subprocess.run(
        [sys.executable, "-m", "squeal", "build", str(tmp)],
        cwd=ROOT, check=True, capture_output=True,
    )
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    calls = [
        ("a", "[0,1,2,3,4]"),
        ("b", "[2,3,4]"),
        ("c", "[0,3,6,9]"),
        ("d", "[10,7,4,1]"),
        ("e", "[]"),
        ("f", "[]"),
        ("g", "[]"),
        ("h", "[]"),
        ("i", "[3,2,1,0]"),
        ("squares", "[0,1,4,9]"),
    ]
    expr = ", ".join(f'io:format("~p|", [r:{name}()])' for name, _ in calls)
    expr += ', io:format("~p|~p~n", [catch r:bad_step(), catch r:bad_float()]), halt().'
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval", expr],
        capture_output=True, text=True, check=True,
    )
    flat = "".join(out.stdout.split())
    assert flat.startswith("".join(f"{expected}|" for _, expected in calls))
    assert "{bad_argument,range,0}" in flat
    assert "{bad_argument,range,1.5}" in flat


def test_range_can_be_shadowed():
    src = "def range(n):\n    n * 2\n\ndef m():\n    range(21)\n"
    assert Atom("squeal_range") not in _function_names(src)
    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "src").mkdir()
    (tmp / "src" / "m.ee").write_text(src)
    subprocess.run(
        [sys.executable, "-m", "squeal", "build", str(tmp)],
        cwd=ROOT, check=True, capture_output=True,
    )
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval",
         'io:format("~p~n", [m:m()]), halt().'],
        capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "42"


def test_shell_mode():
    from squeal.session import Session, compile_cell
    from squeal.repl import ErlangRepl

    s = Session()
    repl = ErlangRepl()
    try:
        cases = [
            ("range(5)", "[0,1,2,3,4]"),
            ("range(2, 5)", "[2,3,4]"),
            ("range(0, 10, 3)", "[0,3,6,9]"),
            ("range(10, 0, -3)", "[10,7,4,1]"),
            ("range(5, 5)", "[]"),
            ("[x * x for x in range(4)]", "[0,1,4,9]"),
        ]
        for cell, expected in cases:
            forms, _ = compile_cell(cell + "\n", s)
            assert repl.eval_forms(forms) == ("ok", expected)
        forms, _ = compile_cell("range(0, 10, 0)\n", s)
        assert repl.eval_forms(forms) == ("error", "{error,{bad_argument,range,0}}")
    finally:
        repl.close()
