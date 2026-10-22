"""Shell-режим и persistent REPL для Jupyter."""

from __future__ import annotations

import pytest

from squeal.session import Session, compile_cell
from squeal.repl import ErlangRepl


def test_compile_cell_assignment():
    s = Session()
    forms, suppress = compile_cell("x = 1\n", s)
    assert suppress is False
    assert len(forms) == 1
    assert forms[0][0] == "match"


def test_mangling_persists_across_cells():
    s = Session()
    forms, _ = compile_cell("x = 1\n", s)
    assert forms[0][2] == ("var", 1, "X")
    forms, _ = compile_cell("x = x + 1\n", s)
    # второе связывание -> X@1, RHS ссылается на X
    assert forms[0][2] == ("var", 1, "X@1")


def test_def_compiles_to_named_fun():
    s = Session()
    forms, suppress = compile_cell("def f(x):\n    x + 1\n", s)
    assert suppress is True
    form = forms[0]
    assert form[0] == "match"
    assert form[2] == ("var", 1, "F")
    fun = form[3]
    assert fun[0] == "named_fun" and fun[2] == "F"


def test_class_registers_and_erases():
    s = Session()
    forms, _ = compile_cell("class T(StartingWithAtom):\n    x: int\n", s)
    assert forms == []
    assert "T" in s.classes
    forms, _ = compile_cell("T(1)\n", s)
    assert forms[0][0] == "tuple"  # конструктор инлайнится


def test_repl_persistence():
    s = Session()
    repl = ErlangRepl()
    try:
        forms, _ = compile_cell("x = 1\n", s)
        assert repl.eval_forms(forms) == ("ok", "1")
        forms, _ = compile_cell("x + 1\n", s)
        assert repl.eval_forms(forms) == ("ok", "2")
    finally:
        repl.close()


def test_repl_def_recursion():
    s = Session()
    repl = ErlangRepl()
    try:
        forms, suppress = compile_cell(
            "def fact(n):\n    if n < 1:\n        r = 1\n    else:\n        r = n * fact(n - 1)\n    r\n",
            s,
        )
        assert suppress is True
        status, value = repl.eval_forms(forms)
        assert status == "ok" and value.startswith("#Fun")
        forms, _ = compile_cell("fact(5)\n", s)
        assert repl.eval_forms(forms) == ("ok", "120")
    finally:
        repl.close()


def test_repl_runtime_error():
    s = Session()
    repl = ErlangRepl()
    try:
        forms, _ = compile_cell("1 / 0\n", s)
        status, value = repl.eval_forms(forms)
        assert status == "error"
        assert "badarith" in value
    finally:
        repl.close()


def test_ipykernel_hook():
    from IPython.core.interactiveshell import InteractiveShell
    from IPython.utils.capture import capture_output
    import squeal.notebook as nb

    shell = InteractiveShell.instance()
    nb.load_ipython_extension(shell)
    try:
        with capture_output() as c1:
            shell.run_cell("x = 1")
        with capture_output() as c2:
            shell.run_cell("x + 1")
        assert c2.stdout.strip() == "2"
        # Python ничего не выполнил: x нет в Python-пространстве имён
        assert "x" not in shell.user_ns
    finally:
        nb.unload_ipython_extension(shell)
        InteractiveShell.clear_instance()


def test_shell_mode_helper_is_variable_call():
    s = Session()
    forms, _ = compile_cell("2 ** 3\n", s)
    call = forms[0]
    assert call[0] == "call" and call[2][0] == "var"  # {call, {var, '_squeal_pow'}, ...}


def test_shell_mode_pow_and_comprehension():
    s = Session()
    repl = ErlangRepl()
    try:
        forms, _ = compile_cell("2 ** 10\n", s)
        assert repl.eval_forms(forms) == ("ok", "1024")
        forms, _ = compile_cell("[x * 2 for x in [1, 2, 3]]\n", s)
        assert repl.eval_forms(forms) == ("ok", "[2,4,6]")
        forms, _ = compile_cell("{k: 1 for k in {'a': 9}}\n", s)
        assert repl.eval_forms(forms) == ("ok", "#{a => 1}")
    finally:
        repl.close()
