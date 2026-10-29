"""Translations: the one place that knows which language Wirely is showing.

Every piece of text the person reads is written in English in the code and passed through ``tr()``. ``tr()``
looks the English up in the catalogue for the chosen language (``wirely/locale/<code>.json``, a plain
{English: translation} map) and gives back the translation, or the English itself if there isn't one. So a
missing translation can never break anything — it just shows in English.

Saved circuits never contain translated text (part kinds, property keys and choices like "Red" are stored in
English and only *shown* translated), so a circuit saved in one language opens in any other.

The desktop app and the browser version share this file and the catalogues.
"""
from __future__ import annotations

import json
import os

LANGUAGES = (("en", "English"), ("es", "Español"), ("de", "Deutsch"), ("ja", "日本語"))
DEFAULT = "en"
LOCALE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locale")

_lang = DEFAULT
_table: dict[str, str] = {}
_listeners: list = []


def codes():
    return [c for c, _n in LANGUAGES]


def native_name(code):
    return dict(LANGUAGES).get(code, code)


def language():
    return _lang


def catalogue(code):
    """The {English: translation} map for a language ({} for English or if the file is missing)."""
    if code == DEFAULT:
        return {}
    try:
        with open(os.path.join(LOCALE_DIR, f"{code}.json"), encoding="utf-8") as fh:
            data = json.load(fh)
        return {k: v for k, v in data.items() if isinstance(v, str) and v}
    except (OSError, ValueError):
        return {}


def set_language(code):
    """Switch language. Unknown codes fall back to English. Returns the code now in use."""
    global _lang, _table
    if code not in codes():
        code = DEFAULT
    _lang = code
    _table = catalogue(code)
    for fn in list(_listeners):
        try:
            fn(code)
        except Exception:               # noqa: BLE001 - a broken listener must not stop the switch
            pass
    return code


def on_change(fn):
    """Call fn(code) whenever the language changes."""
    _listeners.append(fn)
    return fn


def tr(text, /, **kw):
    """The text in the current language. ``kw`` fills any {placeholders} (done after translating).
    ``text`` is positional-only so a placeholder may itself be called ``text``."""
    out = _table.get(text, text) if _table else text
    if kw:
        try:
            return out.format(**kw)
        except (KeyError, IndexError, ValueError):
            return text.format(**kw)    # a damaged translation: fall back to the English
    return out


def trn(one, other, n, /, **kw):
    """Singular or plural. ``one`` and ``other`` are the English forms; both may use {n}."""
    return tr(one if n == 1 else other, n=n, **kw)
