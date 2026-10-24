"""Built-in zip and enumerate: eager lists, helpers, errors and comprehensions."""

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


def _forms(source: str, name: str = "m") -> list:
    return compile_source(source, "src/m.ee", name)


def _body(source: str, name: str = "m"):
    forms = _forms(source, name)
    fn = next(f for f in forms if f[0] == Atom("function") and f[2] == Atom(name))
    return fn[4][0][4][0]


def _function_names(source: str, name: str = "m") -> list:
    return [f[2] for f in _forms(source, name) if f[0] == Atom("function")]


def test_zip_call_form():
    body = _body("def m(a, b):\n    zip(a, b)\n")
    assert body[0] == Atom("call")
    assert body[2] == (Atom("atom"), 2, Atom("squeal_zip"))
    assert body[3] == [(Atom("var"), 2, Atom("A")), (Atom("var"), 2, Atom("B"))]


def test_enumerate_defaults_to_zero():
    body = _body("def m(xs):\n    enumerate(xs)\n")
    assert body[2] == (Atom("atom"), 2, Atom("squeal_enumerate"))
    assert body[3] == [(Atom("integer"), 2, 0), (Atom("var"), 2, Atom("Xs"))]

    body = _body("def m(xs):\n    enumerate(xs, 5)\n")
    assert body[3] == [(Atom("integer"), 2, 5), (Atom("var"), 2, Atom("Xs"))]


def test_helpers_emitted_on_demand():
    assert _function_names("def m(a, b):\n    zip(a, b)\n")[1:] == [Atom("squeal_zip")]
    assert _function_names("def m(xs):\n    enumerate(xs)\n")[1:] == [
        Atom("squeal_enumerate")
    ]
    assert _function_names("def m(xs):\n    xs\n") == [Atom("m")]


def test_arity_errors():
    for source in [
        "def m(a):\n    zip(a)\n",
        "def m(a, b, c):\n    zip(a, b, c)\n",
        "def m():\n    enumerate()\n",
        "def m(a, b, c):\n    enumerate(a, b, c)\n",
        "def m(a, b):\n    zip(a, b=b)\n",
    ]:
        with pytest.raises(SquealError):
            compile_source(source, "src/m.ee", "m")


def test_zip_can_be_shadowed():
    src = "def zip(a, b):\n    a\n\ndef m(xs, ys):\n    zip(xs, ys)\n"
    names = _function_names(src)
    assert Atom("squeal_zip") not in names  # встроенная не подключается
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
         'io:format("~p~n", [m:m([1], [2])]), halt().'],
        capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "[1]"


def test_semantics_in_erl():
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    src.mkdir()
    (src / "z.ee").write_text(
        "def zip_short():\n    zip([1, 2, 3], [\"a\", \"b\"])\n"
        "def zip_empty():\n    zip([], [1])\n"
        "def enum():\n    enumerate([\"a\", \"b\"])\n"
        "def enum_start():\n    enumerate([\"a\"], 5)\n"
        "def both():\n    [(i, a + b) for i, (a, b) in enumerate(zip([1, 2], [10, 20, 30]))]\n"
        "def bad_zip():\n    zip([1], {\"a\": 2})\n"
        "def bad_enum():\n    enumerate({\"a\": 2})\n"
    )
    subprocess.run(
        [sys.executable, "-m", "squeal", "build", str(tmp)],
        cwd=ROOT, check=True, capture_output=True,
    )
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval",
         'io:format("~p|~p|~p|~p|~p|", [z:zip_short(), z:zip_empty(), z:enum(), '
         'z:enum_start(), z:both()]), '
         'io:format("~p|~p~n", [catch z:bad_zip(), catch z:bad_enum()]), halt().'],
        capture_output=True, text=True, check=True,
    )
    # ~p wraps at 80 columns, so compare with whitespace squeezed out
    flat = "".join(out.stdout.split())
    assert flat.startswith(
        '[{1,<<"a">>},{2,<<"b">>}]|[]|[{0,<<"a">>},{1,<<"b">>}]|'
        '[{5,<<"a">>}]|[{0,11},{1,22}]|'
    )
    assert "{bad_argument,zip," in flat
    assert "{bad_argument,enumerate," in flat


def test_shell_mode():
    from squeal.session import Session, compile_cell
    from squeal.repl import ErlangRepl

    s = Session()
    repl = ErlangRepl()
    try:
        cases = [
            ('zip([1, 2, 3], ["a", "b"])', '[{1,<<"a">>},{2,<<"b">>}]'),
            ('enumerate(["a", "b"])', '[{0,<<"a">>},{1,<<"b">>}]'),
            ('enumerate(["a", "b"], 5)', '[{5,<<"a">>},{6,<<"b">>}]'),
            ("[x * 2 for i, x in enumerate([10, 20])]", "[20,40]"),
            ("[a + b for a, b in zip([1, 2], [10, 20, 30])]", "[11,22]"),
        ]
        for cell, expected in cases:
            forms, _ = compile_cell(cell + "\n", s)
            assert repl.eval_forms(forms) == ("ok", expected)
        forms, _ = compile_cell('enumerate({"a": 2})\n', s)
        assert repl.eval_forms(forms)[0] == "error"

        # переопределение встроенной: действует по имени в следующих клетках
        forms, _ = compile_cell("def zip(a, b):\n    a\n", s)
        repl.eval_forms(forms)
        forms, _ = compile_cell("zip([7], [8])\n", s)
        assert repl.eval_forms(forms) == ("ok", "[7]")
    finally:
        repl.close()
