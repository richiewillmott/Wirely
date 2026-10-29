"""On-sheet controls shown while the simulation runs: sliders for light level, temperature and knobs."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem

from ..i18n import tr
from ..model.units import fmt
from . import theme

W, H = 84, 30
TRACK_Y = 21


class Scale:
    """Maps a part value to slider position 0..1 and back."""

    def __init__(self, kind):
        self.kind = kind

    def to_pos(self, v):
        if self.kind == "ldr":
            return max(0.0, min(1.0, math.log10(max(v, 0.1) / 0.1) / 5.0))
        if self.kind == "thermistor":
            return max(0.0, min(1.0, (v + 20) / 140.0))
        return max(0.0, min(1.0, v / 100.0))

    def from_pos(self, f):
        f = max(0.0, min(1.0, f))
        if self.kind == "ldr":
            v = 0.1 * 10 ** (5 * f)
            return float(f"{v:.2g}") if v < 10 else float(round(v, -1 if v < 1000 else -2))
        if self.kind == "thermistor":
            return round(-20 + 140 * f)
        return round(100 * f)

    def text(self, v):
        if self.kind == "ldr":
            word = tr("dark" if v < 5 else "dim" if v < 100 else "room" if v < 1000 else "bright")
            return f"{fmt(v, 'lux')} · {word}"
        if self.kind == "thermistor":
            return f"{v:g} °C"
        return f"{v:g} %"


class SliderItem(QGraphicsItem):
    """A small slider drawn under a part; drag it (or use the mouse wheel over it) while the circuit runs."""

    def __init__(self, comp_item, key, on_change):
        super().__init__()
        self.comp_item = comp_item
        self.comp = comp_item.comp
        self.key = key
        self.on_change = on_change
        self.scale = Scale(self.comp.kind)
        self.setZValue(15)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tr("Drag to change it while the circuit runs (or use the mouse wheel)"))
        self._drag = False
        self.place()

    def place(self):
        it = self.comp_item
        sym = it._sym.translated(it.pos())
        body = it._body
        upright = body.height() > body.width()
        cands = [(sym.left() - W - 8, sym.center().y() - H / 2), (sym.right() + 8, sym.center().y() + 14),
                 (sym.center().x() - W / 2, sym.bottom() + 6), (sym.center().x() - W / 2, sym.top() - H - 18)]
        if not upright:
            cands = [cands[2], cands[3], cands[0], cands[1]]
        sc = it.scene()

        def clutter(pos):
            r = QRectF(pos[0], pos[1], W, H).adjusted(-4, -4, 4, 4)
            n = 0
            if sc is not None:
                from .items import ComponentItem, WireItem
                for other in sc.items(r):
                    if other is it or other is self:
                        continue
                    if isinstance(other, ComponentItem) and other.shape().translated(other.pos()).intersects(r):
                        n += 3
                    elif isinstance(other, WireItem) and other.shape().intersects(r):
                        n += 1
                    elif isinstance(other, SliderItem):
                        n += 3
            return n
        best = min(cands, key=lambda c: (clutter(c), cands.index(c)))
        self.setPos(*best)

    def boundingRect(self):
        return QRectF(-2, -2, W + 4, H + 4)

    def value(self):
        return float(self.comp.value(self.key))

    def _knob_x(self):
        return 6 + self.scale.to_pos(self.value()) * (W - 12)

    def paint(self, p: QPainter, _o, _w=None):
        p.setRenderHint(QPainter.Antialiasing)
        bg = QColor(theme.PANEL)
        bg.setAlpha(235)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0, 0, W, H), 6, 6)
        f = QFont()
        f.setPixelSize(9)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(0, 2, W, 12), Qt.AlignCenter, self.scale.text(self.value()))
        # track: dark → bright for light, blue → red for temperature
        x0, x1 = 6, W - 6
        kx = self._knob_x()
        pen = QPen(QColor(theme.BORDER), 3.2)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(x0, TRACK_Y), QPointF(x1, TRACK_Y))
        acc = {"ldr": QColor("#f59f00"), "thermistor": QColor("#f03e3e")}.get(self.comp.kind, QColor(theme.ACCENT))
        pen.setColor(acc)
        p.setPen(pen)
        p.drawLine(QPointF(x0, TRACK_Y), QPointF(kx, TRACK_Y))
        p.setPen(QPen(acc, 1.6))
        p.setBrush(QColor(theme.PANEL))
        p.drawEllipse(QPointF(kx, TRACK_Y), 5, 5)

    def _set_from(self, x):
        f = (x - 6) / (W - 12)
        v = self.scale.from_pos(f)
        if v != self.value():
            self.on_change(self.comp.id, self.key, v)
            self.update()

    def mousePressEvent(self, e):
        self._drag = True
        self._set_from(e.pos().x())
        e.accept()

    def mouseMoveEvent(self, e):
        if self._drag:
            self._set_from(e.pos().x())

    def mouseReleaseEvent(self, e):
        self._drag = False

    def wheelEvent(self, e):
        f = self.scale.to_pos(self.value()) + (0.04 if e.delta() > 0 else -0.04)
        v = self.scale.from_pos(f)
        self.on_change(self.comp.id, self.key, v)
        self.update()
        e.accept()
