"""A tiny parser for Erlang terms printed with ``~p`` (for the Gleam reference forms).

Returns Python values: atom → ``Atom``, string → ``str``, tuple → ``tuple``,
list → ``list``, numbers → ``int``/``float``.
"""

from __future__ import annotations

import re

from squeal.term import Atom

_ATOM = re.compile(r"[a-z][a-zA-Z0-9_@]*")
_NUMBER = re.compile(r"-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?")


def parse(text: str):
    return _Parser(text).parse()


class _Parser:
    def __init__(self, text: str):
        self.t = text
        self.i = 0
        self.n = len(text)

    def parse(self):
        self._ws()
        value = self._value()
        self._ws()
        return value

    def _ws(self):
        while self.i < self.n and self.t[self.i] in " \t\r\n":
            self.i += 1

    def _value(self):
        c = self.t[self.i]
        if c == "{":
            return self._tuple()
        if c == "[":
            return self._list()
        if c == '"':
            return self._string()
        if c == "'":
            return self._quoted_atom()
        return self._atom_or_number()

    def _tuple(self):
        self.i += 1
        items = []
        self._ws()
        if self.t[self.i] == "}":
            self.i += 1
            return tuple(items)
        while True:
            items.append(self._value())
            self._ws()
            c = self.t[self.i]
            if c == ",":
                self.i += 1
                self._ws()
                continue
            if c == "}":
                self.i += 1
                return tuple(items)
            raise ValueError(self._err("expected ',' or '}' in a tuple"))

    def _list(self):
        self.i += 1
        items = []
        self._ws()
        if self.t[self.i] == "]":
            self.i += 1
            return items
        while True:
            items.append(self._value())
            self._ws()
            c = self.t[self.i]
            if c == ",":
                self.i += 1
                self._ws()
                continue
            if c == "]":
                self.i += 1
                return items
            raise ValueError(self._err("expected ',' or ']' in a list"))

    def _string(self):
        self.i += 1
        out = []
        while self.t[self.i] != '"':
            c = self.t[self.i]
            if c == "\\":
                self.i += 1
                out.append(_unescape(self.t[self.i]))
                self.i += 1
            else:
                out.append(c)
                self.i += 1
        self.i += 1
        return "".join(out)

    def _quoted_atom(self):
        self.i += 1
        out = []
        while self.t[self.i] != "'":
            c = self.t[self.i]
            if c == "\\":
                self.i += 1
                out.append(_unescape(self.t[self.i]))
                self.i += 1
            else:
                out.append(c)
                self.i += 1
        self.i += 1
        return Atom("".join(out))

    def _atom_or_number(self):
        m = _NUMBER.match(self.t, self.i)
        if m:
            tok = m.group(0)
            self.i = m.end()
            if "." in tok or "e" in tok or "E" in tok:
                return float(tok)
            return int(tok)
        m = _ATOM.match(self.t, self.i)
        if m:
            self.i = m.end()
            return Atom(m.group(0))
        raise ValueError(self._err("unrecognized term"))

    def _err(self, what: str) -> str:
        return f"{what}: {self.t[self.i:self.i + 20]!r}"


def _unescape(c: str) -> str:
    return {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'"}.get(c, c)
