"""Reading and writing component values the way people type them: 10k, 4k7, 2M2, 100n, 4.7µF, 0.5 …

parse("10k")  -> 10000.0      parse("4k7") -> 4700.0      parse("100nF", "F") -> 1e-07
fmt(4700, "Ω") -> "4.7kΩ"     fmt(1e-07, "F") -> "100nF"
"""
from __future__ import annotations

import math
import re

from ..i18n import tr

PREFIXES = {
    "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3,
    "": 1.0, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9,
}
# symbols people use for the unit itself; they are ignored when parsing
UNIT_WORDS = {
    "Ω": ["Ω", "ω", "ohms", "ohm", "R", "r"],
    "F": ["F", "f"], "V": ["V", "v"], "A": ["A", "a"], "W": ["W", "w"], "Hz": ["Hz", "hz", "HZ"],
    "s": ["s", "S", "sec"], "%": ["%"], "°C": ["°C", "C", "c"], "H": ["H", "h"], "lux": ["lux", "lx"],
}

_NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"




def parse(text, unit: str = "") -> float:
    """Turn what someone typed into a number. Raises ValueError if it makes no sense."""
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip().replace(" ", "").replace(",", ".")
    if not s:
        raise ValueError(tr("Please type a value"))
    if s.lower().endswith("meg"):           # SPICE style 1meg
        s = s[:-3] + "M"
    # strip a trailing unit word (longest first), e.g. "10kΩ", "4.7uF", "9V"
    for word in sorted(UNIT_WORDS.get(unit, []), key=len, reverse=True):
        if s.endswith(word) and len(s) > len(word):
            rest = s[: -len(word)]
            # "4R7"/"4k7" handled below, so only strip when what is left still parses as a value
            if re.fullmatch(_NUM + r"[pnuµμmkKMG]?", rest) or re.fullmatch(r"\d+[pnuµμmkKMG]\d+", rest):
                s = rest
                break
    # 4k7, 2M2, 4R7, 4n7 style (the letter acts as the decimal point)
    m = re.fullmatch(r"(\d+)([pnuµμmkKMGRr])(\d+)", s)
    if m:
        whole, p, frac = m.groups()
        mult = 1.0 if p in "Rr" else PREFIXES[p]
        return float(f"{whole}.{frac}") * mult
    m = re.fullmatch(r"(" + _NUM + r")([pnuµμmkKMG]?)", s)
    if not m:
        raise ValueError(tr("'{text}' isn't a value I understand (try e.g. 10k, 4k7, 100n)", text=text))
    return float(m.group(1)) * PREFIXES[m.group(2)]


def fmt(value: float, unit: str = "", digits: int = 3) -> str:
    """Neat engineering text for a number: 4700 -> 4.7k, 1e-7 -> 100n (plus the unit)."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "–"
    if unit in ("%", "°C", "lux"):
        return f"{_trim(value, digits)}{unit}"
    if value == 0:
        return f"0{unit}"
    a = abs(value)
    for p, mult in (("G", 1e9), ("M", 1e6), ("k", 1e3), ("", 1.0), ("m", 1e-3), ("µ", 1e-6), ("n", 1e-9), ("p", 1e-12)):
        if a >= mult * 0.9995:
            return f"{_trim(value / mult, digits)}{p}{unit}"
    return f"{value:.3g}{unit}"


def _trim(x: float, digits: int) -> str:
    s = f"{x:.{digits}g}"
    if "e" in s:
        s = f"{x:.{digits}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


# ------------------------------------------------------------------ a number box with a unit box beside it
# Units that get a drop-down of multipliers next to the number (Ω kΩ MΩ, pF nF µF …), in the order offered
UNIT_STEPS = {
    "Ω": ("", "k", "M"),
    "F": ("p", "n", "µ", "m", ""),
    "H": ("µ", "m", ""),
    "Hz": ("", "k", "M"),
}


def has_unit_box(unit: str) -> bool:
    return unit in UNIT_STEPS


def unit_choices(unit: str) -> list:
    """What the unit box shows, e.g. ["Ω", "kΩ", "MΩ"]."""
    return [p + unit for p in UNIT_STEPS.get(unit, ("",))]


def split(value: float, unit: str):
    """A value as (number text, unit-box choice): 4700 Ω -> ("4.7", "kΩ"); 1e-7 F -> ("100", "nF")."""
    steps = UNIT_STEPS.get(unit, ("",))
    mults = [PREFIXES[p] for p in steps]
    a = abs(value)
    k = 0
    for i, m in enumerate(mults):
        if a >= m * 0.9995:
            k = i
    if value == 0:
        k = steps.index("") if "" in steps else 0
    return _trim(value / mults[k], 6), steps[k] + unit


def join(text, choice: str, unit: str) -> float:
    """The number typed plus the unit box: ("4.7", "kΩ") -> 4700. If what was typed already says its own size
    (4k7, 100n, 2.2MΩ …), that wins and the box is ignored."""
    s = str(text).strip().replace(" ", "").replace(",", ".")
    if re.fullmatch(_NUM, s):
        prefix = choice[: len(choice) - len(unit)] if choice.endswith(unit) else ""
        return float(s) * PREFIXES.get(prefix, 1.0)
    return parse(text, unit)
