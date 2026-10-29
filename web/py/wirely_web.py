"""Wirely in a web browser: the glue between the web page (JavaScript) and Wirely's own Python code.

The browser runs real Python (Pyodide). This module loads the desktop app's sheet, drawing and simulator
code unchanged — wirely/ui/scene.py, items.py, symbols.py, simcontrol.py, graph.py and the whole of wirely/sim —
with qtshim standing in for Qt. Instead of painting pixels, drawing is recorded as a list of commands that
the page replays on a canvas. So the web version behaves and looks like the desktop app.

The page calls App methods with plain numbers and strings and gets JSON text back.
"""
from __future__ import annotations

import json
import math
import sys
import time

import qtshim

qtshim.install()

IN_BROWSER = sys.platform == "emscripten"
if IN_BROWSER:                                     # measure text with the browser's real fonts
    try:
        import js                                  # noqa: F401  (Pyodide's bridge to JavaScript)

        def _measure(text, px, bold, mono):
            return float(js.wirelyMeasure(text, px, bool(bold), bool(mono)))
        qtshim.measure = _measure
    except Exception:                              # noqa: BLE001 - fall back to the estimate
        pass

from PySide6.QtCore import QPointF, QRectF, Qt                       # noqa: E402  (the shim)
from PySide6.QtGui import QColor, QPainter                           # noqa: E402

from wirely import __version__, i18n                               # noqa: E402
from wirely.i18n import tr, trn                                      # noqa: E402
from wirely.model import parts as P                                  # noqa: E402
from wirely.model.circuit import Circuit                             # noqa: E402
from wirely.model.types_info import describe                         # noqa: E402
from wirely.model.units import fmt, has_unit_box, join, parse, split, unit_choices  # noqa: E402
from wirely.sim.audio import Synth                                   # noqa: E402
from wirely.ui import icons, symbols as S, theme                     # noqa: E402
from wirely.ui import simcontrol as SC                               # noqa: E402
from wirely.ui.graph import TIMEBASES, VOLTS, GraphPanel             # noqa: E402
from wirely.ui.items import ComponentItem, DraftWire, WireItem, live_look_key  # noqa: E402
from wirely.ui.live_items import SliderItem                          # noqa: E402
from wirely.ui.scene import CircuitScene                             # noqa: E402

SceneEvent = qtshim.SceneEvent
DRAG_START = 4
EMPTY_HINT = "Pick a part from the gallery, or drag from a pin to draw a wire."


# ============================================================================================ small helpers
class _Viewport:
    def __init__(self, view):
        self.view = view

    def setCursor(self, c):
        self.view.cursor = c

    def rect(self):
        return QRectF(0, 0, self.view.w, self.view.h)

    def update(self):
        pass

    def width(self):
        return self.view.w

    def height(self):
        return self.view.h


class _Transform:
    def __init__(self, z):
        self.z = z

    def m11(self):
        return self.z


class WebView:
    """What the scene code asks of its view: the zoom (for click tolerance) and the cursor."""

    def __init__(self):
        self.zoom = 1.6
        self.w, self.h = 800, 600
        self.cursor = "default"
        self._vp = _Viewport(self)

    def transform(self):
        return _Transform(self.zoom)

    def viewport(self):
        return self._vp


class _Choice:
    """Stands in for the graph panel's drop-down boxes."""

    def __init__(self):
        self.i = 0

    def currentIndex(self):
        return self.i


class _Text:
    def __init__(self):
        self.text = ""

    def setText(self, t):
        self.text = t


class _Nothing:
    def update(self):
        pass

    def isVisible(self):
        return True


def make_graph():
    """The desktop graph panel's own logic (traces, scales, drawing), without its widgets."""
    g = GraphPanel.__new__(GraphPanel)          # skip building the desktop widgets
    g.traces, g.t_now, g.vmax_hint = {}, 0.0, 9.0
    g.tbox, g.vbox, g.chips, g.plot = _Choice(), _Choice(), _Text(), _Nothing()
    g.clear()
    return g


class WebSynth(Synth):
    """Keeps track of what each buzzer / speaker / motor should sound like; the page plays it."""

    def __init__(self):
        super().__init__()
        self.click_count = 0

    def click(self):
        self.click_count += 1


class _Sound:
    def __init__(self, synth):
        self.synth = synth


# ============================================================================================ the app
class App:
    def __init__(self):
        self.view = WebView()
        self.scene = CircuitScene(Circuit())
        self.scene._views.append(self.view)
        self.circuit = self.scene.circuit
        self.simc = SC.SimController()
        self.synth = WebSynth()
        self.simc.sound = _Sound(self.synth)
        self.sound_on = True
        self.scene.attach_sim(self.simc)
        self.graph = make_graph()
        self.graph_on = False
        self.graph_by_hand = False
        self.status = ""
        self.toasts = []
        self.pending_edit = None
        self.band = None                   # rubber-band selection: (start point, current point, additive)
        self._press = None
        self.clip = None
        self._paste_n = 0
        self.name = "Untitled"
        self.history = [self.circuit.to_dict()]
        self.hi = 0
        self.saved_at = 0
        self.sim_dirty = False
        self.ids = {}                      # drawing key -> number the page caches it under
        self.new_defs = {}
        self.reset_defs = True
        self.scene.edited.connect(self._on_edited)
        self.scene.editRequested.connect(self._on_edit_requested)
        self.scene.status.connect(self._on_status)
        self.simc.message.connect(self._on_sim_message)
        self.simc.stateChanged.connect(self._on_sim_state)
        SC.FRAME_MS = 33

    # ------------------------------------------------------------------ signals from the scene / simulator
    def _on_edited(self, label):
        now = self.circuit.to_dict()
        if now != self.history[self.hi]:
            del self.history[self.hi + 1:]
            self.history.append(now)
            self.hi = len(self.history) - 1
            if len(self.history) > 200:
                self.history.pop(0)
                self.hi -= 1
                self.saved_at -= 1

    def _on_edit_requested(self, cid):
        self.pending_edit = cid

    def _on_status(self, text):
        self.status = text

    def _on_sim_message(self, cid, text):
        # a part that has broken is an error; a warning is something that can still be put right
        self.toasts.append([text, "error" if self.simc.is_broken(cid) else "warn"])

    def _on_sim_state(self, state):
        if state == "stopped":
            # switch positions and slider settings changed while running are kept, without an undo step
            self.history[self.hi] = self.circuit.to_dict()
            self.scene.refresh_connections()
            self.status = ""
            self.synth.silence_all()
        elif state == "running":
            self.status = tr("Running — click switches, drag sliders, hover over wires to read voltages.")
        else:
            self.status = tr("Paused — press Play to carry on, or Stop to edit.")

    # ------------------------------------------------------------------ files
    def _set_circuit(self, circuit, name):
        self.stop()
        self.graph.clear()
        if not any(c.kind == "scope_probe" for c in circuit.components.values()):
            self.graph_on = False
        self.circuit = circuit
        self.scene.set_circuit(circuit)
        self.name = name
        self.history = [circuit.to_dict()]
        self.hi = 0
        self.saved_at = 0

    def new(self):
        self._set_circuit(Circuit(), "Untitled")
        return ""

    def load(self, text, name="Untitled"):
        """Open a .wirely file's text. Returns "" or what went wrong."""
        try:
            d = json.loads(text)
            if d.get("app") not in ("Wirely", "Sparkbench"):
                raise ValueError(tr("This isn't a Wirely circuit file."))
            if int(d.get("version", 1)) > 1:
                raise ValueError(tr("This file was saved by a newer version of Wirely — please update."))
            c = Circuit.from_dict(d)
        except Exception as e:                   # noqa: BLE001 - show any problem to the user
            return tr("Couldn't open {name}: {e}", name=name, e=e)
        self._set_circuit(c, name)
        return ""

    def save_text(self):
        return json.dumps(self.circuit.to_dict(), indent=1, ensure_ascii=False)

    def mark_saved(self, name=None):
        if name:
            self.name = name
        self.saved_at = self.hi

    def is_dirty(self):
        return self.hi != self.saved_at

    def is_empty(self):
        return self.circuit.is_empty()

    def bom_csv(self):
        rows = self.circuit.bill_of_materials()
        out = [",".join((tr("Qty"), tr("Part"), tr("Labels")))]
        for r in rows:
            out.append(f'{r["qty"]},"{r["description"]}","{" ".join(r["refs"])}"')
        return "\n".join(out)

    def bom(self):
        return json.dumps(self.circuit.bill_of_materials())

    # ------------------------------------------------------------------ undo
    def _restore(self, data):
        self.scene.cancel()
        self.circuit.load_dict(data)
        self.scene.rebuild()

    def undo(self):
        if self.hi > 0 and not self.simc.active():
            self.hi -= 1
            self._restore(self.history[self.hi])

    def redo(self):
        if self.hi < len(self.history) - 1 and not self.simc.active():
            self.hi += 1
            self._restore(self.history[self.hi])

    # ------------------------------------------------------------------ mouse and keys (sheet coordinates)
    def set_view(self, zoom, w, h):
        self.view.zoom, self.view.w, self.view.h = float(zoom), float(w), float(h)

    def press(self, x, y, button, buttons, mods, sx, sy):
        e = SceneEvent(x, y, button, buttons, mods, sx, sy)
        self._press = (sx, sy)
        self.scene.mousePressEvent(e)
        sim = self.scene.sim_active()
        if not e.isAccepted() and button == Qt.LeftButton and not sim:
            self.band = (QPointF(x, y), QPointF(x, y), bool(mods & (Qt.ControlModifier | Qt.ShiftModifier)),
                         [it for it in self.scene.selectedItems()])
        return self._reply()

    def move(self, x, y, buttons, mods, sx, sy):
        if self.band is not None:
            if buttons & Qt.LeftButton:
                start, _cur, add, before = self.band
                self.band = (start, QPointF(x, y), add, before)
                self._band_select()
            else:
                self.band = None
            return self._reply()
        e = SceneEvent(x, y, 0, buttons, mods, sx, sy)
        self.scene.mouseMoveEvent(e)
        return self._reply()

    def _band_rect(self):
        a, b = self.band[0], self.band[1]
        return QRectF(min(a.x(), b.x()), min(a.y(), b.y()), abs(a.x() - b.x()), abs(a.y() - b.y()))

    def _band_select(self):
        r = self._band_rect()
        if r.width() < 2 and r.height() < 2:
            return
        self.scene.clearSelection()
        for it in self.band[3] if self.band[2] else []:
            it.setSelected(True)
        for it in list(self.scene.comp_items.values()) + list(self.scene.wire_items.values()):
            if it.intersects_scene(r):
                it.setSelected(True)

    def release(self, x, y, button, buttons, mods, sx, sy):
        if self.band is not None and button == Qt.LeftButton:
            self.band = None
            return self._reply()
        e = SceneEvent(x, y, button, buttons, mods, sx, sy)
        self.scene.mouseReleaseEvent(e)
        return self._reply()

    def dblclick(self, x, y, mods, sx, sy):
        e = SceneEvent(x, y, Qt.LeftButton, Qt.LeftButton, mods, sx, sy)
        self.scene.mouseDoubleClickEvent(e)
        return self._reply()

    def wheel_slider(self, x, y, delta):
        """Mouse wheel over a slider while running: returns True if a slider took it."""
        if not self.scene.sim_active():
            return False
        pos = QPointF(x, y)
        if not any(it in self.scene.sliders for it in self.scene.items(pos)):
            return False
        e = SceneEvent(x, y, delta=delta)
        self.scene.wheelEvent(e)
        return True

    def hit(self, x, y):
        """What's under a finger: "pin", "slider", "item" (a part or wire) or "none" (so a drag pans)."""
        sc = self.scene
        pos = QPointF(x, y)
        if sc.sim_active():
            if any(it in sc.sliders for it in sc.items(pos)):
                return "slider"
            it = sc.item_at(pos)
            return "item" if isinstance(it, ComponentItem) and it.comp.kind in SC.INTERACTIVE else "none"
        if sc.pin_at(pos) is not None:
            return "pin"
        return "item" if sc.item_at(pos) is not None else "none"

    def leave(self):
        self.scene.hover_info = None
        self.scene._mouse_pos = None
        self.scene.leave()
        g = getattr(self.scene, "_ghost", None)
        if g is not None:
            g.hide()

    def escape(self):
        self.band = None
        self.scene.keyPressEvent(SceneEvent(key=Qt.Key_Escape))

    def _reply(self):
        out = {"cursor": self.view.cursor}
        if self.pending_edit:
            out["edit"] = self.pending_edit
            self.pending_edit = None
        return json.dumps(out)

    # ------------------------------------------------------------------ actions (toolbar, menus, keys)
    def start_placing(self, kind, keep=False):
        if self.simc.active():
            self.toasts.append([tr("Press Stop to go back to editing, then add the part."), "info"])
            return
        self.scene.start_placing(kind, keep=bool(keep))

    def action(self, name):
        sc = self.scene
        running = self.simc.active()
        if name == "undo":
            self.undo()
        elif name == "redo":
            self.redo()
        elif name == "select":
            sc.set_mode("select")
        elif name == "wire" and not running:
            sc.set_mode("wire")
        elif name == "delete" and not running:
            if sc._wiring is not None:
                sc.undo_corner()
            else:
                sc.delete_selected()
        elif name == "select_all" and not running:
            sc.select_all()
        elif name == "rotate" and not running:
            sc.rotate_selected(True)
        elif name == "rotate_ccw" and not running:
            sc.rotate_selected(False)
        elif name == "flip" and not running:
            sc.flip_selected()
        elif name == "copy":
            data = sc.copy_data()
            if data:
                self.clip = data
                self._paste_n = 0
            return data or ""
        elif name == "cut" and not running:
            data = sc.copy_data()
            if data:
                self.clip = data
                self._paste_n = 0
                sc.delete_selected()
            return data or ""
        elif name == "paste" and not running and self.clip:
            self._paste_n += 1
            sc.paste_data(self.clip, (20 * self._paste_n, 20 * self._paste_n))
        elif name == "duplicate" and not running:
            data = sc.copy_data()
            if data:
                sc.paste_data(data, (20, 20))
        elif name == "props":
            comps = sc.selected_components()
            if len(comps) == 1:
                return comps[0].id
        elif name == "play":
            self.run()
        elif name == "pause":
            self.simc.pause()
        elif name == "stop":
            self.stop()
        elif name == "volts":
            sc.show_volts = not sc.show_volts
        elif name == "flow":
            sc.show_flow = not sc.show_flow
        elif name == "readings":
            sc.show_readings = not sc.show_readings
        elif name == "copy_readings":
            return sc.readings_text()
        elif name == "sound":
            self.sound_on = not self.sound_on
        elif name == "graph":
            self.graph_on = not self.graph_on
            self.graph_by_hand = self.graph_on
        elif name == "grid":
            sc.show_grid = not sc.show_grid
        elif name == "dark":
            self.set_theme("light" if theme.MODE == "dark" else "dark")
        return ""

    def paste_text(self, text):
        """Paste circuit parts copied in another tab or window (the system clipboard)."""
        if self.simc.active():
            return False
        self._paste_n += 1
        ok = self.scene.paste_data(text, (20 * self._paste_n, 20 * self._paste_n))
        if ok:
            self.clip = text
        return bool(ok)

    def state(self):
        """Which buttons make sense right now."""
        sc = self.scene
        comps, wires = sc.selected_ids()
        running = self.simc.active()
        n, w = len(self.circuit.components), len(self.circuit.wires)
        return json.dumps({
            "sim": self.simc.state, "mode": sc.mode, "place": sc._place_kind if sc.mode == "place" else None,
            "sel": bool(comps or wires), "comps": len(comps), "running": running,
            "undo": self.hi > 0 and not running, "redo": self.hi < len(self.history) - 1 and not running,
            "paste": bool(self.clip) and not running, "volts": sc.show_volts, "flow": sc.show_flow, "readings": sc.show_readings,
            "sound": self.sound_on, "graph": self.graph_on, "grid": sc.show_grid, "dark": theme.MODE == "dark", "us": S.STYLE == "us",
            "dirty": self.is_dirty(), "name": tr("Untitled") if self.name == "Untitled" else self.name,
            "untitled": self.name == "Untitled", "empty": self.circuit.is_empty(),
            "counts": trn("{n} part", "{n} parts", n) + " · " + trn("{n} wire", "{n} wires", w),
            "status": self.status or (tr(EMPTY_HINT) if not running else ""),
            "wiring": sc._wiring is not None,
        })

    def context(self, x, y):
        """What a right-click offers here (it also selects what's under the mouse, like the desktop app)."""
        sc = self.scene
        item = sc.item_at(QPointF(x, y))
        running = self.simc.active()
        menu = []
        if isinstance(item, ComponentItem):
            if not item.isSelected():
                sc.clearSelection()
                item.setSelected(True)
            menu.append([tr("Properties…"), "props", "Enter"])
            if not running:
                menu += [None, [tr("Rotate"), "rotate", "R"], [tr("Rotate anticlockwise"), "rotate_ccw", "Shift+R"],
                         [tr("Flip"), "flip", "F"], None, [tr("Duplicate"), "duplicate", "Ctrl+D"],
                         [tr("Copy"), "copy", "Ctrl+C"], [tr("Cut"), "cut", "Ctrl+X"], [tr("Delete"), "delete", "Del"]]
        elif isinstance(item, WireItem) and not running:
            if not item.isSelected():
                sc.clearSelection()
                item.setSelected(True)
            menu.append([tr("Delete"), "delete", "Del"])
        elif not running:
            menu += [[tr("Paste"), "paste", "Ctrl+V"], [tr("Select all"), "select_all", "Ctrl+A"], None,
                     [tr("Zoom to fit"), "fit", "Ctrl+0"]]
        else:
            menu.append([tr("Pause"), "pause", "F6"] if self.simc.state == "running" else [tr("Run"), "play", "F5"])
            menu.append([tr("Stop"), "stop", "F7"])
        return json.dumps(menu)

    # ------------------------------------------------------------------ the properties box
    def part_form(self, cid):
        comp = self.circuit.components.get(cid)
        if not comp:
            return "null"
        part = comp.part
        fields = []
        for p in part.props:
            v = comp.value(p.key)
            f = {"key": p.key, "label": p.tr_label, "kind": p.kind, "help": p.tr_help}
            if p.kind == "bool":
                f["value"] = bool(v)
            elif p.kind == "text":
                f["value"] = str(v)
            elif p.kind == "choice":
                f["value"] = str(v)
                f["choices"] = list(p.choices)                    # the values that get saved (English)
                f["choice_labels"] = [P.choice_text(ch) for ch in p.choices]      # what the person reads
                if p.key == "colour":
                    f["colours"] = {ch: S.LED_RGB[ch] for ch in p.choices if ch in S.LED_RGB}
                if p.key == "model":
                    f["info"] = {ch: describe(ch) for ch in p.choices}
            elif has_unit_box(p.unit):
                # the number, with a box beside it for its size: Ω / kΩ / MΩ, pF / nF / µF …
                f["value"], f["unit"] = split(float(v), p.unit)
                f["units"] = unit_choices(p.unit)
                f["placeholder"] = tr("e.g. {value}", value=split(float(p.default), p.unit)[0])
                f["help"] = p.tr_help or tr("Type the number and pick its size — or type it all, like 4k7 or 100n")
            else:
                f["value"] = fmt(v, p.unit)
                f["placeholder"] = tr("e.g. {value}", value=fmt(p.default, p.unit))
                f["help"] = p.tr_help or tr("Type values like 10k, 4k7, 2M2, 100n, 4.7µ")
            fields.append(f)
        return json.dumps({"id": cid, "ref": comp.ref, "name": part.tr_name, "description": part.tr_description,
                           "fields": fields, "kind": comp.kind,
                           "icon": self._icon_ops(comp.kind, 76, 50, comp.props, theme.PANEL)})

    def _read_form(self, comp, values):
        out, problems, bad = {}, [], []
        for p in comp.part.props:
            if p.key not in values:
                continue
            raw = values[p.key]
            if p.kind == "bool":
                out[p.key] = bool(raw)
            elif p.kind == "text":
                out[p.key] = str(raw).strip() or " "
            elif p.kind == "choice":
                out[p.key] = str(raw)
            else:
                try:
                    if p.key + "__unit" in values:
                        v = join(raw, values[p.key + "__unit"], p.unit)
                    else:
                        v = parse(raw, p.unit)
                    if p.min is not None and v < p.min:
                        raise ValueError(tr("{label} must be at least {value}", label=p.tr_label, value=fmt(p.min, p.unit)))
                    if p.max is not None and v > p.max:
                        raise ValueError(tr("{label} can be at most {value}", label=p.tr_label, value=fmt(p.max, p.unit)))
                    out[p.key] = v
                except ValueError as e:
                    problems.append(str(e))
                    bad.append(p.key)
        ref = str(values.get("_ref", comp.ref)).strip()
        if not ref:
            problems.append(tr("The label can't be empty"))
            bad.append("_ref")
        elif any(c.ref == ref and c.id != comp.id for c in self.circuit.components.values()):
            problems.append(tr("Another part is already called {ref}", ref=ref))
            bad.append("_ref")
        return out, ref, problems, bad

    def tidy_value(self, cid, key, text, choice):
        """Someone typed the whole value (4k7, 100n) next to a unit box: [number, unit-box choice] to show
        instead (or null if it doesn't make sense yet)."""
        comp = self.circuit.components.get(cid)
        p = comp.part.prop(key) if comp else None
        if p is None:
            return "null"
        try:
            return json.dumps(list(split(join(text, choice, p.unit), p.unit)))
        except ValueError:
            return "null"

    def check_form(self, cid, values_json):
        comp = self.circuit.components.get(cid)
        if not comp:
            return json.dumps({"error": "", "bad": []})
        _o, _r2, problems, bad = self._read_form(comp, json.loads(values_json))
        return json.dumps({"error": problems[0] if problems else "", "bad": bad})

    def apply_form(self, cid, values_json):
        comp = self.circuit.components.get(cid)
        if not comp:
            return ""
        values, ref, problems, _bad = self._read_form(comp, json.loads(values_json))
        if problems:
            return problems[0]
        if self.simc.active():                 # change it live: the circuit carries on running
            for k, v in values.items():
                if comp.value(k) != v:
                    self.simc.set_value(cid, k, v)
            comp.ref = ref
            self.scene.sync_component(cid)
            self.sim_dirty = True
        else:
            self.scene.update_component(cid, values, ref)
        return ""

    # ------------------------------------------------------------------ running
    def run(self):
        sc = self.scene
        if self.simc.state == "paused":
            self.simc.resume()
            return ""
        if self.simc.state == "running":
            self.simc.pause()
            return ""
        if self.circuit.is_empty():
            self.toasts.append([tr("Add some parts and wire them up first — then press Play."), "info"])
            return ""
        sc.cancel()
        sc.set_mode("select")
        probes = [c for c in self.circuit.components.values() if c.kind == "scope_probe"]
        self.graph.clear()
        self.graph_on = bool(probes) or (self.graph_on and self.graph_by_hand)
        try:
            self.simc.start(self.circuit)
        except Exception as e:                 # noqa: BLE001 - never crash the editor because of a bad circuit
            self.simc.stop()
            self.toasts.append([tr("The simulation couldn't start:") + f" {e}", "error"])
            return str(e)
        return ""

    def stop(self):
        if self.simc.active():
            self.simc.stop()

    def set_speed(self, s):
        self.simc.set_speed(float(s))

    def speeds(self):
        return json.dumps([[tr(n), v] for n, v in SC.SPEEDS])

    def tick(self):
        """One step of the running simulation (the page calls this about 30 times a second)."""
        if self.simc.state != "running":
            return False
        self.scene.frame_changed = True
        try:
            self.simc._tick()
        except Exception as e:                 # noqa: BLE001
            self.simc.stop()
            self.toasts.append([tr("The simulation stopped:") + f" {e}", "error"])
        if self.simc.live.samples or self.simc.active():
            if self.simc.live.samples:
                self.graph.add_samples(self.simc.live.samples, self.simc.live.t)
                self.simc.live.samples = []
        return bool(self.scene.frame_changed)     # False: the sheet looks just the same, no need to draw it

    def sim_info(self):
        if not self.simc.active():
            return json.dumps(None)
        t = self.simc.live.t
        txt = f"t = {t:.2f} s" if t < 100 else f"t = {t:.0f} s"
        behind = self.simc.behind and self.simc.state == "running"
        if behind:
            txt += "  · " + tr("slowed")
        sound = []
        if self.sound_on and self.simc.state == "running":
            for key, v in self.synth.voices.items():
                sound.append([key, v.freq, v.target, v.shape])
        return json.dumps({"time": txt, "behind": behind, "vmax": self.simc.live.vmax, "sound": sound,
                           "clicks": self.synth.click_count if self.sound_on else 0,
                           "volts": self.scene.show_volts})

    def take_toasts(self):
        t, self.toasts = self.toasts, []
        return json.dumps(t)

    # ------------------------------------------------------------------ drawing
    def _def(self, key, make):
        """Number for a drawing; the page is sent the drawing commands only the first time."""
        i = self.ids.get(key)
        if i is None:
            if len(self.ids) > 6000:
                self.ids.clear()
                self.new_defs.clear()
                self.reset_defs = True
            i = len(self.ids) + 1
            self.ids[key] = i
            self.new_defs[i] = make()
        return i

    @staticmethod
    def _paint(item):
        p = QPainter()
        item.paint(p, None)
        return p.ops

    def frame(self, x0, y0, x1, y1):
        """Everything to draw on the sheet for the area x0,y0–x1,y1 (sheet units), as JSON."""
        sc = self.scene
        anim_t = sc.anim_t
        mode = theme.MODE
        exporting = sc.exporting
        draw = []
        for it in sc.all_items():
            if not it.isVisible():
                continue
            if isinstance(it, ComponentItem):
                c = it.comp
                live = None if (it.ghost or exporting) else sc.live_part(c.id)
                key = ("c", c.kind, c.rot, c.flip, c.ref, json.dumps(c.props, sort_keys=True, default=str),
                       it.isSelected() and not exporting, it.hover and not exporting, it.ghost,
                       live_look_key(live, c.kind, anim_t), mode)
            elif isinstance(it, WireItem):
                vc = None if exporting else sc.wire_colour(it.wire.id)
                key = ("w", tuple(it.wire.points), it.isSelected() and not exporting, it.hover and not exporting,
                       vc.css() if vc is not None else None, mode)
            elif isinstance(it, SliderItem):
                key = ("s", it.comp.kind, it.value(), mode)
            elif isinstance(it, DraftWire):
                draw.append([0, 0, 0, 1, self._paint(it)])
                continue
            else:
                continue
            i = self._def(key, lambda it=it: self._paint(it))
            draw.append([i, it.x(), it.y(), it.opacity()])
        fg = QPainter()
        sc.drawForeground(fg, QRectF(x0, y0, x1 - x0, y1 - y0))
        out = {"draw": draw, "fg": fg.ops}
        if self.new_defs or self.reset_defs:
            out["defs"] = {str(k): v for k, v in self.new_defs.items()}
            if self.reset_defs:
                out["reset"] = True
            self.new_defs = {}
            self.reset_defs = False
        if self.band is not None:
            r = self._band_rect()
            out["band"] = [r.x(), r.y(), r.width(), r.height()]
        if sc.sim_active() and sc.hover_info:
            pos, title, lines = sc.hover_info
            out["bubble"] = [pos.x(), pos.y(), title, lines]
        return json.dumps(out, separators=(",", ":"))

    def bounds(self):
        """The area the circuit covers (for zoom to fit), like the desktop's export rectangle."""
        r = QRectF()
        for it in list(self.scene.comp_items.values()) + list(self.scene.wire_items.values()):
            br = it.boundingRect().translated(it.pos())
            r = r.united(br)
        if r.isEmpty():
            return json.dumps(None)
        return json.dumps([r.x(), r.y(), r.width(), r.height()])

    def export_frame(self):
        """The diagram in black-on-white paper colours (no grid, selection or pin marks), for saving a picture."""
        sc = self.scene
        saved = {k: getattr(theme, k) for k in theme.LIGHT}
        for k, v in theme.LIGHT.items():
            setattr(theme, k, v)
        selected = sc.selectedItems()
        for it in selected:
            it.setSelected(False)
        ghost = getattr(sc, "_ghost", None)
        ghost_vis = ghost is not None and ghost.isVisible()
        if ghost is not None:
            ghost.hide()
        draft_vis = sc.draft.isVisible()
        sc.draft.hide()
        sc.exporting = True
        try:
            r = QRectF()
            for it in list(sc.comp_items.values()) + list(sc.wire_items.values()):
                r = r.united(it.boundingRect().translated(it.pos()))
            if r.isEmpty():
                r = QRectF(-100, -75, 200, 150)
            # tighter than the items' own bounds (those leave room for glows): use the parts and wires
            tight = QRectF()
            for it in sc.comp_items.values():
                tight = tight.united(it._sym.translated(it.pos())).united(
                    it._label[0].translated(it.pos()) if it._label[1] else QRectF())
            for it in sc.wire_items.values():
                tight = tight.united(it._path.boundingRect())
            if not tight.isEmpty():
                r = tight
            r = r.adjusted(-30, -30, 30, 30)
            ops = []
            for it in sc.all_items():
                if not it.isVisible() or not isinstance(it, (ComponentItem, WireItem)):
                    continue
                p = QPainter()
                p.save()
                p.translate(it.x(), it.y())
                it.paint(p, None)
                p.restore()
                ops += p.ops
            fg = QPainter()
            sc.drawForeground(fg, r)
            ops += fg.ops
        finally:
            sc.exporting = False
            for k, v in saved.items():
                setattr(theme, k, v)
            for it in selected:
                it.setSelected(True)
            if draft_vis:
                sc.draft.show()
            if ghost_vis:
                ghost.show()
        return json.dumps({"rect": [r.x(), r.y(), r.width(), r.height()], "ops": ops})

    # ------------------------------------------------------------------ the graph
    def graph_ops(self, w, h, mx, my, tb, vb):
        g = self.graph
        g.tbox.i, g.vbox.i = int(tb), int(vb)
        p = QPainter()
        mouse = QPointF(mx, my) if mx >= 0 else None
        g.paint_plot(p, QRectF(0, 0, w, h), mouse)
        g._update_chips()
        return json.dumps({"ops": p.ops, "chips": g.chips.text})

    def graph_clear(self):
        self.graph.clear()

    def graph_choices(self):
        return json.dumps({"time": [tr(n) for n, _v in TIMEBASES], "volts": [tr(n) for n, _v in VOLTS]})

    def graph_csv(self):
        """The recorded graph probe voltages as a spreadsheet (CSV): one row per time."""
        chans = sorted(ch for ch, trace in self.graph.traces.items() if trace.t)
        if not chans:
            return ""
        rows = {}
        for ch in chans:
            trace = self.graph.traces[ch]
            for t, v in zip(trace.t, trace.v):
                rows.setdefault(t, {})[ch] = v
        out = [tr("time (s)") + "," + ",".join(f"{ch} (V)" for ch in chans)]
        for t in sorted(rows):
            out.append(f"{t:.9g}," + ",".join(f"{rows[t][ch]:.6g}" if ch in rows[t] else "" for ch in chans))
        return "\n".join(out)

    # ------------------------------------------------------------------ gallery, icons, theme
    def _icon_ops(self, kind, w, h, props=None, paper=None):
        """Same framing as symbols.pixmap (the desktop's gallery pictures), recorded instead of painted."""
        part = P.get(kind)
        p = QPainter()
        bx, by, bw, bh = part.box
        xs = [bx, bx + bw] + [x for _n, x, _y in part.pins]
        ys = [by, by + bh] + [y for _n, _x, y in part.pins]
        x0, x1, y0, y1 = min(xs) - 3, max(xs) + 3, min(ys) - 3, max(ys) + 3
        s = min(w / (x1 - x0), h / (y1 - y0))
        p.translate(w / 2, h / 2)
        p.scale(s, s)
        p.translate(-(x0 + x1) / 2, -(y0 + y1) / 2)
        values = part.defaults()
        values.update(props or {})
        S.draw(p, kind, values, QColor(theme.INK), paper=QColor(paper or theme.PANEL))
        return p.ops

    def gallery(self, w=62, h=40):
        cats = []
        for cat, parts in P.by_category():
            cats.append({"name": tr(cat), "search": (cat + " " + tr(cat)).lower(), "parts": [
                {"key": pd.key, "tile": pd.tr_tile_name, "name": pd.tr_name, "description": pd.tr_description,
                 "keywords": pd.search_text, "icon": self._icon_ops(pd.key, w, h)} for pd in parts]})
        return json.dumps(cats)

    def toolbar_icons(self, names_json):
        out = {}
        for name in json.loads(names_json):
            p = QPainter()
            icons.draw(name, p)
            out[name] = p.ops
        return json.dumps(out)

    def logo_ops(self):
        p = QPainter()
        icons.draw_mark(p, 1.0)
        return json.dumps(p.ops)

    def set_symbols(self, style):
        """'us' for American symbols (zigzag resistors …), 'uk' for British ones."""
        S.set_style(style)
        self.ids.clear()                 # every drawing is made again in the new style
        self.new_defs.clear()
        self.reset_defs = True
        return S.STYLE

    def set_theme(self, mode):
        theme.apply(mode)
        self.ids.clear()
        self.new_defs.clear()
        self.reset_defs = True
        return json.dumps({k: getattr(theme, k) for k in theme.LIGHT})

    def colours(self):
        return json.dumps({k: getattr(theme, k) for k in theme.LIGHT})

    def volt_stops(self, vmax):
        return json.dumps([theme.volt_colour(vmax * k / 10, vmax).css() for k in range(11)])

    def version(self):
        return __version__

    # ------------------------------------------------------------------ language
    def languages(self):
        return json.dumps(i18n.LANGUAGES)

    def set_language(self, code):
        """Show everything in this language from now on. Returns the code in use. Messages already waiting are
        dropped (they were written in the old language) and the status line is written again."""
        code = i18n.set_language(code)
        self.scene.retranslate()
        self.toasts = []
        if self.simc.state == "stopped":
            self.status = ""
        else:
            self._on_sim_state(self.simc.state)
        return code

    def catalogue(self, code=None):
        """The {English: translation} map for a language, for the page's own text."""
        return json.dumps(i18n.catalogue(code or i18n.language()), ensure_ascii=False)


def selftest():
    """Quick check used by the build: open every example, draw it, run it for a moment."""
    import glob
    import os
    app = App()
    here = os.path.dirname(os.path.abspath(__file__))
    found = sorted(glob.glob(os.path.join(here, "examples", "*.wirely")) or
                   glob.glob(os.path.join(here, "..", "..", "examples", "*.wirely")))
    report = []
    for path in found:
        with open(path, encoding="utf-8") as fh:
            err = app.load(fh.read(), os.path.basename(path))
        assert not err, err
        app.frame(-1000, -1000, 1000, 1000)
        app.run()
        t0 = time.perf_counter()
        for _ in range(3):
            app.tick()
            app.frame(-1000, -1000, 1000, 1000)
        report.append((os.path.basename(path), round(time.perf_counter() - t0, 3)))
        app.stop()
    return report


if __name__ == "__main__":
    for row in selftest():
        print(*row)
