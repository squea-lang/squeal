# Методы (OOP) — предложение

Рабочий документ (не спека): список методов для утверждения и правки.

## Принципы

- Методы есть **только** у структур стандартной библиотеки; сторонний код определять методы не может.
- Только **неизменяющие** методы: в Python мутирующие (`append`, `sort`, `update`, …) меняют объект и
  возвращают `None` — в squeal мутации нет.
- **Диспетчеризация по типу значения** в рантайме: получатель — обычное значение, тип проверяется при
  вызове (`is_binary` / `is_map` / `is_list` / `is_tuple`); не тот тип — падение (`badarg`/`badmap`).
- Список методов — таблица в компиляторе; неизвестный метод — ошибка компиляции (как сейчас).

## dict (map)

| Метод | Python | Erlang |
|---|---|---|
| `keys()` | список ключей | `maps:keys/1` |
| `values()` | список значений | `maps:values/1` |
| `items()` | список пар `(k, v)` | `maps:to_list/1` |
| `get(k)` | значение или `None` | `maps:get(K, M, nil)` |
| `get(k, d)` | значение или `d` | `maps:get(K, M, D)` |

## str (binary)

| Метод | Erlang |
|---|---|
| `startswith(p)` | `string:prefix(S, P) =/= nomatch` |
| `endswith(p)` | `string:suffix(S, P) =/= nomatch` |
| `lower()` | `string:lowercase/1` |
| `upper()` | `string:uppercase/1` |
| `strip()` | `string:trim/1` (оба края, пробелы) |
| `lstrip()` | `string:trim(S, leading)` |
| `rstrip()` | `string:trim(S, trailing)` |
| `split(sep)` | `string:split(S, Sep, all)` |
| `split()` | `string:lexemes(S, " \t\n\r\f\v")` — серии пробельных схлопываются |
| `join(parts)` | `iolist_to_binary(lists:join(S, Parts))` |
| `replace(old, new)` | `binary:replace(S, Old, New, [global])` |
| `find(sub)` | `binary:match/2` → позиция, иначе `-1` |

## list / tuple

| Метод | Erlang |
|---|---|
| `count(x)` | число элементов `=:=` X |

## set

**Пропущено**: в squeal нет множеств — ни литерала, ни включения, ни значения. Чтобы появились методы
`set`, сначала нужна отдельная фича с представлением множества (например, на `ordsets`/`maps`).

## Явно не входит (мутирующие)

`append`, `extend`, `insert`, `remove`, `pop`, `clear`, `sort`, `reverse`, `update`, `setdefault`,
`popitem`, `add`, `discard`, `difference_update`, …

## Коллизии имён

Реально сталкиваются только два имени; для них — `case` по типу получателя:

- `count/1` — `str` (подстрока), `list` (элемент), `tuple` (элемент);

  для str не нужен count

- `index/1` — `list`, `tuple`

  index не нужен

Остальные имена уникальны для своего типа.

## Вопросы к автору

1. `find` возвращает `-1` (как Python) или `nil`?
  find не нужен
2. `list.index` — падать при отсутствии (Python: `ValueError`) или вернуть `-1`?
  index не нужен
3. Нужны ли `xs.sorted()` / `xs.reversed()` (в Python их нет — там `sorted()`/`reversed()`)?
  нет
4. Нужны ли `isdigit()`, `isalpha()`, `isspace()`, `capitalize()`, `title()`, `splitlines()`?
  только splitlines
5. Нужны ли аргументы сверх базовых: `strip(chars)`, `split(sep, maxsplit)`, `replace(old, new, count)`?
  нет
6. `startswith`/`endswith` — можно ли передавать кортеж вариантов, как в Python?
  нет
