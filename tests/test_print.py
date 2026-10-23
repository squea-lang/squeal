"""The built-in print: forms, checks, value display and notebook output."""

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


def _body(source: str, name: str = "m"):
    forms = compile_source(source, "src/m.ee", name)
    fn = [f for f in forms if f[0] == Atom("function")][0]
    return fn[4][0][4][0]


def _function_names(source: str, name: str = "m") -> list:
    forms = compile_source(source, "src/m.ee", name)
    return [f[2] for f in forms if f[0] == Atom("function")]


def test_print_is_helper_call():
    body = _body('def m(x):\n    print(x)\n')
    assert body[0] == Atom("call")
    assert body[2] == (Atom("atom"), 2, Atom("squeal_print"))
    assert body[3] == [(Atom("var"), 2, Atom("X"))]


def test_print_emits_helpers_only_when_used():
    names = _function_names('def m(x):\n    print(x)\n')
    assert names[1:] == [
        Atom("squeal_print"), Atom("squeal_str"),
        Atom("squeal_str_tuple"), Atom("squeal_str_map"),
    ]
    names = _function_names("def m(x):\n    x\n")
    assert names == [Atom("m")]


def test_print_errors():
    for source in [
        "def m():\n    print()\n",
        "def m(a, b):\n    print(a, b)\n",
        "def m(a):\n    print(a, sep=',')\n",
        "def print(x):\n    x\n",
    ]:
        with pytest.raises(SquealError):
            compile_source(source, "src/m.ee", "m")


def test_print_representation_in_erl():
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    src.mkdir()
    (src / "p.ee").write_text(
        'def txt():\n    print("hi")\n    "|"\n'
        "def num():\n    print(42)\n    \"|\"\n"
        "def flt():\n    print(1.5)\n    \"|\"\n"
        "def neg():\n    print(-0.25)\n    \"|\"\n"
        "def lst():\n    print([1, 'a', \"s\"])\n    \"|\"\n"
        "def tup():\n    print((1, 2))\n    \"|\"\n"
        "def one():\n    print((1,))\n    \"|\"\n"
        "def nothing():\n    print(())\n    \"|\"\n"
        "def dct():\n    print({'b': 2, 'a': 1})\n    \"|\"\n"
        "def edct():\n    print({})\n    \"|\"\n"
        "def atoms():\n    print(True)\n    print(None)\n    print('ok')\n    \"|\"\n"
        "def nested():\n    print([[1], {'k': (2,)}])\n    \"|\"\n"
        "def value():\n    print(\"hi\")\n    7\n"
    )
    subprocess.run(
        [sys.executable, "-m", "squeal", "build", str(tmp)],
        cwd=ROOT, check=True, capture_output=True,
    )
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    expr = (
        'io:format("~ts", [p:txt()]), io:format("~ts", [p:num()]), '
        'io:format("~ts", [p:flt()]), io:format("~ts", [p:neg()]), '
        'io:format("~ts", [p:lst()]), io:format("~ts", [p:tup()]), '
        'io:format("~ts", [p:one()]), io:format("~ts", [p:nothing()]), '
        'io:format("~ts", [p:dct()]), io:format("~ts", [p:edct()]), '
        'io:format("~ts", [p:atoms()]), io:format("~ts", [p:nested()]), '
        'io:format("~p", [p:value()]), halt().'
    )
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval", expr],
        capture_output=True, text=True, check=True,
    )
    assert out.stdout == (
        "hi\n|42\n|1.5\n|-0.25\n|[1, a, s]\n|(1, 2)\n|(1,)\n|()\n|"
        "{a: 1, b: 2}\n|{}\n|true\nnil\nok\n|[[1], {k: (2,)}]\n|hi\n7"
    )


def test_print_in_notebook():
    from IPython.core.interactiveshell import InteractiveShell
    from IPython.utils.capture import capture_output
    import squeal.notebook as nb

    shell = InteractiveShell.instance()
    nb.load_ipython_extension(shell)
    try:
        with capture_output() as out:
            shell.run_cell('print("hi")')
        # neither the cell value (nil) nor any extra noise
        assert out.stdout.strip() == "hi"

        with capture_output() as out:
            shell.run_cell("print([1, 2])")
        assert out.stdout.strip() == "[1, 2]"

        with capture_output() as out:
            shell.run_cell("x = 5")
        assert out.stdout.strip() == "5"
    finally:
        nb.unload_ipython_extension(shell)
        InteractiveShell.clear_instance()


def test_print_order_in_repl(capsys):
    from squeal.session import Session, compile_cell
    from squeal.repl import ErlangRepl

    s = Session()
    repl = ErlangRepl()
    try:
        forms, _ = compile_cell("print(1)\nprint(2)\n", s)
        assert repl.eval_forms(forms) == ("ok", "nil")
    finally:
        repl.close()
    # like Python: newlines end each line instead of leading the block
    assert capsys.readouterr().out == "1\n2\n"
