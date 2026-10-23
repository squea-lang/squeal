---
id: squeal-compiler-package
type: module-design
title: Squeal — пакет компилятора
status: active
parent: squeal-architecture
---

# Squeal — пакет компилятора

Пакет `squeal/` превращает `.ee`-исходник в Erlang Abstract Format и `.beam`. Правила языка
живут в architecture.md, правила образцов — в `squeal-patterns` (patterns.md); здесь —
ответственность пакета, его границы и стадии.

## Ответственность

- `python -m squeal build DIR` компилирует дерево `src/*.ee` в
  `build/dev/erlang/<app>/ebin` (`<app>` — имя каталога проекта); артефакты `.abstr` — в
  `build/dev/erlang/<app>/_squeal_artefacts`.
- Ошибки компиляции — `squeal: <путь>:<строка>: <текст>` в stderr, exit 1 (без traceback).
  Текст сообщений — по-английски (нижний регистр, без точки в конце); комментарии и
  докстринги кода остаются русскими.
- Наружу пакет зовёт только `escript` (драйвер компиляции). Парсер — стоковый `ast.parse`
  из CPython 3.15; `compile()` не вызывается, чтобы питоновские проверки не мешали семантике.

## Стадии

- `frontend.py` — Python AST → IR. Атомы и строки различаются по кавычкам исходника
  (`'ok'` — атом, `"ok"` — строка): `ast` стиль кавычек не хранит, фронтенд снимает его токенизатором.
  Тела функций — последовательность операторов: присваивание (имя/список/кортеж), `return`, выражение;
  `|=` — слияние map; `if`/`else` и `match`/`case` (образцы: литералы, `_`, захват, or, списки/кортежи, словарь; guard);
  `for`/`while`/`del`/AugAssign(кроме `|=`)/присваивание по индексу-атрибуту — ошибка.
  Классы `StartingWithAtom`: конструктор `T(…)` инлайнится в кортеж `{t, …}`, образец `case T(…)` → `{t, …}`;
  `snake_case` — порт Gleam; `NativeRecord`/`Map` — ошибка; арность конструктора и класс-образца проверяется;
  декораторы — только над функциями (`@dec` с учётом импортов/scope, `@mod.dec` → `fun mod:dec/1`,
  вызовы; арность 1 проверяется статически);
  встроенные `Ok`/`Error` (прелюдия) — `{ok, …}`/`{error, …}`.
  `lambda` → IR; включения list/dict (все генераторы через `squeal_iter`, `for k, v in m.items()` → map-генератор,
  получатель `.items()` может быть любым выражением); вызов метода → `ir.Method` (имя, арность, получатель);
  `print(x)` → `ir.Print` (ровно один аргумент, без именованных); `def` в теле функции → `ir.NestedDef`;
  set comprehension и generator-выражения — ошибка. `from a.b.c import f, g as h` — импорты
  (несколько имён, псевдоним `as`); `import *` и `import X` — ошибка.
- `ir.py` — узлы IR; отделяет бэкенд от Python AST, чтобы фронтенд можно было заменить своим парсером.
- `checks.py` — семантика, которой нет в синтаксисе (дубли по (имя, арность), резерв имён хелперов,
  включая `squeal_on_load`).
- `backend.py` — IR → Erlang Abstract Format; формы повторяют Gleam, аннотация — строка `.ee`;
  операторы Python-семантики (`// % **`) — хелперы `squeal_floordiv`/`squeal_mod`/`_squeal_pow`
  (int и float), генерируются по требованию; имена хелперов зарезервированы; линейный scope на функцию
  маппит имена как Gleam (`x` → `X`, переприсваивание → `X@N`), деструктуризация — `match` с образцом;
  `if`/`match` → `case`-выражение с вынесенным присваиванием цели (проверка одинаковой цели у веток);
  в хвостовой позиции тела `case` — само значение, без обёртки в `match`;
  `lambda` → `{'fun', …}`, вызов имени из scope → `{call, {var, …}}`; определения и вызовы различаются
  по (имя, арность); включения → `lc`/`mc`/`m_generate`;
  вложенный `def` → `named_fun` (рекурсия) с привязкой имени как обычной переменной, декораторы
  применяются сразу (`F = Dec(fun …)`), имя в `_scope` разрешается как переменная и в декораторах;
  `squeal_iter/1` генерируется по требованию (map → ключи, список → как есть); декораторы —
  `f@impl/N` + обёртка через `persistent_term` + `squeal_on_load/0` (`-on_load`);
  методы stdlib — таблица в бэкенде: `str` → `string:*`/`binary:*` под проверкой `is_binary`,
  `dict` → `maps:*`, `list`/`tuple` → `count` через `case` по `is_list`/`is_tuple` (свежие имена
  привязок `_squeal@…`), неверный получатель — `erlang:error({bad_receiver, Метод, Значение})`,
  неизвестное имя/арность — `SquealError`;
  `print` → `squeal_print/1` (`io:format("~ts~n")`), хелперы `squeal_str/1`, `squeal_str_tuple/1`,
  `squeal_str_map/1` — питоновское представление значения, генерируются по требованию;
  `term.py` печатает Erlang-float (`1e-5` → `1.0e-5`) и строки (`\x{HEX}` для не-ASCII/управляющих).
  импорт → `{call, {remote, a@b@c, f}}` (имя из scope имеет приоритет над импортом).
- `term.py` — `Atom` и печать термов в текст для `file:consult`.
- `squeal_compile.escript` — читает `.abstr`, зовёт `compile:forms` (+ `return`), печатает `.erl`
  через `erl_pp`; ошибки линта форматирует в `путь:строка: текст` (дамп терма наружу не выходит).
- `compiler.py` — конвейер (`compile_source`, `build`); `__main__.py` — командная строка.
- `session.py` — shell-режим: клетка → формы; session хранит маппинг имён/классы/импорты.
- `repl.py` + `repl.escript` — persistent Erlang-REPL (`erl_eval:exprs`, bindings живут;
  `'$pp'` — `erl_pp` формы для печати эквивалента; вывод `print` копится в process dictionary и
  уходит фреймом `OUT <base64>` до строки `OK …`, клиент печатает его в stdout).
- `notebook.py` — ipykernel-хук (`pre/post_run_cell` + `ast_transformer` в `pass` + input-трансформер
  для образцов-присваиваний); перед результатом включений печатает `erl: …`; значение клетки `nil`
  не печатает.

## Границы и ограничения

- Этап 7: на верхнем уровне `def`, `class`, `from … import …`; дерево `src/**` (модуль `a@b@c`),
  вывод в `build/dev/erlang/<app>/ebin`. Вне: `import X`/`import *`, generator-выражения,
  `NativeRecord`/`Map`, `is`/`is not`, цепочки сравнений, циклы и мутация (запрещены).
- Типов нет, `-spec` не генерируется (см. architecture.md).
