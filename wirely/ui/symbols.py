"""Circuit symbols in UK / IEC 60617 style (box resistors, filament lamp with a cross …), drawn with QPainter.

Every drawing is in the part's own coordinates (centre at 0,0, pins as listed in model/parts.py). The caller
sets up rotation and flipping; text drawn with `upright()` always stays the right way up.
All artwork here is original to Wirely.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

from ..i18n import tr
from ..model import parts as P
from ..model.circuit import transform

LW = 2.0          # line width in sheet units

LED_RGB = {
    "Red": "#ff3b30", "Green": "#2fd158", "Yellow": "#ffd60a", "Blue": "#2f7bff",
    "White": "#f4f6ff", "Orange": "#ff9f0a",
}


# Symbol style: "uk" (British / IEC: box resistors) or "us" (American / ANSI: zigzag resistors). Only the look
# changes — same pins, same sizes, same circuits.
STYLE = "uk"


def set_style(style):
    global STYLE
    STYLE = "us" if style == "us" else "uk"


def _zigzag(c, x0, x1, amp=6.0, peaks=6, w=LW):
    """A zigzag from (x0, 0) to (x1, 0): the American resistor."""
    step = (x1 - x0) / peaks
    pts = [(x0, 0.0)]
    pts += [(x0 + step * (k + 0.5), -amp if k % 2 == 0 else amp) for k in range(peaks)]
    pts.append((x1, 0.0))
    c.poly(pts, None, w, closed=False)


class Ctx:
    """What a drawing needs: the painter, ink colour, the part's values and its rotation (for text)."""

    def __init__(self, p: QPainter, ink: QColor, props: dict, rot=0, flip=False, paper=None, kind=""):
        self.p, self.ink, self.props, self.rot, self.flip = p, QColor(ink), props or {}, rot, flip
        self.paper = QColor(paper) if paper is not None else QColor("#ffffff")
        self.kind = kind
        self.pin_labels = []

    def pen(self, w=LW, color=None, style=Qt.SolidLine):
        pen = QPen(color or self.ink, w, style)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        return pen

    def line(self, x1, y1, x2, y2, w=LW, color=None):
        self.p.setPen(self.pen(w, color))
        self.p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def poly(self, pts, fill=None, w=LW, closed=True):
        self.p.setPen(self.pen(w))
        self.p.setBrush(QBrush(fill) if fill is not None else Qt.NoBrush)
        poly = QPolygonF([QPointF(x, y) for x, y in pts])
        if closed:
            self.p.drawPolygon(poly)
        else:
            self.p.drawPolyline(poly)

    def rect(self, x, y, w, h, fill=None, lw=LW):
        self.p.setPen(self.pen(lw))
        self.p.setBrush(QBrush(fill) if fill is not None else Qt.NoBrush)
        self.p.drawRect(QRectF(x, y, w, h))

    def circle(self, x, y, r, fill=None, lw=LW):
        self.p.setPen(self.pen(lw))
        self.p.setBrush(QBrush(fill) if fill is not None else Qt.NoBrush)
        self.p.drawEllipse(QPointF(x, y), r, r)

    def arrow(self, x1, y1, x2, y2, head=5.0, w=1.6):
        """Line with a filled arrow head at (x2, y2)."""
        self.line(x1, y1, x2, y2, w)
        a = math.atan2(y2 - y1, x2 - x1)
        pts = [QPointF(x2, y2),
               QPointF(x2 - head * math.cos(a - 0.45), y2 - head * math.sin(a - 0.45)),
               QPointF(x2 - head * math.cos(a + 0.45), y2 - head * math.sin(a + 0.45))]
        self.p.setPen(self.pen(1))
        self.p.setBrush(self.ink)
        self.p.drawPolygon(QPolygonF(pts))

    def unrotate(self):
        """Undo the part's rotation/flip around the current origin (for pictures that must stay level)."""
        if self.rot % 4:
            self.p.rotate(-90 * (self.rot % 4))
        if self.flip:
            self.p.scale(-1, 1)

    def label_at(self, x, y, text, align, size=7.5):
        """Small pin name just inside a chip's edge, kept upright. `align` says which side it hugs."""
        if not text:
            return
        p = self.p
        p.save()
        p.translate(x, y)
        if self.flip:
            p.scale(-1, 1)
        p.rotate(-90 * self.rot)
        # after un-rotating, work out which way "inwards" now points so the text sits inside the box
        t = p.worldTransform()
        f = QFont()
        f.setPixelSize(int(round(size)) or 1)
        p.setFont(f)
        p.setPen(self.ink)
        w = 40
        ins = QPointF(1, 0) if align & Qt.AlignLeft else QPointF(-1, 0) if align & Qt.AlignRight else \
            QPointF(0, 1) if align & Qt.AlignTop else QPointF(0, -1)
        # direction in the part's own frame -> direction on screen
        ins = _rotvec(ins, self.rot, self.flip)
        side_pin = bool(align & (Qt.AlignLeft | Qt.AlignRight))
        if abs(ins.x()) > abs(ins.y()):
            r = QRectF(0, -size, w, 2 * size) if ins.x() > 0 else QRectF(-w, -size, w, 2 * size)
            a = (Qt.AlignLeft if ins.x() > 0 else Qt.AlignRight) | Qt.AlignVCenter
        elif side_pin:
            # a chip turned on its side: its side pins (only 10 apart) are now along the top or bottom, so
            # their names run along the pins (reading upwards) instead of crashing into each other
            p.rotate(-90)
            r = QRectF(0, -size, w, 2 * size) if ins.y() < 0 else QRectF(-w, -size, w, 2 * size)
            a = (Qt.AlignLeft if ins.y() < 0 else Qt.AlignRight) | Qt.AlignVCenter
        else:
            r = QRectF(-w / 2, 0, w, size + 2) if ins.y() > 0 else QRectF(-w / 2, -size - 2, w, size + 2)
            a = Qt.AlignHCenter | (Qt.AlignTop if ins.y() > 0 else Qt.AlignBottom)
        del t
        p.drawText(r, a, text)
        p.restore()

    def upright(self, x, y, text, size=11.0, bold=True, color=None, align=Qt.AlignCenter):
        """Text centred on (x, y) that stays readable whatever the rotation."""
        p = self.p
        p.save()
        p.translate(x, y)
        if self.flip:
            p.scale(-1, 1)
        p.rotate(-90 * self.rot)
        f = QFont()
        f.setPixelSize(max(1, int(round(size))))
        f.setBold(bold)
        p.setFont(f)
        p.setPen(color or self.ink)
        p.drawText(QRectF(-40, -size, 80, size * 2), align, text)
        p.restore()


# ------------------------------------------------------------------------------------------ helpers
def _rotvec(vec, rot, flip, inverse=False):
    """Turn a direction the same way a part is turned (or back again)."""
    x, y = vec.x(), vec.y()
    if not inverse:
        if flip:
            x = -x
        for _ in range(rot % 4):
            x, y = -y, x
    else:
        for _ in range(rot % 4):
            x, y = y, -x
        if flip:
            x = -x
    return QPointF(x, y)


def _leads(c: Ctx, inner=20, outer=30, y=0):
    c.line(-outer, y, -inner, y)
    c.line(inner, y, outer, y)


def _plus(c: Ctx, x, y, s=3.5):
    c.line(x - s, y, x + s, y, 1.4)
    c.line(x, y - s, x, y + s, 1.4)


# ------------------------------------------------------------------------------------------ power
def _cell(c):
    c.line(-30, 0, -4, 0)
    c.line(4, 0, 30, 0)
    c.line(-4, -16, -4, 16)
    c.line(4, -8, 4, 8, 4.5)
    _plus(c, -13, -11)


def _battery(c):
    c.line(-30, 0, -14, 0)
    c.line(14, 0, 30, 0)
    for x in (-14, 7):
        c.line(x, -16, x, 16)
        c.line(x + 7, -8, x + 7, 8, 4.5)
    c.p.setPen(c.pen(1.5, style=Qt.DashLine))
    c.p.drawLine(QPointF(-5, 0), QPointF(5, 0))
    _plus(c, -22, -11)


def _dc_supply(c):
    _leads(c, 16)
    c.circle(0, 0, 16)
    c.line(-8, -3, 8, -3, 1.8)
    c.p.setPen(c.pen(1.8, style=Qt.DashLine))
    c.p.drawLine(QPointF(-8, 3), QPointF(8, 3))
    _plus(c, -23, -9)


def _ac_supply(c):
    _leads(c, 16)
    c.circle(0, 0, 16)
    path = QPainterPath()
    path.moveTo(-9, 0)
    for i in range(1, 37):
        x = -9 + 18 * i / 36
        path.lineTo(x, -6 * math.sin(2 * math.pi * i / 36))
    c.p.setPen(c.pen(1.8))
    c.p.setBrush(Qt.NoBrush)
    c.p.drawPath(path)


def _rail_pos(c):
    c.line(0, 0, 0, -14)
    c.line(-10, -14, 10, -14, 2.4)
    v = c.props.get("voltage", 9.0)
    from ..model.units import fmt
    c.upright(0, -23, ("+" if v >= 0 else "") + fmt(v, "V"), 10.5)


def _ground(c):
    c.line(0, 0, 0, 8)
    c.line(-12, 8, 12, 8, 2.2)
    c.line(-7.5, 13, 7.5, 13, 2.0)
    c.line(-3, 18, 3, 18, 1.8)


# ------------------------------------------------------------------------------------------ resistors
def _resistor(c):
    _leads(c)
    if STYLE == "us":
        _zigzag(c, -20, 20)
    else:
        c.rect(-20, -7, 40, 14, c.paper)


def _var_resistor(c):
    _resistor(c)
    c.arrow(-15, 13, 16, -13, 6)


def _potentiometer(c):
    _resistor(c)
    c.arrow(0, -30, 0, -8.5, 6, 2)


def _fuse(c):
    if STYLE == "us":                   # an S-shaped wire
        c.line(-30, 0, -14, 0)
        c.line(14, 0, 30, 0)
        path = QPainterPath()
        path.moveTo(-14, 0)
        path.cubicTo(-7, -14, 0, -7, 0, 0)
        path.cubicTo(0, 7, 7, 14, 14, 0)
        c.p.setPen(c.pen())
        c.p.setBrush(Qt.NoBrush)
        c.p.drawPath(path)
        return
    c.rect(-18, -5, 36, 10, c.paper)
    c.line(-30, 0, 30, 0)


# ------------------------------------------------------------------------------------------ capacitors
def _capacitor(c):
    c.line(-20, 0, -4, 0)
    c.line(4, 0, 20, 0)
    c.line(-4, -12, -4, 12, 2.6)
    c.line(4, -12, 4, 12, 2.6)


def _electrolytic(c):
    if STYLE == "us":                   # straight + plate, curved − plate
        c.line(-20, 0, -4, 0)
        c.line(5, 0, 20, 0)
        c.line(-4, -12, -4, 12, 2.6)
        path = QPainterPath()
        path.moveTo(8, -12)
        path.quadTo(2, 0, 8, 12)
        c.p.setPen(c.pen(2.6))
        c.p.setBrush(Qt.NoBrush)
        c.p.drawPath(path)
        _plus(c, -12, -11, 3)
        return
    c.line(-20, 0, -8, 0)
    c.line(8, 0, 20, 0)
    c.rect(-8, -12, 4, 24, c.paper, 1.6)
    c.rect(4, -12, 4, 24, c.ink, 1.6)
    _plus(c, -14, -11, 3)


# ------------------------------------------------------------------------------------------ switches
def _contact(c, x, y):
    c.circle(x, y, 2.6, c.paper, 1.6)


def _switch(c):
    _leads(c, 14)
    if c.props.get("closed"):
        c.line(-12, -1, 13, -3, LW)
    else:
        c.line(-12, -1, 11, -13, LW)
    _contact(c, -14, 0)
    _contact(c, 14, 0)


def _push_make(c):
    _leads(c, 14)
    y = -3.5 if c.props.get("pressed") else -9
    c.line(-14, y, 14, y, 2.2)
    c.line(0, y, 0, y - 9)
    c.line(-5, y - 9, 5, y - 9, 2.2)
    _contact(c, -14, 0)
    _contact(c, 14, 0)


def _push_break(c):
    _leads(c, 14)
    y = 11 if c.props.get("pressed") else 3.5
    c.line(-14, y, 14, y, 2.2)
    c.line(0, y, 0, -12)
    c.line(-5, -12, 5, -12, 2.2)
    _contact(c, -14, 0)
    _contact(c, 14, 0)


def _spdt(c):
    c.line(-30, 0, -14, 0)
    c.line(14, -10, 30, -10)
    c.line(14, 10, 30, 10)
    ty = -8 if c.props.get("position", "A") == "A" else 8
    c.line(-12, 0, 12, ty)
    _contact(c, -14, 0)
    _contact(c, 14, -10)
    _contact(c, 14, 10)
    c.upright(22, -17, "A", 8, False)
    c.upright(22, 17, "B", 8, False)


# ------------------------------------------------------------------------------------------ sensors
def _ldr(c):
    c.line(-30, 0, -12, 0)
    c.line(12, 0, 30, 0)
    c.circle(0, 0, 17, None, 1.6)
    if STYLE == "us":
        _zigzag(c, -12, 12, 5, 4)
    else:
        c.rect(-12, -5, 24, 10, c.paper)
    c.arrow(-21, -24, -9, -12, 5, 1.5)
    c.arrow(-9, -27, 3, -15, 5, 1.5)


def _thermistor(c):
    _resistor(c)
    c.line(-22, 13, -15, 13, 1.6)
    c.line(-15, 13, 15, -13, 1.6)
    c.upright(15, 12, "-t°", 8.5, False)


# ------------------------------------------------------------------------------------------ diodes
def _diode_body(c, fill=None, bar="plain"):
    c.line(-30, 0, -10, 0)
    c.line(9, 0, 30, 0)
    c.poly([(-10, -10), (-10, 10), (9, 0)], fill if fill is not None else c.paper)
    if bar == "zener":
        c.poly([(13, -12), (9, -10), (9, 10), (5, 12)], None, LW, closed=False)
    else:
        c.line(9, -10, 9, 10, 2.2)


def _diode(c):
    _diode_body(c, c.ink)


def led_fill(col, glow):
    """An LED's body colour: pale when off; when lit, its full, strong colour (the glow around it shows how
    bright it is)."""
    fill = QColor(col)
    fill.setAlphaF(0.22 if glow <= 0.02 else min(1.0, 0.7 + 0.5 * glow))
    return fill


def _led(c):
    col = QColor(LED_RGB.get(c.props.get("colour", "Red"), "#ff3b30"))
    glow = c.props.get("_glow", 0.0)            # set by the simulator from r2 on
    _diode_body(c, led_fill(col, glow))
    c.arrow(-1, -13, 7, -23, 4.5, 1.5)
    c.arrow(6, -10, 14, -20, 4.5, 1.5)


def _zener(c):
    _diode_body(c, c.ink, "zener")


# ------------------------------------------------------------------------------------------ transistors
def _bjt(c, npn=True):
    c.circle(4, 0, 18, None, 1.6)
    c.line(-30, 0, -6, 0)
    c.line(-6, -11, -6, 11, 2.6)
    # collector / emitter legs (collector at top for NPN, emitter at top for PNP)
    c.line(-6, -5, 10, -15)
    c.line(10, -15, 10, -30)
    c.line(-6, 5, 10, 15)
    c.line(10, 15, 10, 30)
    if npn:     # arrow out of the emitter (bottom leg)
        c.arrow(-6 + 16 * 0.35, 5 + 10 * 0.35, 8.5, 14, 6, 0.1)
    else:       # arrow into the base on the emitter (top leg)
        c.arrow(9, -14.5, -6 + 16 * 0.45, -5 - 10 * 0.45, 6, 0.1)


def _npn(c):
    _bjt(c, True)


def _pnp(c):
    _bjt(c, False)


# ------------------------------------------------------------------------------------------ outputs
def _lamp(c):
    _leads(c, 13)
    glow = c.props.get("_glow", 0.0)
    fill = QColor(255, 214, 10)
    fill.setAlphaF(0.85 * glow)
    c.circle(0, 0, 13, fill if glow > 0 else c.paper)
    if STYLE == "us":                   # a looped filament between the two leads
        c.line(-13, 0, -6, 0, 1.8)
        c.line(6, 0, 13, 0, 1.8)
        path = QPainterPath()
        path.moveTo(-6, 0)
        path.cubicTo(-6, -10, 2, -10, 2, -5)
        path.cubicTo(2, -1, -2, -1, -2, -5)
        path.cubicTo(-2, -10, 6, -10, 6, 0)
        c.p.setPen(c.pen(1.8))
        c.p.setBrush(Qt.NoBrush)
        c.p.drawPath(path)
        return
    d = 13 / math.sqrt(2)
    c.line(-d, -d, d, d, 1.8)
    c.line(-d, d, d, -d, 1.8)


def _buzzer(c):
    c.line(-30, 0, -9, 0)
    c.line(9, 0, 30, 0)
    c.line(-9, 0, -9, 8)
    c.line(9, 0, 9, 8)
    path = QPainterPath()
    path.moveTo(-15, 8)
    path.lineTo(15, 8)
    path.arcTo(QRectF(-15, -7, 30, 30), 0, 180)
    path.closeSubpath()
    c.p.setPen(c.pen())
    c.p.setBrush(c.paper)
    c.p.drawPath(path)
    _plus(c, -21, -7)


def _speaker(c):
    c.line(-30, 0, -4, 0)
    c.line(4, 0, 30, 0)
    c.line(-4, 0, -4, -8)
    c.line(4, 0, 4, -8)
    c.rect(-7, -15, 14, 7, c.paper)
    c.poly([(-7, -15), (-14, -25), (14, -25), (7, -15)], c.paper)


def _motor(c):
    _leads(c, 14)
    c.circle(0, 0, 14, c.paper)
    c.upright(0, 0, "M", 13)


def _meter(c, letter):
    _leads(c, 14)
    c.circle(0, 0, 14, c.paper)
    c.upright(0, 0, letter, 13)
    _plus(c, -21, -8)


DRAW = {
    "cell": _cell, "battery": _battery, "dc_supply": _dc_supply, "ac_supply": _ac_supply,
    "rail_pos": _rail_pos, "ground": _ground,
    "resistor": _resistor, "var_resistor": _var_resistor, "potentiometer": _potentiometer, "fuse": _fuse,
    "capacitor": _capacitor, "electrolytic": _electrolytic,
    "switch": _switch, "push_make": _push_make, "push_break": _push_break, "spdt": _spdt,
    "ldr": _ldr, "thermistor": _thermistor,
    "diode": _diode, "led": _led, "zener": _zener, "npn": _npn, "pnp": _pnp,
    "lamp": _lamp, "buzzer": _buzzer, "speaker": _speaker, "motor": _motor,
    "voltmeter": lambda c: _meter(c, "V"), "ammeter": lambda c: _meter(c, "A"),
}


# ------------------------------------------------------------------------------------------ r3: chips & logic
CHANNEL_RGB = {"A": "#e0a800", "B": "#0ea5e9", "C": "#d946ef", "D": "#16a34a"}


def _signal_gen(c):
    _leads(c, 16)
    c.circle(0, 0, 16, c.paper)
    c.p.save()
    c.unrotate()
    w = c.props.get("waveform", "Square")
    path = QPainterPath()
    if w == "Square":
        pts = [(-9, 4), (-9, -5), (0, -5), (0, 5), (9, 5), (9, -4)]
        path.moveTo(*pts[0])
        for pt in pts[1:]:
            path.lineTo(*pt)
    elif w == "Triangle":
        path.moveTo(-9, 4)
        path.lineTo(-4.5, -5)
        path.lineTo(4.5, 5)
        path.lineTo(9, -4)
    else:
        path.moveTo(-9, 0)
        for i in range(1, 37):
            path.lineTo(-9 + 18 * i / 36, -6 * math.sin(2 * math.pi * i / 36))
    c.p.setPen(c.pen(1.8))
    c.p.setBrush(Qt.NoBrush)
    c.p.drawPath(path)
    c.p.restore()
    _plus(c, -23, -9)


def _mosfet(c, n=True):
    c.circle(4, 0, 18, None, 1.6)
    c.line(-30, 0, -10, 0)
    c.line(-10, -12, -10, 12, 2.2)
    for y0, y1 in ((-14, -7), (-3, 3), (7, 14)):
        c.line(-4, y0, -4, y1, 2.4)
    top, bot = (-11, 11)
    c.line(-4, top, 10, top)
    c.line(-4, bot, 10, bot)
    c.line(10, top, 10, -30)
    c.line(10, bot, 10, 30)
    # body tied to the source (bottom for N, top for P)
    src = bot if n else top
    c.line(10, 0, 10, src, 1.6)
    if n:
        c.arrow(9, 0, -3, 0, 5.5, 1.6)        # arrow points in
    else:
        c.arrow(-3, 0, 9, 0, 5.5, 1.6)        # arrow points out


def _gate_body(c, kind):
    p = c.p
    path = QPainterPath()
    if kind in ("and", "nand", "schmitt_nand"):
        path.moveTo(-25, -20)
        path.lineTo(0, -20)
        path.arcTo(QRectF(-20, -20, 40, 40), 90, -180)
        path.lineTo(-25, 20)
        path.closeSubpath()
        tip = 20
        ins = -25
    elif kind in ("or", "nor", "xor"):
        path.moveTo(-25, -20)
        path.quadTo(5, -20, 25, 0)
        path.quadTo(5, 20, -25, 20)
        path.quadTo(-12, 0, -25, -20)
        tip = 25
        ins = -20
    else:  # not, schmitt
        path.moveTo(-20, -16)
        path.lineTo(14, 0)
        path.lineTo(-20, 16)
        path.closeSubpath()
        tip = 14
        ins = -20
    p.setPen(c.pen())
    p.setBrush(c.paper)
    p.drawPath(path)
    if kind == "xor":
        back = QPainterPath()
        back.moveTo(-31, -20)
        back.quadTo(-18, 0, -31, 20)
        p.setBrush(Qt.NoBrush)
        p.drawPath(back)
        ins = -26
    bubble = kind in ("nand", "nor", "not", "schmitt_not", "schmitt_nand")
    if bubble:
        c.circle(tip + 3.5, 0, 3.5, c.paper, 1.8)
        c.line(tip + 7, 0, 40, 0)
    else:
        c.line(tip, 0, 40, 0)
    if kind in ("not", "schmitt_not"):
        c.line(-40, 0, -20, 0)
    else:
        c.line(-40, -10, ins, -10)
        c.line(-40, 10, ins, 10)
    if kind in ("schmitt_not", "schmitt_nand"):
        dx = -2 if kind == "schmitt_nand" else 0
        hp = QPainterPath()
        hp.moveTo(-14 + dx, 4)
        hp.lineTo(-5 + dx, 4)
        hp.lineTo(-7 + dx, -4)
        hp.lineTo(2 + dx, -4)
        hp.moveTo(-12 + dx, 4)
        hp.lineTo(-10 + dx, -4)
        hp.lineTo(-5 + dx, -4)
        p.setPen(c.pen(1.2))
        p.setBrush(Qt.NoBrush)
        p.drawPath(hp)


def _box_ic(c, x0, y0, x1, y1, title, labels=None, numbers=None, clock=None, title_y=None):
    """A chip drawn as a box with labelled pins (leads from each pin to the box edge)."""
    part = P.get(c.kind)
    for name, px, py in part.pins:
        if px < x0:
            c.line(px, py, x0, py)
            lx, ly, al = x0 + 4, py, Qt.AlignLeft | Qt.AlignVCenter
            nx, ny = (px + x0) / 2, py - 5
        elif px > x1:
            c.line(x1, py, px, py)
            lx, ly, al = x1 - 4, py, Qt.AlignRight | Qt.AlignVCenter
            nx, ny = (px + x1) / 2, py - 5
        elif py < y0:
            c.line(px, py, px, y0)
            lx, ly, al = px, y0 + 6, Qt.AlignHCenter | Qt.AlignTop
            nx, ny = px + 6, (py + y0) / 2
        else:
            c.line(px, y1, px, py)
            lx, ly, al = px, y1 - 6, Qt.AlignHCenter | Qt.AlignBottom
            nx, ny = px + 6, (py + y1) / 2
        c.pin_labels.append((lx, ly, (labels or {}).get(name, name), al))
        if numbers and name in numbers:
            c.upright(nx, ny, str(numbers[name]), 6.5, False)
    c.rect(x0, y0, x1 - x0, y1 - y0, c.paper)
    for lx, ly, text, al in c.pin_labels:
        c.label_at(lx, ly, text, al)
    if clock:
        cx, cy = x0, clock
        c.poly([(cx, cy - 4), (cx + 6, cy), (cx, cy + 4)], None, 1.2, closed=False)
    ty = title_y if title_y is not None else (y0 + y1) / 2 + (8 if c.kind == "timer555" else 0)
    if title_y is not None and c.rot % 2 == 1:
        # a narrow box (a regulator) turned on its side: the title runs along it
        p = c.p
        p.save()
        p.translate((x0 + x1) / 2, ty)
        if c.flip:
            p.scale(-1, 1)
        p.rotate(-90 * c.rot - 90)
        f = QFont()
        f.setPixelSize(11)
        f.setBold(True)
        p.setFont(f)
        p.setPen(c.ink)
        p.drawText(QRectF(-40, -11, 80, 22), Qt.AlignCenter, title)
        p.restore()
        return
    c.upright((x0 + x1) / 2, ty, title, 11)


def _timer555(c):
    _box_ic(c, -40, -40, 40, 40, "555",
            numbers={"GND": 1, "TRIG": 2, "OUT": 3, "RESET": 4, "CTRL": 5, "THR": 6, "DIS": 7, "VCC": 8},
            labels={})


def _opamp(c):
    c.line(-40, -10, -30, -10)
    c.line(-40, 10, -30, 10)
    c.line(30, 0, 40, 0)
    c.line(0, -30, 0, -15)
    c.line(0, 30, 0, 15)
    c.poly([(-30, -30), (-30, 30), (30, 0)], c.paper)
    c.line(-25, -10, -19, -10, 1.5)
    c.line(-25, 10, -19, 10, 1.5)
    c.line(-22, 7, -22, 13, 1.5)


def _dff(c):
    _box_ic(c, -30, -40, 30, 40, "", labels={"CLK": "", "Qn": "Q̅"}, clock=0)


def _counter4017(c):
    _box_ic(c, -40, -60, 40, 60, "4017", labels={"CLK": ""}, clock=-20)


def _decoder4511(c):
    _box_ic(c, -40, -40, 40, 40, "4511")


SEG_GEOM = {  # segment: (x0, y0, x1, y1) inside a 24 × 44 digit centred at (4, -4)
    "a": (-6, -26, 14, -26), "b": (16, -24, 16, -6), "c": (16, -2, 16, 16), "d": (-6, 18, 14, 18),
    "e": (-8, -2, -8, 16), "f": (-8, -24, -8, -6), "g": (-6, -4, 14, -4),
}


def _sevenseg(c):
    for i, s in enumerate("abcdefg"):
        y = -30 + 10 * i
        c.line(-50, y, -30, y)
        c.upright(-40, y - 5, s, 6.5, False)
    c.line(0, 50, 0, 60)
    p = c.p
    p.setPen(c.pen())
    p.setBrush(QColor("#1b1d21"))
    p.drawRoundedRect(QRectF(-30, -50, 60, 100), 5, 5)
    col = QColor(LED_RGB.get(c.props.get("colour", "Red"), "#ff3b30"))
    lit = c.props.get("_segs") or [0.0] * 7
    for i, s in enumerate("abcdefg"):
        x0, y0, x1, y1 = SEG_GEOM[s]
        on = QColor(col)
        off = QColor(col)
        off.setAlphaF(0.13)
        k = lit[i]
        seg = QColor(int(off.red() + (on.red() - off.red()) * k), int(off.green() + (on.green() - off.green()) * k),
                     int(off.blue() + (on.blue() - off.blue()) * k))
        seg.setAlphaF(0.13 + 0.87 * k)
        pen = QPen(seg, 5.0)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(x0 - 2, y0), QPointF(x1 - 2, y1))
    p.setPen(Qt.NoPen)
    dp = QColor(col)
    dp.setAlphaF(0.13)
    p.setBrush(dp)                 # decimal point: not connected, always off
    p.drawEllipse(QPointF(19, 19), 2.2, 2.2)


def _scope_probe(c):
    ch = c.props.get("channel", "A")
    col = QColor(CHANNEL_RGB.get(ch, "#e0a800"))
    c.line(0, 0, 0, -12, 1.8, col)
    p = c.p
    p.setPen(Qt.NoPen)
    p.setBrush(col)
    p.drawRoundedRect(QRectF(-11, -32, 22, 20), 4, 4)
    c.upright(0, -22, ch, 12, True, QColor("#ffffff"))
    p.setBrush(col)
    p.drawEllipse(QPointF(0, 0), 2.6, 2.6)


def _logic_probe(c):
    c.line(0, 0, 0, -10, 1.8)
    lvl = c.props.get("_level")
    colours = {"H": "#e03131", "L": "#2f9e44", "?": "#868e96"}
    fill = QColor(colours.get(lvl, "#ffffff")) if lvl else c.paper
    p = c.p
    p.setPen(c.pen(1.6))
    p.setBrush(fill)
    p.drawRoundedRect(QRectF(-12, -38, 24, 28), 5, 5)
    c.upright(0, -24, lvl or "LP", 11 if lvl else 8, True, QColor("#ffffff") if lvl else None)


DRAW.update({
    "signal_gen": _signal_gen, "nmos": lambda c: _mosfet(c, True), "pmos": lambda c: _mosfet(c, False),
    "not": lambda c: _gate_body(c, "not"), "and": lambda c: _gate_body(c, "and"), "or": lambda c: _gate_body(c, "or"),
    "nand": lambda c: _gate_body(c, "nand"), "nor": lambda c: _gate_body(c, "nor"),
    "xor": lambda c: _gate_body(c, "xor"), "schmitt_not": lambda c: _gate_body(c, "schmitt_not"),
    "dff": _dff, "timer555": _timer555, "opamp": _opamp, "counter4017": _counter4017,
    "decoder4511": _decoder4511, "sevenseg": _sevenseg, "scope_probe": _scope_probe, "logic_probe": _logic_probe,
})


# ------------------------------------------------------------------------------------------ r4 parts
def _inductor(c):
    c.line(-30, 0, -20, 0)
    c.line(20, 0, 30, 0)
    path = QPainterPath()
    path.moveTo(-20, 0)
    for k in range(4):
        x0 = -20 + 10 * k
        path.arcTo(QRectF(x0, -5, 10, 10), 180, -180)
    c.p.setPen(c.pen())
    c.p.setBrush(Qt.NoBrush)
    c.p.drawPath(path)


def _relay(c):
    # coil
    c.line(-20, -30, -20, -15)
    c.line(-20, 15, -20, 30)
    c.rect(-28, -15, 16, 30, c.paper)
    c.line(-28, 15, -12, -15, 1.4)
    # contacts
    c.line(20, 30, 20, 14)
    c.line(10, -30, 10, -14)
    c.line(30, -30, 30, -14)
    on = bool(c.props.get("_on"))
    tip = (29, -13) if on else (11, -13)
    c.line(20, 13, tip[0], tip[1])
    for x, y in ((20, 14), (10, -14), (30, -14)):
        c.circle(x, y, 2.2, c.paper, 1.4)
    c.p.setPen(c.pen(1.2, style=Qt.DashLine))
    c.p.drawLine(QPointF(-12, 0), QPointF(17 if not on else 23, 0))
    c.upright(5, -24, "NC", 6.5, False)
    c.upright(37, -22, "NO", 6.5, False)


def _relay_dpdt(c):
    # coil
    c.line(-40, -30, -40, -15)
    c.line(-40, 15, -40, 30)
    c.rect(-48, -15, 16, 30, c.paper)
    c.line(-48, 15, -32, -15, 1.4)
    on = bool(c.props.get("_on"))
    for oy in (-20, 20):
        c.line(0, oy, 12, oy)
        c.line(28, oy - 10, 40, oy - 10)
        c.line(28, oy + 10, 40, oy + 10)
        c.line(14, oy, 27, oy + (8 if on else -8))
        for x, y in ((12, oy), (28, oy - 10), (28, oy + 10)):
            c.circle(x, y, 2.2, c.paper, 1.4)
        c.upright(36, oy - 15, "NC", 6, False)
        c.upright(36, oy + 5, "NO", 6, False)
    c.p.setPen(c.pen(1.2, style=Qt.DashLine))
    yb = 4 if on else -4
    c.p.drawLine(QPointF(-32, 0), QPointF(20, 0))
    c.p.drawLine(QPointF(20, -20 + yb), QPointF(20, 20 + yb))


def _reed_switch(c):
    c.line(-30, 0, -14, 0)
    c.line(14, 0, 30, 0)
    p = c.p
    p.setPen(c.pen(1.2))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(-20, -9, 40, 18), 8, 8)
    closed = bool(c.props.get("magnet"))
    c.line(-14, 0, 3, 0, 1.8)
    c.line(14, 0, -3, 0 if closed else -5, 1.8)
    if closed:      # the magnet, drawn just above
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#e03131"))
        p.drawRect(QRectF(-10, -19, 10, 7))
        p.setBrush(QColor("#1971c2"))
        p.drawRect(QRectF(0, -19, 10, 7))


def _tilt_switch(c):
    c.line(-30, 0, -12, 0)
    c.line(12, 0, 30, 0)
    p = c.p
    p.setPen(c.pen(1.4))
    p.setBrush(Qt.NoBrush)
    tilted = bool(c.props.get("tilted"))
    p.save()
    if tilted:
        p.rotate(-12)
    p.drawRoundedRect(QRectF(-14, -10, 28, 16), 6, 6)
    p.restore()
    c.circle(-12, 0, 2.2, c.paper, 1.4)
    c.circle(12, 0, 2.2, c.paper, 1.4)
    p.setPen(Qt.NoPen)
    p.setBrush(c.ink)
    p.drawEllipse(QPointF(0 if tilted else -6, 0 if tilted else -4), 4.5, 4.5)


def _moisture(c):
    c.line(-30, 0, -8, 0)
    c.line(30, 0, 8, 0)
    c.line(-8, 0, -8, 14, 2.6)
    c.line(8, 0, 8, 14, 2.6)
    p = c.p
    p.setPen(c.pen(1.2))
    p.setBrush(QColor("#4dabf7"))
    drop = QPainterPath()
    drop.moveTo(0, -18)
    drop.cubicTo(5, -11, 6, -7, 0, -5)
    drop.cubicTo(-6, -7, -5, -11, 0, -18)
    p.drawPath(drop)


def _phototransistor(c):
    c.circle(4, 0, 18, None, 1.6)
    c.line(-6, -11, -6, 11, 2.6)
    c.line(-6, -5, 10, -15)
    c.line(10, -15, 10, -30)
    c.line(-6, 5, 10, 15)
    c.line(10, 15, 10, 30)
    c.arrow(-6 + 16 * 0.35, 5 + 10 * 0.35, 8.5, 14, 6, 0.1)
    c.arrow(-26, -22, -14, -10, 5, 1.5)
    c.arrow(-22, -28, -10, -16, 5, 1.5)


def _optocoupler(c):
    """Optoisolator: LED on the left (A top, K bottom), phototransistor on the right (C top, E bottom)."""
    c.rect(-30, -32, 60, 64, None, 1.2)
    # the LED, pointing down
    c.line(-40, -20, -18, -20)
    c.line(-18, -20, -18, -8)
    c.poly([(-27, -8), (-9, -8), (-18, 6)], c.paper)
    c.line(-27, 6, -9, 6, 2.2)
    c.line(-18, 6, -18, 20)
    c.line(-18, 20, -40, 20)
    # its light, lit up while the simulation runs and the LED conducts
    ir = c.props.get("_ir", 0.0)
    if ir > 0.02:
        lit = QColor(255, 170, 30)
        c.p.setPen(Qt.NoPen)
        glow = QColor(255, 190, 60, int(70 * ir))
        c.p.setBrush(glow)
        c.p.drawRoundedRect(QRectF(-7, -11, 16, 20), 6, 6)
        old = c.ink
        c.ink = lit
        c.arrow(-5, -5, 6, -5, 4.5, 1.6)
        c.arrow(-5, 3, 6, 3, 4.5, 1.6)
        c.ink = old
    else:
        c.arrow(-5, -5, 6, -5, 4.5, 1.5)
        c.arrow(-5, 3, 6, 3, 4.5, 1.5)
    # the phototransistor
    c.line(12, -11, 12, 11, 2.6)
    c.line(12, -5, 26, -14)
    c.line(26, -14, 26, -20)
    c.line(26, -20, 40, -20)
    c.line(12, 5, 26, 14)
    c.line(26, 14, 26, 20)
    c.line(26, 20, 40, 20)
    c.arrow(12 + 14 * 0.35, 5 + 9 * 0.35, 24.5, 13, 5.5, 0.1)


def _shunt_ref(c):
    """TL431: like a Zener (cathode at the top, anode at the bottom) with the REF lead touching the triangle."""
    c.line(0, -30, 0, -9)
    c.line(0, 10, 0, 30)
    c.poly([(-10, 10), (10, 10), (0, -9)], c.paper)
    c.poly([(-13, -5), (-10, -9), (10, -9), (13, -13)], None, 2.2, closed=False)
    c.line(-30, 0, -5, 0)
    c.label_at(4, -24, "K", Qt.AlignLeft | Qt.AlignVCenter, 6.5)
    c.label_at(4, 24, "A", Qt.AlignLeft | Qt.AlignVCenter, 6.5)
    c.label_at(-27, -6, "REF", Qt.AlignLeft | Qt.AlignVCenter, 6)


def _ssr(c):
    """Solid-state relay: the optoisolator's LED on the left, a switch (two MOSFETs) on the right."""
    c.rect(-30, -32, 60, 64, None, 1.2)
    c.line(-40, -20, -18, -20)
    c.line(-18, -20, -18, -8)
    c.poly([(-27, -8), (-9, -8), (-18, 6)], c.paper)
    c.line(-27, 6, -9, 6, 2.2)
    c.line(-18, 6, -18, 20)
    c.line(-18, 20, -40, 20)
    ir = c.props.get("_ir", 0.0)
    on = c.props.get("_on", False)
    if ir > 0.02:
        old = c.ink
        c.ink = QColor(255, 170, 30)
        c.arrow(-6, -5, 4, -5, 4.5, 1.6)
        c.arrow(-6, 3, 4, 3, 4.5, 1.6)
        c.ink = old
    else:
        c.arrow(-6, -5, 4, -5, 4.5, 1.5)
        c.arrow(-6, 3, 4, 3, 4.5, 1.5)
    # output switch: O1 at the top right, O2 at the bottom right
    c.line(40, -20, 20, -20)
    c.line(20, -20, 20, -10)
    c.line(40, 20, 20, 20)
    c.line(20, 20, 20, 10)
    if on:
        c.line(20, 10, 20, -10, 2.0)
    else:
        c.line(20, 10, 12, -8, 2.0)
    c.circle(20, -10, 1.8, c.ink, 1)
    c.circle(20, 10, 1.8, c.ink, 1)


OVERBAR = "\u0305"


def _lo(name):
    """Pin label with a bar over it (active-low)."""
    return "".join(ch + OVERBAR for ch in name)


def _mux4051(c):
    _box_ic(c, -40, -50, 40, 40, "4051", labels={"INH": "INH"})


def _sr164(c):
    _box_ic(c, -40, -50, 40, 40, "164", labels={"MR": _lo("MR"), "CP": "CP"}, clock=10)


def _sr595(c):
    _box_ic(c, -40, -50, 40, 50, "595", labels={"MR": _lo("MR"), "OE": _lo("OE")}, clock=-20)


def _sr165(c):
    _box_ic(c, -40, -70, 40, 60, "165", labels={"CE": _lo("CE"), "PL": _lo("PL"), "Q7N": _lo("Q7")}, clock=30)


def _sr597(c):
    _box_ic(c, -40, -70, 40, 70, "597", labels={"PL": _lo("PL"), "MR": _lo("MR")}, clock=30)


# ------------------------------------------------------------------------------------------ 1.4.0 parts
LED_MIX_RGB = {"Red": "#ff3b30", "Green": "#2fd158", "Blue": "#2f7bff"}


def _mini_diode(c, x0, x1, y, fill, w=8):
    """A small diode pointing from x0 to x1 (either way) at height y, with a filled body."""
    c.poly([(x0, y - w), (x0, y + w), (x1, y)], fill)
    c.line(x1, y - w, x1, y + w, 2.0)


def _lit(c, colour, k):
    return led_fill(QColor(LED_MIX_RGB[colour]), k)


def _led_bi2(c):
    g = list(c.props.get("_glows") or [0.0, 0.0])
    c.line(-30, 0, -14, 0)
    c.line(14, 0, 30, 0)
    c.line(-14, -9, -14, 9)
    c.line(14, -9, 14, 9)
    for y, xa, xb, col, k in ((-9, -6, 6, "Red", g[0]), (9, 6, -6, "Green", g[1])):
        c.line(-14, y, min(xa, xb), y)
        c.line(max(xa, xb), y, 14, y)
        _mini_diode(c, xa, xb, y, _lit(c, col, k), 6)
    c.arrow(0, -18, 7, -26, 4, 1.4)
    c.arrow(7, -16, 14, -24, 4, 1.4)


def _led_multi(c, colours):
    g = list(c.props.get("_glows") or [0.0] * len(colours))
    ys = [-20, 0, 20] if len(colours) == 3 else [-10, 10]
    for (col, y, k) in zip(colours, ys, g):
        c.line(-30, y, -8, y)
        _mini_diode(c, -8, 6, y, _lit(c, col, k), 7)
        c.line(6, y, 14, y)
        c.upright(-22, y - 6, col[0], 7, False)
    c.line(14, ys[0], 14, ys[-1])
    c.line(14, 0, 30, 0)
    top = ys[0]
    c.arrow(-2, top - 10, 5, top - 18, 4, 1.4)
    c.arrow(5, top - 8, 12, top - 16, 4, 1.4)


def _bridge(c):
    """Bridge rectifier: four diodes round a diamond, all pointing towards +."""
    c.line(0, -40, 0, -30)
    c.line(0, 30, 0, 40)
    c.line(30, 0, 40, 0)
    c.line(-40, 0, -30, 0)
    p = c.p
    for (xa, ya), (xb, yb) in (((-30, 0), (0, -30)), ((0, -30), (30, 0)), ((-30, 0), (0, 30)), ((0, 30), (30, 0))):
        c.line(xa, ya, xb, yb, 1.8)
        mx, my = (xa + xb) / 2, (ya + yb) / 2
        ang = math.degrees(math.atan2(yb - ya, xb - xa))
        p.save()
        p.translate(mx, my)
        p.rotate(ang)
        c.poly([(-5, -5), (-5, 5), (4, 0)], c.ink, 1.2)
        c.line(4, -5, 4, 5, 1.8)
        p.restore()
    c.upright(9, -32, "~", 10, False)
    c.upright(9, 32, "~", 10, False)
    c.upright(34, -8, "+", 9, True)
    c.upright(-34, -8, "−", 9, True)


def _scr(c):
    _diode_body(c, c.ink)
    c.line(9, 6, 10, 16)
    c.line(10, 16, 10, 30)
    if c.props.get("_on"):
        p = c.p
        p.setPen(Qt.NoPen)
        lit = QColor(theme_accent())
        lit.setAlphaF(0.35)
        p.setBrush(lit)
        p.drawRoundedRect(QRectF(-14, -14, 28, 28), 6, 6)


def theme_accent():
    from . import theme
    return theme.ACCENT


def _reg_fixed(c):
    model = str(c.props.get("model", "7805")).replace("LM", "")
    _box_ic(c, -40, -20, 40, 20, model, labels={"IN": "IN", "OUT": "OUT", "GND": "GND"}, title_y=-9)


def _reg_adj(c):
    _box_ic(c, -40, -20, 40, 20, "LM317", labels={"IN": "IN", "OUT": "OUT", "ADJ": "ADJ"}, title_y=-9)


def _coil_v(c, x, y0, y1, bulge):
    """A coil drawn down the page from y0 to y1, its loops bulging left (-1) or right (+1)."""
    path = QPainterPath()
    path.moveTo(x, y0)
    n = 4
    hgt = (y1 - y0) / n
    for k in range(n):
        yy = y0 + hgt * k
        if bulge < 0:
            path.arcTo(QRectF(x - hgt / 2, yy, hgt, hgt), 90, 180)
        else:
            path.arcTo(QRectF(x - hgt / 2, yy, hgt, hgt), 90, -180)
    c.p.setPen(c.pen())
    c.p.setBrush(Qt.NoBrush)
    c.p.drawPath(path)


def _transformer(c):
    c.line(-40, -30, -12, -30)
    c.line(-12, -30, -12, -24)
    c.line(-40, 30, -12, 30)
    c.line(-12, 30, -12, 24)
    c.line(40, -30, 12, -30)
    c.line(12, -30, 12, -24)
    c.line(40, 30, 12, 30)
    c.line(12, 30, 12, 24)
    _coil_v(c, -12, -24, 24, 1)
    _coil_v(c, 12, -24, 24, -1)
    c.line(-2, -26, -2, 26, 1.6)
    c.line(2, -26, 2, 26, 1.6)


def _dpdt(c):
    a = c.props.get("position", "A") == "A"
    for oy in (-20, 20):
        c.line(-30, oy, -14, oy)
        c.line(14, oy - 10, 30, oy - 10)
        c.line(14, oy + 10, 30, oy + 10)
        c.line(-12, oy, 12, oy + (-8 if a else 8))
        _contact(c, -14, oy)
        _contact(c, 14, oy - 10)
        _contact(c, 14, oy + 10)
    c.p.setPen(c.pen(1.2, style=Qt.DashLine))
    c.p.drawLine(QPointF(0, -20 + (-4 if a else 4)), QPointF(0, 20 + (-4 if a else 4)))
    c.upright(22, -37, "A", 8, False)
    c.upright(22, -3, "B", 8, False)


def _hall(c):
    c.line(0, -30, 0, -18)
    c.line(0, 18, 0, 30)
    c.line(18, 0, 30, 0)
    c.rect(-18, -18, 36, 36, c.paper)
    c.upright(0, 1, "H", 13)
    c.upright(-8, -25, "+V", 6.5, False)
    c.upright(-8, 25, "0V", 6.5, False)
    c.upright(25, -6, "OUT", 6, False)
    if c.props.get("magnet"):         # the magnet, drawn beside it
        p = c.p
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#e03131"))
        p.drawRect(QRectF(-30, -10, 7, 10))
        p.setBrush(QColor("#1971c2"))
        p.drawRect(QRectF(-30, 0, 7, 10))


def _solenoid(c):
    c.line(-30, 0, -18, 0)
    c.line(18, 0, 30, 0)
    path = QPainterPath()
    path.moveTo(-18, 0)
    for k in range(4):
        path.arcTo(QRectF(-18 + 9 * k, -5, 9, 10), 180, -180)
    c.p.setPen(c.pen())
    c.p.setBrush(Qt.NoBrush)
    c.p.drawPath(path)
    x = -14 if c.props.get("_on") else -4         # the plunger: pulled in while energised
    c.rect(x, 8, 28, 5, c.ink, 1.0)
    c.line(x + 28, 10.5, x + 34, 10.5, 1.6)


def _comparator(c):
    c.line(-40, -10, -30, -10)
    c.line(-40, 10, -30, 10)
    c.line(30, 0, 40, 0)
    c.poly([(-30, -30), (-30, 30), (30, 0)], c.paper)
    c.line(-25, -10, -19, -10, 1.5)              # + at the top
    c.line(-22, -13, -22, -7, 1.5)
    c.line(-25, 10, -19, 10, 1.5)                # − at the bottom
    # open-collector output mark
    c.line(4, -4, 12, -4, 1.2)
    c.line(8, -4, 8, 4, 1.2)
    c.line(5, 4, 11, 4, 1.2)


def _ic4026(c):
    _box_ic(c, -40, -40, 40, 60, "4026", labels={"CLK": ""}, clock=-30)


def _l293d(c):
    _box_ic(c, -40, -60, 40, 50, "L293D", labels={"EN12": "EN1,2", "EN34": "EN3,4"})


def _ic4060(c):
    _box_ic(c, -40, -60, 40, 50, "4060", labels={"PI": "RS", "PO": "RTC", "POn": "CTC"})


def _jkff(c):
    _box_ic(c, -30, -40, 30, 40, "", labels={"CLK": "", "Qn": "Q̅"}, clock=0)


def _xtal_clock(c):
    c.rect(-30, -18, 60, 36, c.paper)
    c.line(30, 0, 40, 0)
    # a crystal: two plates with the quartz between them
    c.line(-22, -8, -22, 8, 1.6)
    c.line(-8, -8, -8, 8, 1.6)
    c.rect(-19, -6, 8, 12, None, 1.4)
    # and the square wave it makes
    c.poly([(0, 6), (5, 6), (5, -6), (12, -6), (12, 6), (19, 6), (19, -6), (24, -6)], None, 1.4, closed=False)


def _stepper(c):
    for y, x0, x1 in ((-10, -40, -16), (10, -40, -16), (-10, 16, 40), (10, 16, 40)):
        c.line(x0, y, x1, y)
    c.circle(0, 0, 19, c.paper, 1.8)
    # step marks round the inside, and the shaft's pointer showing where it is
    for k in range(8):
        a = math.radians(k * 45)
        c.line(15 * math.cos(a), 15 * math.sin(a), 17.5 * math.cos(a), 17.5 * math.sin(a), 1.0)
    ang = math.radians(float(c.props.get("_angle", 0.0)) - 90)
    c.line(0, 0, 12 * math.cos(ang), 12 * math.sin(ang), 2.2)
    c.circle(0, 0, 2.5, c.ink, 1.0)
    c.upright(-30, -16, "A", 7, False)
    c.upright(30, -16, "B", 7, False)


def _rotary(c):
    c.line(-30, 0, -16, 0)
    pos = str(c.props.get("position", "1"))
    for k, y in enumerate((-30, -10, 10, 30)):
        c.line(14, y, 30, y)
        _contact(c, 12, y)
        c.upright(22, y - 6, str(k + 1), 6.5, False)
    _contact(c, -14, 0)
    sel = int(pos) - 1 if pos in ("1", "2", "3", "4") else 0
    y = (-30, -10, 10, 30)[sel]
    c.line(-12, 0, 10, y * 0.92, 1.8)
    # the knob's arc
    p = c.p
    p.setPen(c.pen(1.0, style=Qt.DashLine))
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(-20, -32, 64, 64), 120 * 16, 120 * 16)


KEYPAD_KEYS = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#")


def keypad_key_at(x, y):
    """Which key is at (x, y) in the keypad's own frame, or None."""
    for n, k in enumerate(KEYPAD_KEYS):
        cx, cy = -20 + 20 * (n % 3), -38 + 20 * (n // 3)
        if abs(x - cx) <= 9 and abs(y - cy) <= 8:
            return k
    return None


def _keypad(c):
    c.rect(-40, -55, 80, 110, c.paper)
    pressed = str(c.props.get("_key") or "")
    for n, k in enumerate(KEYPAD_KEYS):
        cx, cy = -20 + 20 * (n % 3), -38 + 20 * (n // 3)
        down = k == pressed
        p = c.p
        p.setPen(c.pen(1.2))
        p.setBrush(QColor(theme_accent()) if down else c.paper)
        p.drawRoundedRect(QRectF(cx - 8, cy - 7, 16, 14), 3, 3)
        c.upright(cx, cy, k, 8, True, QColor("#ffffff") if down else None)
    for name, px, py in P.get("keypad").pins:
        c.line(px, 55, px, py)
        c.upright(px, 50, name, 5, False)


DRAW.update({
    "led_bi2": _led_bi2, "led_bi3": lambda c: _led_multi(c, ("Red", "Green")),
    "led_rgb": lambda c: _led_multi(c, ("Red", "Green", "Blue")), "bridge": _bridge, "scr": _scr,
    "reg_fixed": _reg_fixed, "reg_adj": _reg_adj, "transformer": _transformer, "dpdt": _dpdt, "hall": _hall,
    "solenoid": _solenoid, "comparator": _comparator, "ic4026": _ic4026, "ic4060": _ic4060,
    "jkff": _jkff, "xtal_clock": _xtal_clock, "stepper": _stepper, "rotary": _rotary, "keypad": _keypad,
    "schmitt_nand": lambda c: _gate_body(c, "schmitt_nand"), "l293d": _l293d,
})


def note_lines(props):
    # the notes that come with the examples are shown in the chosen language; anything a person typed is left alone
    return tr(str(props.get("text", ""))).split("\n") if props.get("text") else [" "]


def _note(c):
    f = QFont()
    f.setPixelSize(12)
    c.p.setFont(f)
    c.p.setPen(c.ink)
    lines = note_lines(c.props)
    h = 16 * len(lines)
    c.p.drawText(QRectF(-300, -h / 2, 600, h), Qt.AlignCenter, "\n".join(lines))


DRAW.update({
    "inductor": _inductor, "relay": _relay, "relay_dpdt": _relay_dpdt, "reed_switch": _reed_switch, "tilt_switch": _tilt_switch,
    "moisture": _moisture, "phototransistor": _phototransistor, "optocoupler": _optocoupler, "note": _note,
    "shunt_ref": _shunt_ref, "ssr": _ssr, "mux4051": _mux4051, "sr164": _sr164, "sr595": _sr595,
    "sr165": _sr165, "sr597": _sr597,
})


def draw(p: QPainter, kind: str, props: dict, ink, rot=0, flip=False, paper=None):
    """Draw part `kind` in local coordinates (painter already rotated/flipped by the caller)."""
    fn = DRAW.get(kind)
    c = Ctx(p, QColor(ink), props, rot, flip, paper, kind)
    if fn is None:      # unknown part from a newer file: a labelled box so nothing disappears
        c.rect(-20, -12, 40, 24)
        c.upright(0, 0, "?", 12)
        return
    fn(c)


def apply_transform(p: QPainter, rot: int, flip: bool):
    """Painter set-up matching model.circuit.transform (flip first, then rotate clockwise)."""
    p.rotate(90 * (rot % 4))
    if flip:
        p.scale(-1, 1)


def local_bounds(kind: str, rot=0, flip=False) -> QRectF:
    """The part's clickable box after rotation/flip, relative to its centre."""
    bx, by, bw, bh = P.get(kind).box
    xs, ys = [], []
    for x, y in ((bx, by), (bx + bw, by), (bx, by + bh), (bx + bw, by + bh)):
        tx, ty = transform(x, y, rot, flip)
        xs.append(tx)
        ys.append(ty)
    return QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))


def pixmap(kind: str, w: int, h: int, ink, paper, props=None, dpr: float = 2.0) -> QPixmap:
    """A picture of the symbol scaled to fit w×h (used for the parts gallery)."""
    part = P.get(kind)
    pm = QPixmap(int(w * dpr), int(h * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    bx, by, bw, bh = part.box
    # include the pins and a little air
    xs = [bx, bx + bw] + [x for _n, x, _y in part.pins]
    ys = [by, by + bh] + [y for _n, _x, y in part.pins]
    x0, x1, y0, y1 = min(xs) - 3, max(xs) + 3, min(ys) - 3, max(ys) + 3
    s = min(w / (x1 - x0), h / (y1 - y0))
    p.translate(w / 2, h / 2)
    p.scale(s, s)
    p.translate(-(x0 + x1) / 2, -(y0 + y1) / 2)
    values = part.defaults()
    values.update(props or {})
    draw(p, kind, values, ink, paper=paper)
    p.end()
    return pm
