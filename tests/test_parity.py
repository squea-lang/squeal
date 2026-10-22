"""Паритет с Gleam: одинаковые формы на эквивалентном коде (см. architecture.md).

Оракул — формы из ``_gleam_artefacts/<mod>.abstr`` (ETF), которые печатает
``gleam build``; достаём их через ``erl -eval`` и парсим в Python.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile

from squeal.compiler import compile_source
from squeal.term import Atom

from erl_term import parse

GLEAM = shutil.which("gleam")
ERL = shutil.which("erl")

# Теги форм, у которых аннотация (строка) стоит вторым элементом.
FORM_TAGS = {
    "attribute", "function", "clause", "op", "call", "remote", "var", "tuple",
    "cons", "nil", "integer", "float", "string", "atom", "bin", "bin_element",
    "map", "map_field_assoc", "map_field_exact", "block", "match", "case",
    "type", "product", "binary",
    "fun", "user_type",
}


def gleam_forms(source: str, module: str, app: str) -> list:
    """Компилирует .gleam-модуль и возвращает его формы из .abstr."""
    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "gleam.toml").write_text(f'name = "{app}"\nversion = "1.0.0"\n')
    src = tmp / "src"
    src.mkdir()
    (src / f"{module}.gleam").write_text(source)

    subprocess.run([GLEAM, "build"], cwd=tmp, check=True, capture_output=True)
    abstr = tmp / "build" / "dev" / "erlang" / app / "_gleam_artefacts" / f"{module}.abstr"

    out = subprocess.run(
        [
            ERL,
            "-noshell",
            "-eval",
            f'{{ok,B}}=file:read_file("{abstr}"), '
            f'io:format("~p.~n",[binary_to_term(B)]), halt().',
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return parse(out.stdout)


def gleam_project_forms(sources: dict, module: str, app: str) -> list:
    """Многомодульный gleam-проект; возвращает формы одного модуля."""
    tmp = pathlib.Path(tempfile.mkdtemp())
    (tmp / "gleam.toml").write_text(f'name = "{app}"\nversion = "1.0.0"\n')
    for rel, content in sources.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    subprocess.run([GLEAM, "build"], cwd=tmp, check=True, capture_output=True)
    abstr = tmp / "build" / "dev" / "erlang" / app / "_gleam_artefacts" / f"{module}.abstr"
    out = subprocess.run(
        [
            ERL,
            "-noshell",
            "-eval",
            f'{{ok,B}}=file:read_file("{abstr}"), '
            f'io:format("~p.~n",[binary_to_term(B)]), halt().',
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return parse(out.stdout)


def _zero_annos(term):
    if isinstance(term, tuple):
        if (
            len(term) >= 2
            and isinstance(term[0], Atom)
            and term[0] in FORM_TAGS
            and isinstance(term[1], int)
        ):
            return (term[0], 0, *(_zero_annos(x) for x in term[2:]))
        return tuple(_zero_annos(x) for x in term)
    if isinstance(term, list):
        return [_zero_annos(x) for x in term]
    return term


def normalize(forms: list) -> list:
    """Выбрасываем атрибуты file/spec/type/export_type (у squeal типов нет) и
    обнуляем аннотации строк (номера у .gleam и .ee расходятся)."""
    out = []
    for form in forms:
        if isinstance(form, tuple) and len(form) >= 3 and form[0] == Atom("attribute"):
            if form[2] in (Atom("file"), Atom("spec"), Atom("type"), Atom("export_type")):
                continue
        out.append(_zero_annos(form))
    return out


def test_hello():
    gleam = 'pub fn hello() {\n  "hi"\n}\n'
    squeal = 'def hello():\n    "hi"\n'

    expected = normalize(gleam_forms(gleam, "hello", "parity_hello"))
    actual = normalize(compile_source(squeal, "src/hello.ee", "hello"))

    assert actual == expected


def test_parity_values():
    gleam = """\
pub fn add(a: Int, b: Int) { a + b }
pub fn sub(a: Int, b: Int) { a - b }
pub fn mul(a: Int, b: Int) { a * b }
pub fn ne(a: Int, b: Int) { a != b }
pub fn lt(a: Int, b: Int) { a < b }
pub fn le(a: Int, b: Int) { a <= b }
pub fn gt(a: Int, b: Int) { a > b }
pub fn ge(a: Int, b: Int) { a >= b }
pub fn and_(a: Bool, b: Bool) { a && b }
pub fn or_(a: Bool, b: Bool) { a || b }
pub fn not_(a: Bool) { !a }
pub fn nil() { Nil }
pub fn tup() { #(1, 2) }
pub fn lst() { [1, 2] }
pub fn flt() { 1.5 }
pub fn str() { "hi" }
pub fn tr() { True }
pub fn fl() { False }
pub fn ident(my_list) { my_list }
"""
    squeal = """\
def add(a, b):
    a + b
def sub(a, b):
    a - b
def mul(a, b):
    a * b
def ne(a, b):
    a != b
def lt(a, b):
    a < b
def le(a, b):
    a <= b
def gt(a, b):
    a > b
def ge(a, b):
    a >= b
def and_(a, b):
    a and b
def or_(a, b):
    a or b
def not_(a):
    not a
def nil():
    None
def tup():
    (1, 2)
def lst():
    [1, 2]
def flt():
    1.5
def str():
    "hi"
def tr():
    True
def fl():
    False
def ident(my_list):
    my_list
"""
    expected = normalize(gleam_forms(gleam, "parity", "parity_values"))
    actual = normalize(compile_source(squeal, "src/parity.ee", "parity"))
    assert actual == expected


def test_parity_assignment():
    gleam = """\
pub fn reassign() -> Int {
  let x = 1
  let x = x + 1
  x
}
pub fn tup(t: #(Int, Int)) -> Int {
  let #(a, b) = t
  a
}
"""
    squeal = """\
def reassign():
    x = 1
    x = x + 1
    x
def tup(t):
    a, b = t
    a
"""
    expected = normalize(gleam_forms(gleam, "assign", "parity_assign"))
    actual = normalize(compile_source(squeal, "src/assign.ee", "assign"))
    assert actual == expected


def test_parity_branching():
    gleam = """\
pub fn iflike(c: Bool, a: Int, b: Int) -> Int {
  let value = case c {
    True -> a
    False -> b
  }
  value
}
pub fn mc(v: Int, x: Int, y: Int) -> Int {
  let value = case v {
    1 -> x
    2 -> x
    _ -> y
  }
  value
}
pub fn guarded(v: Int) -> Int {
  let value = case v {
    n if n > 0 -> n
    _ -> 0
  }
  value
}
pub fn orp(v: Int, x: Int) -> Int {
  let value = case v {
    1 -> x
    2 -> x
    _ -> 0
  }
  value
}
"""
    squeal = """\
def iflike(c, a, b):
    if c:
        value = a
    else:
        value = b
    value
def mc(v, x, y):
    match v:
        case 1:
            value = x
        case 2:
            value = x
        case _:
            value = y
    value
def guarded(v):
    match v:
        case n if n > 0:
            value = n
        case _:
            value = 0
    value
def orp(v, x):
    match v:
        case 1 | 2:
            value = x
        case _:
            value = 0
    value
"""
    expected = normalize(gleam_forms(gleam, "branch", "parity_branch"))
    actual = normalize(compile_source(squeal, "src/branch.ee", "branch"))
    assert actual == expected


def test_parity_classes():
    gleam = """\
pub type CustomType {
  CustomType(x: Int, y: Int)
}
pub fn make() { CustomType(1, 2) }
pub fn get(t: CustomType) -> Int {
  let r = case t {
    CustomType(x, _) -> x
  }
  r
}
"""
    squeal = """\
class CustomType(StartingWithAtom):
    x: int
    y: int
def make():
    CustomType(1, 2)
def get(t):
    match t:
        case CustomType(x, _):
            r = x
    r
"""
    expected = normalize(gleam_forms(gleam, "custom", "parity_custom"))
    actual = normalize(compile_source(squeal, "src/custom.ee", "custom"))
    assert actual == expected


def test_parity_lambda():
    gleam = """\
pub fn lf(y: Int) -> Int {
  let f = fn(x) { x + y }
  f(1)
}
"""
    squeal = """\
def lf(y):
    f = lambda x: x + y
    f(1)
"""
    expected = normalize(gleam_forms(gleam, "lf", "parity_lf"))
    actual = normalize(compile_source(squeal, "src/lf.ee", "lf"))
    assert actual == expected


def test_parity_import():
    sources = {
        "src/a/b/c.gleam": "pub fn f() -> Int { 42 }\n",
        "src/main.gleam": "import a/b/c\npub fn g() -> Int { c.f() }\n",
    }
    expected = normalize(gleam_project_forms(sources, "main", "parity_imp"))
    squeal = "from a.b.c import f\ndef g():\n    f()\n"
    actual = normalize(compile_source(squeal, "src/main.ee", "main"))
    assert actual == expected


def assert_parity(gleam: str, squeal: str, module: str, app: str):
    expected = normalize(gleam_forms(gleam, module, app))
    actual = normalize(compile_source(squeal, f"src/{module}.ee", module))
    assert actual == expected, f"{module}: формы squeal расходятся с Gleam"


def test_parity_unary_minus():
    assert_parity(
        "pub fn neg(x: Int) -> Int { -x }\n",
        "def neg(x):\n    -x\n",
        "neg", "parity_neg",
    )


def test_parity_nested_arith():
    assert_parity(
        "pub fn f(a: Int, b: Int, c: Int) -> Int { { a + b } * c }\n",
        "def f(a, b, c):\n    (a + b) * c\n",
        "narith", "parity_narith",
    )


def test_parity_local_calls():
    assert_parity(
        "pub fn double(x: Int) -> Int { x * 2 }\npub fn quad(x: Int) -> Int { double(double(x)) }\n",
        "def double(x):\n    x * 2\ndef quad(x):\n    double(double(x))\n",
        "lc", "parity_lc",
    )


def test_parity_recursion():
    assert_parity(
        "pub fn fact(n: Int) -> Int {\n  let r = case n < 1 {\n    True -> 1\n    False -> n * fact(n - 1)\n  }\n  r\n}\n",
        "def fact(n):\n    if n < 1:\n        r = 1\n    else:\n        r = n * fact(n - 1)\n    r\n",
        "fact", "parity_fact",
    )


def test_parity_list_match():
    assert_parity(
        "pub fn lm(l: List(Int)) -> Int {\n  let r = case l {\n    [h, ..rest] -> h\n    [] -> 0\n  }\n  r\n}\n",
        "def lm(l):\n    match l:\n        case [h, *rest]:\n            r = h\n        case []:\n            r = 0\n    r\n",
        "lm", "parity_lm",
    )


def test_parity_float():
    assert_parity(
        "pub fn f(x: Float) -> Float { x *. 1.5 }\n",
        "def f(x):\n    x * 1.5\n",
        "fl2", "parity_fl2",
    )


def test_parity_higher_order():
    assert_parity(
        "pub fn apply(f: fn(Int) -> Int, x: Int) -> Int { f(x) }\npub fn g() -> Int { apply(fn(y) { y + 1 }, 2) }\n",
        "def apply(f, x):\n    f(x)\ndef g():\n    apply(lambda y: y + 1, 2)\n",
        "ho", "parity_ho",
    )


def test_parity_nested_destructure():
    assert_parity(
        "pub fn nd(t: #(Int, #(Int, Int))) -> Int {\n  let #(a, #(b, c)) = t\n  a + b + c\n}\n",
        "def nd(t):\n    (a, (b, c)) = t\n    a + b + c\n",
        "nd", "parity_nd",
    )


def test_parity_string_escape():
    assert_parity(
        "pub fn s() -> String { \"a\\nb\" }\n",
        "def s():\n    \"a\\nb\"\n",
        "str2", "parity_str2",
    )


def test_parity_class_guard():
    assert_parity(
        "pub type T {\n  T(x: Int)\n}\npub fn g(v: T) -> Int {\n  let r = case v {\n    T(x) if x > 0 -> x\n    _ -> 0\n  }\n  r\n}\n",
        "class T(StartingWithAtom):\n    x: int\ndef g(v):\n    match v:\n        case T(x) if x > 0:\n            r = x\n        case _:\n            r = 0\n    r\n",
        "cg", "parity_cg",
    )


def test_parity_boolean_chain():
    assert_parity(
        "pub fn bc(a: Bool, b: Bool, c: Bool) -> Bool { a && b && c }\n",
        "def bc(a, b, c):\n    a and b and c\n",
        "bc", "parity_bc",
    )
