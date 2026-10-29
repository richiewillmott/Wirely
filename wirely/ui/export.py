"""Exporting the circuit diagram as a picture (PNG), a drawing (SVG) or a page (PDF).

Exports always use black-on-white "paper" colours, with no grid, selection or pin markers, whatever theme
the app is in — so they print well and look right in reports and documents.
"""
from __future__ import annotations

import contextlib
import os

from PySide6.QtCore import QMarginsF, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter
from PySide6.QtSvg import QSvgGenerator

from ..i18n import tr
from . import theme

MARGIN = 30


@contextlib.contextmanager
def paper_mode(scene):
    """Temporarily switch to paper colours and hide editing marks."""
    saved = {k: getattr(theme, k) for k in theme.LIGHT}
    for k, v in theme.LIGHT.items():
        setattr(theme, k, v)
    selected = scene.selectedItems()
    for it in selected:
        it.setSelected(False)
    ghost = getattr(scene, "_ghost", None)
    if ghost is not None:
        ghost.hide()
    draft_visible = scene.draft.isVisible()
    scene.draft.hide()
    scene.exporting = True
    # draw everything afresh in paper colours, not from the pictures kept for the screen
    cached = [it for it in scene.items() if it.cacheMode() != it.CacheMode.NoCache]
    for it in cached:
        it.setCacheMode(it.CacheMode.NoCache)
    try:
        yield
    finally:
        scene.exporting = False
        for it in cached:
            it.setCacheMode(it.CacheMode.DeviceCoordinateCache)
            it.update()
        for k, v in saved.items():
            setattr(theme, k, v)
        for it in selected:
            it.setSelected(True)
        if draft_visible:
            scene.draft.show()


def diagram_rect(scene) -> QRectF:
    r = QRectF()
    for it in list(scene.comp_items.values()) + list(scene.wire_items.values()):
        r = r.united(it.sceneBoundingRect())
    if r.isEmpty():
        r = QRectF(-100, -75, 200, 150)
    return r.adjusted(-MARGIN, -MARGIN, MARGIN, MARGIN)


def render_image(scene, scale: float = 4.0) -> QImage:
    with paper_mode(scene):
        src = diagram_rect(scene)
        img = QImage(QSize(int(src.width() * scale), int(src.height() * scale)), QImage.Format_ARGB32)
        img.fill(QColor("#ffffff"))
        img.setDotsPerMeterX(int(scale * 96 / 0.0254))
        img.setDotsPerMeterY(int(scale * 96 / 0.0254))
        p = QPainter(img)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        scene.render(p, QRectF(0, 0, img.width(), img.height()), src)
        p.end()
    return img


def export_png(scene, path: str, scale: float = 4.0):
    img = render_image(scene, scale)
    if not img.save(path, "PNG"):
        raise OSError(tr("Couldn't write {path}", path=path))


def export_svg(scene, path: str, title: str = "Circuit"):
    with paper_mode(scene):
        src = diagram_rect(scene)
        gen = QSvgGenerator()
        gen.setFileName(path)
        gen.setTitle(title)
        gen.setDescription(tr("Circuit diagram drawn with Wirely"))
        gen.setSize(QSize(int(src.width()), int(src.height())))
        gen.setViewBox(QRectF(0, 0, src.width(), src.height()))
        p = QPainter(gen)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        p.fillRect(QRectF(0, 0, src.width(), src.height()), QColor("#ffffff"))
        scene.render(p, QRectF(0, 0, src.width(), src.height()), src)
        p.end()
    if not os.path.exists(path):
        raise OSError(tr("Couldn't write {path}", path=path))


def export_pdf(scene, path: str, title: str = ""):
    """One A4 page, landscape or portrait to suit the circuit, with a title at the top."""
    with paper_mode(scene):
        src = diagram_rect(scene)
        w = QPdfWriter(path)
        w.setTitle(title or "Circuit diagram")
        w.setCreator("Wirely")
        w.setResolution(300)
        orient = QPageLayout.Landscape if src.width() >= src.height() else QPageLayout.Portrait
        w.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), orient, QMarginsF(15, 15, 15, 15),
                                    QPageLayout.Millimeter))
        p = QPainter(w)
        if not p.isActive():
            raise OSError(tr("Couldn't write {path}", path=path))
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        page = QRectF(0, 0, w.width(), w.height())
        head = 0.0
        if title:
            f = QFont()
            f.setPixelSize(int(w.resolution() * 0.2))
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#1f2328"))
            head = f.pixelSize() * 2.0
            p.drawText(QRectF(0, 0, page.width(), head), Qt.AlignLeft | Qt.AlignVCenter, title)
        foot = w.resolution() * 0.18
        area = QRectF(0, head, page.width(), page.height() - head - foot)
        # never blow a tiny circuit up to fill the page: at most 1 sheet unit = 0.35 mm × 1.6
        max_scale = w.resolution() / 25.4 * 0.35 * 1.6
        s = min(area.width() / src.width(), area.height() / src.height(), max_scale)
        target = QRectF(0, 0, src.width() * s, src.height() * s)
        target.moveCenter(area.center())
        target.moveTop(area.top())
        scene.render(p, target, src)
        f = QFont()
        f.setPixelSize(int(w.resolution() * 0.09))
        p.setFont(f)
        p.setPen(QColor("#8a929c"))
        p.drawText(QRectF(0, page.height() - foot, page.width(), foot), Qt.AlignRight | Qt.AlignVCenter,
                   tr("Drawn with Wirely"))
        p.end()


def export(scene, path: str, title: str = ""):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".png":
        export_png(scene, path)
    elif ext == ".svg":
        export_svg(scene, path, title or "Circuit")
    elif ext == ".pdf":
        export_pdf(scene, path, title)
    else:
        raise ValueError(tr("Choose a .png, .svg or .pdf file name"))
