"""The things you see on the circuit sheet: parts (ComponentItem) and wires (WireItem)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
import math

from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPainterPathStroker, QPen,
                           QRadialGradient)
from PySide6.QtWidgets import QGraphicsItem

from ..model import parts as P
from ..model.circuit import Component, Wire
from ..model.units import fmt
from . import symbols as S
from . import theme

NO_LABEL = {"ground", "rail_pos", "scope_probe", "logic_probe", "note"}
LABEL_PX = 10.0


def label_lines(comp: Component) -> list[str]:
    if comp.kind in NO_LABEL:
        return []
    lines = [comp.ref]
    vals = []
    for p in comp.part.props:
        if p.on_label:
            v = comp.value(p.key)
            vals.append(fmt(v, p.unit) if p.kind == "number" else P.choice_text(v) if p.kind == "choice" else str(v))
    if vals:
        lines.append(" ".join(vals))
    return lines


def _font_px(px):
    f = QFont()
    f.setPixelSize(px)
    return f


def _font(bold=False):
    f = QFont()
    f.setPixelSize(int(LABEL_PX))
    f.setBold(bold)
    return f


def _r(v, k=2):
    return round(float(v), k)


def live_look_key(live, kind, anim_t):
    """The parts of a part's live readings that change how it looks: while it's running, a part is only drawn again
    when this changes (otherwise its ready-drawn picture is reused). The browser version uses it the same way."""
    if not live:
        return None
    k = (live.get("blown"), bool(live.get("warn")), live.get("reading"))
    for name in sorted(n for n in live if n.startswith("_")):
        val = live[name]
        if isinstance(val, (list, tuple)):
            val = tuple(_r(x) if isinstance(x, (int, float)) else x for x in val)
        elif isinstance(val, float):
            val = _r(val)
        k += ((name, val),)
    if kind == "motor":
        k += (round(live.get("angle", 0.0) / 3),)
    if kind == "buzzer" and live.get("level", 0) > 0:
        k += (_r(live["level"]), round((anim_t * 6) % 1.0, 1))
    return k


class ComponentItem(QGraphicsItem):
    """One part on the sheet. Its position is the part's centre; rotation is applied when drawing."""

    def __init__(self, comp: Component, ghost=False):
        super().__init__()
        self.comp = comp
        self.ghost = ghost
        self.hover = False
        self.setFlag(QGraphicsItem.ItemIsSelectable, not ghost)
        self.setAcceptHoverEvents(not ghost)
        self.setZValue(10 if ghost else 1)
        if ghost:
            self.setOpacity(0.55)
        else:
            # keep a ready-drawn picture: redrawn only when the part changes (see CircuitScene.refresh_look)
            self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        self.look = None
        self.sync()

    # ---- geometry
    def sync(self):
        """Call after the model component changed (moved, rotated, values edited)."""
        self.prepareGeometryChange()
        self.setPos(self.comp.x, self.comp.y)
        self._body = S.local_bounds(self.comp.kind, self.comp.rot, self.comp.flip)
        if self.comp.kind == "note":            # a note is as big as its text
            fm = QFontMetricsF(_font_px(12))
            lines = S.note_lines(self.comp.props)
            w = max(fm.horizontalAdvance(t) for t in lines) + 12
            h = 16 * len(lines) + 6
            self._body = QRectF(-w / 2, -h / 2, w, h)
        pins = [QPointF(*self._pin_local(n)) for n in self.comp.pin_positions()]
        r = QRectF(self._body)
        for pt in pins:
            r = r.united(QRectF(pt.x() - 3, pt.y() - 3, 6, 6))
        self._sym = r
        self._label = self._label_layout()
        b = r.united(self._label[0]) if self._label[1] else QRectF(r)
        # room for glows, warnings and meter readouts while the simulation runs
        self._bounds = b.adjusted(-30, -30, 30, 30).united(self._readout_rect().adjusted(-4, -4, 4, 4))
        self.update()

    def _readout_rect(self):
        """Where a meter shows its reading (under the symbol, always level)."""
        return QRectF(self._sym.center().x() - 34, self._sym.bottom() + 5, 68, 17)

    def _pin_local(self, name):
        x, y = self.comp.pin_positions()[name]
        return x - self.comp.x, y - self.comp.y

    def _label_layout(self):
        lines = label_lines(self.comp)
        if not lines:
            return QRectF(), [], Qt.AlignHCenter
        fm_b, fm = QFontMetricsF(_font(True)), QFontMetricsF(_font(False))
        w = max([fm_b.horizontalAdvance(lines[0])] + [fm.horizontalAdvance(t) for t in lines[1:]])
        h = len(lines) * (LABEL_PX + 2)
        b = self._body
        pins = [QPointF(*self._pin_local(n)) for n in self.comp.pin_positions()]
        right = any(pt.x() > b.right() + 1 for pt in pins)
        above = any(pt.y() < b.top() - 1 for pt in pins)
        below = any(pt.y() > b.bottom() + 1 for pt in pins)
        if b.width() >= b.height() or (right and not above):   # lying flat, or pins on the right: label above
            side = "above"
        elif right and not below:                              # pins on the right and above: label below
            side = "below"
        else:                                                  # standing up: label on the right
            side = "right"
        # … unless pins come out of that side (a chip turned round, a regulator upside down): use a clear one,
        # or the outside top-right corner, where pins never are
        clear = {"above": not above, "below": not below, "right": not right}
        if not clear[side]:
            side = next((s_ for s_ in ("above", "below", "right") if clear[s_]), "corner")
        if side == "above":
            r = QRectF(b.center().x() - w / 2, b.top() - h - 3, w, h)
            align = Qt.AlignHCenter
        elif side == "below":
            r = QRectF(b.center().x() - w / 2, b.bottom() + 3, w, h)
            align = Qt.AlignHCenter
        elif side == "right":
            r = QRectF(b.right() + 5, b.center().y() - h / 2, w, h)
            align = Qt.AlignLeft
        else:
            r = QRectF(b.right() + 2, b.top() - h - 2, w, h)
            align = Qt.AlignLeft
        return r, lines, align

    def boundingRect(self):
        return self._bounds

    def shape(self):
        path = QPainterPath()
        path.addRect(self._body.adjusted(-3, -3, 3, 3))
        return path

    # ---- drawing
    def paint(self, p: QPainter, _opt, _w=None):
        p.setRenderHint(QPainter.Antialiasing)
        sc = self.scene()
        exporting = getattr(sc, "exporting", False)
        live = sc.live_part(self.comp.id) if (sc is not None and not exporting and not self.ghost) else None
        selected = self.isSelected() and not exporting
        if live:
            self._paint_glow(p, live)
        if selected or (self.hover and not exporting):
            fill = QColor(theme.SELECT_HALO if selected else theme.HOVER)
            if not selected:
                fill.setAlpha(45)
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawRoundedRect(self._sym.adjusted(-4, -4, 4, 4), 5, 5)
        ink = QColor(theme.SELECT if selected else theme.INK)
        props = self.comp.props
        if live:
            if live.get("blown"):
                ink = QColor(theme.BLOWN)
            extra = {k: val for k, val in live.items() if k.startswith("_")}
            if extra:
                props = dict(props, **extra)
        p.save()
        S.apply_transform(p, self.comp.rot, self.comp.flip)
        S.draw(p, self.comp.kind, props, ink, self.comp.rot, self.comp.flip, QColor(theme.CANVAS))
        p.restore()
        if live:
            self._paint_live(p, live)
        rect, lines, align = self._label
        if lines:
            y = rect.top()
            for i, t in enumerate(lines):
                p.setFont(_font(i == 0))
                p.setPen(QColor(theme.LABEL if i == 0 else theme.LABEL_VALUE))
                p.drawText(QRectF(rect.left() - 40, y, rect.width() + 80, LABEL_PX + 2) if align == Qt.AlignHCenter
                           else QRectF(rect.left(), y, rect.width() + 40, LABEL_PX + 2),
                           align | Qt.AlignVCenter, t)
                y += LABEL_PX + 2

    # ---- live simulation extras
    def _paint_glow(self, p: QPainter, live):
        g = live.get("_glow", 0.0)
        if g <= 0.02 or live.get("blown"):
            return
        led = "_rgb" in live or self.comp.kind == "led"
        if "_rgb" in live:                  # bi-colour and RGB LEDs: the colours they're mixing
            col = QColor(live["_rgb"])
        elif self.comp.kind == "led":
            col = QColor(S.LED_RGB.get(self.comp.value("colour"), "#ff3b30"))
        else:
            col = QColor(255, 205, 40)
        radius = (22 + 22 * g) if led else (18 + 18 * g)
        c = QPointF(0, 0)       # the LED / lamp itself sits at the part's centre (its box also covers the arrows)
        grad = QRadialGradient(c, radius)
        core = QColor(col).lighter(160) if led else QColor(col)      # a bright, almost white centre
        core.setAlphaF(min(1.0, 0.95 * g + 0.05) if led else 0.75 * g)
        inner = QColor(col)
        inner.setAlphaF(min(1.0, 0.85 * g) if led else 0.75 * g)
        mid = QColor(col)
        mid.setAlphaF(0.4 * g if led else 0.28 * g)
        outer = QColor(col)
        outer.setAlphaF(0.0)
        grad.setColorAt(0.0, core)
        grad.setColorAt(0.18 if led else 0.0, inner)
        grad.setColorAt(0.5 if led else 0.45, mid)
        grad.setColorAt(1.0, outer)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawEllipse(c, radius, radius)

    def _paint_live(self, p: QPainter, live):
        kind = self.comp.kind
        c = self._body.center()
        if live.get("blown"):
            # a puff of smoke and a cross
            p.setPen(Qt.NoPen)
            smoke = QColor(theme.BLOWN)
            smoke.setAlpha(110)
            p.setBrush(smoke)
            for dx, dy, r in ((-6, -14, 6), (3, -19, 7.5), (10, -12, 5)):
                p.drawEllipse(QPointF(c.x() + dx, self._body.top() + dy + 6), r, r)
            pen = QPen(QColor(theme.ERROR), 2.4)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            d = 7
            p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
            p.drawLine(QPointF(c.x() - d, c.y() + d), QPointF(c.x() + d, c.y() - d))
        elif live.get("warn"):
            pen = QPen(QColor(theme.WARN), 1.8, Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(self._sym.adjusted(-6, -6, 6, 6), 6, 6)
        if kind == "motor" and not live.get("blown"):
            a = math.radians(live.get("angle", 0.0))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.ACCENT))
            for k in range(3):
                ang = a + k * 2 * math.pi / 3
                p.drawEllipse(QPointF(c.x() + 10.5 * math.cos(ang), c.y() + 10.5 * math.sin(ang)), 1.9, 1.9)
        if kind == "buzzer" and live.get("level", 0) > 0:
            lvl = live["level"]
            pen = QPen(QColor(theme.ACCENT), 1.6)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            phase = (self.scene().anim_t * 6) % 1.0 if self.scene() else 0
            left = self._label[2] == Qt.AlignLeft          # label on the right: waves go left
            cx = c.x() - 12 if left else c.x() + 12
            start = 140 if left else -40
            pen.setWidthF(2.0)
            for k in range(3):
                r = 8 + 6 * k + 4 * phase
                col = QColor(theme.ACCENT)
                col.setAlphaF(max(0.0, min(1.0, 0.4 + lvl) * (1 - (k + phase) / 3.2)))
                pen.setColor(col)
                p.setPen(pen)
                p.drawArc(QRectF(cx - r, c.y() - r, 2 * r, 2 * r), start * 16, 80 * 16)
        if "reading" in live:
            r = self._readout_rect()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.LCD_BG))
            p.drawRoundedRect(r, 4, 4)
            f = QFont("monospace")
            f.setStyleHint(QFont.Monospace)
            f.setPixelSize(11)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(theme.LCD_TEXT))
            p.drawText(r, Qt.AlignCenter, live["reading"])

    def hoverEnterEvent(self, e):
        self.hover = True
        self.update()

    def hoverLeaveEvent(self, e):
        self.hover = False
        self.update()


class WireItem(QGraphicsItem):
    HIT = 7.0

    def __init__(self, wire: Wire):
        super().__init__()
        self.wire = wire
        self.hover = False
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(0)
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        self.look = None
        self.sync()

    def sync(self):
        self.prepareGeometryChange()
        path = QPainterPath()
        pts = self.wire.points
        path.moveTo(*pts[0])
        for pt in pts[1:]:
            path.lineTo(*pt)
        self._path = path
        st = QPainterPathStroker()
        st.setWidth(self.HIT * 2)
        st.setCapStyle(Qt.RoundCap)
        self._shape = st.createStroke(path)
        self._bounds = path.boundingRect().adjusted(-self.HIT, -self.HIT, self.HIT, self.HIT)
        self.update()

    def boundingRect(self):
        return self._bounds

    def shape(self):
        return self._shape

    def segment_at(self, pos: QPointF) -> int:
        """Index of the segment nearest to pos."""
        best, best_d = 0, 1e18
        for i, ((x1, y1), (x2, y2)) in enumerate(self.wire.segments()):
            px, py = pos.x(), pos.y()
            dx, dy = x2 - x1, y2 - y1
            L = dx * dx + dy * dy
            t = 0 if L == 0 else max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / L))
            d = (x1 + t * dx - px) ** 2 + (y1 + t * dy - py) ** 2
            if d < best_d:
                best, best_d = i, d
        return best

    def paint(self, p: QPainter, _opt, _w=None):
        p.setRenderHint(QPainter.Antialiasing)
        exporting = getattr(self.scene(), "exporting", False)
        selected = self.isSelected() and not exporting
        if selected or (self.hover and not exporting):
            halo = QColor(theme.SELECT_HALO if selected else theme.HOVER)
            if not selected:
                halo.setAlpha(70)
            pen = QPen(halo, 8)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            p.setPen(pen)
            p.drawPath(self._path)
        colour, width = QColor(theme.SELECT if selected else theme.WIRE), S.LW
        sc = self.scene()
        if sc is not None and not exporting and not selected:
            vc = sc.wire_colour(self.wire.id)
            if vc is not None:
                colour, width = vc, 2.8
        pen = QPen(colour, width)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(self._path)
        if selected:       # show the corner points you can drag
            p.setPen(QPen(QColor(theme.SELECT), 1.2))
            p.setBrush(QColor(theme.CANVAS))
            for x, y in self.wire.points:
                p.drawRect(QRectF(x - 2.5, y - 2.5, 5, 5))

    def hoverEnterEvent(self, e):
        self.hover = True
        self.update()

    def hoverLeaveEvent(self, e):
        self.hover = False
        self.update()


class DraftWire(QGraphicsItem):
    """The wire you are drawing at the moment (dashed until you finish it)."""

    def __init__(self):
        super().__init__()
        self.points = []
        self.target = None
        self.setZValue(20)
        self._bounds = QRectF()

    def set(self, points, target=None):
        self.prepareGeometryChange()
        self.points = [tuple(p) for p in points]
        self.target = target
        if self.points:
            xs = [p[0] for p in self.points]
            ys = [p[1] for p in self.points]
            self._bounds = QRectF(min(xs) - 10, min(ys) - 10, max(xs) - min(xs) + 20, max(ys) - min(ys) + 20)
        self.update()

    def boundingRect(self):
        return self._bounds

    def paint(self, p, _o, _w=None):
        if len(self.points) < 1:
            return
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(theme.WIRE_DRAFT)
        pen = QPen(c, S.LW)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        for a, b in zip(self.points, self.points[1:]):
            p.drawLine(QPointF(*a), QPointF(*b))
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(*self.points[0]), 3, 3)
        if self.target is not None:
            g = QColor(theme.PIN_TARGET)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(g, 2))
            p.drawEllipse(QPointF(*self.target), 6, 6)
