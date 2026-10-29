"""The zoomable window onto the circuit sheet: wheel to zoom, middle-drag (or Space + drag) to pan."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QVariantAnimation, QEasingCurve, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QGraphicsView, QWidget

from ..i18n import tr

ZOOM_MIN, ZOOM_MAX = 0.2, 8.0


class CircuitView(QGraphicsView):
    zoomChanged = Signal(float)

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        # the dotted grid is the same every frame: keep a ready-drawn copy (redrawn only on scroll / zoom / theme)
        self.setCacheMode(QGraphicsView.CacheBackground)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setRubberBandSelectionMode(Qt.IntersectsItemShape)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self._pan = None
        self._space = False
        self._anim = None
        self._toasts = []
        self.setTransform(self.transform().fromScale(1.6, 1.6))

    # ---- zoom
    def zoom(self) -> float:
        return self.transform().m11()

    def set_zoom(self, z: float, anchor_view: QPointF | None = None):
        z = max(ZOOM_MIN, min(ZOOM_MAX, z))
        f = z / self.zoom()
        if anchor_view is None:
            self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        self.scale(f, f)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.zoomChanged.emit(self.zoom())

    def zoom_by(self, factor: float):
        self.set_zoom(self.zoom() * factor)

    def wheelEvent(self, e):
        sc = self.scene()
        if sc.sim_active():
            pos = self.mapToScene(e.position().toPoint())
            if any(it in sc.sliders for it in sc.items(pos)):
                super().wheelEvent(e)        # let the slider have it
                return
        if e.modifiers() & Qt.ShiftModifier:     # shift + wheel scrolls sideways
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - e.angleDelta().y())
            return
        steps = e.angleDelta().y() / 120.0
        if steps == 0:
            return
        self.set_zoom(self.zoom() * (1.18 ** steps), e.position())

    def fit(self, rect: QRectF | None, animate=True, max_zoom=2.5):
        """Zoom so the rectangle (in sheet units) fills the window."""
        if rect is None or rect.isEmpty():
            rect = QRectF(-200, -150, 400, 300)
        rect = rect.adjusted(-40, -40, 40, 40)
        vw, vh = max(self.viewport().width(), 50), max(self.viewport().height(), 50)
        z = max(ZOOM_MIN, min(max_zoom, min(vw / rect.width(), vh / rect.height())))
        if not animate or not self.isVisible():
            self.resetTransform()
            self.scale(z, z)
            self.centerOn(rect.center())
            self.zoomChanged.emit(z)
            return
        z0 = self.zoom()
        c0 = self.mapToScene(self.viewport().rect().center())
        c1 = rect.center()
        if self._anim:
            self._anim.stop()
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(260)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def step(t):
            zz = z0 + (z - z0) * t
            self.resetTransform()
            self.scale(zz, zz)
            self.centerOn(c0 + (c1 - c0) * t)
            self.zoomChanged.emit(zz)
        anim.valueChanged.connect(step)
        anim.start()
        self._anim = anim

    def drawForeground(self, p, rect):
        super().drawForeground(p, rect)
        sc = self.scene()
        if sc.sim_active() and sc.show_volts:
            self._draw_legend(p, sc)
        if sc.sim_active() and sc.hover_info:
            self._draw_bubble(p, sc.hover_info)
        if sc.circuit.is_empty() and sc._ghost is None and not sc.exporting:
            from PySide6.QtGui import QColor, QFont
            from . import theme
            p.save()
            p.resetTransform()
            r = self.viewport().rect()
            f = QFont()
            f.setPixelSize(17)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(theme.TEXT_MUTED))
            p.drawText(r.adjusted(0, -30, 0, -30), Qt.AlignCenter, tr("Your circuit sheet is empty"))
            f.setPixelSize(13)
            f.setBold(False)
            p.setFont(f)
            p.drawText(r.adjusted(0, 20, 0, 20), Qt.AlignCenter,
                       tr("Drag parts here from the gallery on the left,") + "\n" +
                       tr("then drag from pin to pin to wire them up.") + "\n" +
                       tr("Or open an example from the File menu."))
            p.restore()

    def _draw_legend(self, p, sc):
        """Colour key for the wire voltages, bottom-left of the window."""
        from PySide6.QtGui import QColor, QFont, QLinearGradient, QPen
        from PySide6.QtCore import QRectF
        from ..model.units import fmt
        from . import theme
        vmax = sc.sim.live.vmax
        p.save()
        p.resetTransform()
        p.setRenderHint(QPainter.Antialiasing)
        r = self.viewport().rect()
        box = QRectF(14, r.height() - 54, 196, 40)
        bg = QColor(theme.PANEL)
        bg.setAlpha(235)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(bg)
        p.drawRoundedRect(box, 8, 8)
        bar = QRectF(box.left() + 12, box.top() + 9, box.width() - 24, 8)
        g = QLinearGradient(bar.topLeft(), bar.topRight())
        for k in range(11):
            g.setColorAt(k / 10, theme.volt_colour(vmax * k / 10, vmax))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(bar, 4, 4)
        f = QFont()
        f.setPixelSize(10)
        p.setFont(f)
        p.setPen(QColor(theme.TEXT_MUTED))
        y = bar.bottom() + 3
        p.drawText(QRectF(bar.left(), y, 60, 14), Qt.AlignLeft, "0 V")
        p.drawText(QRectF(bar.center().x() - 40, y, 80, 14), Qt.AlignCenter, fmt(vmax / 2, "V"))
        p.drawText(QRectF(bar.right() - 60, y, 60, 14), Qt.AlignRight, fmt(vmax, "V"))
        p.restore()

    def retranslate(self):
        self.clear_toasts()         # a message already showing is in the old language
        self.viewport().update()

    def clear_toasts(self):
        for t in list(self._toasts):
            t.close_now()

    def _draw_bubble(self, p, info):
        """Small reading card next to the mouse: what's under it, its voltage and current."""
        from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPen
        from PySide6.QtCore import QRectF
        from . import theme
        pos, title, lines = info
        at = self.mapFromScene(pos)
        p.save()
        p.resetTransform()
        p.setRenderHint(QPainter.Antialiasing)
        fb = QFont()
        fb.setPixelSize(12)
        fb.setBold(True)
        fn = QFont()
        fn.setPixelSize(12)
        w = max([QFontMetricsF(fb).horizontalAdvance(title)] +
                [QFontMetricsF(fn).horizontalAdvance(t) for t in lines]) + 20
        h = 18 * (len(lines) + 1) + 10
        box = QRectF(at.x() + 16, at.y() + 16, w, h)
        vr = self.viewport().rect()
        if box.right() > vr.right() - 4:
            box.moveRight(at.x() - 12)
        if box.bottom() > vr.bottom() - 4:
            box.moveBottom(at.y() - 12)
        bg = QColor(theme.PANEL)
        bg.setAlpha(242)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(bg)
        p.drawRoundedRect(box, 7, 7)
        p.setFont(fb)
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(box.left() + 10, box.top() + 5, w, 18), Qt.AlignLeft | Qt.AlignVCenter, title)
        p.setFont(fn)
        for k, t in enumerate(lines):
            p.drawText(QRectF(box.left() + 10, box.top() + 5 + 18 * (k + 1), w, 18), Qt.AlignLeft | Qt.AlignVCenter, t)
        p.restore()

    def toast(self, text, kind="warn"):
        """A message that pops up at the bottom of the sheet and fades away."""
        Toast(self.viewport(), text, kind, self._toasts)

    # ---- panning: middle button, or hold Space and drag
    def mousePressEvent(self, e):
        if e.button() == Qt.MiddleButton or (e.button() == Qt.LeftButton and self._space):
            self._pan = e.position()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            d = e.position() - self._pan
            self._pan = e.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - d.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - d.y()))
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._pan is not None and e.button() in (Qt.MiddleButton, Qt.LeftButton):
            self._pan = None
            self.viewport().setCursor(Qt.OpenHandCursor if self._space else Qt.ArrowCursor)
            e.accept()
            return
        super().mouseReleaseEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat() and self.scene().mode != "place":
            self._space = True
            self.viewport().setCursor(Qt.OpenHandCursor)
            e.accept()
            return
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self._space = False
            self.viewport().setCursor(Qt.ArrowCursor)
            e.accept()
            return
        super().keyReleaseEvent(e)

    def contextMenuEvent(self, e):
        """Right-click: a menu for whatever is under the mouse (the window decides what's in it)."""
        sc = self.scene()
        if sc._wiring is not None or sc._ghost is not None:
            return                                   # right-click already cancelled what was going on
        provider = getattr(self, "menu_provider", None)
        if provider is None:
            return
        menu = provider(self.mapToScene(e.pos()))
        if menu is not None and not menu.isEmpty():
            menu.exec(e.globalPos())

    def leaveEvent(self, e):
        sc = self.scene()
        sc.hover_info = None
        sc._mouse_pos = None
        self.viewport().update()
        if getattr(sc, "_ghost", None) is not None:
            sc._ghost.hide()
        super().leaveEvent(e)


class Toast(QWidget):
    LIFE_MS = 7000

    def __init__(self, parent, text, kind, stack):
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QGraphicsOpacityEffect
        from . import theme
        super().__init__(parent)
        self.stack = stack
        self.setAttribute(Qt.WA_StyledBackground, True)
        col = theme.ERROR if kind == "error" else theme.WARN
        self.setStyleSheet(f"Toast {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER}; "
                           f"border-left: 4px solid {col}; border-radius: 8px; }} "
                           f"QLabel {{ color: {theme.TEXT}; font-size: 13px; background: transparent; }}")
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 9, 14, 9)
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setMaximumWidth(460)
        h.addWidget(lab)
        self.adjustSize()
        self.eff = QGraphicsOpacityEffect(self)
        self.eff.setOpacity(0.0)
        self.setGraphicsEffect(self.eff)
        stack.append(self)
        if len(stack) > 3:
            stack[0].close_now()
        self.show()
        self.restack()
        self._fade(1.0, 220)
        QTimer.singleShot(self.LIFE_MS, lambda: self._fade(0.0, 600, self.close_now))

    def _fade(self, to, ms, then=None):
        from PySide6.QtCore import QPropertyAnimation
        try:
            a = QPropertyAnimation(self.eff, b"opacity", self)
        except RuntimeError:
            return
        a.setDuration(ms)
        a.setEndValue(to)
        if then:
            a.finished.connect(then)
        a.start()
        self._a = a

    def close_now(self):
        if self in self.stack:
            self.stack.remove(self)
        try:
            self.hide()
            self.deleteLater()
            for t in self.stack:
                t.restack()
        except RuntimeError:
            pass

    def restack(self):
        par = self.parentWidget()
        if par is None:
            return
        y = par.height() - 18
        for t in reversed(self.stack):
            y -= t.height()
            t.move((par.width() - t.width()) // 2, y)
            y -= 8

    def mousePressEvent(self, e):
        self.close_now()
