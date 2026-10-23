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


def test_class_redefinition_across_cells_is_allowed():
    s = Session()
    src = "class T(StartingWithAtom):\n    x: int\n"
    assert compile_cell(src, s)[0] == []
    assert compile_cell(src, s)[0] == []  # повторный запуск клетки — не ошибка


def test_class_duplicate_within_cell_errors():
    import pytest
    from squeal.errors import SquealError
    with pytest.raises(SquealError):
        compile_cell(
            "class T(StartingWithAtom):\n    x: int\nclass T(StartingWithAtom):\n    y: int\n",
            Session(),
        )


def test_session_builtin_ok_error():
    s = Session()
    forms, _ = compile_cell("Ok(1)\n", s)
    assert forms[0][0] == "tuple" and forms[0][2][0] == ("atom", 1, "ok")
    forms, _ = compile_cell("Error('boom')\n", s)
    assert forms[0][2][0] == ("atom", 1, "error")


def test_hook_survives_python_syntax_error():
    from IPython.core.interactiveshell import InteractiveShell
    from IPython.utils.capture import capture_output
    import squeal.notebook as nb

    shell = InteractiveShell.instance()
    nb.load_ipython_extension(shell)
    try:
        with capture_output():
            shell.run_cell("Ok(val) = 1")  # невалидный Python: call = ...
        with capture_output() as c2:
            shell.run_cell("40 + 2")
        assert c2.stdout.strip() == "42"  # сессия жива после SyntaxError
    finally:
        nb.unload_ipython_extension(shell)
        InteractiveShell.clear_instance()


def test_repl_pattern_assign():
    s = Session()
    repl = ErlangRepl()
    try:
        forms, _ = compile_cell("def fun(x):\n    'ok', x\n\nOk(val) = fun(3)\n", s)
        assert repl.eval_forms(forms) == ("ok", "{ok,3}")
        forms, _ = compile_cell("val\n", s)
        assert repl.eval_forms(forms) == ("ok", "3")
    finally:
        repl.close()


def test_hook_accepts_pattern_assign():
    from IPython.core.interactiveshell import InteractiveShell
    from IPython.utils.capture import capture_output
    import squeal.notebook as nb

    shell = InteractiveShell.instance()
    nb.load_ipython_extension(shell)
    try:
        with capture_output() as c1:
            shell.run_cell("def fun(x):\n    'ok', x\n\nOk(val) = fun(3)")
        with capture_output() as c2:
            shell.run_cell("val")
        assert c2.stdout.strip() == "3"
        assert "SyntaxError" not in c1.stdout
    finally:
        nb.unload_ipython_extension(shell)
        InteractiveShell.clear_instance()


def test_repl_pp_comprehension():
    from squeal.notebook import compact
    s = Session()
    repl = ErlangRepl()
    try:
        forms, _ = compile_cell("[x * 2 for x in [1, 2, 3]]\n", s)
        assert compact(repl.pp(forms[0])) == "[X * 2 || X <- squeal_iter([1, 2, 3])]"
        forms, _ = compile_cell("{k: 1 for k in {'a': 9}}\n", s)
        assert compact(repl.pp(forms[0])) == "#{K => 1 || K <- squeal_iter(#{a => 9})}"
    finally:
        repl.close()


def test_hook_prints_erl_comprehension():
    from IPython.core.interactiveshell import InteractiveShell
    from IPython.utils.capture import capture_output
    import squeal.notebook as nb

    shell = InteractiveShell.instance()
    nb.load_ipython_extension(shell)
    try:
        with capture_output() as out:
            shell.run_cell("[x * 2 for x in [1, 2, 3]]")
        assert "erl: [X * 2 || X <- squeal_iter([1, 2, 3])]" in out.stdout
        assert "[2,4,6]" in out.stdout
    finally:
        nb.unload_ipython_extension(shell)
        InteractiveShell.clear_instance()


def test_comprehension_targets_use_local_names():
    from squeal.notebook import compact
    s = Session()
    repl = ErlangRepl()
    try:
        compile_cell("x = 1\nx = x + 1\n", s)           # x -> X, X@1 в сессии
        forms, _ = compile_cell("[x * 2 for x in [1, 2, 3]]\n", s)
        assert compact(repl.pp(forms[0])) == "[X * 2 || X <- squeal_iter([1, 2, 3])]"
    finally:
        repl.close()


def test_repl_arity_overloading():
    s = Session()
    repl = ErlangRepl()
    try:
        forms, _ = compile_cell(
            "def fib(N, current, next):\n    match N:\n        case 0:\n            ret = current\n"
            "        case _ if N > 0:\n            ret = fib(N - 1, next, current + next)\n    ret\n\n"
            "def fib(N):\n    fib(N, 0, 1)\n", s)
        assert repl.eval_forms(forms)[0] == "ok"
        forms, _ = compile_cell("(fib(10), fib(10, 0, 1))\n", s)
        assert repl.eval_forms(forms) == ("ok", "{55,55}")
    finally:
        repl.close()


def test_repl_forward_definition_errors():
    import pytest
    from squeal.errors import SquealError
    with pytest.raises(SquealError) as e:
        compile_cell("def f(x):\n    g(x)\n\ndef g(y):\n    y\n", Session())
    assert "не определена" in str(e.value)


def test_assignment_shadows_definition():
    s = Session()
    repl = ErlangRepl()
    try:
        forms, _ = compile_cell("def f(x):\n    x + 1\n", s)
        repl.eval_forms(forms)
        forms, _ = compile_cell("f = lambda x: x + 100\n", s)
        repl.eval_forms(forms)
        forms, _ = compile_cell("f(1)\n", s)
        assert repl.eval_forms(forms) == ("ok", "101")
    finally:
        repl.close()


def test_functions_are_values_in_shell():
    s = Session()
    repl = ErlangRepl()
    try:
        forms, _ = compile_cell("def f(x):\n    x + 1\n", s)
        repl.eval_forms(forms)
        forms, _ = compile_cell("g = f\n", s)
        assert repl.eval_forms(forms)[0] == "ok"
        forms, _ = compile_cell("g(41)\n", s)
        assert repl.eval_forms(forms) == ("ok", "42")
    finally:
        repl.close()


def test_shell_arity_mismatch_is_clear():
    import pytest
    from squeal.errors import SquealError
    s = Session()
    repl = ErlangRepl()
    try:
        forms, _ = compile_cell("def f(x):\n    x\n", s)
        repl.eval_forms(forms)
        with pytest.raises(SquealError) as e:
            compile_cell("f(1, 2)\n", s)
        assert "не определена" in str(e.value)
    finally:
        repl.close()


def test_extension_load_is_idempotent_and_unloads():
    from IPython.core.interactiveshell import InteractiveShell
    import squeal.notebook as nb

    shell = InteractiveShell.instance()
    try:
        def counts():
            return (
                len(shell.events.callbacks.get("post_run_cell", [])),
                len(shell.ast_transformers),
                len(shell.input_transformers_cleanup),
            )
        nb.load_ipython_extension(shell)
        once = counts()
        nb.load_ipython_extension(shell)
        assert counts() == once          # повторная загрузка ничего не дублирует
        nb.unload_ipython_extension(shell)
        assert counts() == (once[0] - 1, once[1] - 1, once[2] - 1)
    finally:
        InteractiveShell.clear_instance()


def test_decorators_in_shell():
    s = Session()
    repl = ErlangRepl()
    try:
        for cell in [
            "def plus1(fn):\n    lambda x: fn(x) + 1\n",
            "@plus1\ndef r(n):\n    if n > 0:\n        r(n - 1)\n    else:\n        0\n",
            "r(3)",
            "@plus1\n@plus1\ndef z(x):\n    x\n",
            "z(1)",
        ]:
            forms, _ = compile_cell(cell, s)
            status, value = repl.eval_forms(forms)
            if cell in ("r(3)", "z(1)"):
                assert (status, value) in (("ok", "4"), ("ok", "3"))
    finally:
        repl.close()


def test_repl_methods():
    s = Session()
    repl = ErlangRepl()
    try:
        forms, _ = compile_cell('d = {"a": 1}\n', s)
        repl.eval_forms(forms)
        forms, _ = compile_cell('d.get("a")\n', s)
        assert repl.eval_forms(forms) == ("ok", "1")
        forms, _ = compile_cell('d.get("b", 0)\n', s)
        assert repl.eval_forms(forms) == ("ok", "0")
        forms, _ = compile_cell('d.keys()\n', s)
        assert repl.eval_forms(forms) == ("ok", '[<<"a">>]')
        forms, _ = compile_cell('"a,b".split(",")\n', s)
        assert repl.eval_forms(forms) == ("ok", '[<<"a">>,<<"b">>]')
        forms, _ = compile_cell('"  a  ".strip().upper()\n', s)
        assert repl.eval_forms(forms) == ("ok", '<<"A">>')
        forms, _ = compile_cell('[1,2,1].count(1)\n', s)
        assert repl.eval_forms(forms) == ("ok", "2")
    finally:
        repl.close()
