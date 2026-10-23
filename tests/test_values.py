"""Обычные тесты этапа 2: формы и семантика конструкций без аналога в Gleam
(//, %, **, /, ==, словарь, атом) — см. architecture.md."""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile

from squeal.compiler import compile_source
from squeal.term import Atom

ERL = shutil.which("erl")
ROOT = pathlib.Path(__file__).resolve().parent.parent


def _body(source: str, name: str = "m"):
    """Единственная функция модуля и её тело (последнее выражение clause)."""
    forms = compile_source(source, "src/m.ee", name)
    fn = [f for f in forms if f[0] == Atom("function")][0]
    return fn[4][0][4][0]


def test_mod_uses_helper():
    body = _body("def m(a, b):\n    a % b\n")
    assert body[0] == Atom("call")
    assert body[2] == (Atom("atom"), 2, Atom("squeal_mod"))


def test_floordiv_uses_helper():
    body = _body("def m(a, b):\n    a // b\n")
    assert body[0] == Atom("call")
    assert body[2] == (Atom("atom"), 2, Atom("squeal_floordiv"))


def test_pow_emits_helper():
    forms = compile_source("def m(a, b):\n    a ** b\n", "src/m.ee", "m")
    names = [f[2] for f in forms if f[0] == Atom("function")]
    assert names == [Atom("m"), Atom("_squeal_pow"), Atom("_squeal_pow_loop")]


def test_dict_atom_and_string_keys():
    body = _body("def m():\n    {'a': 1}\n")
    assert body == (Atom("map"), 2, [(Atom("map_field_assoc"), 2, (Atom("atom"), 2, Atom("a")), (Atom("integer"), 2, 1))])

    body = _body("def m():\n    {\"a\": 1}\n")
    key = body[2][0][2]
    assert key[0] == Atom("bin")             # бинарный ключ


def test_eq_form():
    body = _body("def m(a, b):\n    a == b\n")
    assert body == (Atom("op"), 2, Atom("=="), (Atom("var"), 2, Atom("A")), (Atom("var"), 2, Atom("B")))


def test_semantics_in_erl():
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    src.mkdir()
    (src / "vals.ee").write_text(
        "def mod(a, b):\n    a % b\n"
        "def floordiv(a, b):\n    a // b\n"
        "def power(a, b):\n    a ** b\n"
        "def fdiv(a, b):\n    a / b\n"
        "def eq(a, b):\n    a == b\n"
        "def d1():\n    {'a': 1}\n"
        "def d2():\n    {\"a\": 1}\n"
        "def atom():\n    'ok'\n"
    )
    subprocess.run(
        [sys.executable, "-m", "squeal", "build", str(tmp)],
        cwd=ROOT, check=True, capture_output=True,
    )
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"

    calls = [
        ("mod(-7,2)", "1"),
        ("floordiv(-7,2)", "-4"),
        ("power(2,10)", "1024"),
        ("power(2,-1)", "0.5"),
        ("fdiv(7,2)", "3.5"),
        ("eq(1,1.0)", "true"),
        ("d1()", "#{a => 1}"),
        ("d2()", '#{<<"a">> => 1}'),
        ("atom()", "ok"),
    ]
    expr = ", ".join(f'io:format("~p ", [vals:{c}])' for c, _ in calls) + ", io:format(\"~n\"), halt()."
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval", expr],
        capture_output=True, text=True, check=True,
    )
    for _, expected in calls:
        assert expected in out.stdout, f"{expected} not in {out.stdout!r}"


def _clause_body(source: str, name: str = "m"):
    forms = compile_source(source, "src/m.ee", name)
    fn = [f for f in forms if f[0] == Atom("function")][0]
    return fn[4][0][4]


def test_destructure_list_form():
    body = _clause_body("def m(l):\n    head, *rest = l\n    head\n")
    assert body[0] == (
        Atom("match"), 2,
        (Atom("cons"), 2, (Atom("var"), 2, Atom("Head")), (Atom("var"), 2, Atom("Rest"))),
        (Atom("var"), 2, Atom("L")),
    )
    assert body[1] == (Atom("var"), 3, Atom("Head"))


def test_merge_form():
    body = _clause_body("def m(d):\n    d |= {'k': 1}\n    d\n")
    assert body[0][0] == Atom("match")
    assert body[0][2] == (Atom("var"), 2, Atom("D@1"))
    call = body[0][3]
    assert call[0] == Atom("call")
    assert call[2] == (Atom("remote"), 2, (Atom("atom"), 2, Atom("maps")), (Atom("atom"), 2, Atom("merge")))


def test_forbidden_constructs():
    import pytest
    from squeal.errors import SquealError
    for source in [
        "def f():\n    for x in [1]:\n        x\n",
        "def f():\n    while True:\n        pass\n",
        "def f():\n    x = 1\n    del x\n",
        "def f(x):\n    x += 1\n",
        "def f(x):\n    x[0] = 1\n",
    ]:
        with pytest.raises(SquealError):
            compile_source(source, "src/m.ee", "m")


def test_assignment_semantics_in_erl():
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    src.mkdir()
    (src / "v.ee").write_text(
        "def reassign():\n    x = 1\n    x = x + 1\n    x\n"
        "def destructure(l):\n    head, *rest = l\n    head\n"
        "def tupd(t):\n    a, b = t\n    a + b\n"
        "def merge(m):\n    m |= {'k': 1}\n    m\n"
    )
    subprocess.run(
        [sys.executable, "-m", "squeal", "build", str(tmp)],
        cwd=ROOT, check=True, capture_output=True,
    )
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    expr = (
        'io:format("~p ~p ~p ~p ~p~n", [v:reassign(), v:destructure([1,2,3]), '
        'v:tupd({10,20}), maps:get(k, v:merge(#{a => 9})), maps:get(a, v:merge(#{a => 9}))]), '
        'halt().'
    )
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval", expr],
        capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "2 1 30 1 9"


def test_if_form():
    body = _clause_body("def f(c):\n    if c:\n        v = 1\n    else:\n        v = 2\n    v\n")
    assert body[0][0] == Atom("match")
    assert body[0][2] == (Atom("var"), 2, Atom("V"))
    case = body[0][3]
    assert case[0] == Atom("case") and len(case[3]) == 2
    assert case[3][0][2] == [(Atom("atom"), 2, Atom("true"))]
    assert case[3][1][2] == [(Atom("atom"), 2, Atom("false"))]


def test_match_no_fallthrough():
    body = _clause_body("def f(v):\n    match v:\n        case 1:\n            r = 'a'\n        case 2:\n            r = 'b'\n    r\n")
    case = body[0][3]
    assert len(case[3]) == 2  # без fallthrough


def test_or_pattern_expands():
    body = _clause_body("def f(v):\n    match v:\n        case 1 | 2:\n            r = 'a'\n        case _:\n            r = 'b'\n    r\n")
    case = body[0][3]
    assert len(case[3]) == 3
    assert case[3][0][2] == [(Atom("integer"), 3, 1)]
    assert case[3][1][2] == [(Atom("integer"), 3, 2)]


def test_capture_pattern():
    body = _clause_body("def f(v):\n    match v:\n        case n:\n            r = n\n    r\n")
    case = body[0][3]
    assert case[3][0][2] == [(Atom("var"), 3, Atom("N"))]


def test_branch_errors():
    import pytest
    from squeal.errors import SquealError
    for source in [
        # разные цели — только в НЕхвостовой позиции (в хвосте теперь допустимы)
        "def f(c):\n    if c:\n        a = 1\n    else:\n        b = 2\n    a\n",
        "def f(v):\n    match v:\n        case 1:\n            a = 1\n        case 2:\n            b = 2\n    a\n",
        "def f(c):\n    if c:\n        v = 1\n",   # if без else
    ]:
        with pytest.raises(SquealError):
            compile_source(source, "src/m.ee", "m")


def test_branching_semantics_and_crash():
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    src.mkdir()
    (src / "branch.ee").write_text(
        "def iflike(c, a, b):\n    if c:\n        value = a\n    else:\n        value = b\n    value\n"
        "def mc(v, x, y):\n    match v:\n        case 1:\n            value = x\n        case 2:\n            value = x\n        case _:\n            value = y\n    value\n"
        "def guarded(v):\n    match v:\n        case n if n > 0:\n            value = n\n        case _:\n            value = 0\n    value\n"
        "def orp(v, x):\n    match v:\n        case 1 | 2:\n            value = x\n        case _:\n            value = 0\n    value\n"
        "def cap(v):\n    match v:\n        case n:\n            value = n\n    value\n"
        "def crashy(v):\n    match v:\n        case 1:\n            value = 'ok'\n    value\n"
    )
    subprocess.run(
        [sys.executable, "-m", "squeal", "build", str(tmp)],
        cwd=ROOT, check=True, capture_output=True,
    )
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    expr = (
        'io:format("~p ~p ~p ~p ~p ~p ~p ~p~n", [branch:iflike(true,10,20), '
        'branch:iflike(false,10,20), branch:mc(1,5,9), branch:mc(3,5,9), '
        'branch:guarded(5), branch:guarded(-5), branch:orp(2,7), branch:cap(42)]), halt().'
    )
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval", expr],
        capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "10 20 5 9 5 0 7 42"

    crash = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval",
         'io:format("~p~n", [branch:crashy(2)]), halt().'],
        capture_output=True, text=True,
    )
    assert crash.returncode != 0
    assert "case_clause" in crash.stderr


def test_error_message_has_file_and_line():
    from squeal.errors import SquealError
    try:
        compile_source("def f():\n    for x in [1]:\n        x\n", "src/m.ee", "m")
    except SquealError as e:
        assert str(e).startswith("src/m.ee:2:")
        return
    assert False, "ожидали SquealError"


def test_cli_error_exit_code():
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    src.mkdir()
    (src / "bad.ee").write_text("def f():\n    for x in [1]:\n        x\n")
    r = subprocess.run(
        [sys.executable, "-m", "squeal", "build", str(tmp)],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert r.returncode == 1
    assert r.stderr.startswith("squeal: src/bad.ee:2:")
    assert "Traceback" not in r.stderr


_SRC_CLASS = "class CustomType(StartingWithAtom):\n    x: int\n    y: int\n"


def test_constructor_form():
    body = _clause_body(_SRC_CLASS + "def make():\n    CustomType(1, 2)\n")
    t = body[0]
    assert t[0] == Atom("tuple")
    assert t[2][0][0] == Atom("atom") and t[2][0][2] == Atom("custom_type")
    assert t[2][1][2] == 1 and t[2][2][2] == 2


def test_class_pattern_form():
    body = _clause_body(
        _SRC_CLASS + "def f(t):\n    match t:\n        case CustomType(x, y):\n            r = (x, y)\n    r\n"
    )
    case = body[0][3]
    pat = case[3][0][2][0]
    assert pat[0] == Atom("tuple")
    assert pat[2][0][2] == Atom("custom_type")
    assert pat[2][1][0] == Atom("var")
    assert pat[2][2][0] == Atom("var")


def test_class_base_errors():
    import pytest
    from squeal.errors import SquealError
    for source in [
        "class Foo(NativeRecord):\n    x: int\n",
        "class Foo:\n    x: int\n",
        "class Foo(StartingWithAtom):\n    x = 1\n",
    ]:
        with pytest.raises(SquealError):
            compile_source(source, "src/m.ee", "m")


def test_class_semantics_in_erl():
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    src.mkdir()
    (src / "klass.ee").write_text(
        _SRC_CLASS
        + "def make():\n    CustomType(1, 2)\n"
        + "def get(t):\n    match t:\n        case CustomType(x, _):\n            r = x\n    r\n"
    )
    subprocess.run(
        [sys.executable, "-m", "squeal", "build", str(tmp)],
        cwd=ROOT, check=True, capture_output=True,
    )
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval",
         'io:format("~p ~p~n", [klass:make(), klass:get({custom_type,5,6})]), halt().'],
        capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "{custom_type,1,2} 5"


def _expr_form(source: str):
    return _clause_body(source)[0]


# --- этап 6: лямбды и включения ---


def test_lambda_form():
    body = _expr_form("def f():\n    lambda x: x + 1\n")
    assert body[0] == Atom("fun")
    clause = body[2][1][0]
    assert clause[2] == [(Atom("var"), 2, Atom("X"))]
    assert clause[4][0][2] == Atom("+")


def test_lambda_two_params():
    body = _expr_form("def f():\n    lambda x, y: x + y\n")
    clause = body[2][1][0]
    assert len(clause[2]) == 2


def test_call_bound_lambda():
    body = _clause_body("def f():\n    g = lambda x: x + 1\n    g(2)\n")
    call = body[1]
    assert call[2] == (Atom("var"), 3, Atom("G"))  # вызов переменной, не атома


def test_listcomp_basic():
    body = _expr_form("def f(l):\n    [x for x in l]\n")
    assert body[0] == Atom("lc")
    gen = body[3][0]
    assert gen[0] == Atom("generate")
    assert gen[2] == (Atom("var"), 2, Atom("X"))
    assert gen[3][0] == Atom("call") and gen[3][2][2] == Atom("squeal_iter")


def test_listcomp_expr():
    body = _expr_form("def f(l):\n    [x * 2 for x in l]\n")
    assert body[2][2] == Atom("*")  # элемент — x * 2


def test_listcomp_filter():
    body = _expr_form("def f(l):\n    [x for x in l if x > 0]\n")
    assert body[3][1][2] == Atom(">")  # фильтр — выражение


def test_listcomp_two_filters():
    body = _expr_form("def f(l, c1, c2):\n    [x for x in l if c1 if c2]\n")
    assert len(body[3]) == 3  # generate + 2 фильтра


def test_listcomp_nested():
    body = _expr_form("def f(l, m):\n    [x + y for x in l for y in m]\n")
    assert [q[0] for q in body[3]] == [Atom("generate"), Atom("generate")]


def test_listcomp_pattern_target():
    body = _expr_form("def f(pairs):\n    [a for (a, b) in pairs]\n")
    gen = body[3][0]
    assert gen[2][0] == Atom("tuple")  # образец {A, B}


def test_dictcomp_keys():
    forms = compile_source("def f(m):\n    {k: 1 for k in m}\n", "src/m.ee", "m")
    fn = [f for f in forms if f[0] == Atom("function")][0]
    body = fn[4][0][4][0]
    assert body[0] == Atom("mc")
    gen = body[3][0]
    assert gen[3][0] == Atom("call") and gen[3][2][2] == Atom("squeal_iter")
    assert any(f[2] == Atom("squeal_iter") for f in forms if f[0] == Atom("function"))


def test_dictcomp_items():
    body = _expr_form("def f(m):\n    {k: v for k, v in m.items()}\n")
    assert body[0] == Atom("mc")
    gen = body[3][0]
    assert gen[0] == Atom("m_generate")
    assert gen[2][0] == Atom("map_field_exact")


def test_dictcomp_pairs_list():
    body = _expr_form("def f(pairs):\n    {k: v for k, v in pairs}\n")
    gen = body[3][0]
    assert gen[0] == Atom("generate")
    assert gen[2][0] == Atom("tuple")  # {K, V} <- squeal_iter(Pairs)


def test_items_expression():
    body = _clause_body("def f(m):\n    p = m.items()\n")
    call = body[0][3]
    assert call[2] == (Atom("remote"), 2, (Atom("atom"), 2, Atom("maps")), (Atom("atom"), 2, Atom("to_list")))


def test_setcomp_and_genexpr_errors():
    import pytest
    from squeal.errors import SquealError
    for source in [
        "def f(l):\n    {x for x in l}\n",
        "def f(l):\n    (x for x in l)\n",
    ]:
        with pytest.raises(SquealError):
            compile_source(source, "src/m.ee", "m")


def test_comprehension_semantics_in_erl():
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    src.mkdir()
    (src / "comp.ee").write_text(
        "def lc(l):\n    [x * 2 for x in l]\n"
        "def lcf(l):\n    [x for x in l if x > 1]\n"
        "def dc(m):\n    {k: 1 for k in m}\n"
        "def dci(m):\n    {k: v for k, v in m.items()}\n"
        "def nested(l, m):\n    [x + y for x in l for y in m]\n"
        "def pat(pairs):\n    [a for (a, b) in pairs]\n"
        "def lam(y):\n    f = lambda x: x + y\n    f(1)\n"
    )
    subprocess.run(
        [sys.executable, "-m", "squeal", "build", str(tmp)],
        cwd=ROOT, check=True, capture_output=True,
    )
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    expr = (
        'io:format("~p ~p ~p ~p ~p ~p ~p ~p~n", [comp:lc([1,2,3]), comp:lcf([1,2,3]), '
        'maps:get(a, comp:dc(#{a => 1, b => 2})), maps:get(b, comp:dc(#{a => 1, b => 2})), '
        'maps:get(a, comp:dci(#{a => 9})), comp:nested([1,2],[10,20]), '
        'comp:pat([{1,2},{3,4}]), comp:lam(10)]), halt().'
    )
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval", expr],
        capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "[2,4,6] [2,3] 1 1 9 [11,21,12,22] [1,3] 11"


def test_filter_non_bool_skips():
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    src.mkdir()
    (src / "f.ee").write_text("def f(l):\n    [x for x in l if 1]\n")
    subprocess.run(
        [sys.executable, "-m", "squeal", "build", str(tmp)],
        cwd=ROOT, check=True, capture_output=True,
    )
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval", 'io:format("~p~n",[f:f([1,2])]), halt().'],
        capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "[]"  # фильтр 1 (не true) → пропуск, не падение


def test_import_remote_form():
    call = _expr_form("from a.b.c import f\ndef g():\n    f(1)\n")
    assert call[0] == Atom("call")
    assert call[2] == (Atom("remote"), 3, (Atom("atom"), 0, Atom("a@b@c")), (Atom("atom"), 0, Atom("f")))
    assert call[3] == [(Atom("integer"), 3, 1)]


def test_import_multiple_and_as():
    src = "from a.b import f, g as h\ndef x():\n    f()\ndef y():\n    h()\n"
    forms = compile_source(src, "src/m.ee", "m")
    fns = {f[2]: f for f in forms if f[0] == Atom("function")}
    fx = fns[Atom("x")][4][0][4][0]
    hy = fns[Atom("y")][4][0][4][0]
    assert fx[2] == (Atom("remote"), 3, (Atom("atom"), 0, Atom("a@b")), (Atom("atom"), 0, Atom("f")))
    assert hy[2] == (Atom("remote"), 5, (Atom("atom"), 0, Atom("a@b")), (Atom("atom"), 0, Atom("g")))


def test_import_errors():
    import pytest
    from squeal.errors import SquealError
    for source in [
        "from a.b import *\ndef f():\n    1\n",
        "import a.b\ndef f():\n    1\n",
    ]:
        with pytest.raises(SquealError):
            compile_source(source, "src/m.ee", "m")


def test_nested_module_build():
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    (src / "a" / "b").mkdir(parents=True)
    (src / "a" / "b" / "c.ee").write_text("def f():\n    42\n")
    (src / "main.ee").write_text("from a.b.c import f\ndef g():\n    f()\n")
    subprocess.run(
        [sys.executable, "-m", "squeal", "build", str(tmp)],
        cwd=ROOT, check=True, capture_output=True,
    )
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    assert (ebin / "a@b@c.beam").exists()
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval", 'io:format("~p~n",[main:g()]), halt().'],
        capture_output=True, text=True, check=True,
    )
    assert out.stdout.strip() == "42"


# --- регрессии на исправленные баги ---


def test_term_float_format():
    from squeal.term import term_to_erlang
    assert term_to_erlang(1e-5) == "1.0e-5"
    assert term_to_erlang(1e20) == "1.0e20"
    assert term_to_erlang(1.5) == "1.5"
    assert term_to_erlang(3.0) == "3.0"


def test_term_string_escaping():
    from squeal.term import term_to_erlang
    assert term_to_erlang("a\rb") == '"a\\rb"'
    assert term_to_erlang("a\x00b") == '"a\\x{0}b"'


def test_float_scientific_in_erl():
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    src.mkdir()
    (src / "f.ee").write_text("def f():\n    1e-5\ndef g():\n    1e10\n")
    subprocess.run([sys.executable, "-m", "squeal", "build", str(tmp)],
                   cwd=ROOT, check=True, capture_output=True)
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval",
         'io:format("~p ~p~n", [f:f(), f:g()]), halt().'],
        capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "1.0e-5 1.0e10"


def test_nonascii_string_in_erl():
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    src.mkdir()
    (src / "s.ee").write_text('def f():\n    "привет"\n')
    subprocess.run([sys.executable, "-m", "squeal", "build", str(tmp)],
                   cwd=ROOT, check=True, capture_output=True)
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval",
         'io:format("~p~n", [s:f() =:= <<"привет"/utf8>>]), halt().'],
        capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "true"


def test_items_nonname_receiver():
    body = _expr_form("def f(g):\n    {k: v for k, v in g().items()}\n")
    gen = body[3][0]
    assert gen[0] == Atom("generate")          # не m_generate
    assert gen[2][0] == Atom("tuple")          # {K, V}
    assert gen[3][0] == Atom("call") and gen[3][2][2] == Atom("squeal_iter")


def test_bare_tuple_pattern():
    body = _clause_body(
        "def f(v):\n    match v:\n        case 1, 2:\n            r = 1\n        case _:\n            r = 0\n    r\n")
    pat = body[0][3][3][0][2][0]
    assert pat[0] == Atom("tuple")             # не cons


def test_constructor_arity():
    import pytest
    from squeal.errors import SquealError
    for src in [
        "class T(StartingWithAtom):\n    x: int\ndef f():\n    T(1, 2)\n",
        "class T(StartingWithAtom):\n    x: int\ndef f(v):\n    match v:\n        case T(x, y):\n            r = x\n        case _:\n            r = 0\n    r\n",
    ]:
        with pytest.raises(SquealError):
            compile_source(src, "src/m.ee", "m")


def test_duplicate_class_error():
    import pytest
    from squeal.errors import SquealError
    with pytest.raises(SquealError):
        compile_source(
            "class T(StartingWithAtom):\n    x: int\nclass T(StartingWithAtom):\n    y: int\n",
            "src/m.ee", "m")


def test_no_temp_variables():
    # % и // больше не строят inline begin…end со временными `_squeal@N`
    body = _expr_form("def m(_value, y):\n    _value % y\n")
    assert body[0] == Atom("call")
    assert body[2] == (Atom("atom"), 2, Atom("squeal_mod"))
    assert body[3][0] == (Atom("var"), 2, Atom("_value"))


def test_build_default_dir_and_app_file():
    import os
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    src.mkdir()
    (src / "hello.ee").write_text('def hello():\n    "hi"\n')
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    subprocess.run([sys.executable, "-m", "squeal", "build"],
                   cwd=tmp, env=env, check=True, capture_output=True)
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    assert (ebin / "hello.beam").exists()
    assert (ebin / f"{tmp.name}.app").exists()


def test_listcomp_over_dict_keys():
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    src.mkdir()
    (src / "lc.ee").write_text("def f(m):\n    [k for k in m]\n")
    subprocess.run([sys.executable, "-m", "squeal", "build", str(tmp)],
                   cwd=ROOT, check=True, capture_output=True)
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval",
         'io:format("~p~n", [lc:f(#{a => 1})]), halt().'],
        capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[a]"


def test_builtin_ok_error():
    body = _expr_form("def f():\n    Ok(1)\n")
    assert body == (Atom("tuple"), 2, [(Atom("atom"), 2, Atom("ok")), (Atom("integer"), 2, 1)])
    body = _expr_form("def f():\n    Error('boom')\n")
    assert body == (Atom("tuple"), 2, [(Atom("atom"), 2, Atom("error")), (Atom("atom"), 2, Atom("boom"))])


def test_builtin_ok_error_pattern():
    body = _clause_body(
        "def f(r):\n    match r:\n        case Ok(v):\n            x = v\n        case Error(e):\n            x = 0\n    x\n"
    )
    case = body[0][3]
    assert case[3][0][2][0][2][0] == (Atom("atom"), 3, Atom("ok"))
    assert case[3][1][2][0][2][0] == (Atom("atom"), 5, Atom("error"))


def test_builtin_ok_arity_error():
    import pytest
    from squeal.errors import SquealError
    with pytest.raises(SquealError):
        compile_source("def f():\n    Ok(1, 2)\n", "src/m.ee", "m")


def test_rewrite_pattern_assignments():
    from squeal.frontend import rewrite_pattern_assignments
    assert rewrite_pattern_assignments("Ok(v) = f(1)\n") == "__pattern_match__(Ok(v), f(1))\n"
    assert rewrite_pattern_assignments("x = 1\n") == "x = 1\n"
    assert rewrite_pattern_assignments("a, b = (1, 2)\n") == "a, b = (1, 2)\n"
    assert rewrite_pattern_assignments("f(x)\n") == "f(x)\n"


def test_pattern_assign_constructor():
    body = _clause_body("def f(v):\n    Ok(x) = v\n    x\n")
    assert body[0][0] == Atom("match")
    assert body[0][2] == (
        Atom("tuple"), 2,
        [(Atom("atom"), 2, Atom("ok")), (Atom("var"), 2, Atom("X"))],
    )
    assert body[1] == (Atom("var"), 3, Atom("X"))


def test_pattern_assign_errors():
    import pytest
    from squeal.errors import SquealError
    with pytest.raises(SquealError):
        compile_source("def f(v):\n    f(x) = v\n", "src/m.ee", "m")      # не класс
    with pytest.raises(SquealError):
        compile_source("def f(v):\n    Ok(x, y) = v\n", "src/m.ee", "m")   # арность


def test_pattern_assign_duplicate_name_errors():
    import pytest
    from squeal.errors import SquealError
    with pytest.raises(SquealError):
        compile_source("def f(v):\n    Ok(x, x) = v\n", "src/m.ee", "m")


def test_arity_overloading_in_module():
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    src.mkdir()
    (src / "fib.ee").write_text(
        "def fib(N):\n    fib(N, 0, 1)\n\n"
        "def fib(N, current, next):\n    match N:\n        case 0:\n            ret = current\n"
        "        case _ if N > 0:\n            ret = fib(N - 1, next, current + next)\n    ret\n"
    )
    subprocess.run([sys.executable, "-m", "squeal", "build", str(tmp)],
                   cwd=ROOT, check=True, capture_output=True)
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval",
         'io:format("~p ~p~n", [fib:fib(10), fib:fib(10, 0, 1)]), halt().'],
        capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "55 55"


def test_duplicate_same_arity_rejected():
    import pytest
    from squeal.errors import SquealError
    with pytest.raises(SquealError):
        compile_source("def f(x):\n    x\ndef f(y):\n    y\n", "src/m.ee", "m")


def test_tail_if_returns_value():
    body = _clause_body("def f(c):\n    if c:\n        1\n    else:\n        2\n")
    assert len(body) == 1 and body[0][0] == Atom("case")
    assert body[0][2] == (Atom("var"), 2, Atom("C"))


def test_tail_match_returns_value():
    body = _clause_body(
        "def f(v):\n    match v:\n        case 1:\n            'one'\n        case _:\n            'other'\n")
    assert len(body) == 1 and body[0][0] == Atom("case")
    assert len(body[0][3]) == 2


def test_tail_case_with_assignments_still_binds():
    body = _clause_body("def f(c):\n    if c:\n        v = 1\n    else:\n        v = 2\n")
    assert len(body) == 1 and body[0][0] == Atom("match")
    assert body[0][2] == (Atom("var"), 2, Atom("V"))
    assert body[0][3][0] == Atom("case")


def test_tail_case_semantics_in_erl():
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    src.mkdir()
    (src / "t.ee").write_text(
        "def pick(c):\n    if c:\n        'yes'\n    else:\n        'no'\n"
        "def num(v):\n    match v:\n        case 1:\n            10\n        case _:\n            20\n"
    )
    subprocess.run([sys.executable, "-m", "squeal", "build", str(tmp)],
                   cwd=ROOT, check=True, capture_output=True)
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval",
         'io:format("~p ~p ~p~n", [t:pick(true), t:pick(false), t:num(1)]), halt().'],
        capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "yes no 10"


def test_float_mod_and_floordiv():
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    src.mkdir()
    (src / "f.ee").write_text(
        "def m(a, b):\n    a % b\ndef d(a, b):\n    a // b\n")
    subprocess.run([sys.executable, "-m", "squeal", "build", str(tmp)],
                   cwd=ROOT, check=True, capture_output=True)
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval",
         'io:format("~p ~p ~p ~p~n", [f:m(7.5, 2), f:m(-7.5, 2), f:d(7.5, 2), f:d(-7.5, 2)]), halt().'],
        capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "1.5 0.5 3.0 -4.0"


def test_source_chars_quotes_with_unicode():
    import ast
    from squeal.frontend import _source_chars

    src = 'привет = "b"\nz = \'a\'\n'
    chars = _source_chars(src)
    got = {}
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            got[node.value] = chars.get((node.lineno, node.col_offset))
    assert got == {"b": '"', "a": "'"}


def test_params_differing_only_by_case():
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    src.mkdir()
    (src / "nm.ee").write_text("def f(N, n):\n    (N, n)\n")
    subprocess.run([sys.executable, "-m", "squeal", "build", str(tmp)],
                   cwd=ROOT, check=True, capture_output=True)
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval",
         'io:format("~p~n", [nm:f(1, 2)]), halt().'],
        capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "{1,2}"


def test_decorators_in_module():
    from squeal.term import term_to_erlang
    src = ("def twice(fn):\n    lambda x: fn(fn(x))\n\n"
           "@twice\ndef inc(x):\n    x + 1\n")
    forms = compile_source(src, "src/m.ee", "m")
    names = [f[2] for f in forms if f[0] == "function"]
    assert "inc@impl" in names and "inc" in names and "squeal_on_load" in names
    wrapper = next(f for f in forms if f[0] == "function" and f[2] == "inc")
    text = term_to_erlang(wrapper)
    assert "persistent_term" in text and "twice" not in text  # применён один раз, не в вызове

    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "src").mkdir()
    (tmp / "src" / "m.ee").write_text(src)
    subprocess.run([sys.executable, "-m", "squeal", "build", str(tmp)],
                   cwd=ROOT, check=True, capture_output=True)
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval",
         'io:format("~p~n", [m:inc(5)]), halt().'],
        capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "7"


def test_decorator_chain_and_recursion_in_module():
    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "src").mkdir()
    (tmp / "src" / "r.ee").write_text(
        "def plus1(fn):\n    lambda x: fn(x) + 1\n\n"
        "@plus1\ndef r(n):\n    if n > 0:\n        r(n - 1)\n    else:\n        0\n\n"
        "@plus1\n@plus1\ndef z(x):\n    x\n")
    subprocess.run([sys.executable, "-m", "squeal", "build", str(tmp)],
                   cwd=ROOT, check=True, capture_output=True)
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval",
         'io:format("~p ~p~n", [r:r(3), r:z(1)]), halt().'],
        capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "4 3"


def test_decorator_errors():
    import pytest
    from squeal.errors import SquealError
    for src in [
        "@(lambda f: f)\ndef g():\n    1\n",              # не имя/модуль/вызов
        "@dec\nclass T(StartingWithAtom):\n    x: int\n",  # класс
    ]:
        with pytest.raises(SquealError):
            compile_source(src, "src/m.ee", "m")


def test_decorator_from_another_module():
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    src.mkdir()
    (src / "a.ee").write_text("def dec(f):\n    lambda x: f(x) + 1\n")
    (src / "b.ee").write_text("from a import dec\n\n@dec\ndef g(x):\n    x * 2\n")
    subprocess.run([sys.executable, "-m", "squeal", "build", str(tmp)],
                   cwd=ROOT, check=True, capture_output=True)
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval", 'io:format("~p~n", [b:g(1)]), halt().'],
        capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "3"


def test_remote_decorator_without_import():
    tmp = pathlib.Path(tempfile.mkdtemp())
    src = tmp / "src"
    src.mkdir()
    (src / "a.ee").write_text("def dec(f):\n    lambda x: f(x) + 1\n")
    (src / "zz.ee").write_text("@a.dec\ndef h(x):\n    x * 3\n")
    subprocess.run([sys.executable, "-m", "squeal", "build", str(tmp)],
                   cwd=ROOT, check=True, capture_output=True)
    ebin = tmp / "build" / "dev" / "erlang" / tmp.name / "ebin"
    out = subprocess.run(
        [ERL, "-noshell", "-pa", str(ebin), "-eval", 'io:format("~p~n", [zz:h(1)]), halt().'],
        capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "4"


def test_decorator_must_be_arity_one():
    import pytest
    from squeal.errors import SquealError
    for src in [
        "def add(a, b):\n    a + b\n\n@add\ndef g(x):\n    x\n",  # арность 2
        "@nope\ndef g(x):\n    x\n",                              # не существует
    ]:
        with pytest.raises(SquealError, match="decorator"):
            compile_source(src, "src/m.ee", "m")
