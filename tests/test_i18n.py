"""The language catalogues are complete and switching language changes what the app says."""
import os
import subprocess
import sys

import pytest

from wirely import i18n
from wirely.i18n import tr, trn

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def _english():
    yield
    i18n.set_language("en")


def test_catalogues_are_complete():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "i18n.py")], capture_output=True, text=True,
                       env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    assert r.returncode == 0, r.stdout


@pytest.mark.parametrize("code,word", [("es", "Resistencia"), ("de", "Widerstand"), ("ja", "抵抗")])
def test_part_names_follow_language(code, word):
    from wirely.model import parts as P
    i18n.set_language(code)
    assert P.get("resistor").tr_name == word


def test_unknown_text_falls_back_to_english():
    i18n.set_language("de")
    assert tr("not a real message {x}", x=3) == "not a real message 3"


def test_plural_helper_in_english():
    assert trn("{n} part", "{n} parts", 2) == "2 parts"
