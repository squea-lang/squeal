"""Nested `def` inside a function body: a fun value, recursion, decorators."""

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


def _function(source: str, name: str = "m"):
    forms = compile_source(source, "src/m.ee", "m")
    return next(f for f in forms if f[0] == Atom("function") and f[2] == Atom(name))


def _find(form, pred, out=None) -> list:
    """Every sub-form matching the predicate."""
    out = [] if out is None else out
    if isinstance(form, tuple):
        if pred(form):
            out.append(form)
        for item in form:
            _find(item, pred, out)
    elif isinstance(form, list):
        for item in form:
            _find(item, pred, out)
    return out


def _build(source: str, module: str = "n") -> pathlib.Path:
    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "src").mkdir()
    (tmp / "src" / f"{module}.ee").write_text(source)
    subprocess.run(
        [sys.executable, "-m", "squeal", "build", str(tmp)],
        cwd=ROOT, check=True, capture_output=True,
    )
    return tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"


def _run(ebin: pathlib.Path, expr: str) -> str:
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval", f'{expr}, halt().'],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def test_nested_def_is_named_fun():
    fn = _function("def m():\n    def f(x):\n        x\n")
    match = fn[4][0][4][0]
    assert match[0] == Atom("match")
    assert match[2] == (Atom("var"), 2, Atom("F"))
    fun = match[3]
    assert fun[0] == Atom("named_fun") and fun[2] == Atom("F")
    # recursion goes through the fun name, not through a module function
    fn = _function("def m(n):\n    def f(x):\n        f(x)\n    f(n)\n", "m")
    calls = _find(fn, lambda f: f[0] == Atom("call") and f[2] == (Atom("var"), 3, Atom("F")))
    assert calls, "no call through the variable F"


def test_nested_def_errors():
    for source in [
        "def m():\n    def f(x=1):\n        x\n",
        "def m():\n    def f(*args):\n        args\n",
    ]:
        with pytest.raises(SquealError):
            compile_source(source, "src/m.ee", "m")


def test_nested_def_shadows_builtin():
    src = "def m(v):\n    def print(x):\n        x + 1\n    print(v)\n"
    names = [f[2] for f in compile_source(src, "src/m.ee", "m") if f[0] == Atom("function")]
    assert Atom("squeal_print") not in names
    ebin = _build(src)
    assert _run(ebin, 'io:format("~p", [n:m(1)])') == "2"


def test_module_semantics():
    ebin = _build(
        "def dec(f):\n"
        "    def fun(x):\n"
        "        f(x) + 100\n"
        "\n"
        "@dec\n"
        "def g(x):\n"
        "    x * 2\n"
        "\n"
        "def rec(n):\n"
        "    def down(k):\n"
        "        if k > 0:\n"
        "            down(k - 1)\n"
        "        else:\n"
        '            "done"\n'
        "    down(n)\n"
        "\n"
        "def captured():\n"
        "    y = 1\n"
        "    def f(x):\n"
        "        x + y\n"
        "    y = 100\n"
        "    f(1)\n"
        "\n"
        "def rebind():\n"
        "    def f(x):\n"
        "        1\n"
        "    def f(x):\n"
        "        2\n"
        "    f(0)\n"
        "\n"
        "def branch(c):\n"
        "    if c:\n"
        "        def f(x):\n"
        "            x + 1\n"
        "    else:\n"
        "        def f(x):\n"
        "            x + 2\n"
        "    f(0)\n"
        "\n"
        "def f(x):\n"
        "    1\n"
        "\n"
        "def shadow():\n"
        "    def f(x):\n"
        "        2\n"
        "    f(0)\n"
    )
    assert _run(ebin, 'io:format("~p ~p ~p ~p ~p ~p ~p ~p", '
                      '[n:g(1), n:rec(3), n:captured(), n:rebind(), '
                      'n:branch(true), n:branch(false), n:shadow(), n:f(0)])') == (
        '102 <<"done">> 2 2 1 2 2 1'
    )


def test_nested_decorator_inside_function():
    ebin = _build(
        "def outer():\n"
        "    def twice(fn):\n"
        "        lambda x: fn(fn(x))\n"
        "    @twice\n"
        "    def inc(x):\n"
        "        x + 1\n"
        "    inc(1)\n"
    )
    assert _run(ebin, 'io:format("~p", [n:outer()])') == "3"


def test_shell_mode_nested_def():
    from squeal.session import Session, compile_cell
    from squeal.repl import ErlangRepl

    s = Session()
    repl = ErlangRepl()
    try:
        for cell in [
            "def dec(f):\n    def fun(x):\n        f(x)\n",
            "@dec\ndef g(x):\n    x + 1\n",
            "def rec(n):\n    def down(k):\n        if k > 0:\n"
            '            down(k - 1)\n        else:\n            "done"\n    down(n)\n',
            "def outer():\n    def twice(fn):\n        lambda x: fn(fn(x))\n"
            "    @twice\n    def inc(x):\n        x + 1\n    inc(1)\n",
        ]:
            forms, _ = compile_cell(cell, s)
            assert repl.eval_forms(forms)[0] == "ok"

        for cell, expected in [("g(3)", "4"), ("rec(3)", '<<"done">>'), ("outer()", "3")]:
            forms, _ = compile_cell(cell, s)
            assert repl.eval_forms(forms) == ("ok", expected)
    finally:
        repl.close()
