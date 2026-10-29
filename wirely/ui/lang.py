"""The desktop app's language setting: remembered between runs, and applied to Qt's own text too."""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QSettings, QTranslator

from .. import i18n

_translators: list = []


def saved() -> str:
    code = str(QSettings("Wirely", "Wirely").value("language", i18n.DEFAULT))
    return code if code in i18n.codes() else i18n.DEFAULT


def apply(code: str) -> str:
    """Use this language from now on: Wirely's own text and Qt's (Save / Cancel / Yes / No buttons, file dialogs)."""
    code = i18n.set_language(code)
    app = QCoreApplication.instance()
    for t in _translators:
        if app is not None:
            app.removeTranslator(t)
    _translators.clear()
    if app is not None and code != i18n.DEFAULT:
        folder = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
        for name in ("qtbase", "qt"):
            t = QTranslator()
            if t.load(f"{name}_{code}", folder):
                app.installTranslator(t)
                _translators.append(t)
    return code


def remember(code: str):
    QSettings("Wirely", "Wirely").setValue("language", code)
