"""The Wirely main window: top bar with menus, toolbar, parts gallery, circuit sheet and status bar."""
from __future__ import annotations

import glob
import os

from PySide6.QtCore import QMimeData, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QUndoCommand, QUndoStack
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu,
                               QMessageBox, QSplitter, QToolButton, QVBoxLayout, QWidget)

from .. import APP_NAME, REVISION, __version__, i18n
from ..i18n import tr, trn
from ..model.circuit import FILE_EXT, Circuit
from . import export as EX
from . import icons, lang, theme
from . import symbols as S
from .dialogs import BomDialog, PropertiesDialog, ShortcutsDialog
from .gallery import Gallery
from .graph import GraphPanel
from .scene import MIME_CLIP, CircuitScene
from .simcontrol import SPEEDS, SimController
from .sound import SoundPlayer
from .view import CircuitView

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EXAMPLES = os.path.join(ROOT, "examples")


def file_filter():
    return tr("Wirely circuits") + f" (*{FILE_EXT} *.spark)"


class Snapshot(QUndoCommand):
    """One undo step: the whole circuit before and after (circuits are small, so this is simple and safe)."""

    def __init__(self, win, before, after, label):
        super().__init__(label)
        self.win, self.before, self.after = win, before, after
        self._first = True

    def redo(self):
        if self._first:
            self._first = False
            return
        self.win._restore(self.after)

    def undo(self):
        self.win._restore(self.before)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("Wirely", "Wirely")
        theme.apply(self.settings.value("theme", "light"))
        S.set_style(self.settings.value("symbols", "uk"))
        QApplication.instance().setStyleSheet(theme.stylesheet())
        self.setWindowIcon(icons.app_icon())
        self.path = None
        self.circuit = Circuit()
        self.scene = CircuitScene(self.circuit)
        self.undo = QUndoStack(self)
        self._last = self.circuit.to_dict()
        self._paste_n = 0
        self._tool_buttons = {}
        self._action_src = {}       # action -> (English text, English tip, shortcut), so it can be re-shown
        self._menu_buttons = []     # (button, English menu name)
        self._build_ui()
        self.scene.edited.connect(self._on_edited)
        self.scene.editRequested.connect(self.edit_part)
        self.scene.status.connect(self._hint)
        self.scene.modeChanged.connect(self._on_mode)
        self.scene.selectionChanged.connect(self._update_actions)
        self.undo.cleanChanged.connect(self._update_title)
        self.undo.indexChanged.connect(self._on_undo_index)
        self.scene.show_grid = self.settings.value("grid", "true") == "true"
        self.resize(1360, 840)
        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        self._update_title()
        self._update_actions()
        self._update_counts()
        self.simc = SimController(self)
        self.sound = SoundPlayer(self)
        self.sound.enabled = self.a_sound.isChecked()
        self.sound.availabilityChanged.connect(self._sound_availability)
        self._sound_availability(self.sound.available())
        self.simc.sound = self.sound
        self.scene.attach_sim(self.simc)
        self.scene.show_volts = self.a_volts.isChecked()
        self.scene.show_flow = self.a_flow.isChecked()
        self.scene.show_readings = self.a_readings.isChecked()
        self.simc.stateChanged.connect(self._on_sim_state)
        self.simc.frame.connect(self._on_sim_frame)
        self.simc.message.connect(self._on_sim_message)
        self._on_sim_state("stopped")
        QTimer.singleShot(0, lambda: self._fit_contents(animate=False))
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(60_000)
        self._autosave_timer.timeout.connect(self.autosave)
        self._autosave_timer.start()

    # ================================================================== layout
    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self._make_actions()
        v.addWidget(self._build_topbar())
        v.addWidget(self._build_toolbar())
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self.gallery = Gallery()
        self.gallery.picked.connect(self._pick_part)
        body.addWidget(self.gallery)
        self.view = CircuitView(self.scene)
        self.view.zoomChanged.connect(lambda z: self.zoom_label.setText(f"{z / 1.6 * 100:.0f}%"))
        self.split = QSplitter(Qt.Vertical)
        self.split.setHandleWidth(1)
        self.split.addWidget(self.view)
        self.graph = GraphPanel()
        self.graph.closed.connect(lambda: self.show_graph(False))
        self.split.addWidget(self.graph)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 1)
        self.graph.hide()
        body.addWidget(self.split, 1)
        self.view.menu_provider = self._context_menu
        v.addLayout(body, 1)
        self.setCentralWidget(central)
        sb = self.statusBar()
        self.hint = QLabel("")
        sb.addWidget(self.hint, 1)
        self.count_label = QLabel("")
        self.zoom_label = QLabel("100%")
        sb.addPermanentWidget(self.count_label)
        sb.addPermanentWidget(self.zoom_label)
        self._hint("")

    def _act(self, text, slot, shortcut=None, icon=None, tip=None, checkable=False):
        a = QAction(self)
        if shortcut:
            a.setShortcuts([QKeySequence(s) for s in (shortcut if isinstance(shortcut, (list, tuple))
                                                      else [shortcut])])
        if icon:
            a.setIcon(icons.icon(icon))
            a.setData(icon)
        a.setCheckable(checkable)
        self._action_src[a] = (text, tip, shortcut)
        self._retr_action(a)
        a.triggered.connect(slot)
        self.addAction(a)
        return a

    def _retr_action(self, a):
        """(Re)write an action's name and tooltip in the current language."""
        text, tip, shortcut = self._action_src[a]
        a.setText(tr(text))
        tip = tr(tip) if tip else a.text().replace("…", "").replace("&", "")
        if shortcut:
            first = shortcut[0] if isinstance(shortcut, (list, tuple)) else shortcut
            tip += f"  ({QKeySequence(first).toString(QKeySequence.NativeText)})"
        a.setToolTip(tip)

    def _make_actions(self):
        A = self._act
        self.a_new = A("New circuit", self.new_file, "Ctrl+N", "new")
        self.a_open = A("Open…", self.open_file, "Ctrl+O", "open")
        self.a_save = A("Save", self.save, "Ctrl+S", "save")
        self.a_save_as = A("Save as…", self.save_as, "Ctrl+Shift+S")
        self.a_export = A("Export diagram…", self.export_diagram, "Ctrl+E", "export",
                          "Export the circuit diagram as PNG, SVG or PDF")
        self.a_bom = A("Bill of materials…", self.show_bom, None, "bom", "Parts list for this circuit")
        self.a_quit = A("Quit", self.close, "Ctrl+Q")
        self.a_undo = A("Undo", self.undo.undo, "Ctrl+Z", "undo")
        self.a_redo = A("Redo", self.undo.redo, ["Ctrl+Y", "Ctrl+Shift+Z"], "redo")
        self.a_cut = A("Cut", self.cut, "Ctrl+X")
        self.a_copy = A("Copy", self.copy, "Ctrl+C")
        self.a_paste = A("Paste", self.paste, "Ctrl+V")
        self.a_dup = A("Duplicate", self.duplicate, "Ctrl+D")
        self.a_copy_pic = A("Copy diagram as picture", self.copy_picture, "Ctrl+Shift+C",
                            tip="Copy the diagram so you can paste it into Word, PowerPoint …")
        self.a_delete = A("Delete", self.delete, ["Delete", "Backspace"], "delete")
        self.a_select_all = A("Select all", self.scene.select_all, "Ctrl+A")
        self.a_rotate = A("Rotate", lambda: self.scene.rotate_selected(True), "R", "rotate", "Rotate clockwise")
        self.a_rotate_ccw = A("Rotate anticlockwise", lambda: self.scene.rotate_selected(False), "Shift+R",
                              "rotate_ccw")
        self.a_flip = A("Flip", self.scene.flip_selected, "F", "flip", "Flip left-to-right")
        self.a_props = A("Properties…", self.edit_selected, ["Return", "Enter"], None, "Change the part's values")
        self.a_select = A("Select", lambda: self.scene.set_mode("select"), None, "select",
                          "Select and move  (Esc)", checkable=True)
        self.a_wire = A("Wire", lambda: self.scene.set_mode("wire"), "W", "wire",
                        "Draw wires — also branch off existing wires", checkable=True)
        self.a_select.setChecked(True)
        self.a_zoom_in = A("Zoom in", lambda: self.view.zoom_by(1.25), ["Ctrl+=", "+", "="], "zoom_in")
        self.a_zoom_out = A("Zoom out", lambda: self.view.zoom_by(0.8), ["Ctrl+-", "-"], "zoom_out")
        self.a_fit = A("Zoom to fit", self.zoom_fit, "Ctrl+0", "zoom_fit", "Show the whole circuit")
        self.a_grid = A("Show grid", self.toggle_grid, "G", "grid", checkable=True)
        self.a_dark = A("Dark theme", self.toggle_theme, None, "theme", "Switch between light and dark",
                        checkable=True)
        self.a_dark.setChecked(theme.MODE == "dark")
        self.a_us = A("US symbols", self.toggle_symbols, None, None,
                      "Draw parts the American way (zigzag resistors) instead of the British way", checkable=True)
        self.a_us.setChecked(S.STYLE == "us")
        self.a_help = A("Mouse and keyboard…", lambda: ShortcutsDialog(self).exec(), "F1")
        self.a_about = A("About Wirely", self.about)
        self.a_play = A("Run", self.sim_run, "F5", "play", "Run the circuit — watch it work")
        self.a_pause = A("Pause", self.sim_pause, "F6", "pause", "Pause the simulation")
        self.a_stop = A("Stop", self.sim_stop, ["Shift+F5", "F7"], "stop", "Stop and go back to editing")
        self.a_volts = A("Voltage colours", self._toggle_volts, None, "volts",
                         "Colour the wires by voltage while running", checkable=True)
        self.a_readings = A("Readings", self._toggle_readings, None, "readings",
                            "Show the voltage and current on every wire and part while running — or click one "
                            "wire or part to pin just its reading", checkable=True)
        self.a_copy_readings = A("Copy readings", self.copy_readings, None, None,
                                 "Copy every part's voltage, current and power as a table — paste it into a "
                                 "spreadsheet or your write-up")
        self.a_copy_readings.setEnabled(False)
        self.a_flow = A("Current flow", self._toggle_flow, None, "flow",
                        "Show current flowing along the wires while running", checkable=True)
        self.a_sound = A("Sound", self._toggle_sound, None, "sound", "Buzzers, speakers, motors and relays make "
                         "sound while running", checkable=True)
        self.a_sound.setChecked(self.settings.value("sound", "true") == "true")
        self.a_graph = A("Graph", self._graph_toggled, "Ctrl+G", "graph",
                         "Show the graph of the voltages at the graph probes", checkable=True)
        self.a_volts.setChecked(self.settings.value("volts", "true") == "true")
        self.a_flow.setChecked(self.settings.value("flow", "true") == "true")
        self.a_readings.setChecked(self.settings.value("readings", "false") == "true")
        # one checkable entry per language, each in its own language so it can always be found again
        self.lang_group = QActionGroup(self)
        self.lang_group.setExclusive(True)
        self.lang_actions = {}
        for code, native in i18n.LANGUAGES:
            la = QAction(native, self)
            la.setCheckable(True)
            la.setChecked(code == i18n.language())
            la.triggered.connect(lambda _checked=False, c=code: self.set_language(c))
            self.lang_group.addAction(la)
            self.lang_actions[code] = la

    def _tool(self, action, text_beside=False):
        b = QToolButton()
        b.setDefaultAction(action)
        b.setIconSize(QSize(22, 22))
        b.setAutoRaise(True)
        if text_beside:
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._tool_buttons[action] = b
        return b

    @staticmethod
    def _sep():
        f = QFrame()
        f.setObjectName("sep")
        f.setFixedHeight(28)
        return f

    def _build_topbar(self):
        bar = QWidget()
        bar.setObjectName("topbar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 6, 12, 6)
        h.setSpacing(4)
        self.logo_pic = QLabel()
        self.logo_pic.setPixmap(icons.logo_pixmap(26))
        h.addWidget(self.logo_pic)
        logo = QLabel("wirely")
        logo.setObjectName("logo")
        h.addWidget(logo)
        h.addSpacing(18)
        self.menus = {}
        for name, acts in (
            ("File", [self.a_new, self.a_open, "recent", "examples", None, self.a_save, self.a_save_as, None,
                      self.a_export, self.a_copy_pic, self.a_bom, None, self.a_quit]),
            ("Edit", [self.a_undo, self.a_redo, None, self.a_cut, self.a_copy, self.a_paste, self.a_dup,
                      self.a_delete, self.a_select_all, None, self.a_rotate, self.a_rotate_ccw, self.a_flip,
                      None, self.a_props]),
            ("Simulate", [self.a_play, self.a_pause, self.a_stop, None, self.a_volts, self.a_flow, self.a_readings, self.a_copy_readings,
                          self.a_graph, self.a_sound]),
            ("View", [self.a_zoom_in, self.a_zoom_out, self.a_fit, None, self.a_grid, self.a_dark, self.a_us]),
            ("Language", list(self.lang_actions.values())),
            ("Help", [self.a_help, self.a_about]),
        ):
            m = QMenu(self)
            for a in acts:
                if a is None:
                    m.addSeparator()
                elif a == "examples":
                    self.examples_menu = m.addMenu(tr("Open example"))
                    self._fill_examples()
                elif a == "recent":
                    self.recent_menu = m.addMenu(tr("Open recent"))
                    self.recent_menu.aboutToShow.connect(self._fill_recent)
                else:
                    m.addAction(a)
            b = QToolButton()
            b.setObjectName("menuButton")
            b.setText(tr(name))
            self._menu_buttons.append((b, name))
            b.setMenu(m)
            b.setPopupMode(QToolButton.InstantPopup)
            h.addWidget(b)
            self.menus[name] = m
        h.addSpacing(18)
        self.docname = QLabel(tr("Untitled"))
        self.docname.setObjectName("docname")
        h.addWidget(self.docname)
        h.addStretch(1)
        self.tip_label = QLabel(tr("Wheel: zoom · Middle-drag: pan · Double-click a part to change it"))
        self.tip_label.setObjectName("muted")
        h.addWidget(self.tip_label)
        return bar

    def _build_toolbar(self):
        bar = QWidget()
        bar.setObjectName("toolbar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 3, 8, 3)
        h.setSpacing(2)
        T = self._tool
        for a in (self.a_new, self.a_open, self.a_save):
            h.addWidget(T(a))
        h.addWidget(self._sep())
        for a in (self.a_undo, self.a_redo):
            h.addWidget(T(a))
        h.addWidget(self._sep())
        h.addWidget(T(self.a_select))
        h.addWidget(T(self.a_wire))
        h.addWidget(self._sep())
        for a in (self.a_rotate, self.a_flip, self.a_delete):
            h.addWidget(T(a))
        h.addStretch(1)
        # simulation controls in the middle
        sim = QWidget()
        sh = QHBoxLayout(sim)
        sh.setContentsMargins(0, 0, 0, 0)
        sh.setSpacing(2)
        for a in (self.a_play, self.a_pause, self.a_stop):
            sh.addWidget(T(a))
        sh.addSpacing(6)
        self.speed_box = QComboBox()
        self.speed_box.setToolTip(tr("Simulation speed"))
        for name, _v in SPEEDS:
            self.speed_box.addItem(tr(name))
        self.speed_box.setCurrentIndex([n for n, _v in SPEEDS].index("Real time"))
        self.speed_box.currentIndexChanged.connect(lambda i: self.simc.set_speed(SPEEDS[i][1]))
        sh.addWidget(self.speed_box)
        self.time_label = QLabel("")
        self.time_label.setObjectName("muted")
        self.time_label.setMinimumWidth(92)
        sh.addWidget(self.time_label)
        sh.addWidget(self._sep())
        sh.addWidget(T(self.a_volts))
        sh.addWidget(T(self.a_flow))
        sh.addWidget(T(self.a_readings))
        sh.addWidget(T(self.a_graph))
        sh.addWidget(T(self.a_sound))
        h.addWidget(sim)
        h.addStretch(1)
        for a in (self.a_zoom_out, self.a_zoom_in, self.a_fit):
            h.addWidget(T(a))
        h.addWidget(self._sep())
        h.addWidget(T(self.a_bom))
        h.addWidget(T(self.a_export))
        h.addWidget(T(self.a_dark))
        return bar

    # ================================================================== undo / state
    def _on_edited(self, label):
        now = self.circuit.to_dict()
        if now != self._last:
            self.undo.push(Snapshot(self, self._last, now, label))
            self._last = now
        self._update_counts()
        self._update_actions()

    def _restore(self, data):
        self.scene.cancel()
        self.circuit.load_dict(data)
        self._last = self.circuit.to_dict()
        self.scene.rebuild()
        self._update_counts()

    def _update_title(self, *_):
        name = os.path.splitext(os.path.basename(self.path))[0] if self.path else tr("Untitled")
        dirty = not self.undo.isClean()
        self.docname.setText(name + ("  •" if dirty else ""))
        self.setWindowTitle(f"{name}{' *' if dirty else ''} – {APP_NAME}")

    def _update_actions(self):
        try:
            comps, wires = self.scene.selected_ids()
        except RuntimeError:        # the window is closing
            return
        has = bool(comps or wires)
        running = hasattr(self, "simc") and self.simc.active()
        for a in (self.a_delete, self.a_cut, self.a_dup):
            a.setEnabled(has and not running)
        self.a_copy.setEnabled(has)
        for a in (self.a_rotate, self.a_rotate_ccw, self.a_flip):
            a.setEnabled((bool(comps) or self.scene.mode == "place") and not running)
        for a in (self.a_paste, self.a_select_all, self.a_select, self.a_wire, self.a_new, self.a_open):
            a.setEnabled(not running)
        self.a_props.setEnabled(len(comps) == 1)
        self.a_undo.setEnabled(self.undo.canUndo() and not running)
        self.a_redo.setEnabled(self.undo.canRedo() and not running)
        self.a_undo.setToolTip(tr("Undo {what}", what=self.undo.undoText()) + "  (Ctrl+Z)" if self.undo.canUndo()
                               else tr("Undo"))
        self.a_redo.setToolTip(tr("Redo {what}", what=self.undo.redoText()) + "  (Ctrl+Y)" if self.undo.canRedo()
                               else tr("Redo"))

    def _on_undo_index(self, _i):
        self._update_actions()
        self._update_counts()

    def _update_counts(self):
        n, w = len(self.circuit.components), len(self.circuit.wires)
        self.count_label.setText(trn("{n} part", "{n} parts", n) + " · " + trn("{n} wire", "{n} wires", w))

    def _hint(self, text):
        self.hint.setText(text or tr("Pick a part from the gallery, or drag from a pin to draw a wire."))

    def _on_mode(self, mode):
        self.a_select.setChecked(mode != "wire")
        self.a_wire.setChecked(mode == "wire")
        self.gallery.set_armed(self.scene._place_kind if mode == "place" else None)
        self._update_actions()

    def _pick_part(self, kind):
        if self.simc.active():
            self.view.toast(tr("Press Stop to go back to editing, then add the part."), "info")
            return
        self.scene.start_placing(kind, keep=bool(QApplication.keyboardModifiers() & Qt.ShiftModifier))
        self.view.setFocus()

    # ================================================================== files
    def _confirm_discard(self) -> bool:
        if self.undo.isClean():
            return True
        r = QMessageBox.question(self, APP_NAME, tr("Save changes to this circuit first?"),
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def _set_circuit(self, circuit, path):
        self.graph.clear()
        if not any(c.kind == "scope_probe" for c in circuit.components.values()):
            self.show_graph(False)
        self.circuit = circuit
        self.scene.set_circuit(circuit)
        self.path = path
        self._last = circuit.to_dict()
        self.undo.clear()
        self.undo.setClean()
        self._update_title()
        self._update_counts()
        self._fit_contents(animate=False)
        QTimer.singleShot(0, lambda: self._fit_contents(animate=False))   # again once the window has its size

    def new_file(self):
        self.sim_stop()
        if self._confirm_discard():
            self._set_circuit(Circuit(), None)

    def open_file(self, path=None):
        self.sim_stop()
        if not path:
            if not self._confirm_discard():
                return
            path, _ = QFileDialog.getOpenFileName(self, tr("Open circuit"), self.settings.value("dir", ""), file_filter())
            if not path:
                return
        try:
            c = Circuit.load(path)
        except Exception as e:      # noqa: BLE001 - show any problem to the user
            QMessageBox.warning(self, APP_NAME, tr("Couldn't open {name}:", name=os.path.basename(path)) + f"\n{e}")
            return
        self._set_circuit(c, path)
        self._add_recent(path)

    def save(self) -> bool:
        if not self.path or self.path.startswith(EXAMPLES):
            return self.save_as()
        try:
            self.circuit.save(self.path)
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, tr("Couldn't save:") + f"\n{e}")
            return False
        self.undo.setClean()
        self._update_title()
        self.clear_autosave()
        self.statusBar().showMessage(tr("Saved {name}", name=os.path.basename(self.path)), 3000)
        return True

    def save_as(self) -> bool:
        start = os.path.join(self.settings.value("dir", ""), self.docname.text().strip(" •") + FILE_EXT)
        path, _ = QFileDialog.getSaveFileName(self, tr("Save circuit"), start, file_filter())
        if not path:
            return False
        if not path.lower().endswith(FILE_EXT):
            path += FILE_EXT
        self.path = path
        self.settings.setValue("dir", os.path.dirname(path))
        self._add_recent(path)
        return self.save()

    def _add_recent(self, path):
        if path.startswith(EXAMPLES):
            return
        rec = [p for p in (self.settings.value("recent") or []) if p != path]
        self.settings.setValue("recent", [path] + rec[:7])

    def _fill_recent(self):
        self.recent_menu.clear()
        rec = [p for p in (self.settings.value("recent") or []) if os.path.exists(p)]
        if not rec:
            self.recent_menu.addAction(tr("(nothing yet)")).setEnabled(False)
        for p in rec:
            self.recent_menu.addAction(os.path.basename(p), lambda p=p: self._open_checked(p))

    def _open_checked(self, path):
        if self._confirm_discard():
            self.open_file(path)

    def _fill_examples(self):
        self.examples_menu.clear()
        for p in sorted(glob.glob(os.path.join(EXAMPLES, "*" + FILE_EXT))):
            name = os.path.splitext(os.path.basename(p))[0]
            self.examples_menu.addAction(tr(name), lambda p=p: self._open_checked(p))

    # ================================================================== export
    def _title_for_export(self):
        return self.docname.text().strip(" •")

    def export_diagram(self):
        if self.circuit.is_empty():
            QMessageBox.information(self, APP_NAME, tr("There's nothing to export yet — add some parts first."))
            return
        last = self.settings.value("export_ext", ".png")
        start = os.path.join(self.settings.value("dir", ""), self._title_for_export() + last)
        kinds = {".png": tr("PNG picture") + " (*.png)", ".svg": tr("SVG drawing") + " (*.svg)",
                 ".pdf": tr("PDF page") + " (*.pdf)"}
        path, chosen = QFileDialog.getSaveFileName(self, tr("Export circuit diagram"), start, ";;".join(kinds.values()),
                                                   kinds.get(last, kinds[".png"]))
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in (".png", ".svg", ".pdf"):
            ext = next((e for e, k in kinds.items() if k == chosen), ".png")
            path += ext
        try:
            EX.export(self.scene, path, self._title_for_export())
        except Exception as e:      # noqa: BLE001
            QMessageBox.warning(self, APP_NAME, tr("Couldn't export:") + f"\n{e}")
            return
        self.settings.setValue("export_ext", ext)
        self.statusBar().showMessage(tr("Exported {name}", name=os.path.basename(path)), 4000)

    def copy_picture(self):
        if self.circuit.is_empty():
            return
        QApplication.clipboard().setImage(EX.render_image(self.scene, 3.0))
        self.statusBar().showMessage(tr("Diagram copied — paste it into your document"), 3000)

    def show_bom(self):
        BomDialog(self.circuit, self).exec()

    # ================================================================== editing
    def edit_part(self, cid):
        comp = self.circuit.components.get(cid)
        if not comp:
            return
        dlg = PropertiesDialog(comp, self.circuit, self)
        if dlg.exec():
            if self.simc.active():          # change it live: the circuit carries on running
                for k, v in dlg.values.items():
                    if comp.value(k) != v:
                        self.simc.set_value(cid, k, v)
                comp.ref = dlg.new_ref
                self.scene.sync_component(cid)
                self._sim_dirty = True
            else:
                self.scene.update_component(cid, dlg.values, dlg.new_ref)

    def _context_menu(self, pos):
        """What a right-click offers: depends on what's under the mouse and whether the circuit is running."""
        from .items import ComponentItem, WireItem
        item = self.scene.item_at(pos)
        m = QMenu(self)
        running = self.simc.active()
        if isinstance(item, ComponentItem):
            if not item.isSelected():
                self.scene.clearSelection()
                item.setSelected(True)
            m.addAction(self.a_props)
            if not running:
                m.addSeparator()
                for a in (self.a_rotate, self.a_rotate_ccw, self.a_flip, None, self.a_dup, self.a_copy, self.a_cut,
                          self.a_delete):
                    m.addSeparator() if a is None else m.addAction(a)
        elif isinstance(item, WireItem) and not running:
            if not item.isSelected():
                self.scene.clearSelection()
                item.setSelected(True)
            m.addAction(self.a_delete)
        elif not running:
            m.addAction(self.a_paste)
            m.addAction(self.a_select_all)
            m.addSeparator()
            m.addAction(self.a_fit)
        else:
            m.addAction(self.a_pause if self.simc.state == "running" else self.a_play)
            m.addAction(self.a_stop)
        self._update_actions()
        return m

    # ================================================================== autosave
    def _autosave_paths(self):
        from PySide6.QtCore import QStandardPaths
        d = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation) or os.path.expanduser("~/.wirely")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "autosave" + FILE_EXT), os.path.join(d, "autosave.json")

    def autosave(self):
        """Every minute, keep a copy of unsaved work in case the computer or program crashes."""
        if self.undo.isClean() or self.circuit.is_empty():
            return
        try:
            data, meta = self._autosave_paths()
            self.circuit.save(data)
            import json
            with open(meta, "w", encoding="utf-8") as fh:
                json.dump({"path": self.path or ""}, fh)
        except OSError:
            pass

    def clear_autosave(self):
        for p in self._autosave_paths():
            try:
                os.remove(p)
            except OSError:
                pass

    def offer_recovery(self):
        """At start-up: if Wirely didn't close properly last time, offer the unsaved circuit back."""
        data, meta = self._autosave_paths()
        if not os.path.exists(data):
            return False
        r = QMessageBox.question(self, APP_NAME, tr("Wirely didn't close properly last time.") + "\n" +
                                 tr("Do you want to get back the circuit you hadn't saved?"),
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if r == QMessageBox.Yes:
            try:
                import json
                c = Circuit.load(data)
                with open(meta, encoding="utf-8") as fh:
                    path = json.load(fh).get("path") or None
                self._set_circuit(c, path)
                self.undo.resetClean()             # not saved yet: show it as changed
                self._update_title()
                return True
            except (OSError, ValueError):
                pass
        self.clear_autosave()
        return False

    # ================================================================== simulation
    def sim_run(self):
        if self.simc.state == "paused":
            self.simc.resume()
            return
        if self.simc.state == "running":
            self.simc.pause()           # F5 toggles
            return
        if self.circuit.is_empty():
            self.view.toast(tr("Add some parts and wire them up first — then press Play."), "info")
            return
        self.scene.cancel()
        self.scene.set_mode("select")
        self.view.clear_toasts()
        probes = [c for c in self.circuit.components.values() if c.kind == "scope_probe"]
        self.graph.clear()
        self.show_graph(bool(probes) or (self.graph.isVisible() and self.a_graph.isChecked() and
                                         getattr(self, "_graph_by_hand", False)))
        try:
            self.simc.start(self.circuit)
        except Exception as e:      # noqa: BLE001 - never crash the editor because of a bad circuit
            self.simc.stop()
            QMessageBox.warning(self, APP_NAME, tr("The simulation couldn't start:") + f"\n{e}")

    def sim_pause(self):
        self.simc.pause()

    def sim_stop(self):
        if self.simc.active():
            self.simc.stop()

    def _on_sim_state(self, state):
        running = state == "running"
        noisy = any(c.kind in ("buzzer", "speaker", "motor", "relay", "relay_dpdt", "solenoid")
                    for c in self.circuit.components.values())
        if running and noisy:
            self.sound.start()
        elif state == "stopped":
            self.sound.stop()
        self.a_play.setEnabled(state != "running")
        self._play_tip(state)
        self.a_pause.setEnabled(running)
        self.a_stop.setEnabled(state != "stopped")
        self.a_copy_readings.setEnabled(state != "stopped")
        self.gallery.setEnabled(state == "stopped")
        self._update_actions()
        if state == "stopped":
            self.time_label.setText("")
            self.view.clear_toasts()
            # switch positions and slider settings changed while running are kept, without an undo step
            if getattr(self, "_sim_dirty", False) or self.circuit.to_dict() != self._last:
                self._last = self.circuit.to_dict()
            self._sim_dirty = False
            self.scene.refresh_connections()
            self._hint("")
        else:
            self._state_hint(state)
        self.scene.update()

    def _play_tip(self, state):
        self.a_play.setToolTip(tr("Resume") + "  (F5)" if state == "paused"
                               else tr("Run the circuit — watch it work") + "  (F5)")

    def _state_hint(self, state):
        self._hint(tr("Running — click switches, drag sliders, hover over wires to read voltages.")
                   if state == "running" else tr("Paused — press Play to carry on, or Stop to edit."))

    def _graph_toggled(self):
        self._graph_by_hand = self.a_graph.isChecked()
        self.show_graph(self.a_graph.isChecked())

    def show_graph(self, on: bool):
        self.graph.setVisible(on)
        self.a_graph.setChecked(on)
        if on and self.split.sizes()[1] < 120:
            total = sum(self.split.sizes())
            self.split.setSizes([int(total * 0.68), int(total * 0.32)])

    def _on_sim_frame(self):
        if not self.simc.active():
            return
        if self.simc.live.samples:
            self.graph.add_samples(self.simc.live.samples, self.simc.live.t)
        t = self.simc.live.t
        txt = f"t = {t:.2f} s" if t < 100 else f"t = {t:.0f} s"
        if self.simc.behind and self.simc.state == "running":
            txt += "  · " + tr("slowed")
            self.time_label.setToolTip(tr("This circuit is too busy to simulate in real time, so it runs slower."))
        else:
            self.time_label.setToolTip(tr("Simulated time since you pressed Play"))
        self.time_label.setText(txt)

    def _on_sim_message(self, cid, text):
        # a part that has broken is an error; a warning is something that can still be put right
        self.view.toast(text, "error" if self.simc.is_broken(cid) else "warn")

    def _toggle_volts(self):
        self.scene.show_volts = self.a_volts.isChecked()
        self.settings.setValue("volts", "true" if self.scene.show_volts else "false")
        self.scene.repaint_all()
        self.view.viewport().update()

    def _toggle_sound(self):
        on = self.a_sound.isChecked()
        self.settings.setValue("sound", "true" if on else "false")
        self.sound.set_enabled(on)

    def _sound_availability(self, ok):
        if not ok:
            self.a_sound.setEnabled(False)
            self.a_sound.setToolTip(tr("No working sound output was found on this computer"))

    def copy_readings(self):
        text = self.scene.readings_text()
        if text:
            QApplication.clipboard().setText(text)
            self.statusBar().showMessage(tr("Readings copied — paste them into a spreadsheet or document"), 4000)

    def _toggle_readings(self):
        self.scene.show_readings = self.a_readings.isChecked()
        self.settings.setValue("readings", "true" if self.scene.show_readings else "false")
        self.scene.update()

    def _toggle_flow(self):
        self.scene.show_flow = self.a_flow.isChecked()
        self.settings.setValue("flow", "true" if self.scene.show_flow else "false")
        self.scene.update()

    def edit_selected(self):
        comps = self.scene.selected_components()
        if len(comps) == 1:
            self.edit_part(comps[0].id)

    def delete(self):
        if self.scene._wiring is not None:      # Backspace while drawing a wire: undo the last corner
            self.scene.undo_corner()
            return
        self.scene.delete_selected()

    def copy(self):
        data = self.scene.copy_data()
        if data:
            md = QMimeData()
            md.setData(MIME_CLIP, data.encode())
            md.setText(data)
            QApplication.clipboard().setMimeData(md)
            self._paste_n = 0

    def cut(self):
        self.copy()
        self.scene.delete_selected()

    def paste(self):
        md = QApplication.clipboard().mimeData()
        if md is None or not md.hasFormat(MIME_CLIP):
            return
        self._paste_n += 1
        self.scene.paste_data(bytes(md.data(MIME_CLIP)).decode(), (20 * self._paste_n, 20 * self._paste_n))

    def duplicate(self):
        data = self.scene.copy_data()
        if data:
            self.scene.paste_data(data, (20, 20))

    # ================================================================== view
    def _fit_contents(self, animate=True):
        r = EX.diagram_rect(self.scene) if not self.circuit.is_empty() else None
        self.view.fit(r, animate=animate, max_zoom=2.2 if r is not None else 1.6)

    def zoom_fit(self):
        self._fit_contents()

    def toggle_grid(self):
        self.scene.show_grid = not self.scene.show_grid
        self.a_grid.setChecked(self.scene.show_grid)
        self.settings.setValue("grid", "true" if self.scene.show_grid else "false")
        self.view.resetCachedContent()
        self.scene.update()

    def toggle_symbols(self):
        S.set_style("uk" if S.STYLE == "us" else "us")
        self.settings.setValue("symbols", S.STYLE)
        self.a_us.setChecked(S.STYLE == "us")
        self.gallery.refresh()
        self.scene.repaint_all()

    def toggle_theme(self):
        self.set_theme("light" if theme.MODE == "dark" else "dark")

    def set_theme(self, mode):
        theme.apply(mode)
        self.settings.setValue("theme", theme.MODE)
        QApplication.instance().setStyleSheet(theme.stylesheet())
        for a in self.actions():
            if a.data():
                a.setIcon(icons.icon(a.data()))
        self.a_dark.setChecked(theme.MODE == "dark")
        self.gallery.refresh()
        self.view.resetCachedContent()
        self.scene.repaint_all()
        self.view.viewport().update()

    def about(self):
        QMessageBox.about(self, tr("About Wirely"),
                          f"<h3>{APP_NAME} {__version__}</h3>"
                          f"<p>{tr('Version {v}', v=__version__)}</p>"
                          f"<p>{tr('Draw a circuit, press play, watch it work.')}<br>"
                          f"{tr('Free and open source under the GNU GPL v3.')}</p>"
                          f"<p>{tr('By Richard Willmott, built with help from Claude.')}</p>")

    # ================================================================== language
    def set_language(self, code):
        """Switch every word on screen to another language, straight away, and remember the choice."""
        code = lang.apply(code)
        lang.remember(code)
        self.lang_actions[code].setChecked(True)
        self.retranslate()

    def retranslate(self):
        for a in list(self._action_src):
            self._retr_action(a)
        for b, name in self._menu_buttons:
            b.setText(tr(name))
        self.examples_menu.setTitle(tr("Open example"))
        self.recent_menu.setTitle(tr("Open recent"))
        self._fill_examples()
        self.tip_label.setText(tr("Wheel: zoom · Middle-drag: pan · Double-click a part to change it"))
        self.speed_box.setToolTip(tr("Simulation speed"))
        i = self.speed_box.currentIndex()
        self.speed_box.blockSignals(True)
        for n, (name, _v) in enumerate(SPEEDS):
            self.speed_box.setItemText(n, tr(name))
        self.speed_box.setCurrentIndex(i)
        self.speed_box.blockSignals(False)
        self.scene.retranslate()
        self.gallery.retranslate()
        self.graph.retranslate()
        self.view.retranslate()
        self._update_title()
        self._update_counts()
        self._update_actions()
        self._play_tip(self.simc.state)
        self._sound_availability(self.sound.available())
        if self.simc.state == "stopped":
            self._hint("")
        else:
            self._state_hint(self.simc.state)
        if self.simc.active():
            self._on_sim_frame()
        self.scene.update()

    def showEvent(self, e):
        super().showEvent(e)
        self.a_grid.setChecked(self.scene.show_grid)

    def closeEvent(self, e):
        self.sim_stop()
        if not self._confirm_discard():
            e.ignore()
            return
        self.settings.setValue("geometry", self.saveGeometry())
        self.clear_autosave()
        e.accept()
