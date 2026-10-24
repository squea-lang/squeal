# Squeal

Gleam-подобный язык для BEAM (виртуальной машины Erlang) с синтаксисом Python.
Исходники — файлы `.ee`; компилятор генерирует Erlang Abstract Format и `.beam` так же,
как Gleam 1.19.

## Установка

```
pip install squealang      # на PyPI имя свободного «squeal» занято другим пакетом
```

Пакет требует Python 3.15 и Erlang/OTP с `escript` в `PATH`. После установки доступны
`squeal build DIR` и `python -m squeal build DIR`.

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
- `zip(a, b)` — пары до конца короткого списка, `enumerate(xs[, start])` — пары `(номер, значение)`;
  оба неленивые и принимают только списки;
- `range(...)` — питоновский range, но неленивый: возвращает список;
- `print`/`zip`/`enumerate`/`range` можно переопределить своим `def` — имя разрешается как обычное (по имени);
- методы стандартной библиотеки: `d.keys()/values()/items()/get()`, `s.startswith/endswith/
  lower/upper/strip/lstrip/rstrip/split/join/replace/splitlines`, `xs.count(x)` у списков и кортежей;
- `==` как в Python (`1 == 1.0` → true), `// % **` — Python-семантика.

Полные правила — в `specs/goal-and-requirements.md` и `specs/architecture.md`.

## Разработка

```
python -m venv .venv
.venv/bin/pip install pytest
.venv/bin/python -m pytest
```

Тесты включают 18 паритет-пар с Gleam: на эквивалентном коде squeal и Gleam 1.19.2 генерируют
одинаковые Erlang-формы. Для них нужен установленный `gleam` в `PATH` (сам компилятор Gleam в
репозиторий не входит — для справки держите локальный клон `gleam/`, он в `.gitignore`).
