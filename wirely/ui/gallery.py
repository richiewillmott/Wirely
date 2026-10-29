"""The parts gallery down the left side: categories of parts you click or drag onto the sheet."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QDrag
from PySide6.QtWidgets import (QGridLayout, QLabel, QLineEdit, QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from ..i18n import tr
from ..model import parts as P
from . import symbols as S
from . import theme
from .scene import MIME_PART

TILE_W, TILE_H = 82, 78
ICON_W, ICON_H = 62, 40


class PartTile(QWidget):
    picked = Signal(str)

    def __init__(self, part: P.PartDef):
        super().__init__()
        self.part = part
        self.setObjectName("partTile")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedSize(TILE_W, TILE_H)
        self.setCursor(Qt.OpenHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(3, 6, 3, 3)
        lay.setSpacing(2)
        self.pic = QLabel()
        self.pic.setAlignment(Qt.AlignCenter)
        self.pic.setFixedHeight(ICON_H + 2)
        self.name = QLabel()
        self.name.setObjectName("tileName")
        self.name.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.name.setWordWrap(True)
        lay.addWidget(self.pic)
        lay.addWidget(self.name, 1)
        self._press = None
        self.retranslate()
        self.refresh()

    def retranslate(self):
        part = self.part
        self.setToolTip(f"<b>{part.tr_name}</b><br>{part.tr_description}<br><i>" +
                        tr("Click, then click on the sheet — or drag it there.") + "</i>")
        self.name.setText(part.tr_tile_name)

    def refresh(self):
        self.pic.setPixmap(S.pixmap(self.part.key, ICON_W, ICON_H, QColor(theme.INK), QColor(theme.PANEL)))

    def set_armed(self, on: bool):
        self.setProperty("armed", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if self._press is None or not (e.buttons() & Qt.LeftButton):
            return
        if (e.position().toPoint() - self._press).manhattanLength() < 6:
            return
        self._press = None
        drag = QDrag(self)
        md = QMimeData()
        md.setData(MIME_PART, QByteArray(self.part.key.encode()))
        drag.setMimeData(md)
        pm = S.pixmap(self.part.key, ICON_W, ICON_H, QColor(theme.ACCENT), QColor(theme.PANEL))
        drag.setPixmap(pm)
        drag.setHotSpot(QPoint(ICON_W // 2, ICON_H // 2))
        drag.exec(Qt.CopyAction)

    def mouseReleaseEvent(self, e):
        if self._press is not None and e.button() == Qt.LeftButton:
            self._press = None
            self.picked.emit(self.part.key)


class Category(QWidget):
    COLS = 3

    def __init__(self, name: str, parts: list, on_pick):
        super().__init__()
        self.name = name
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = QToolButton()
        self.header.setObjectName("categoryHeader")
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setArrowType(Qt.DownArrow)
        self.header.setText(tr(name).replace("&", "&&"))   # a single & would vanish on Windows
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.header.clicked.connect(self.toggle)
        lay.addWidget(self.header)
        self.body = QWidget()
        self.grid = QGridLayout(self.body)
        self.grid.setContentsMargins(8, 0, 8, 6)
        self.grid.setSpacing(2)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        lay.addWidget(self.body)
        self.tiles = []
        for part in parts:
            t = PartTile(part)
            t.picked.connect(on_pick)
            self.tiles.append(t)
        self._layout(self.tiles)
        self.open = True

    def retranslate(self):
        self.header.setText(tr(self.name).replace("&", "&&"))
        for t in self.tiles:
            t.retranslate()

    def _layout(self, tiles):
        for t in self.tiles:
            self.grid.removeWidget(t)
            t.hide()
        for i, t in enumerate(tiles):
            self.grid.addWidget(t, i // self.COLS, i % self.COLS)
            t.show()

    def toggle(self):
        self.set_open(not self.open)

    def set_open(self, on: bool):
        self.open = on
        self.body.setVisible(on)
        self.header.setArrowType(Qt.DownArrow if on else Qt.RightArrow)

    def filter(self, text: str) -> bool:
        t = text.lower().strip()
        cat = (self.name + " " + tr(self.name)).lower()
        shown = [tile for tile in self.tiles if not t or t in tile.part.search_text or t in cat]
        self._layout(shown)
        self.setVisible(bool(shown))
        if t:
            self.body.setVisible(True)
            self.header.setArrowType(Qt.DownArrow)
        else:
            self.body.setVisible(self.open)
        return bool(shown)


class Gallery(QWidget):
    picked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("leftpanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(Category.COLS * (TILE_W + 2) + 30)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = QLabel()
        self.header.setObjectName("sectionHeader")
        lay.addWidget(self.header)
        self.search = QLineEdit()
        self.search.setObjectName("filter")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.search)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 0, 8)
        v.setSpacing(0)
        self.categories = []
        for name, parts in P.by_category():
            cat = Category(name, parts, self.picked.emit)
            self.categories.append(cat)
            v.addWidget(cat)
        self.empty = QLabel()
        self.empty.setObjectName("hint")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.hide()
        v.addWidget(self.empty)
        v.addStretch(1)
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)
        self.retranslate()

    def retranslate(self):
        self.header.setText(tr("Parts"))
        self.search.setPlaceholderText(tr("Search parts (e.g. LED, 555, switch)"))
        self.empty.setText(tr("No parts match."))
        for c in self.categories:
            c.retranslate()
        self._filter(self.search.text())

    def _filter(self, text):
        any_shown = False
        for c in self.categories:
            any_shown |= c.filter(text)
        self.empty.setVisible(not any_shown)

    def tiles(self):
        return [t for c in self.categories for t in c.tiles]

    def set_armed(self, kind: str | None):
        for t in self.tiles():
            t.set_armed(t.part.key == kind)

    def refresh(self):
        for t in self.tiles():
            t.refresh()
