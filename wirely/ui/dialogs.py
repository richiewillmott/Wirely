"""Dialogs: part properties (double-click a part), bill of materials, keyboard shortcuts."""
from __future__ import annotations

import csv

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..i18n import tr
from ..model import parts as P
from ..model.circuit import Circuit, Component
from ..model.types_info import describe
from ..model.units import _NUM, fmt, has_unit_box, join, parse, split, unit_choices
from . import symbols as S
from . import theme


def _plain_number(text) -> bool:
    import re
    return re.fullmatch(_NUM, str(text).strip().replace(" ", "").replace(",", ".")) is not None


class PropertiesDialog(QDialog):
    """Change a part's reference and values. Values are typed the normal way: 10k, 4k7, 100n …"""

    def __init__(self, comp: Component, circuit: Circuit, parent=None):
        super().__init__(parent)
        self.comp, self.circuit = comp, circuit
        part = comp.part
        self.setWindowTitle(f"{comp.ref} – {part.tr_name}")
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        top = QHBoxLayout()
        pic = QLabel()
        pic.setPixmap(S.pixmap(part.key, 76, 50, QColor(theme.INK), QColor(theme.PANEL), comp.props))
        top.addWidget(pic)
        tv = QVBoxLayout()
        title = QLabel(part.tr_name)
        title.setObjectName("dialogTitle")
        hint = QLabel(part.tr_description)
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        tv.addWidget(title)
        tv.addWidget(hint)
        top.addLayout(tv, 1)
        lay.addLayout(top)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.ref = QLineEdit(comp.ref)
        self.ref.setToolTip(tr("The label on the diagram, e.g. R1"))
        form.addRow(tr("Label"), self.ref)
        self.fields = {}
        self.unit_boxes = {}
        for p in part.props:
            v = comp.value(p.key)
            if p.kind == "bool":
                w = QCheckBox()
                w.setChecked(bool(v))
            elif p.kind == "text":
                w = QPlainTextEdit(str(v))
                w.setFixedHeight(70)
                w.setTabChangesFocus(True)
            elif p.kind == "choice":
                w = QComboBox()
                for ch in p.choices:         # shown in the chosen language; the English is what gets saved
                    if p.key == "colour" and ch in S.LED_RGB:
                        pm = QPixmap(14, 14)
                        pm.fill(QColor(S.LED_RGB[ch]))
                        w.addItem(QIcon(pm), P.choice_text(ch), ch)
                    else:
                        w.addItem(P.choice_text(ch), ch)
                if w.findData(str(v)) >= 0:
                    w.setCurrentIndex(w.findData(str(v)))
                if p.key == "model":
                    for ix, ch in enumerate(p.choices):
                        if describe(ch):
                            w.setItemData(ix, describe(ch), Qt.ToolTipRole)
            elif has_unit_box(p.unit):
                # the number, with a box beside it for its size: Ω / kΩ / MΩ, pF / nF / µF …
                num, choice = split(float(v), p.unit)
                w = QLineEdit(num)
                dnum, dchoice = split(float(p.default), p.unit)
                w.setPlaceholderText(tr("e.g. {value}", value=dnum))
                w.setToolTip(p.tr_help or tr("Type the number and pick its size — or type it all, like 4k7 or 100n"))
                box = QComboBox()
                box.addItems(unit_choices(p.unit))
                box.setCurrentText(choice)
                box.setToolTip(tr("Ω, kΩ (thousand), MΩ (million) … or pF, nF, µF …"))
                w.textChanged.connect(self._validate)
                box.currentTextChanged.connect(self._validate)
                w.editingFinished.connect(lambda p=p, w=w, box=box: self._tidy(p, w, box))
                self.unit_boxes[p.key] = box
                row = QWidget()
                rl = QHBoxLayout(row)
                rl.setContentsMargins(0, 0, 0, 0)
                rl.setSpacing(6)
                rl.addWidget(w, 1)
                rl.addWidget(box)
                self.fields[p.key] = (p, w)
                form.addRow(p.tr_label, row)
                continue
            else:
                w = QLineEdit(fmt(v, p.unit))
                w.setPlaceholderText(tr("e.g. {value}", value=fmt(p.default, p.unit)))
                tip = p.tr_help or tr("Type values like 10k, 4k7, 2M2, 100n, 4.7µ")
                w.setToolTip(tip)
                w.textChanged.connect(self._validate)
            self.fields[p.key] = (p, w)
            form.addRow(p.tr_label, w)
            if p.kind == "choice" and p.key == "model":
                # what this type is good for — so you can tell why you'd pick one over another
                info = QLabel(describe(w.currentData()))
                info.setObjectName("hint")
                info.setWordWrap(True)
                info.setMinimumWidth(300)
                w.currentIndexChanged.connect(lambda i, lab=info, box=w: lab.setText(describe(box.itemData(i))))
                self.type_info = info
                form.addRow("", info)
        lay.addLayout(form)
        self.error = QLabel("")
        self.error.setObjectName("dialogError")
        self.error.setWordWrap(True)
        lay.addWidget(self.error)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton(tr("Cancel"))
        cancel.clicked.connect(self.reject)
        self.ok = QPushButton(tr("OK"))
        self.ok.setObjectName("primary")
        self.ok.setDefault(True)
        self.ok.clicked.connect(self._accept)
        btns.addWidget(cancel)
        btns.addWidget(self.ok)
        lay.addLayout(btns)
        self.values = {}

    def _tidy(self, p, w, box):
        """Someone typed the whole value (4k7, 100n): show it as a number and its size in the box instead."""
        try:
            v = join(w.text(), box.currentText(), p.unit)
        except ValueError:
            return
        num, choice = split(v, p.unit)
        if (num, choice) != (w.text().strip(), box.currentText()) and not _plain_number(w.text()):
            w.setText(num)
            box.setCurrentText(choice)

    def _read(self):
        out, problems = {}, []
        for key, (p, w) in self.fields.items():
            if p.kind == "bool":
                out[key] = w.isChecked()
            elif p.kind == "text":
                out[key] = w.toPlainText().strip() or " "
            elif p.kind == "choice":
                out[key] = w.currentData()
            else:
                try:
                    if key in self.unit_boxes:
                        v = join(w.text(), self.unit_boxes[key].currentText(), p.unit)
                    else:
                        v = parse(w.text(), p.unit)
                    if p.min is not None and v < p.min:
                        raise ValueError(tr("{label} must be at least {value}", label=p.tr_label, value=fmt(p.min, p.unit)))
                    if p.max is not None and v > p.max:
                        raise ValueError(tr("{label} can be at most {value}", label=p.tr_label, value=fmt(p.max, p.unit)))
                    out[key] = v
                    w.setProperty("invalid", "false")
                except ValueError as e:
                    problems.append(str(e))
                    w.setProperty("invalid", "true")
                w.style().unpolish(w)
                w.style().polish(w)
        ref = self.ref.text().strip()
        if not ref:
            problems.append(tr("The label can't be empty"))
        elif any(c.ref == ref and c.id != self.comp.id for c in self.circuit.components.values()):
            problems.append(tr("Another part is already called {ref}", ref=ref))
        return out, ref, problems

    def _validate(self):
        _out, _ref, problems = self._read()
        self.error.setText(problems[0] if problems else "")
        self.ok.setEnabled(not problems)

    def _accept(self):
        out, ref, problems = self._read()
        if problems:
            self.error.setText(problems[0])
            return
        self.values, self.new_ref = out, ref
        self.accept()


class BomDialog(QDialog):
    def __init__(self, circuit: Circuit, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Bill of materials"))
        self.resize(560, 420)
        self.rows = circuit.bill_of_materials()
        lay = QVBoxLayout(self)
        title = QLabel(tr("Parts list — {n} parts", n=sum(r["qty"] for r in self.rows)))
        title.setObjectName("dialogTitle")
        lay.addWidget(title)
        t = QTableWidget(len(self.rows), 3)
        t.setHorizontalHeaderLabels([tr("Qty"), tr("Part"), tr("Labels")])
        t.verticalHeader().hide()
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        for i, r in enumerate(self.rows):
            q = QTableWidgetItem(str(r["qty"]))
            q.setTextAlignment(Qt.AlignCenter)
            t.setItem(i, 0, q)
            t.setItem(i, 1, QTableWidgetItem(r["description"]))
            t.setItem(i, 2, QTableWidgetItem(", ".join(r["refs"])))
        lay.addWidget(t, 1)
        btns = QHBoxLayout()
        copy = QPushButton(tr("Copy"))
        copy.clicked.connect(self._copy)
        save = QPushButton(tr("Save as CSV…"))
        save.clicked.connect(self._save)
        close = QPushButton(tr("Close"))
        close.setObjectName("primary")
        close.clicked.connect(self.accept)
        btns.addWidget(copy)
        btns.addWidget(save)
        btns.addStretch(1)
        btns.addWidget(close)
        lay.addLayout(btns)

    def _copy(self):
        text = f"{tr('Qty')}\t{tr('Part')}\t{tr('Labels')}\n" + "\n".join(f"{r['qty']}\t{r['description']}\t{', '.join(r['refs'])}"
                                                   for r in self.rows)
        QApplication.clipboard().setText(text)

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("Save parts list"), "parts list.csv", tr("CSV files") + " (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow([tr("Qty"), tr("Part"), tr("Labels")])
            for r in self.rows:
                w.writerow([r["qty"], r["description"], " ".join(r["refs"])])


SHORTCUTS = [
    ("Place a part", "Click it in the gallery, then click on the sheet (or drag it across)"),
    ("Draw a wire", "Drag from one pin to another — or click a pin, click corners, click the end pin"),
    ("Branch off a wire", "W (wire tool), then press on the wire"),
    ("Move a wire", "Drag the wire sideways; drag a loose end to reconnect it"),
    ("Change a value", "Double-click the part (or select it and press Enter)"),
    ("Rotate / flip", "R  /  Shift+R  /  F"),
    ("Delete", "Delete or Backspace"),
    ("Copy / paste / duplicate", "Ctrl+C  /  Ctrl+V  /  Ctrl+D"),
    ("Undo / redo", "Ctrl+Z  /  Ctrl+Y"),
    ("Run / pause / stop", "F5  /  F6  /  Shift+F5 (or the buttons in the middle of the toolbar)"),
    ("While running", "Click switches, hold push switches, drag the sliders, hover to read voltages"),
    ("Graph (oscilloscope)", "Put graph probes (A–D) on wires, press Play; Ctrl+G shows / hides the graph"),
    ("Readings", "While running, the Readings button shows the voltage and current on every wire and part — "
                 "or click any wire or part to pin just its reading (click again to unpin). Drag a reading to "
                 "move it out of the way"),
    ("Logic probe", "Touch it on a wire: H = high, L = low"),
    ("Sound", "Buzzers, speakers, motors and relays make sound while running — the speaker button turns it off"),
    ("Right-click", "A menu for whatever's under the mouse (rotate, delete, properties …)"),
    ("Notes", "Add a Text note (Labels) to explain your circuit; double-click to edit it"),
    ("Zoom", "Mouse wheel, or + and −;  Fit everything: Ctrl+0"),
    ("Pan", "Middle-drag, or hold Space and drag"),
    ("Stop what you're doing", "Esc (or right-click)"),
]


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("How to use Wirely"))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 14)
        title = QLabel(tr("Mouse and keyboard"))
        title.setObjectName("dialogTitle")
        lay.addWidget(title)
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(7)
        for a, b in SHORTCUTS:
            l = QLabel(f"<b>{tr(a)}</b>")
            r = QLabel(tr(b))
            r.setWordWrap(True)
            form.addRow(l, r)
        w = QWidget()
        w.setLayout(form)
        lay.addWidget(w)
        ok = QPushButton(tr("Close"))
        ok.setObjectName("primary")
        ok.clicked.connect(self.accept)
        h = QHBoxLayout()
        h.addStretch(1)
        h.addWidget(ok)
        lay.addLayout(h)
