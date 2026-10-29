"""The start-up splash screen: appears the moment Wirely is opened, shows the version and revision, and a
progress bar while the rest loads. It closes itself once the main window is up. It only needs PySide6 and
the logo picture, and if anything goes wrong it simply doesn't appear — it never stops Wirely starting."""
import os
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QRadialGradient)
from PySide6.QtWidgets import QApplication, QWidget

from ..i18n import tr

W, H = 720, 400
BAR_H = 40
TEAL = QColor(16, 163, 163)
BLUE = QColor(43, 125, 233)
AMBER = QColor(255, 200, 60)
ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def _version():
    try:
        from .. import __revision__, __version__
        return tr("Version {v}", v=__version__) if __revision__ == __version__ else f"{__version__}  ·  {__revision__}"
    except Exception:       # noqa: BLE001
        return ""


class Splash(QWidget):
    MIN_SECONDS = 1.2        # stay up at least this long, so it doesn't just flash

    def __init__(self):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(W, H)
        self.text = tr("Starting…")
        self.frac = 0.0
        self.t0 = time.monotonic()
        self._bg = self._make_background()
        scr = QGuiApplication.primaryScreen()
        if scr is not None:
            g = scr.availableGeometry()
            self.move(g.center().x() - W // 2, g.center().y() - H // 2)

    # ------------------------------------------------------------------ progress
    def step(self, text, frac):
        self.text = text
        self.frac = max(self.frac, min(1.0, frac))
        self.repaint()
        QApplication.processEvents()

    def finish(self, window):
        self.step(tr("Ready"), 1.0)
        end = time.monotonic() + max(0.0, self.MIN_SECONDS - (time.monotonic() - self.t0))
        while time.monotonic() < end:
            QApplication.processEvents()
            time.sleep(0.01)
        window.raise_()
        window.activateWindow()
        self.close()

    # ------------------------------------------------------------------ drawing
    def _make_background(self):
        dpr = self.devicePixelRatioF() if hasattr(self, "devicePixelRatioF") else 1.0
        pm = QPixmap(int(W * dpr), int(H * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, W, H), 10, 10)
        p.setClipPath(clip)
        g = QLinearGradient(0, 0, W, H)
        g.setColorAt(0.0, QColor(12, 16, 22))
        g.setColorAt(0.6, QColor(18, 26, 34))
        g.setColorAt(1.0, QColor(16, 40, 46))
        p.fillRect(QRectF(0, 0, W, H), g)
        for cx, cy, r, col in ((W * 0.83, H * 0.22, W * 0.55, BLUE), (W * 0.62, H * 0.95, W * 0.5, TEAL)):
            rg = QRadialGradient(QPointF(cx, cy), r)
            c0 = QColor(col)
            c0.setAlpha(60)
            c1 = QColor(col)
            c1.setAlpha(0)
            rg.setColorAt(0.0, c0)
            rg.setColorAt(1.0, c1)
            p.fillRect(QRectF(0, 0, W, H), rg)
        self._draw_traces(p)
        logo = QPixmap(os.path.join(ASSETS, "logo_256.png"))
        if not logo.isNull():
            p.drawPixmap(QRectF(58, 146, 96, 96), logo, QRectF(logo.rect()))
        f = QFont("Segoe UI")
        f.setPixelSize(56)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(245, 247, 250))
        p.drawText(QRectF(176, 144, 460, 66), Qt.AlignLeft | Qt.AlignVCenter, "Wirely")
        f2 = QFont("Segoe UI")
        f2.setPixelSize(15)
        p.setFont(f2)
        p.setPen(QColor(170, 186, 198))
        p.drawText(QRectF(180, 206, 460, 24), Qt.AlignLeft | Qt.AlignVCenter,
                   tr("Draw a circuit, press play, watch it work"))
        v = _version()
        if v:
            f3 = QFont("Segoe UI")
            f3.setPixelSize(12)
            p.setFont(f3)
            p.setPen(QColor(140, 156, 168))
            p.drawText(QRectF(24, 18, W - 48, 18), Qt.AlignRight | Qt.AlignVCenter, v)
        p.fillRect(QRectF(0, H - BAR_H, W, BAR_H), QColor(14, 19, 25))
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.drawLine(QPointF(0, H - BAR_H + 0.5), QPointF(W, H - BAR_H + 0.5))
        p.end()
        return pm

    @staticmethod
    def _draw_traces(p):
        """Faint circuit-board traces with junction dots across the right-hand side."""
        rnd = random.Random(7)
        grid = 24
        for _ in range(16):
            x = rnd.randrange(14, 30) * grid
            y = rnd.randrange(1, 14) * grid
            path = QPainterPath()
            path.moveTo(x, y)
            pts = [(x, y)]
            for _k in range(rnd.randrange(2, 5)):
                if rnd.random() < 0.5:
                    x += rnd.choice((-1, 1)) * rnd.randrange(2, 6) * grid
                else:
                    y += rnd.choice((-1, 1)) * rnd.randrange(1, 4) * grid
                x = max(10 * grid, min(W + grid, x))
                y = max(grid, min(H - BAR_H - grid, y))
                path.lineTo(x, y)
                pts.append((x, y))
            a = rnd.randrange(18, 40)
            p.setPen(QPen(QColor(120, 220, 220, a), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(120, 220, 220, a + 20))
            for px, py in (pts[0], pts[-1]):
                p.drawEllipse(QPointF(px, py), 3, 3)
        # a few glowing "current" dots
        for _ in range(5):
            x, y = rnd.randrange(14, 29) * grid, rnd.randrange(1, 13) * grid
            rg = QRadialGradient(QPointF(x, y), 9)
            rg.setColorAt(0, QColor(255, 200, 60, 150))
            rg.setColorAt(1, QColor(255, 200, 60, 0))
            p.setBrush(QBrush(rg))
            p.drawEllipse(QPointF(x, y), 9, 9)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.drawPixmap(0, 0, self._bg)
        f = QFont("Segoe UI")
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(QColor(190, 202, 212))
        p.drawText(QRectF(22, H - BAR_H, 320, BAR_H), Qt.AlignLeft | Qt.AlignVCenter, self.text)
        bx, bw, bh = W - 22 - 300, 300, 6
        by = H - BAR_H / 2 - bh / 2
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(QColor(8, 11, 15))
        p.drawRoundedRect(QRectF(bx, by, bw, bh), 3, 3)
        if self.frac > 0:
            fill = QRectF(bx, by, max(bh, bw * self.frac), bh)
            g = QLinearGradient(fill.left(), 0, fill.right(), 0)
            g.setColorAt(0, BLUE)
            g.setColorAt(0.7, TEAL)
            g.setColorAt(1, AMBER)
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(fill, 3, 3)
            gx = fill.right()
            rg = QRadialGradient(QPointF(gx - 2, by + bh / 2), 14)
            rg.setColorAt(0, QColor(255, 220, 140, 170))
            rg.setColorAt(1, QColor(255, 220, 140, 0))
            p.setBrush(rg)
            p.drawEllipse(QPointF(gx - 2, by + bh / 2), 14, 6)
        p.end()


def show_splash():
    """Create and show the splash (returns None if anything goes wrong — never stops Wirely starting)."""
    try:
        s = Splash()
        s.show()
        s.step(tr("Starting…"), 0.05)
        return s
    except Exception:       # noqa: BLE001
        return None
