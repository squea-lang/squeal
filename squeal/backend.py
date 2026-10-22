"""Бэкенд: IR → Erlang Abstract Format (как значения Python).

Формы повторяют Gleam 1.19 для совпадающих конструкций (см. architecture.md);
операторы Python-семантики (``// % **``) и деструктуризация — собственные формы.
Аннотация каждой формы — строка исходника ``.ee``.
"""

from __future__ import annotations

from . import ir
from .errors import SquealError
from .term import Atom

COMPILE_OPTS = [
    Atom("no_auto_import"),
    Atom("nowarn_ignored"),
    Atom("nowarn_unused_vars"),
    Atom("nowarn_unused_function"),
    Atom("nowarn_nomatch"),
    Atom("inline"),
]

_OP_SYMBOL = {
    "Add": "+",
    "Sub": "-",
    "Mult": "*",
    "Div": "/",
    "Eq": "==",
    "NotEq": "/=",
    "Lt": "<",
    "LtE": "=<",
    "Gt": ">",
    "GtE": ">=",
}


def variable_name(name: str) -> Atom:
    """``x`` → ``X``, ``my_list`` → ``My_list`` (как у Gleam)."""
    return Atom(name[0].upper() + name[1:])


def _atom(line, name) -> tuple:
    return (Atom("atom"), line, Atom(name))


def _var(line, name) -> tuple:
    return (Atom("var"), line, Atom(name))


def _int(line, value) -> tuple:
    return (Atom("integer"), line, value)


def _local_call(line, name, args) -> tuple:
    return (Atom("call"), line, (Atom("atom"), line, Atom(name)), args)


def _remote_call(line, module, function, args) -> tuple:
    return (
        Atom("call"),
        line,
        (Atom("remote"), line, (Atom("atom"), line, Atom(module)), (Atom("atom"), line, Atom(function))),
        args,
    )


def _op(line, op, left, right) -> tuple:
    return (Atom("op"), line, Atom(op), left, right)


def _pattern_names(pat) -> list:
    """Имена, связываемые образцом (для перекрытия определений присваиванием)."""
    if isinstance(pat, (ir.PName, ir.PStar)):
        return [pat.name]
    if isinstance(pat, (ir.PList, ir.PTuple)):
        names = []
        for item in pat.items:
            names.extend(_pattern_names(item))
        return names
    return []


class _Gen:
    def __init__(self):
        self._temp = 0
        self._used_pow = False
        self._used_iter = False
        self._shell_mode = False
        self._imports: dict[str, tuple] = {}
        self._scope: dict[str, Atom] = {}
        self._taken: dict[str, int] = {}
        self._defs: dict[tuple, Atom] = {}
        self._later_defs: set[tuple] = set()

    def _helper_call(self, line, name, args) -> tuple:
        """Вызов хелпера: в модуле — локальная функция, в REPL — связанный fun."""
        if self._shell_mode:
            return (Atom("call"), line, _var(line, name), args)
        return _local_call(line, name, args)

    # --- имена переменных ---

    def _allocate(self, name: str) -> Atom:
        """Новое Erlang-имя для привязки (счётчик общий у значений и определений)."""
        count = self._taken.get(name, 0)
        base = variable_name(name)
        new = base if count == 0 else Atom(f"{base}@{count}")
        self._taken[name] = count + 1
        return new

    def _drop_defs(self, name: str) -> None:
        for key in [k for k in self._defs if k[0] == name]:
            del self._defs[key]

    def _bind(self, name: str) -> Atom:
        new = self._allocate(name)
        self._scope[name] = new
        return new

    def _bind_def(self, name: str, arity: int) -> Atom:
        """Определение функции: имя различается по арности (как в Erlang/Gleam)."""
        new = self._allocate(name)
        self._defs[(name, arity)] = new
        self._scope.pop(name, None)
        return new

    def _resolve(self, name: str) -> Atom:
        erlang = self._scope.get(name)
        if erlang is None:
            raise SquealError(f"имя {name!r} не определено")
        return erlang

    def new_temp(self) -> Atom:
        """Неколлидирующее имя: ``_squeal@N`` (в Python-идентификаторе нет ``@``)."""
        name = f"_squeal@{self._temp}"
        self._temp += 1
        return Atom(name)

    # --- модуль и функции ---

    def module_forms(self, module: ir.Module) -> list:
        self._imports = dict(module.imports)
        forms = [
            (Atom("attribute"), 0, Atom("module"), Atom(module.name)),
            (Atom("attribute"), 0, Atom("compile"), list(COMPILE_OPTS)),
            (
                Atom("attribute"),
                0,
                Atom("export"),
                [(Atom(f.name), len(f.params)) for f in module.functions],
            ),
            (Atom("attribute"), 0, Atom("export_type"), []),
            (Atom("attribute"), 0, Atom("file"), (module.path, 0)),
        ]
        for function in module.functions:
            forms.append(self.function_form(function))
        if self._used_pow:
            forms.extend(self.pow_helpers())
        if self._used_iter:
            forms.append(self.iter_helper())
        return forms

    def function_form(self, function: ir.Function) -> tuple:
        self._scope = {}
        self._taken = {}
        self._defs = {}
        self._temp = 0
        line = function.line

        param_forms = []
        for p in function.params:
            param_forms.append(_var(line, self._bind(p)))

        body = [self.stmt_form(s) for s in function.statements[:-1]]
        body.append(self.tail_stmt_form(function.statements[-1]))
        return (
            Atom("function"),
            line,
            Atom(function.name),
            len(param_forms),
            [(Atom("clause"), line, param_forms, [], body)],
        )

    # --- операторы ---

    def tail_stmt_form(self, stmt) -> tuple:
        """Последний оператор тела: `if`/`match` может отдать значение без хвостового
        присваивания. Старое поведение (все ветки присваивают одну переменную)
        сохраняется — переменная остаётся связанной."""
        if isinstance(stmt, (ir.If, ir.Match)):
            return self._case_tail(stmt)
        return self.stmt_form(stmt)

    def _tail_of(self, stmt):
        """Имя, которое ветка связывает в хвосте, или None."""
        if isinstance(stmt, ir.Assign) and isinstance(stmt.target, ir.PName):
            return stmt.target.name
        if isinstance(stmt, ir.If):
            return self._tail_assign_target([stmt.then_body, stmt.else_body])
        if isinstance(stmt, ir.Match):
            return self._tail_assign_target([c.body for c in stmt.cases])
        return None

    def _tail_assign_target(self, bodies):
        names = []
        for stmts in bodies:
            name = self._tail_of(stmts[-1])
            if name is None:
                return None
            names.append(name)
        return names[0] if len(set(names)) == 1 else None

    def _case_tail(self, node) -> tuple:
        if self._tail_assign_target(
            [node.then_body, node.else_body] if isinstance(node, ir.If)
            else [c.body for c in node.cases]
        ) is not None:
            target, case = self._case_value(node)
            return (Atom("match"), node.line, _var(node.line, self._bind(target)), case)
        return self._case_value_only(node)

    def _branch_tail(self, stmts):
        saved_scope = dict(self._scope)
        saved_taken = dict(self._taken)
        saved_defs = dict(self._defs)
        body = self._branch_tail_body(stmts)
        self._scope = saved_scope
        self._taken = saved_taken
        self._defs = saved_defs
        return body

    def _branch_tail_body(self, stmts):
        body = [self.stmt_form(s) for s in stmts[:-1]]
        last = stmts[-1]
        if isinstance(last, (ir.If, ir.Match)):
            body.append(self._case_value_only(last))
        elif isinstance(last, ir.Assign):
            body.append(self.stmt_form(last))
        elif isinstance(last, ir.Expr):
            body.append(self.expr_form(last.value))
        else:
            raise SquealError(f"{last.line}: хвост ветки должен быть выражением")
        return body

    def _case_value_only(self, node) -> tuple:
        if isinstance(node, ir.If):
            cond = self.expr_form(node.condition)
            then_body = self._branch_tail(node.then_body)
            else_body = self._branch_tail(node.else_body)
            return (Atom("case"), node.line, cond, [
                (Atom("clause"), node.line, [_atom(node.line, "true")], [], then_body),
                (Atom("clause"), node.line, [_atom(node.line, "false")], [], else_body),
            ])
        subject = self.expr_form(node.subject)
        clauses = []
        for c in node.cases:
            saved_scope = dict(self._scope)
            saved_taken = dict(self._taken)
            saved_defs = dict(self._defs)
            patterns = self._case_patterns(c.pattern)
            guard = [[self.expr_form(c.guard)]] if c.guard is not None else []
            body = self._branch_tail_body(c.body)
            self._scope = saved_scope
            self._taken = saved_taken
            self._defs = saved_defs
            for p in patterns:
                clauses.append((Atom("clause"), c.line, [p], guard, body))
        return (Atom("case"), node.line, subject, clauses)

    # --- операторы ---

    def stmt_form(self, stmt) -> tuple:
        if isinstance(stmt, ir.Assign):
            value = self.expr_form(stmt.value)
            for name in _pattern_names(stmt.target):
                self._drop_defs(name)  # присваивание перекрывает функцию
            pattern = self._pattern(stmt.target)
            return (Atom("match"), stmt.line, pattern, value)
        if isinstance(stmt, ir.Expr):
            return self.expr_form(stmt.value)
        if isinstance(stmt, ir.Def):
            return self.def_form(stmt, self._bind_def(stmt.name, len(stmt.params)))
        if isinstance(stmt, (ir.If, ir.Match)):
            target, case = self._case_value(stmt)
            return (Atom("match"), stmt.line, _var(stmt.line, self._bind(target)), case)
        raise SquealError(f"нечем генерировать оператор: {stmt!r}")

    def def_form(self, stmt: ir.Def, name: Atom) -> tuple:
        """`F = fun F(X) -> … end` — именованный fun, чтобы работала рекурсия."""
        line = stmt.line
        self._later_defs.discard((stmt.name, len(stmt.params)))
        saved_scope = dict(self._scope)
        saved_taken = dict(self._taken)
        saved_defs = dict(self._defs)
        param_forms = [_var(line, self._bind(p)) for p in stmt.params]
        body = [self.stmt_form(s) for s in stmt.statements[:-1]]
        body.append(self.tail_stmt_form(stmt.statements[-1]))
        self._scope = saved_scope
        self._taken = saved_taken
        self._defs = saved_defs
        fun = (
            Atom("named_fun"),
            line,
            name,
            [(Atom("clause"), line, param_forms, [], body)],
        )
        return (Atom("match"), line, _var(line, name), fun)

    def _case_value(self, node):
        if isinstance(node, ir.If):
            cond = self.expr_form(node.condition)
            t_target, t_body, t_result = self._branch(node.then_body)
            e_target, e_body, e_result = self._branch(node.else_body)
            self._check_target(node.line, [t_target, e_target])
            case = (Atom("case"), node.line, cond, [
                (Atom("clause"), node.line, [_atom(node.line, "true")], [], t_body + [t_result]),
                (Atom("clause"), node.line, [_atom(node.line, "false")], [], e_body + [e_result]),
            ])
            return t_target, case
        if isinstance(node, ir.Match):
            subject = self.expr_form(node.subject)
            clauses = []
            targets = []
            for c in node.cases:
                saved_scope = dict(self._scope)
                saved_taken = dict(self._taken)
                saved_defs = dict(self._defs)
                patterns = self._case_patterns(c.pattern)  # связывает переменные образца
                guard = [[self.expr_form(c.guard)]] if c.guard is not None else []
                c_target, c_body, c_result = self._branch_body(c.body)
                self._scope = saved_scope
                self._taken = saved_taken
                self._defs = saved_defs
                targets.append(c_target)
                for p in patterns:
                    clauses.append((Atom("clause"), c.line, [p], guard, c_body + [c_result]))
            self._check_target(node.line, targets)
            return targets[0], (Atom("case"), node.line, subject, clauses)
        raise SquealError(f"не ветвление: {node!r}")

    def _branch(self, stmts):
        saved_scope = dict(self._scope)
        saved_taken = dict(self._taken)
        saved_defs = dict(self._defs)
        target, body, result = self._branch_body(stmts)
        self._scope = saved_scope
        self._taken = saved_taken
        self._defs = saved_defs
        return target, body, result

    def _branch_body(self, stmts):
        body = []
        for stmt in stmts[:-1]:
            body.append(self.stmt_form(stmt))
        last = stmts[-1]
        if isinstance(last, ir.Assign) and isinstance(last.target, ir.PName):
            target = last.target.name
            result = self.expr_form(last.value)
        elif isinstance(last, (ir.If, ir.Match)):
            target, result = self._case_value(last)
        else:
            raise SquealError(
                f"{last.line}: ветка должна заканчиваться присваиванием той же переменной"
            )
        return target, body, result

    def _check_target(self, line, targets):
        if len(set(targets)) != 1:
            raise SquealError(f"{line}: ветки присваивают разные переменные: {targets}")

    def _has_bindings(self, pat):
        if isinstance(pat, (ir.PName, ir.PStar)):
            return True
        if isinstance(pat, (ir.PList, ir.PTuple)):
            return any(self._has_bindings(i) for i in pat.items)
        if isinstance(pat, ir.PMap):
            return any(self._has_bindings(v) for _, v in pat.items)
        if isinstance(pat, ir.OrPattern):
            return any(self._has_bindings(p) for p in pat.patterns)
        return False

    def _case_patterns(self, pattern):
        if isinstance(pattern, ir.OrPattern):
            if any(self._has_bindings(p) for p in pattern.patterns):
                raise SquealError(
                    f"{pattern.line}: or-образец не может связывать переменные"
                )
            out = []
            for p in pattern.patterns:
                out.extend(self._case_patterns(p))
            return out
        return [self._pattern(pattern)]

    def _pattern(self, pat) -> tuple:
        if isinstance(pat, ir.PName):
            return _var(pat.line, self._bind(pat.name))
        if isinstance(pat, ir.PTuple):
            return (Atom("tuple"), pat.line, [self._pattern(i) for i in pat.items])
        if isinstance(pat, ir.PList):
            return self._list_pattern(pat)
        if isinstance(pat, ir.Wildcard):
            return _var(pat.line, "_")
        if isinstance(pat, ir.PMap):
            fields = [
                (Atom("map_field_exact"), pat.line, self.expr_form(k), self._pattern(v))
                for k, v in pat.items
            ]
            return (Atom("map"), pat.line, fields)
        if isinstance(pat, (ir.Int, ir.Float, ir.String, ir.AtomLit, ir.Bool, ir.Nil)):
            return self.expr_form(pat)
        raise SquealError(f"нечем генерировать образец: {pat!r}")

    def _list_pattern(self, pat: ir.PList) -> tuple:
        line = pat.line
        items = list(pat.items)
        tail = None
        if items and isinstance(items[-1], ir.PStar):
            tail = items.pop()
        form = _var(tail.line, self._bind(tail.name)) if tail else (Atom("nil"), line)
        for item in reversed(items):
            form = (Atom("cons"), line, self._pattern(item), form)
        return form

    # --- выражения ---

    def expr_form(self, expr) -> tuple:
        if isinstance(expr, ir.Int):
            return _int(expr.line, expr.value)
        if isinstance(expr, ir.Float):
            return (Atom("float"), expr.line, expr.value)
        if isinstance(expr, ir.String):
            return (
                Atom("bin"),
                expr.line,
                [
                    (
                        Atom("bin_element"),
                        expr.line,
                        (Atom("string"), expr.line, expr.value),
                        Atom("default"),
                        [Atom("utf8")],
                    )
                ],
            )
        if isinstance(expr, ir.AtomLit):
            return _atom(expr.line, expr.name)
        if isinstance(expr, ir.Bool):
            return _atom(expr.line, "true" if expr.value else "false")
        if isinstance(expr, ir.Nil):
            return _atom(expr.line, "nil")
        if isinstance(expr, ir.Var):
            return _var(expr.line, self._resolve(expr.name))
        if isinstance(expr, ir.Tuple):
            return (
                Atom("tuple"),
                expr.line,
                [self.expr_form(x) for x in expr.items],
            )
        if isinstance(expr, ir.List):
            return self._list_form(expr)
        if isinstance(expr, ir.Dict):
            return self._dict_form(expr)
        if isinstance(expr, ir.UnaryOp):
            return self._unary(expr)
        if isinstance(expr, ir.BinOp):
            return self._binop(expr)
        if isinstance(expr, ir.BoolOp):
            return self._boolop(expr)
        if isinstance(expr, ir.Call):
            args = [self.expr_form(a) for a in expr.args]
            key = (expr.name, len(expr.args))
            if key in self._defs:
                callee = _var(expr.line, self._defs[key])
            elif expr.name in self._scope:
                callee = _var(expr.line, self._resolve(expr.name))
            elif expr.name in self._imports:
                module, fname = self._imports[expr.name]
                return (
                    Atom("call"), expr.line,
                    (Atom("remote"), expr.line,
                     (Atom("atom"), 0, Atom(module)), (Atom("atom"), 0, Atom(fname))),
                    args,
                )
            elif self._shell_mode:
                hint = ""
                if key in self._later_defs:
                    hint = " (определена ниже в этой клетке — переставьте её выше)"
                raise SquealError(
                    f"{expr.line}: функция {expr.name}/{len(expr.args)} не определена{hint}"
                )
            else:
                callee = (Atom("atom"), expr.line, Atom(expr.name))
            return (Atom("call"), expr.line, callee, args)
        if isinstance(expr, ir.Lambda):
            return self._lambda_form(expr)
        if isinstance(expr, ir.Items):
            return _remote_call(
                expr.line, "maps", "to_list", [self.expr_form(expr.receiver)]
            )
        if isinstance(expr, ir.ListComp):
            return self._listcomp_form(expr)
        if isinstance(expr, ir.DictComp):
            return self._dictcomp_form(expr)
        if isinstance(expr, ir.Merge):
            return _remote_call(
                expr.line, "maps", "merge",
                [self.expr_form(expr.left), self.expr_form(expr.right)],
            )
        raise SquealError(f"нечем генерировать выражение: {expr!r}")

    def _list_form(self, expr: ir.List) -> tuple:
        form = (Atom("nil"), expr.line)
        for item in reversed(expr.items):
            form = (Atom("cons"), expr.line, self.expr_form(item), form)
        return form

    def _dict_form(self, expr: ir.Dict) -> tuple:
        fields = [
            (Atom("map_field_assoc"), expr.line, self.expr_form(k), self.expr_form(v))
            for k, v in expr.items
        ]
        return (Atom("map"), expr.line, fields)

    def _unary(self, expr: ir.UnaryOp) -> tuple:
        operand = self.expr_form(expr.operand)
        if expr.op == "USub":
            return (Atom("op"), expr.line, Atom("-"), operand)
        if expr.op == "Not":
            return (Atom("op"), expr.line, Atom("not"), operand)
        if expr.op == "UAdd":
            return operand
        raise SquealError(f"унарный оператор {expr.op} не поддержан")

    def _binop(self, expr: ir.BinOp) -> tuple:
        line = expr.line
        if expr.op in _OP_SYMBOL:
            return _op(
                line,
                _OP_SYMBOL[expr.op],
                self.expr_form(expr.left),
                self.expr_form(expr.right),
            )
        if expr.op == "FloorDiv":
            return self._floordiv(line, expr.left, expr.right)
        if expr.op == "Mod":
            return self._mod(line, expr.left, expr.right)
        if expr.op == "Pow":
            self._used_pow = True
            return self._helper_call(
                line, "_squeal_pow", [self.expr_form(expr.left), self.expr_form(expr.right)]
            )
        raise SquealError(f"бинарный оператор {expr.op} не поддержан")

    def _boolop(self, expr: ir.BoolOp) -> tuple:
        op = "andalso" if expr.op == "And" else "orelse"
        form = self.expr_form(expr.operands[0])
        for operand in expr.operands[1:]:
            form = (Atom("op"), expr.line, Atom(op), form, self.expr_form(operand))
        return form

    def _mod_expr(self, line, ta: Atom, tb: Atom) -> tuple:
        """Mod = (A rem B + B) rem B — питоновский ``%`` (знак делителя)."""
        return (Atom("op"), line, Atom("rem"),
                (Atom("op"), line, Atom("+"),
                    (Atom("op"), line, Atom("rem"), _var(line, ta), _var(line, tb)),
                    _var(line, tb)),
                _var(line, tb))

    def _mod(self, line, left, right) -> tuple:
        a = self.expr_form(left)
        b = self.expr_form(right)
        ta = self.new_temp()
        tb = self.new_temp()
        return (Atom("block"), line, [
            (Atom("match"), line, _var(line, ta), a),
            (Atom("match"), line, _var(line, tb), b),
            self._mod_expr(line, ta, tb),
        ])

    def _floordiv(self, line, left, right) -> tuple:
        a = self.expr_form(left)
        b = self.expr_form(right)
        ta = self.new_temp()
        tb = self.new_temp()
        result = (Atom("op"), line, Atom("div"),
                  (Atom("op"), line, Atom("-"), _var(line, ta), self._mod_expr(line, ta, tb)),
                  _var(line, tb))
        return (Atom("block"), line, [
            (Atom("match"), line, _var(line, ta), a),
            (Atom("match"), line, _var(line, tb), b),
            result,
        ])

    def _lambda_form(self, expr: ir.Lambda) -> tuple:
        saved_scope = dict(self._scope)
        saved_taken = dict(self._taken)
        params = [_var(expr.line, self._bind(p)) for p in expr.params]
        body = self.expr_form(expr.body)
        self._scope = saved_scope
        self._taken = saved_taken
        return (
            Atom("fun"),
            expr.line,
            (Atom("clauses"), [(Atom("clause"), expr.line, params, [], [body])]),
        )

    def _listcomp_form(self, expr: ir.ListComp) -> tuple:
        saved_scope = dict(self._scope)
        saved_taken = dict(self._taken)
        self._taken = {}  # цели включений — локальный scope, имена не наследуют X@N
        quals = self._qualifiers(expr.qualifiers)
        elt = self.expr_form(expr.element)
        self._scope = saved_scope
        self._taken = saved_taken
        return (Atom("lc"), expr.line, elt, quals)

    def _dictcomp_form(self, expr: ir.DictComp) -> tuple:
        saved_scope = dict(self._scope)
        saved_taken = dict(self._taken)
        self._taken = {}
        quals = self._qualifiers(expr.qualifiers)
        key = self.expr_form(expr.key)
        value = self.expr_form(expr.value)
        self._scope = saved_scope
        self._taken = saved_taken
        return (
            Atom("mc"),
            expr.line,
            (Atom("map_field_assoc"), expr.line, key, value),
            quals,
        )

    def _qualifiers(self, quals) -> list:
        out = []
        for q in quals:
            if isinstance(q, ir.Gen):
                self._used_iter = True
                iter_form = self._helper_call(
                    q.line, "squeal_iter", [self.expr_form(q.iter)]
                )
                pattern = self._pattern(q.target)
                out.append((Atom("generate"), q.line, pattern, iter_form))
            elif isinstance(q, ir.MapGen):
                map_form = self.expr_form(q.map)
                key_pat = self._pattern(q.key)
                val_pat = self._pattern(q.value)
                out.append(
                    (
                        Atom("m_generate"),
                        q.line,
                        (Atom("map_field_exact"), q.line, key_pat, val_pat),
                        map_form,
                    )
                )
            elif isinstance(q, ir.Filter):
                out.append(self.expr_form(q.expr))
            else:
                raise SquealError(f"нечем генерировать квалификатор: {q!r}")
        return out

    def iter_helper(self) -> tuple:
        """squeal_iter/1: map → ключи, список → как есть (иначе bad_generator)."""
        line = 0
        m = _var(line, "M")
        l = _var(line, "L")
        return (
            Atom("function"),
            line,
            Atom("squeal_iter"),
            1,
            [
                (Atom("clause"), line, [m], [[_remote_call(line, "erlang", "is_map", [m])]],
                 [_remote_call(line, "maps", "keys", [m])]),
                (Atom("clause"), line, [l], [], [l]),
            ],
        )

    def pow_helpers(self) -> list:
        """Приватные _squeal_pow/2 и _squeal_pow_loop/3: int**int (≥0) — целочисленно,
        иначе math:pow."""
        line = 0
        a = _var(line, "A")
        b = _var(line, "B")
        is_integer = lambda v: _remote_call(line, "erlang", "is_integer", [v])  # noqa: E731
        guard = [[
            is_integer(a), is_integer(b),
            (Atom("op"), line, Atom(">="), b, _int(line, 0)),
        ]]
        pow_fn = (Atom("function"), line, Atom("_squeal_pow"), 2, [
            (Atom("clause"), line, [a, b], guard,
             [_local_call(line, "_squeal_pow_loop", [a, b, _int(line, 1)])]),
            (Atom("clause"), line, [a, b], [],
             [_remote_call(line, "math", "pow", [a, b])]),
        ])

        a2 = _var(line, "A")
        n = _var(line, "N")
        acc = _var(line, "Acc")
        even_guard = [[(Atom("op"), line, Atom("=:="),
                        (Atom("op"), line, Atom("rem"), n, _int(line, 2)), _int(line, 0))]]
        loop_fn = (Atom("function"), line, Atom("_squeal_pow_loop"), 3, [
            (Atom("clause"), line, [_var(line, "_"), _int(line, 0), acc], [], [acc]),
            (Atom("clause"), line, [a2, n, acc], even_guard,
             [_local_call(line, "_squeal_pow_loop",
                          [(Atom("op"), line, Atom("*"), a2, a2),
                           (Atom("op"), line, Atom("div"), n, _int(line, 2)), acc])]),
            (Atom("clause"), line, [a2, n, acc], [],
             [_local_call(line, "_squeal_pow_loop",
                          [a2, (Atom("op"), line, Atom("-"), n, _int(line, 1)),
                           (Atom("op"), line, Atom("*"), acc, a2)])]),
        ])
        return [pow_fn, loop_fn]


def module_forms(module: ir.Module) -> list:
    return _Gen().module_forms(module)
