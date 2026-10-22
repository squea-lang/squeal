"""Erlang-термы как значения Python и их печать в текст.

Атом — подкласс str (``Atom``), чтобы отличать его от строкового литерала.
Формы бэкенда — вложенные кортежи/списки/Atom/str/int, которые печатает
:func:`term_to_erlang` в текст, читаемый ``file:consult``.
"""

from __future__ import annotations

import re

_BARE_ATOM = re.compile(r"^[a-z][a-zA-Z0-9_@]*$")

# Слова Erlang, которые нельзя печатать голым атомом.
_RESERVED = {
    "after", "and", "andalso", "band", "begin", "bnot", "bor", "bsl", "bsr",
    "bxor", "case", "catch", "cond", "div", "else", "end", "fun", "if", "let",
    "maybe", "not", "of", "or", "orelse", "query", "receive", "rem", "try",
    "when", "xor",
}


class Atom(str):
    """Атом Erlang."""


def _float_text(value: float) -> str:
    """Erlang-float: всегда с десятичной точкой (``1e-05`` → ``1.0e-5``)."""
    r = repr(value)
    if "e" in r or "E" in r:
        mantissa, exp = re.split("[eE]", r)
        if "." not in mantissa:
            mantissa += ".0"
        return f"{mantissa}e{int(exp)}"
    if "." not in r:
        r += ".0"
    return r


def _string_text(value: str) -> str:
    out = ['"']
    for ch in value:
        o = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\f":
            out.append("\\f")
        elif ch == "\v":
            out.append("\\v")
        elif o < 0x20 or o > 0x7E:
            out.append("\\x{%X}" % o)  # не-ASCII/управляющие → \x{HEX}
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def term_to_erlang(term) -> str:
    """Печать терма как Erlang-текст."""
    if isinstance(term, Atom):
        name = str(term)
        if name in _RESERVED or not _BARE_ATOM.match(name):
            return "'" + name.replace("\\", "\\\\").replace("'", "\\'") + "'"
        return name
    if isinstance(term, bool):
        return "true" if term else "false"
    if isinstance(term, int):
        return str(term)
    if isinstance(term, float):
        return _float_text(term)
    if isinstance(term, str):
        return _string_text(term)
    if isinstance(term, tuple):
        return "{" + ",".join(term_to_erlang(x) for x in term) + "}"
    if isinstance(term, list):
        return "[" + ",".join(term_to_erlang(x) for x in term) + "]"
    raise TypeError(f"не Erlang-терм: {term!r}")
