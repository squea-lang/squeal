# Squeal

Gleam-подобный язык для BEAM (виртуальной машины Erlang) с синтаксисом Python.
Исходники — файлы `.ee`; компилятор генерирует Erlang Abstract Format и `.beam` так же,
как Gleam 1.19.

## Быстрый старт

Проект — каталог с деревом `src/`:

```
my_app/
└── src/
    └── hello.ee
```

`hello.ee`:

```python
def hello():
    "hi"
```

Сборка:

```
python -m squeal build my_app
```

Запуск:

```
erl -pa my_app/build/dev/erlang/my_app/ebin -noshell \
  -eval 'io:format("~p~n", [hello:hello()]), halt().'
# => <<"hi">>
```

Модуль — это путь файла под `src/`: `src/a/b/c.ee` → модуль `a@b@c`; импорт
`from a.b.c import f` → вызов `a@b@c:f(...)`.

## Язык

Синтаксис Python, семантика Gleam/Erlang:

- неизменяемость: циклов `for`/`while` нет, мутация запрещена; `x = x + 1` — переприсваивание
  (новое Erlang-имя `X@1`);
- атомы — одинарные кавычки `'ok'`, строки — двойные `"..."`;
- `if`/`else` и `match`/`case` (в условии — только bool; несматченный match — «let it crash»);
- классы `class T(StartingWithAtom): x: int` → кортеж `{t, …}`;
- `lambda`, list/dict comprehensions, декораторы;
- `print(x)` — печать в stdout (питоновское представление значений), возвращает `nil`;
- методы стандартной библиотеки: `d.keys()/values()/items()/get()`, `s.startswith/endswith/
  lower/upper/strip/lstrip/rstrip/split/join/replace/splitlines`, `xs.count(x)` у списков и кортежей;
- `==` как в Python (`1 == 1.0` → true), `// % **` — Python-семантика.

Полные правила — в `goal-and-requirements.md` и `architecture.md`.

## Разработка

```
python -m venv .venv
.venv/bin/pip install pytest
.venv/bin/python -m pytest
```

Тесты включают 18 паритет-пар с Gleam: на эквивалентном коде squeal и Gleam генерируют
одинаковые Erlang-формы.
