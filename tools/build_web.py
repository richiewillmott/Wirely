"""Builds the browser version of Wirely (Wirely Web) into a folder you can put on any web server.

    python tools/build_web.py                      # -> _site/
    python tools/build_web.py --pyodide path/to/pyodide/package   # also copy Pyodide in (no CDN needed)

What goes in the folder:
  index.html, app.js, style.css, …   the page (from web/)
  locale/                             the translations (one JSON file per language), shared with the desktop app
  wirely-py.zip                       Wirely's Python code: wirely/model, wirely/sim and the drawing / sheet code
                                      from wirely/ui, plus web/py (the Qt stand-in and the glue)
  examples/                           the example circuits and a list of them
  pyodide/                            Python for the browser, if --pyodide is given (otherwise it loads from
                                      the jsDelivr CDN)

The desktop app is not changed by any of this.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# the desktop UI files the web version reuses (they only need the parts of Qt that web/py/qtshim.py provides)
UI_FILES = ["__init__.py", "symbols.py", "theme.py", "items.py", "scene.py", "live_items.py", "simcontrol.py",
            "graph.py", "icons.py", "dialogs.py"]
STATIC = ["index.html", "app.js", "style.css", "sw.js", "manifest.webmanifest"]
PYODIDE_FILES = ["pyodide.js", "pyodide.mjs", "pyodide.asm.mjs", "pyodide.asm.wasm", "python_stdlib.zip",
                 "pyodide-lock.json", "package.json"]


def build_zip(path):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        def add(src, arc):
            z.write(src, arc)
        add(os.path.join(ROOT, "wirely", "__init__.py"), "wirely/__init__.py")
        add(os.path.join(ROOT, "wirely", "i18n.py"), "wirely/i18n.py")
        loc = os.path.join(ROOT, "wirely", "locale")             # the translations (Spanish, German, Japanese)
        for name in sorted(os.listdir(loc)) if os.path.isdir(loc) else []:
            if name.endswith(".json"):
                add(os.path.join(loc, name), f"wirely/locale/{name}")
        for sub in ("model", "sim"):
            d = os.path.join(ROOT, "wirely", sub)
            for name in sorted(os.listdir(d)):
                if name.endswith(".py"):
                    add(os.path.join(d, name), f"wirely/{sub}/{name}")
        for name in UI_FILES:
            add(os.path.join(ROOT, "wirely", "ui", name), f"wirely/ui/{name}")
        web_py = os.path.join(ROOT, "web", "py")
        for base, _dirs, files in os.walk(web_py):
            for name in sorted(files):
                if name.endswith(".py"):
                    full = os.path.join(base, name)
                    add(full, os.path.relpath(full, web_py).replace(os.sep, "/"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(ROOT, "_site"))
    ap.add_argument("--pyodide", help="folder with Pyodide's files (e.g. the 'package' folder of the npm package)")
    ap.add_argument("--numpy", help="numpy wheel for Pyodide to put next to it (optional)")
    a = ap.parse_args(argv)
    from wirely import __version__

    out = os.path.abspath(a.out)
    if os.path.isdir(out):
        shutil.rmtree(out)
    os.makedirs(out)
    web = os.path.join(ROOT, "web")
    for name in STATIC:
        src = os.path.join(web, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(out, name))
    if os.path.isdir(os.path.join(web, "icons")):
        shutil.copytree(os.path.join(web, "icons"), os.path.join(out, "icons"))
    # the version goes into the service worker, so a new release replaces the copy browsers keep offline
    sw = os.path.join(out, "sw.js")
    if os.path.exists(sw):
        with open(sw, encoding="utf-8") as fh:
            build = (os.environ.get("GITHUB_SHA") or "")[:7] or time.strftime("%Y%m%d%H%M%S")
            text = fh.read().replace("__VERSION__", f"{__version__}-{build}")
        with open(sw, "w", encoding="utf-8") as fh:
            fh.write(text)
    build_zip(os.path.join(out, "wirely-py.zip"))
    # the page reads the same translations for its own text (and for the loading messages, before Python is up)
    if os.path.isdir(os.path.join(ROOT, "wirely", "locale")):
        shutil.copytree(os.path.join(ROOT, "wirely", "locale"), os.path.join(out, "locale"))
    ex_out = os.path.join(out, "examples")
    os.makedirs(ex_out)
    names = []
    for name in sorted(os.listdir(os.path.join(ROOT, "examples"))):
        if name.endswith(".wirely"):
            shutil.copy2(os.path.join(ROOT, "examples", name), os.path.join(ex_out, name))
            names.append(name[:-len(".wirely")])
    with open(os.path.join(ex_out, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(names, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(out, "version.json"), "w", encoding="utf-8") as fh:
        json.dump({"version": __version__}, fh)
    if a.pyodide:
        dst = os.path.join(out, "pyodide")
        os.makedirs(dst)
        for name in PYODIDE_FILES:
            src = os.path.join(a.pyodide, name)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(dst, name))
        if a.numpy and os.path.exists(a.numpy):
            shutil.copy2(a.numpy, os.path.join(dst, os.path.basename(a.numpy)))
    # GitHub Pages: serve files as they are
    open(os.path.join(out, ".nojekyll"), "w").close()
    # the service worker keeps a copy of every file, so Wirely works offline after the first visit
    files = sorted(os.path.relpath(os.path.join(b, f), out).replace(os.sep, "/")
                   for b, _d, fs in os.walk(out) for f in fs if f not in ("sw.js", ".nojekyll", "package.json"))
    if os.path.exists(sw):
        with open(sw, encoding="utf-8") as fh:
            text = fh.read().replace("__FILES__", json.dumps(files, ensure_ascii=False))
        with open(sw, "w", encoding="utf-8") as fh:
            fh.write(text)
    size = sum(os.path.getsize(os.path.join(b, f)) for b, _d, fs in os.walk(out) for f in fs)
    print(f"Wirely Web {__version__} built in {out}  ({size / 1e6:.1f} MB, {len(names)} examples)")


if __name__ == "__main__":
    main()
