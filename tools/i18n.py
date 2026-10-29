#!/usr/bin/env python3
"""Find every piece of text Wirely shows and check each language has a translation for it.

    python tools/i18n.py            report what is missing / unused / broken in each language
    python tools/i18n.py keys       print every English string (JSON), in order
    python tools/i18n.py missing es print the English strings that Spanish doesn't have yet (JSON)

The English text in the code IS the key (see wirely/i18n.py), so a new sentence only needs a line in
wirely/locale/es.json, de.json and ja.json. Strings come from:
  * tr(...) / trn(...) calls in the Python code (desktop app and web glue) and in web/app.js,
  * the actions and menu names of the desktop window,
  * the data tables: part names, descriptions, property labels, choices, type notes, shortcuts, speeds …,
  * the fixed text of web/index.html, and the notes that come with the example circuits.
Exit status is 1 if anything is missing or broken, so it can run in CI.
"""
from __future__ import annotations

import ast
import glob
import html.parser
import json
import os
import re
import string
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
LOCALE = os.path.join(ROOT, "wirely", "locale")
LANGS = ("es", "de", "ja")


# ---------------------------------------------------------------------------------------------- Python code
def _strings_in(node):
    """The message(s) an expression can produce: a literal, either side of an if/else, the values of a lookup
    table ({...}[key] or {...}.get(key, default)). Dict keys and anything computed are not words."""
    if isinstance(node, ast.Constant):
        return [node.value] if isinstance(node.value, str) and node.value.strip() else []
    if isinstance(node, ast.IfExp):
        return _strings_in(node.body) + _strings_in(node.orelse)
    if isinstance(node, ast.Subscript):
        return _strings_in(node.value)
    if isinstance(node, ast.Dict):
        return [s for v in node.values for s in _strings_in(v)]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _strings_in(node.left) + _strings_in(node.right)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get":
        return _strings_in(node.func.value) + [s for a in node.args[1:] for s in _strings_in(a)]
    return []


def python_keys():
    out = {}
    files = glob.glob(os.path.join(ROOT, "wirely", "**", "*.py"), recursive=True) + glob.glob(
        os.path.join(ROOT, "web", "py", "*.py"))
    for path in sorted(files):
        if os.sep + "fallback" + os.sep in path or path.endswith(os.path.join("wirely", "i18n.py")):
            continue
        tree = ast.parse(open(path, encoding="utf-8").read())
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            name = n.func.id if isinstance(n.func, ast.Name) else n.func.attr if isinstance(n.func, ast.Attribute) else ""
            if name in ("tr", "trn") and n.args:
                for a in n.args[: 2 if name == "trn" else 1]:
                    for s in _strings_in(a):
                        out.setdefault(s, path)
            elif name in ("A", "_act") and path.endswith("mainwindow.py"):
                # A(text, slot, shortcut, icon, tip): the text and the tip are shown
                for i, a in enumerate(n.args):
                    if i in (0, 4):
                        for s in _strings_in(a):
                            out.setdefault(s, path)
                for kw in n.keywords:
                    if kw.arg == "tip":
                        for s in _strings_in(kw.value):
                            out.setdefault(s, path)
    # the menu names across the top of the desktop window
    src = open(os.path.join(ROOT, "wirely", "ui", "mainwindow.py"), encoding="utf-8").read()
    for m in re.finditer(r'^\s+\("([A-Z][A-Za-z ]+)", (?:\[|list\()', src, re.M):
        out.setdefault(m.group(1), "mainwindow.py")
    return out


# ---------------------------------------------------------------------------------------------- data tables
def data_keys():
    out = {}

    def add(s, where):
        if isinstance(s, str) and s.strip():
            out.setdefault(s, where)

    from wirely.model import parts as P
    from wirely.model.types_info import TYPE_INFO
    for pd in P._PARTS:
        for s in (pd.name, pd.tile_name, pd.category, pd.description):
            add(s, "parts")
        for p in pd.props:
            add(p.label, "parts")
            add(p.help, "parts")
            for c in p.choices:
                if re.search(r"[A-Za-z]{3,}", str(c)) and not re.search(r"\d", str(c)):
                    add(str(c), "parts")
    for v in TYPE_INFO.values():
        add(v, "types_info")
    from wirely.ui.dialogs import SHORTCUTS
    for a, b in SHORTCUTS:
        add(a, "dialogs")
        add(b, "dialogs")
    from wirely.ui.graph import TIMEBASES, VOLTS
    from wirely.ui.simcontrol import SPEEDS
    for table in (SPEEDS, TIMEBASES, VOLTS):
        for name, _v in table:
            add(name, "tables")
    for path in sorted(glob.glob(os.path.join(ROOT, "examples", "*.wirely"))):
        add(os.path.splitext(os.path.basename(path))[0], "examples")
        for c in json.load(open(path, encoding="utf-8")).get("components", []):
            if c.get("kind") == "note":
                add(c.get("props", {}).get("text"), "examples")
    return out


# ---------------------------------------------------------------------------------------------- web page
SHORTCUT_LIKE = re.compile(r"^(Ctrl\+|Shift\+|F\d+$|Del$|Enter$|[A-Z]$|[+−▸]$)")


def js_keys():
    out = {}
    src = open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
    for m in re.finditer(r'\btrn?\(\s*"((?:[^"\\]|\\.)*)"(?:\s*,\s*"((?:[^"\\]|\\.)*)")?', src):
        for g in m.groups():
            if g:
                out.setdefault(json.loads('"' + g + '"'), "app.js")
    # the menus and the help rows are written as plain English lists and translated when shown
    i = src.index("const MENUS = {")
    block = src[i: src.index("\n};", i)]
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', block):
        s = m.group(1)
        if re.search(r"[A-Za-z]{3,}", s) and not re.fullmatch(r"[a-z_]+(:.*)?", s) and not SHORTCUT_LIKE.match(s):
            out.setdefault(s, "app.js")
    j = src.index("const web = [[")
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', src[j: src.index("];", j)]):
        out.setdefault(m.group(1), "app.js")
    return out


class _Html(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found, self.stack = [], []

    def handle_starttag(self, tag, attrs):
        self.stack.append(tag)
        d = dict(attrs)
        for a in ("title", "placeholder", "aria-label", "alt"):
            if d.get(a):
                self.found.append(d[a])
        if tag == "meta" and d.get("name") == "description" and d.get("content"):
            self.found.append(d["content"])

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()

    def handle_data(self, data):
        if self.stack and self.stack[-1] in ("script", "style"):
            return
        if data.strip():
            self.found.append(data.strip())


def html_keys():
    p = _Html()
    p.feed(open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read())
    return {s: "index.html" for s in p.found if re.search(r"[A-Za-z]{3,}", s)}


# ---------------------------------------------------------------------------------------------- the checks
def all_keys():
    out = {}
    for fn in (python_keys, data_keys, js_keys, html_keys):
        for k, v in fn().items():
            out.setdefault(k, v)
    return out


def placeholders(s):
    return sorted({f for _lit, f, _spec, _conv in string.Formatter().parse(s) if f})


def load(code):
    path = os.path.join(LOCALE, f"{code}.json")
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}


def problems(code, keys):
    cat = load(code)
    missing = [k for k in keys if not cat.get(k)]
    unused = [k for k in cat if k not in keys]
    broken = []
    for k, v in cat.items():
        if not isinstance(v, str) or not v.strip():
            broken.append((k, "empty"))
            continue
        try:
            if placeholders(k) != placeholders(v):
                broken.append((k, f"placeholders {placeholders(k)} vs {placeholders(v)}"))
        except ValueError as e:
            broken.append((k, f"bad format string: {e}"))
    return missing, unused, broken


def main(argv):
    keys = all_keys()
    if argv[:1] == ["keys"]:
        print(json.dumps(list(keys), ensure_ascii=False, indent=1))
        return 0
    if argv[:1] == ["missing"]:
        print(json.dumps([k for k in keys if not load(argv[1]).get(k)], ensure_ascii=False, indent=1))
        return 0
    bad = False
    print(f"{len(keys)} strings to translate")
    for code in LANGS:
        missing, unused, broken = problems(code, keys)
        print(f"  {code}: {len(keys) - len(missing)} done, {len(missing)} missing, {len(unused)} unused, {len(broken)} broken")
        for k in missing[:10]:
            print("      missing:", repr(k)[:110])
        for k in unused[:5]:
            print("      unused: ", repr(k)[:110])
        for k, why in broken[:10]:
            print("      broken: ", repr(k)[:80], why)
        bad = bad or bool(missing or broken)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
