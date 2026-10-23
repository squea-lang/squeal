"""Standard-library methods (methods.md): forms, dispatch, semantics."""

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

NOMATCH = (Atom("atom"), 2, Atom("nomatch"))


def _body(source: str, name: str = "m"):
    forms = compile_source(source, "src/m.ee", name)
    fn = [f for f in forms if f[0] == Atom("function")][0]
    return fn[4][0][4][0]


def _remote(form):
    """Unwrap a form to {remote, ...} if it is a remote call."""
    return form[2] if form[0] == Atom("call") else None


def test_dict_methods_are_maps_calls():
    for source, fun, arity in [
        ("def m(d):\n    d.keys()\n", "keys", 1),
        ("def m(d):\n    d.values()\n", "values", 1),
        ("def m(d):\n    d.items()\n", "to_list", 1),
    ]:
        body = _body(source)
        remote = _remote(body)
        assert remote[2] == (Atom("atom"), 2, Atom("maps"))
        assert remote[3] == (Atom("atom"), 2, Atom(fun))
        assert len(body[3]) == arity


def test_dict_get_one_and_two_args():
    body = _body("def m(d):\n    d.get('a')\n")
    assert body[3] == [
        (Atom("atom"), 2, Atom("a")),
        (Atom("var"), 2, Atom("D")),
        (Atom("atom"), 2, Atom("nil")),
    ]

    body = _body("def m(d, z):\n    d.get('a', z)\n")
    assert body[3] == [
        (Atom("atom"), 2, Atom("a")),
        (Atom("var"), 2, Atom("D")),
        (Atom("var"), 2, Atom("Z")),
    ]


def test_str_method_checks_binary_type():
    body = _body("def m(s):\n    s.lower()\n")
    assert body[0] == Atom("case")
    assert body[2] == (Atom("var"), 2, Atom("S"))
    ok, fail = body[3]
    assert ok[2] == [(Atom("var"), 2, Atom("_squeal@m1"))]
    guard = ok[3][0][0]
    assert _remote(guard)[3] == (Atom("atom"), 2, Atom("is_binary"))
    assert ok[4][0][2] == (
        Atom("remote"), 2,
        (Atom("atom"), 2, Atom("string")), (Atom("atom"), 2, Atom("lowercase")),
    )
    # the non-matching branch raises {bad_receiver, method, value}
    assert fail[2] == [(Atom("var"), 2, Atom("_squeal@r2"))]
    error = fail[4][0]
    assert error[2] == (Atom("remote"), 2,
                        (Atom("atom"), 2, Atom("erlang")), (Atom("atom"), 2, Atom("error")))
    assert error[3][0][2] == [
        (Atom("atom"), 2, Atom("bad_receiver")),
        (Atom("atom"), 2, Atom("lower")),
        (Atom("var"), 2, Atom("_squeal@r2")),
    ]


def test_endswith_compares_tail():
    body = _body('def m(s):\n    s.endswith("yz")\n')
    andalso = body[3][0][4][0]
    assert andalso[2] == Atom("andalso")
    assert andalso[4][2] == Atom("=:=")  # tail =:= "yz"


def test_count_dispatches_on_list_and_tuple():
    body = _body("def m(xs, t):\n    xs.count(1)\n")
    assert body[0] == Atom("case")
    checks = [clause[3][0][0][2][3][2] for clause in body[3][:2]]
    assert checks == [Atom("is_list"), Atom("is_tuple")]


def test_unknown_method_is_compile_error():
    with pytest.raises(SquealError, match="method"):
        compile_source("def m(s):\n    s.foo()\n", "src/m.ee", "m")
    with pytest.raises(SquealError, match="method"):
        compile_source("def m(s):\n    s.get()\n", "src/m.ee", "m")
    with pytest.raises(SquealError, match="method"):
        compile_source("def m(s):\n    s.lower(1)\n", "src/m.ee", "m")


def test_methods_semantics_in_erl():
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    src.mkdir()
    (src / "methods.ee").write_text(
        "def keys(d):\n    d.keys()\n"
        "def values(d):\n    d.values()\n"
        "def items(d):\n    d.items()\n"
        "def get1(d):\n    d.get('a')\n"
        "def get2(d):\n    d.get('b', 0)\n"
        "def starts(s):\n    s.startswith(\"ab\")\n"
        "def ends(s):\n    s.endswith(\"yz\")\n"
        "def lower(s):\n    s.lower()\n"
        "def upper(s):\n    s.upper()\n"
        "def strip(s):\n    s.strip()\n"
        "def lstrip(s):\n    s.lstrip()\n"
        "def rstrip(s):\n    s.rstrip()\n"
        "def split0(s):\n    s.split()\n"
        "def split1(s):\n    s.split(\",\")\n"
        "def join(s, parts):\n    s.join(parts)\n"
        "def replace(s):\n    s.replace(\"a\", \"b\")\n"
        "def splitlines(s):\n    s.splitlines()\n"
        "def count_list(xs):\n    xs.count(1)\n"
        "def count_tuple(t):\n    t.count(1)\n"
        "def chain(s):\n    s.strip().lower().split(\",\")\n"
        "def wrong(s):\n    s.lower()\n"
    )
    subprocess.run(
        [sys.executable, "-m", "squeal", "build", str(tmp)],
        cwd=ROOT, check=True, capture_output=True,
    )
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"

    cases = [
        ("keys(#{a => 1})", "[a]"),
        ("values(#{a => 1})", "[1]"),
        ("items(#{a => 1})", "[{a,1}]"),
        ("get1(#{a => 1})", "1"),
        ("get1(#{})", "nil"),
        ("get2(#{a => 1})", "0"),
        ('starts(<<"abcd">>)', "true"),
        ('starts(<<"xbcd">>)', "false"),
        ('ends(<<"xxyz">>)', "true"),
        ('ends(<<"xyzz">>)', "false"),
        ('lower(<<"ABC">>)', '<<"abc">>'),
        ('upper(<<"abc">>)', '<<"ABC">>'),
        ('strip(<<"  a  ">>)', '<<"a">>'),
        ('lstrip(<<"  a  ">>)', '<<"a  ">>'),
        ('rstrip(<<"  a  ">>)', '<<"  a">>'),
        ('split0(<<" a  b ">>)', '[<<"a">>,<<"b">>]'),
        ('split1(<<"a,b">>)', '[<<"a">>,<<"b">>]'),
        ('join(<<",">>, [<<"a">>,<<"b">>])', '<<"a,b">>'),
        ('replace(<<"aaa">>)', '<<"bbb">>'),
        ('splitlines(<<"a\\r\\nb\\nc">>)', '[<<"a">>,<<"b">>,<<"c">>]'),
        ('splitlines(<<>>)', "[]"),
        ('splitlines(<<"a\\n">>)', '[<<"a">>]'),
        ('splitlines(<<"\\n">>)', "[<<>>]"),
        ("count_list([1,2,1])", "2"),
        ("count_tuple({1,2,1})", "2"),
        ('chain(<<" A, B ">>)', '[<<"a">>,<<" b">>]'),
    ]
    expr = ", ".join(f'io:format("~p|", [methods:{c}])' for c, _ in cases)
    expr += ', io:format("~p~n", [catch methods:wrong([1,2])]), halt().'
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval", expr],
        capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip().split("|")[:-1] == [expected for _, expected in cases]
    # a wrong receiver names the method and the value
    assert "{bad_receiver,lower," in out.stdout.rsplit("|", 1)[-1]


def test_items_in_comprehension_still_works():
    body = _body("def m(d):\n    [k for k, v in d.items()]\n")
    assert body[0] == Atom("lc")
    assert body[3][0][0] == Atom("m_generate")


def test_join_rejects_non_strings():
    ebin = _build_join()
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval",
         'io:format("~p ~p | ~p~n", [j:ok(), j:empty(), catch j:bad()]), halt().'],
        capture_output=True, text=True, check=True,
    )
    assert out.stdout.startswith('<<"a,b,c">> <<>> | ')
    assert "{bad_argument,join,1}" in out.stdout


def _build_join() -> pathlib.Path:
    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "src").mkdir()
    (tmp / "src" / "j.ee").write_text(
        'def ok():\n    ",".join(["a", "b", "c"])\n'
        "def empty():\n    \",\".join([])\n"
        "def bad():\n    \",\".join([1, 2])\n"
    )
    subprocess.run(
        [sys.executable, "-m", "squeal", "build", str(tmp)],
        cwd=ROOT, check=True, capture_output=True,
    )
    return tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
