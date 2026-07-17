"""Shared access to Path of Building Community's static game data export.

PoB's `src/Data/*.lua` files are generated directly from GGG's game data on
every patch, making them a far more stable source than scraping poedb.tw's
HTML (which breaks whenever the site's layout changes). This module provides
a raw-file fetcher and a small Lua table literal parser shared by the gem,
item, and mod scrapers.
"""

import re
from typing import Union

import httpx

from scrapers.common import HEADERS

POB_RAW_BASE = "https://raw.githubusercontent.com/PathOfBuildingCommunity/PathOfBuilding/dev/src/Data"

_COMMENT_RE = re.compile(r"--\[\[.*?\]\]|--[^\n]*")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_NUMBER_RE = re.compile(r"-?\d+\.?\d*(?:[eE][+-]?\d+)?")

# A parsed Lua value: table (dict for keyed / dict with "_array" for mixed / list for pure array),
# string, number, bool, or nil (None).
LuaValue = Union[dict, list, str, float, int, bool, None]


def fetch_lua_file(path: str) -> str:
    """Fetch a raw .lua file from PathOfBuilding's Data directory. e.g. path='Gems.lua' or 'Uniques/amulet.lua'."""
    resp = httpx.get(f"{POB_RAW_BASE}/{path}", headers=HEADERS, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    return resp.text


class _LuaTableParser:
    """Minimal recursive-descent parser for Lua table literals (data-only, no expressions/functions)."""

    def __init__(self, text: str):
        self.text = _COMMENT_RE.sub("", text)
        self.pos = 0
        self.len = len(self.text)

    def parse(self) -> LuaValue:
        self._skip_ws()
        return self._parse_value()

    def _skip_ws(self):
        while self.pos < self.len and self.text[self.pos] in " \t\r\n":
            self.pos += 1

    def _peek(self) -> str:
        return self.text[self.pos] if self.pos < self.len else ""

    def _parse_value(self) -> LuaValue:
        self._skip_ws()
        c = self._peek()
        if c == "{":
            return self._parse_table()
        if c == '"' or c == "'":
            return self._parse_string(c)
        if self.text[self.pos:self.pos + 2] == "[[":
            return self._parse_long_string()
        if c == "-" or c.isdigit():
            m = _NUMBER_RE.match(self.text, self.pos)
            if m:
                self.pos = m.end()
                s = m.group(0)
                return float(s) if ("." in s or "e" in s or "E" in s) else int(s)
        m = _IDENT_RE.match(self.text, self.pos)
        if m:
            word = m.group(0)
            self.pos += len(word)
            if word == "true":
                return True
            if word == "false":
                return False
            if word == "nil":
                return None
            return word  # bareword (e.g. enum reference like SkillType.Fire) — kept as-is
        raise ValueError(f"Unexpected token at {self.pos}: {self.text[self.pos:self.pos + 30]!r}")

    def _parse_string(self, quote: str) -> str:
        self.pos += 1
        start = self.pos
        out = []
        while self.pos < self.len and self.text[self.pos] != quote:
            if self.text[self.pos] == "\\" and self.pos + 1 < self.len:
                out.append(self.text[start:self.pos])
                out.append(self.text[self.pos + 1])
                self.pos += 2
                start = self.pos
            else:
                self.pos += 1
        out.append(self.text[start:self.pos])
        self.pos += 1  # closing quote
        return "".join(out)

    def _parse_long_string(self) -> str:
        end = self.text.find("]]", self.pos + 2)
        if end == -1:
            content = self.text[self.pos + 2:]
            self.pos = self.len
        else:
            content = self.text[self.pos + 2:end]
            self.pos = end + 2
        return content

    def _parse_table(self) -> dict | list:
        self.pos += 1  # consume '{'
        arr: list[LuaValue] = []
        obj: dict[str, LuaValue] = {}
        while True:
            self._skip_ws()
            if self._peek() == "}":
                self.pos += 1
                break
            if self._peek() == "":
                break

            key = None
            if self._peek() == "[":
                self.pos += 1
                self._skip_ws()
                key = self._parse_value()
                self._skip_ws()
                if self._peek() == "]":
                    self.pos += 1
                self._skip_ws()
                if self._peek() == "=":
                    self.pos += 1
            else:
                m = _IDENT_RE.match(self.text, self.pos)
                if m and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", m.group(0)):
                    save = self.pos
                    ident = m.group(0)
                    self.pos += len(ident)
                    self._skip_ws()
                    if self._peek() == "=":
                        key = ident
                        self.pos += 1
                    else:
                        self.pos = save

            value = self._parse_value()
            if key is not None:
                obj[key] = value
            else:
                arr.append(value)

            self._skip_ws()
            if self._peek() in (",", ";"):
                self.pos += 1
                continue
            self._skip_ws()
            if self._peek() == "}":
                self.pos += 1
                break

        if obj and arr:
            obj["_array"] = arr
            return obj
        return obj if obj else arr


def parse_lua_table(text: str) -> dict[str, LuaValue]:
    """Parse a Lua chunk of the form `return { ["Key"] = {...}, ... }` into a Python dict.

    Every PoB data file this is used on (Gems.lua, Mod*.lua) is a single keyed table at the
    top level, so callers can rely on a dict — not the full LuaValue union.
    """
    idx = text.find("return")
    if idx != -1:
        text = text[idx + len("return"):]
    result = _LuaTableParser(text).parse()
    return result if isinstance(result, dict) else {}


def _find_matching_brace(text: str, start: int) -> int:
    """Given the index of an opening '{', return the index of its matching '}'."""
    depth = 0
    i = start
    in_str = None
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
        elif c in ('"', "'"):
            in_str = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return len(text) - 1


def parse_lua_assignments(text: str, var_name: str) -> dict[str, LuaValue]:
    """Parse a sequence of `var_name["Key"] = { ... }` statements (PoB's Skills/*.lua style)."""
    text = _COMMENT_RE.sub("", text)
    pattern = re.compile(re.escape(var_name) + r'\["([^"]+)"\]\s*=\s*')
    result: dict[str, LuaValue] = {}
    for m in pattern.finditer(text):
        key = m.group(1)
        brace_start = text.find("{", m.end())
        if brace_start == -1:
            continue
        brace_end = _find_matching_brace(text, brace_start)
        try:
            result[key] = _LuaTableParser(text[brace_start:brace_end + 1]).parse()
        except Exception:
            continue
    return result
