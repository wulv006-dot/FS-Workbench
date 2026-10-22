#!/usr/bin/env python3
"""Minimal JS object/array literal parser -> Python objects.

Handles: objects (bare/quoted keys), arrays, single/double quoted strings with
escapes, numbers, true/false/null, trailing commas, // and /* */ comments.
Not a full JS engine; sufficient for extracting data blocks from the dashboard
page source.
"""
import json
import re


class NotLiteral(Exception):
    pass


class Parser:
    def __init__(self, src, pos=0):
        self.s = src
        self.i = pos

    def ws(self):
        s, n = self.s, len(self.s)
        while self.i < n:
            c = s[self.i]
            if c in " \t\r\n\ufeff":
                self.i += 1
            elif c == "/" and self.i + 1 < n and s[self.i + 1] == "/":
                j = s.find("\n", self.i)
                self.i = n if j < 0 else j + 1
            elif c == "/" and self.i + 1 < n and s[self.i + 1] == "*":
                j = s.find("*/", self.i + 2)
                self.i = n if j < 0 else j + 2
            else:
                break

    def value(self):
        self.ws()
        if self.i >= len(self.s):
            raise NotLiteral("eof")
        c = self.s[self.i]
        if c == "{":
            return self.obj()
        if c == "[":
            return self.arr()
        if c in "\"'":
            return self.string()
        if c == "`":
            return self.template()
        m = re.compile(r"-?(?:0[xX][0-9a-fA-F]+|\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+)").match(self.s, self.i)
        if m:
            self.i = m.end()
            t = m.group(0)
            try:
                if t.lower().startswith(("0x", "-0x")):
                    return int(t, 16)
                if "." in t or "e" in t.lower():
                    return float(t)
                return int(t)
            except ValueError:
                raise NotLiteral(t)
        for word, val in (("true", True), ("false", False), ("null", None), ("undefined", None), ("void 0", None)):
            if self.s.startswith(word, self.i):
                self.i += len(word)
                return val
        raise NotLiteral(self.s[self.i:self.i + 40])

    def string(self):
        q = self.s[self.i]
        self.i += 1
        out = []
        s, n = self.s, len(self.s)
        while self.i < n:
            c = s[self.i]
            if c == "\\":
                self.i += 1
                e = s[self.i]
                if e == "n":
                    out.append("\n")
                elif e == "t":
                    out.append("\t")
                elif e == "r":
                    out.append("\r")
                elif e == "b":
                    out.append("\b")
                elif e == "f":
                    out.append("\f")
                elif e == "u":
                    out.append(chr(int(s[self.i + 1:self.i + 5], 16)))
                    self.i += 4
                elif e == "x":
                    out.append(chr(int(s[self.i + 1:self.i + 3], 16)))
                    self.i += 2
                elif e == "\n":
                    pass
                else:
                    out.append(e)
                self.i += 1
            elif c == q:
                self.i += 1
                return "".join(out)
            else:
                out.append(c)
                self.i += 1
        raise NotLiteral("unterminated string")

    def template(self):
        self.i += 1
        out = []
        s, n = self.s, len(self.s)
        while self.i < n:
            c = s[self.i]
            if c == "\\":
                out.append(s[self.i + 1])
                self.i += 2
            elif c == "`":
                self.i += 1
                return "".join(out)
            elif c == "$" and self.i + 1 < n and s[self.i + 1] == "{":
                depth = 1
                j = self.i + 2
                while j < n and depth:
                    if s[j] == "{":
                        depth += 1
                    elif s[j] == "}":
                        depth -= 1
                    j += 1
                out.append(s[self.i:j])
                self.i = j
            else:
                out.append(c)
                self.i += 1
        raise NotLiteral("unterminated template")

    def key(self):
        self.ws()
        c = self.s[self.i]
        if c in "\"'":
            return self.string()
        m = re.compile(r"[A-Za-z_$][\w$]*|\d+").match(self.s, self.i)
        if not m:
            raise NotLiteral("bad key at %d: %r" % (self.i, self.s[self.i:self.i + 30]))
        self.i = m.end()
        return m.group(0)

    def obj(self):
        self.i += 1
        d = {}
        while True:
            self.ws()
            if self.i >= len(self.s):
                raise NotLiteral("eof in object")
            if self.s[self.i] == "}":
                self.i += 1
                return d
            k = self.key()
            self.ws()
            if self.s[self.i] != ":":
                raise NotLiteral("expected ':' at %d got %r" % (self.i, self.s[self.i:self.i + 20]))
            self.i += 1
            d[k] = self.value()
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1
            elif self.i < len(self.s) and self.s[self.i] == "}":
                self.i += 1
                return d
            else:
                raise NotLiteral("expected ',' or '}' at %d got %r" % (self.i, self.s[self.i:self.i + 20]))

    def arr(self):
        self.i += 1
        a = []
        while True:
            self.ws()
            if self.i >= len(self.s):
                raise NotLiteral("eof in array")
            if self.s[self.i] == "]":
                self.i += 1
                return a
            a.append(self.value())
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1
            elif self.i < len(self.s) and self.s[self.i] == "]":
                self.i += 1
                return a
            else:
                raise NotLiteral("expected ',' or ']' at %d got %r" % (self.i, self.s[self.i:self.i + 20]))


def extract(src, marker, skip=0):
    """Parse the first literal that starts after `marker`."""
    start = src.find(marker)
    if start < 0:
        raise NotLiteral("marker not found: " + marker)
    i = start + len(marker)
    while i < len(src) and src[i] not in "{[": 
        i += 1
    p = Parser(src, i)
    return p.value(), p.i


if __name__ == "__main__":
    import sys
    src = open(sys.argv[1], encoding="utf-8").read()
    val, _ = extract(src, sys.argv[2])
    print(json.dumps(val, ensure_ascii=False)[:2000])
