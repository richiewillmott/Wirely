"""The circuit sheet: shows a Circuit and handles placing, selecting, moving and wiring with the mouse.

The Circuit (model) is always the truth. Mouse actions change the model, keep the items in step, and when an
action is finished `edited` is emitted so the window can record an undo step.
"""
from __future__ import annotations

import json
import re

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QGraphicsScene

from ..i18n import tr
from ..model import parts as P
from ..model.circuit import Circuit, Component, Wire, drag_end, move_segment, route, snap, tidy
from ..model.circuit import on_segment as _on_seg
from . import theme
from .items import ComponentItem, DraftWire, WireItem, live_look_key

MIME_PART = "application/x-wirely-part"
MIME_CLIP = "application/x-wirely-clip"
DRAG_START = 4          # pixels before a press becomes a drag


def _pt(p: QPointF):
    return (snap(p.x()), snap(p.y()))


class CircuitScene(QGraphicsScene):
    edited = Signal(str)            # an action finished: label for the undo list
    editRequested = Signal(str)     # double-clicked part (component id)
    status = Signal(str)            # short hint for the status bar
    modeChanged = Signal(str)       # "select" | "wire" | "place"

    def __init__(self, circuit: Circuit | None = None):
        super().__init__()
        self.setSceneRect(-4000, -3000, 8000, 6000)
        self.circuit = circuit or Circuit()
        self.comp_items: dict[str, ComponentItem] = {}
        self.wire_items: dict[str, WireItem] = {}
        self.mode = "select"
        self.show_grid = True
        self.exporting = False
        self._junctions, self._open_pins = [], []
        self._hover_pin = None
        self._drag = None           # what the current left-button drag is doing
        self._ghost = None          # part waiting to be placed
        self._place_kind = None
        self._place_keep = False
        self.draft = DraftWire()
        self.addItem(self.draft)
        self.draft.hide()
        self._wiring = None         # {"fixed": [...], "click": bool}
        # live simulation
        self.sim = None             # SimController while running / paused
        self.show_volts = True
        self.show_flow = True
        self.show_readings = False
        self.pinned = set()         # wires and parts whose reading is shown while running (clicked)
        self.tag_offsets = {}       # reading labels dragged somewhere else: wire/part id -> (dx, dy)
        self._tag_hits = []         # where the reading labels were drawn last frame: (rect, id)
        self._drag_tag = None       # (id, mouse start, offset at start) while a reading label is being dragged
        self.anim_t = 0.0
        self.sliders = []
        self._held = None           # push switch being held down
        self._junction_net = {}
        self.hover_info = None      # (scene point, title, lines) for the reading bubble
        self.rebuild()

    # ================================================================== model <-> items
    def rebuild(self):
        """Recreate every item from the model (after loading, undo …)."""
        for it in list(self.comp_items.values()) + list(self.wire_items.values()):
            self.removeItem(it)
        self.comp_items.clear()
        self.wire_items.clear()
        for c in self.circuit.components.values():
            self._add_comp_item(c)
        for w in self.circuit.wires.values():
            self._add_wire_item(w)
        self.refresh_connections()

    def _add_comp_item(self, c: Component):
        it = ComponentItem(c)
        self.addItem(it)
        self.comp_items[c.id] = it
        return it

    def _add_wire_item(self, w: Wire):
        it = WireItem(w)
        self.addItem(it)
        self.wire_items[w.id] = it
        return it

    def set_circuit(self, circuit: Circuit):
        self.cancel()
        self.pinned = set()
        self.tag_offsets = {}
        self.circuit = circuit
        self.rebuild()

    def retranslate(self):
        """A language change: labels show translated choices and notes are as big as their text, so redo them."""
        for it in self.comp_items.values():
            it.sync()
        self.update()

    def refresh_connections(self):
        self._junctions = self.circuit.junctions()
        self._open_pins = [pos for _c, _n, pos in self.circuit.unconnected_pins()]
        self.update()

    def sync_component(self, cid):
        it = self.comp_items.get(cid)
        if it:
            it.sync()

    # ================================================================== helpers
    def tolerance(self) -> float:
        v = self.views()
        s = v[0].transform().m11() if v else 1.0
        return max(4.0, 8.0 / max(s, 0.05))

    def pin_at(self, pos: QPointF, exclude=()):
        """(component, pin name, position) of the nearest pin within reach, or None."""
        tol = self.tolerance()
        best, best_d = None, tol * tol
        for c in self.circuit.components.values():
            if c.id in exclude:
                continue
            for name, (x, y) in c.pin_positions().items():
                d = (x - pos.x()) ** 2 + (y - pos.y()) ** 2
                if d <= best_d:
                    best, best_d = (c, name, (x, y)), d
        return best

    def wire_end_at(self, pos: QPointF):
        tol = self.tolerance()
        for w in self.circuit.wires.values():
            for end in (0, -1):
                x, y = w.points[end]
                if (x - pos.x()) ** 2 + (y - pos.y()) ** 2 <= tol * tol:
                    return w, end
        return None

    def item_at(self, pos: QPointF):
        for it in self.items(pos):
            if isinstance(it, (ComponentItem, WireItem)) and it.isVisible() and not getattr(it, "ghost", False):
                return it
        return None

    def selected_ids(self):
        comps = [it.comp.id for it in self.selectedItems() if isinstance(it, ComponentItem)]
        wires = [it.wire.id for it in self.selectedItems() if isinstance(it, WireItem)]
        return comps, wires

    def selected_components(self):
        return [it.comp for it in self.selectedItems() if isinstance(it, ComponentItem)]

    def select_ids(self, ids):
        self.clearSelection()
        for i in ids:
            it = self.comp_items.get(i) or self.wire_items.get(i)
            if it:
                it.setSelected(True)

    # ================================================================== live simulation
    def sim_active(self) -> bool:
        return self.sim is not None and self.sim.active()

    def attach_sim(self, controller):
        self.sim = controller
        controller.frame.connect(self._on_frame)
        controller.stateChanged.connect(self._on_sim_state)

    def _on_sim_state(self, state):
        from .live_items import SliderItem
        from .simcontrol import ADJUSTABLE
        for sl in self.sliders:
            self.removeItem(sl)
        self.sliders = []
        self._held = None
        self.hover_info = None
        if state != "stopped":
            self.cancel()
            self.clearSelection()
            for it in self.comp_items.values():
                key = ADJUSTABLE.get(it.comp.kind)
                if key:
                    sl = SliderItem(it, key, self.sim_set_value)
                    self.addItem(sl)
                    self.sliders.append(sl)
            # which net each junction dot belongs to (for its colour)
            self._junction_net = {}
            for net in self.sim.sim.nets:
                for pt in self._junctions:
                    if pt in net.points:
                        self._junction_net[pt] = net.name
        self.repaint_all()

    def _on_frame(self):
        self.anim_t = self.sim.live.t if self.sim else 0.0
        self.update_hover()
        changed = self.refresh_look()
        fg = self._foreground_key()
        # nothing on screen looks any different: don't draw the same picture again (saves a lot of CPU)
        self.frame_changed = bool(changed or fg != self._last_fg)
        if self.frame_changed:
            self._last_fg = fg
            self.update()

    _last_fg = None
    frame_changed = True

    def repaint_all(self):
        """Draw every part and wire afresh (the theme, voltage colours or simulation state changed)."""
        for it in list(self.comp_items.values()) + list(self.wire_items.values()):
            it.look = ("stale",)
            it.update()
        self._last_fg = None
        self.refresh_look()
        self.update()

    def refresh_look(self) -> bool:
        """Parts and wires keep a ready-drawn picture; redraw only those whose live look has changed (a glow,
        a reading, a wire's voltage colour …). Returns True if any did."""
        active = self.sim_active()
        changed = False
        for it in self.comp_items.values():
            k = live_look_key(self.live_part(it.comp.id), it.comp.kind, self.anim_t) if active else None
            if k != it.look:
                it.look = k
                it.update()
                changed = True
        colours = active and self.show_volts
        wire_v, vmax = (self.sim.live.wire_v, self.sim.live.vmax) if colours else ({}, 1.0)
        for wid, it in self.wire_items.items():
            v = wire_v.get(wid)            # its colour comes from its voltage (finer steps than you can see)
            k = (round(v / max(vmax, 1e-9) * 400), round(vmax, 2)) if v is not None else None
            if k != it.look:
                it.look = k
                it.update()
                changed = True
        return changed

    def _foreground_key(self):
        """What the dots, junctions, readings and colour key are drawn from, to the precision you can see."""
        if not self.sim_active():
            return None
        live = self.sim.live
        h = self.hover_info
        bubble = (round(h[0].x(), 1), round(h[0].y(), 1), h[1], tuple(h[2])) if h else None

        def r3(v):
            return float(f"{v:.3g}") if isinstance(v, float) else v
        k = [round(live.vmax, 2), self.show_flow, self.show_volts, self.show_readings, tuple(sorted(self.pinned)),
             tuple(sorted(self.tag_offsets.items())), bubble]
        if self.show_volts:
            k.append(tuple((n, round(v, 2)) for n, v in sorted(live.net_v.items())))
        if self.show_flow:
            k.append(tuple((round(ph, 1), r3(a)) for _a, _b, ph, a in live.flows))
        if self.show_readings or self.pinned:
            k.append(tuple((wid, r3(v)) for wid, v in sorted(live.wire_v.items())))
            k.append(tuple(r3(a) for _a, _b, _ph, a in live.flows))
            for cid in sorted(live.parts):
                info = live.parts[cid]
                k.append((cid, info.get("reading"), r3(info.get("v")), r3(info.get("i")), r3(info.get("p"))))
        return tuple(k)

    def sim_set_value(self, cid, key, value):
        if self.sim_active():
            self.sim.set_value(cid, key, value)
            it = self.comp_items.get(cid)
            if it:
                it.update()

    def live_part(self, cid):
        if not self.sim_active():
            return None
        return self.sim.live.parts.get(cid)

    def wire_colour(self, wid):
        if not (self.sim_active() and self.show_volts):
            return None
        v = self.sim.live.wire_v.get(wid)
        if v is None:
            return None
        return theme.volt_colour(v, self.sim.live.vmax)

    def _wire_current(self, wire, pos):
        """Current in the piece of this wire nearest the mouse, and which way it flows (an arrow)."""
        best = None
        px, py = pos.x(), pos.y()
        for (x1, y1), (x2, y2), _ph, amps in self.sim.live.flows:
            # only pieces that belong to this wire
            if not any(_on_seg((x1, y1), a_, b_) and _on_seg((x2, y2), a_, b_) for a_, b_ in wire.segments()):
                continue
            dx, dy = x2 - x1, y2 - y1
            L = dx * dx + dy * dy
            t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L))
            d = (x1 + t * dx - px) ** 2 + (y1 + t * dy - py) ** 2
            if best is None or d < best[0]:
                if amps < 0:
                    dx, dy = -dx, -dy
                arrow = ("→" if dx > 0 else "←") if abs(dx) >= abs(dy) else ("↓" if dy > 0 else "↑")
                best = (d, abs(amps), arrow)
        return (best[1], best[2]) if best else (0.0, "")

    def _probe_info(self, pos):
        """(title, lines) to show next to the mouse while the simulation runs, or None."""
        from ..model.units import fmt
        item = self.item_at(pos)
        live = self.sim.live
        if isinstance(item, WireItem):
            v = live.wire_v.get(item.wire.id)
            if v is None:
                return None
            amps, arrow = self._wire_current(item.wire, pos)
            cur = f"{fmt(amps, 'A')} {arrow}" if amps >= 1e-6 else tr("no current")
            return tr("Wire"), [tr("Voltage: {v}", v=fmt(v if abs(v) >= 1e-3 else 0.0, "V")),
                                tr("Current: {i}", i=cur)]
        if isinstance(item, ComponentItem):
            info = live.parts.get(item.comp.id)
            if not info or "v" not in info:
                return None
            lines = [tr("Voltage across: {v}", v=fmt(abs(info["v"]), "V")),
                     tr("Current: {i}", i=fmt(abs(info["i"]), "A"))]
            if self.power_only(item.comp):
                lines = [tr("Power: {p}", p=fmt(abs(info.get("p", 0.0)), "W"))]
            elif abs(info.get("p", 0)) > 1e-6 and item.comp.kind not in ("cell", "battery", "dc_supply", "ac_supply",
                                                                          "rail_pos", "signal_gen"):
                lines.append(tr("Power: {p}", p=fmt(abs(info["p"]), "W")))
            if "rpm" in info:
                lines.append(tr("Speed: {rpm:.0f} rpm", rpm=abs(info["rpm"])))
            if info.get("blown"):
                lines.append(tr("Broken — press Stop to mend it"))
            return item.comp.ref, lines

    def _probe_text(self, pos):
        info = self._probe_info(pos)
        return None if info is None else f"{info[0]}:  " + "   ".join(info[1])

    def update_hover(self, pos=None):
        """Refresh the reading bubble at the mouse (called on mouse moves and every frame)."""
        if pos is not None:
            self._mouse_pos = pos
        p = getattr(self, "_mouse_pos", None)
        if self._drag_tag is not None or (p is not None and self.tag_at(p) is not None):
            self.hover_info = None             # over a reading label (or dragging one): no bubble on top of it
            return
        info = self._probe_info(p) if (p is not None and self.sim_active()) else None
        self.hover_info = (p, info[0], info[1]) if info else None

    def _sim_press(self, e):
        from .simcontrol import INTERACTIVE, TOGGLES
        pos = e.scenePos()
        for it in self.items(pos):
            if it in self.sliders:
                QGraphicsScene.mousePressEvent(self, e)
                return
        tag = self.tag_at(pos)
        if tag is not None and e.button() == Qt.LeftButton:       # a reading label: drag it out of the way
            self._drag_tag = (tag, QPointF(pos), self.tag_offsets.get(tag, (0.0, 0.0)))
            e.accept()
            return
        item = self.item_at(pos)
        if isinstance(item, ComponentItem) and item.comp.kind in INTERACTIVE and e.button() == Qt.LeftButton:
            c = item.comp
            if c.kind in TOGGLES:
                key = TOGGLES[c.kind]
                self.sim_set_value(c.id, key, not c.value(key))
            elif c.kind in ("spdt", "dpdt"):
                self.sim_set_value(c.id, "position", "B" if c.value("position") == "A" else "A")
            elif c.kind == "rotary":
                self.sim_set_value(c.id, "position", str(int(c.value("position")) % 4 + 1))
            elif c.kind == "keypad":
                key = self._keypad_key(item, pos)
                if key:
                    self.sim_set_value(c.id, "_key", key)
                    self._held = c.id
            else:
                self.sim_set_value(c.id, "pressed", True)
                self._held = c.id
        elif isinstance(item, (ComponentItem, WireItem)) and e.button() == Qt.LeftButton:
            # click a wire or part to pin its reading on the sheet (click again to take it off)
            key = item.comp.id if isinstance(item, ComponentItem) else item.wire.id
            self.pinned.symmetric_difference_update({key})
            self.update()
        e.accept()

    def tag_at(self, pos):
        """The wire or part whose reading label is under pos (the top one), or None."""
        for r, key in reversed(self._tag_hits):
            if r.adjusted(-2, -2, 2, 2).contains(pos):
                return key
        return None

    def _keypad_key(self, item, pos):
        """Which key of a keypad is under pos (allowing for the keypad being turned round)."""
        from . import symbols as S
        local = pos - item.pos()
        q = S._rotvec(QPointF(local.x(), local.y()), item.comp.rot, item.comp.flip, inverse=True)
        return S.keypad_key_at(q.x(), q.y())

    def _sim_release(self, e):
        if self._drag_tag is not None:
            self._drag_tag = None
            e.accept()
            return
        if self._held:
            comp = self.circuit.components.get(self._held)
            if comp is not None and comp.kind == "keypad":
                self.sim_set_value(self._held, "_key", "")
                comp.props.pop("_key", None)
            else:
                self.sim_set_value(self._held, "pressed", False)
            self._held = None
        QGraphicsScene.mouseReleaseEvent(self, e)

    def _sim_move(self, e):
        from .simcontrol import INTERACTIVE
        pos = e.scenePos()
        if self._drag_tag is not None:
            key, start, (ox, oy) = self._drag_tag
            self.tag_offsets[key] = (ox + pos.x() - start.x(), oy + pos.y() - start.y())
            self._mouse_pos = pos
            self.hover_info = None
            self.update()
            return
        QGraphicsScene.mouseMoveEvent(self, e)
        if self.tag_at(pos) is not None:
            self._mouse_pos = pos
            self.hover_info = None
            for v in self.views():
                v.viewport().setCursor(Qt.OpenHandCursor)
            self.status.emit(tr("Drag the reading to move it out of the way"))
            return
        item = self.item_at(pos)
        clickable = isinstance(item, ComponentItem) and item.comp.kind in INTERACTIVE
        for v in self.views():
            v.viewport().setCursor(Qt.PointingHandCursor if clickable else Qt.ArrowCursor)
        self.update_hover(pos)
        if self.sim.state != "running":        # paused: no frames are coming, so show the bubble move now
            self.update()
        text = self._probe_text(pos)
        if clickable:
            is_push = item.comp.kind.startswith("push")
            what = tr({"reed_switch": "click to move the magnet", "hall": "click to move the magnet",
                       "tilt_switch": "click to tilt it", "rotary": "click to turn it to the next position",
                       "keypad": "hold down a key to press it"}.get(
                item.comp.kind, "hold down to press" if is_push else "click to switch"))
            text = f"{text}   ·   {what}" if text else what[:1].upper() + what[1:]
        elif isinstance(item, (ComponentItem, WireItem)) and text:
            key = item.comp.id if isinstance(item, ComponentItem) else item.wire.id
            text += "   ·   " + tr("click to unpin its reading" if key in self.pinned else "click to pin its reading")
        self.status.emit(text or tr("Running — click switches, drag sliders, hover over wires to read voltages."))

    # ================================================================== modes
    def set_mode(self, mode: str):
        self.cancel()
        self.mode = mode
        self.modeChanged.emit(mode)
        if mode == "wire":
            self.status.emit(tr("Wire: press on a pin or a wire and drag to another pin. Click to add corners, Esc to stop."))
        else:
            self.status.emit("")
        for v in self.views():
            v.viewport().setCursor(Qt.CrossCursor if mode == "wire" else Qt.ArrowCursor)

    def start_placing(self, kind: str, keep=False):
        """Pick up a part from the gallery: it follows the mouse until you click on the sheet."""
        self.cancel()
        self._place_kind = kind
        self._place_keep = keep
        comp = Component(kind, 0, 0, props=P.get(kind).defaults(), ref=self.circuit.next_ref(P.get(kind).prefix))
        self._ghost = ComponentItem(comp, ghost=True)
        self.addItem(self._ghost)
        self._ghost.hide()
        self.mode = "place"
        self.modeChanged.emit("place")
        self.status.emit(tr("Click on the sheet to place the {name}. R rotates, F flips, Esc cancels.",
                            name=P.get(kind).tr_name_lower))

    def _move_ghost(self, pos: QPointF):
        if self._ghost:
            self._ghost.comp.x, self._ghost.comp.y = _pt(pos)
            self._ghost.sync()
            self._ghost.show()

    def _drop_ghost(self, pos: QPointF):
        g = self._ghost.comp
        c = self.circuit.add(g.kind, *_pt(pos), rot=g.rot, flip=g.flip, props=dict(g.props))
        self._add_comp_item(c)
        self.clearSelection()
        self.comp_items[c.id].setSelected(True)
        self.refresh_connections()
        self.edited.emit(tr("Add {ref}", ref=c.ref))
        if self._place_keep:
            self._ghost.comp.ref = self.circuit.next_ref(P.get(g.kind).prefix)
            self._ghost.sync()
        else:
            self.cancel()
            self.set_mode("select")
        return c

    def cancel(self):
        """Stop whatever is half-done (placing a part, drawing a wire, dragging)."""
        if self._ghost is not None:
            self.removeItem(self._ghost)
            self._ghost = None
            self._place_kind = None
            if self.mode == "place":
                self.mode = "select"
                self.modeChanged.emit("select")
        if self._wiring is not None:
            self._wiring = None
            self.draft.hide()
        if self._drag is not None and self._drag.get("restore"):
            self._drag["restore"]()
            self._drag = None
            self.refresh_connections()
        self._drag = None
        self.status.emit("")

    # ================================================================== editing operations
    def _apply_moves(self, moves: dict, orig_comps: dict, orig_wires: dict, translate_wires: set, delta=(0, 0)):
        """Put components at new places (moves: id -> (x, y, rot, flip)) and make the wires follow.

        orig_comps / orig_wires hold the state from before the action, so a drag is always worked out from
        where it started (no drift). Wires in translate_wires move bodily by delta."""
        moved_pins = {}
        for cid, (x, y, rot, flip) in moves.items():
            c = self.circuit.components[cid]
            ox, oy, orot, oflip = orig_comps[cid]
            c.x, c.y, c.rot, c.flip = ox, oy, orot, oflip
            old = c.pin_positions()
            c.x, c.y, c.rot, c.flip = x, y, rot, flip
            new = c.pin_positions()
            for name, pos in old.items():
                moved_pins[pos] = new[name]
            self.sync_component(cid)
        dx, dy = delta
        for wid in translate_wires:
            w = self.circuit.wires.get(wid)
            if w:
                w.points = [(x + dx, y + dy) for x, y in orig_wires[wid]]
                for e in (orig_wires[wid][0], orig_wires[wid][-1]):
                    moved_pins.setdefault(e, (e[0] + dx, e[1] + dy))
        for wid, pts in orig_wires.items():
            if wid in translate_wires or wid not in self.circuit.wires:
                continue
            a, b = pts[0], pts[-1]
            na, nb = moved_pins.get(a), moved_pins.get(b)
            w = self.circuit.wires[wid]
            if na and nb and (na[0] - a[0], na[1] - a[1]) == (nb[0] - b[0], nb[1] - b[1]):
                ddx, ddy = na[0] - a[0], na[1] - a[1]
                w.points = [(x + ddx, y + ddy) for x, y in pts]
            else:
                new = list(pts)
                if na:
                    new = drag_end(new, 0, na)
                if nb:
                    new = drag_end(new, -1, nb)
                w.points = new if len(new) >= 2 else [na or a, nb or b]
        for wid in self.wire_items:
            self.wire_items[wid].sync()

    def _snapshot_geometry(self, comp_ids=None):
        comps = {cid: (c.x, c.y, c.rot, c.flip) for cid, c in self.circuit.components.items()
                 if comp_ids is None or cid in comp_ids}
        wires = {wid: list(w.points) for wid, w in self.circuit.wires.items()}
        return comps, wires

    def rotate_selected(self, clockwise=True):
        if self._ghost is not None:
            g = self._ghost.comp
            g.rot = (g.rot + (1 if clockwise else 3)) % 4
            self._ghost.sync()
            return
        comps = self.selected_components()
        if not comps:
            return
        oc, ow = self._snapshot_geometry()
        moves = {c.id: (c.x, c.y, (c.rot + (1 if clockwise else 3)) % 4, c.flip) for c in comps}
        self._apply_moves(moves, oc, ow, set())
        self.refresh_connections()
        self.edited.emit(tr("Rotate"))

    def flip_selected(self):
        if self._ghost is not None:
            self._ghost.comp.flip = not self._ghost.comp.flip
            self._ghost.sync()
            return
        comps = self.selected_components()
        if not comps:
            return
        oc, ow = self._snapshot_geometry()
        moves = {c.id: (c.x, c.y, c.rot, not c.flip) for c in comps}
        self._apply_moves(moves, oc, ow, set())
        self.refresh_connections()
        self.edited.emit(tr("Flip"))

    def delete_selected(self):
        comps, wires = self.selected_ids()
        if not comps and not wires:
            return
        for cid in comps:
            self.removeItem(self.comp_items.pop(cid))
            self.circuit.remove(cid)
        for wid in wires:
            self.removeItem(self.wire_items.pop(wid))
            self.circuit.remove(wid)
        self.refresh_connections()
        self.edited.emit(tr("Delete"))

    def select_all(self):
        for it in list(self.comp_items.values()) + list(self.wire_items.values()):
            it.setSelected(True)

    def copy_data(self) -> str | None:
        comps, wires = self.selected_ids()
        if not comps and not wires:
            return None
        d = {"components": [self.circuit.components[c].to_dict() for c in comps],
             "wires": [self.circuit.wires[w].to_dict() for w in wires]}
        return json.dumps(d)

    def paste_data(self, text: str, offset=(20, 20)):
        try:
            d = json.loads(text)
        except (ValueError, TypeError):
            return False
        new_ids = []
        dx, dy = offset
        for cd in d.get("components", []):
            part = P.PARTS.get(cd.get("kind"))
            if not part:
                continue
            c = self.circuit.add(cd["kind"], cd["x"] + dx, cd["y"] + dy, cd.get("rot", 0), cd.get("flip", False),
                                 cd.get("props"))
            self._add_comp_item(c)
            new_ids.append(c.id)
        for wd in d.get("wires", []):
            w = self.circuit.add_wire([(x + dx, y + dy) for x, y in wd["points"]])
            if w:
                self._add_wire_item(w)
                new_ids.append(w.id)
        if not new_ids:
            return False
        self.select_ids(new_ids)
        self.refresh_connections()
        self.edited.emit(tr("Paste"))
        return True

    def update_component(self, cid, props: dict, ref: str | None = None):
        c = self.circuit.components[cid]
        c.props.update(props)
        if ref:
            c.ref = ref
        self.sync_component(cid)
        self.edited.emit(tr("Edit {ref}", ref=c.ref))

    # ================================================================== mouse
    def mousePressEvent(self, e):
        if self.sim_active():
            self._sim_press(e)
            return
        pos = e.scenePos()
        if e.button() != Qt.LeftButton:
            if e.button() == Qt.RightButton and (self._wiring or self._ghost):
                self.cancel()
                if self.mode == "place":
                    self.set_mode("select")
                e.accept()
                return
            super().mousePressEvent(e)
            return
        e.accept()
        if self._ghost is not None:
            self._drop_ghost(pos)
            return
        if self._wiring is not None:            # click-to-route mode: add a corner or finish
            self._wiring_click(pos)
            return
        mods = e.modifiers()
        pin = self.pin_at(pos)
        if pin is not None:
            self._start_wire(pin[2], from_pin=True)
            return
        if self.mode == "wire":
            end = self.wire_end_at(pos)
            self._start_wire(end[0].points[end[1]] if end else _pt(pos), from_pin=False)
            return
        end = self.wire_end_at(pos)
        item = self.item_at(pos)
        if end is not None and isinstance(item, WireItem) and item.wire is end[0]:
            # grab the loose end of a wire and move it
            w, idx = end
            if not (mods & (Qt.ControlModifier | Qt.ShiftModifier)):
                self.clearSelection()
            item.setSelected(True)
            orig = list(w.points)

            def restore(w=w, orig=orig):
                w.points = orig
                self.wire_items[w.id].sync()
            self._drag = {"kind": "wire_end", "wire": w, "end": idx, "orig": orig, "start": e.screenPos(),
                          "moved": False, "restore": restore}
            return
        if item is None:
            if not (mods & (Qt.ControlModifier | Qt.ShiftModifier)):
                self.clearSelection()
            e.ignore()           # lets the view draw a selection rectangle
            return
        if mods & Qt.ControlModifier:
            item.setSelected(not item.isSelected())
            return
        if not item.isSelected():
            if not (mods & Qt.ShiftModifier):
                self.clearSelection()
            item.setSelected(True)
        comps, wires = self.selected_ids()
        oc, ow = self._snapshot_geometry()
        if isinstance(item, WireItem) and not comps and len(wires) == 1:
            seg = item.segment_at(pos)
            orig = list(item.wire.points)

            def restore(w=item.wire, orig=orig):
                w.points = orig
                self.wire_items[w.id].sync()
            self._drag = {"kind": "segment", "wire": item.wire, "seg": seg, "orig": orig, "anchor": _pt(pos),
                          "start": e.screenPos(), "moved": False, "restore": restore}
            return

        def restore(oc=oc, ow=ow):
            for cid, (x, y, r, f) in oc.items():
                c = self.circuit.components.get(cid)
                if c:
                    c.x, c.y, c.rot, c.flip = x, y, r, f
                    self.sync_component(cid)
            for wid, pts in ow.items():
                if wid in self.circuit.wires:
                    self.circuit.wires[wid].points = pts
                    self.wire_items[wid].sync()
        self._drag = {"kind": "move", "comps": comps, "wires": set(wires), "oc": oc, "ow": ow,
                      "anchor": _pt(pos), "start": e.screenPos(), "moved": False, "restore": restore}

    def mouseMoveEvent(self, e):
        if self.sim_active():
            self._sim_move(e)
            return
        pos = e.scenePos()
        if self._ghost is not None:
            self._move_ghost(pos)
            return
        if self._wiring is not None:
            self._update_wire(pos)
            return
        d = self._drag
        if d is not None and e.buttons() & Qt.LeftButton:
            if not d["moved"]:
                if (e.screenPos() - d["start"]).manhattanLength() < DRAG_START:
                    return
                d["moved"] = True
            if d["kind"] == "move":
                ax, ay = d["anchor"]
                nx, ny = _pt(pos)
                dx, dy = nx - ax, ny - ay
                moves = {cid: (d["oc"][cid][0] + dx, d["oc"][cid][1] + dy, d["oc"][cid][2], d["oc"][cid][3])
                         for cid in d["comps"]}
                self._apply_moves(moves, d["oc"], d["ow"], d["wires"], (dx, dy))
            elif d["kind"] == "segment":
                ax, ay = d["anchor"]
                nx, ny = _pt(pos)
                d["wire"].points = move_segment(d["orig"], d["seg"], nx - ax, ny - ay)
                self.wire_items[d["wire"].id].sync()
            elif d["kind"] == "wire_end":
                pin = self.pin_at(pos)
                target = pin[2] if pin else _pt(pos)
                d["wire"].points = drag_end(d["orig"], d["end"], target)
                self.wire_items[d["wire"].id].sync()
            self.refresh_connections()
            return
        # just hovering: show which pin you'd start a wire from
        pin = self.pin_at(pos)
        hp = pin[2] if pin else None
        if hp != self._hover_pin:
            self._hover_pin = hp
            for v in self.views():
                v.viewport().setCursor(Qt.CrossCursor if (hp or self.mode == "wire") else Qt.ArrowCursor)
            if hp:
                self.status.emit(tr("Drag from this pin to draw a wire."))
            self.update()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.sim_active():
            self._sim_release(e)
            return
        if e.button() != Qt.LeftButton:
            super().mouseReleaseEvent(e)
            return
        if self._wiring is not None:
            w = self._wiring
            if not w["click"]:
                if w["dragged"]:
                    self._finish_wire(e.scenePos())
                else:
                    w["click"] = True       # it was a click: carry on routing with clicks
                    self.status.emit(tr("Click to add corners; click a pin or wire to finish. "
                                        "Double-click to stop here, Esc cancels, Backspace undoes a corner."))
            return
        d, self._drag = self._drag, None
        if d is None:
            super().mouseReleaseEvent(e)
            return
        if d["moved"]:
            if d["kind"] in ("segment", "wire_end"):
                w = d["wire"]
                w.points = tidy(w.points)
                if len(w.points) < 2:
                    self.removeItem(self.wire_items.pop(w.id))
                    self.circuit.remove(w.id)
                else:
                    self.wire_items[w.id].sync()
            self.refresh_connections()
            self.edited.emit(tr({"move": "Move", "segment": "Move wire", "wire_end": "Move wire end"}[d["kind"]]))

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self._wiring is not None and not self.sim_active():
            self._finish_wire(e.scenePos(), here=True)
            return
        item = self.item_at(e.scenePos())
        if self.sim_active():
            from .simcontrol import INTERACTIVE
            if isinstance(item, ComponentItem) and item.comp.kind in INTERACTIVE:
                self._sim_press(e)       # a quick double click on a switch flips it twice: keep up
                return
        if isinstance(item, ComponentItem):
            self.editRequested.emit(item.comp.id)
        e.accept()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            busy = self._wiring is not None or self._ghost is not None or self._drag is not None
            self.cancel()
            if not busy:
                self.clearSelection()
                if self.mode != "select":
                    self.set_mode("select")
            e.accept()
            return
        if e.key() == Qt.Key_Backspace and self._wiring is not None:
            self.undo_corner()
            e.accept()
            return
        super().keyPressEvent(e)

    # ================================================================== drawing wires
    def undo_corner(self):
        """Backspace while drawing a wire: take back the last corner (or stop if there are none)."""
        if self._wiring is None:
            return
        fixed = self._wiring["fixed"]
        if len(fixed) > 1:
            fixed.pop()
            self._update_wire(self._wiring["last_pos"])
        else:
            self.cancel()

    def _start_wire(self, start, from_pin):
        self.clearSelection()
        self._wiring = {"fixed": [tuple(start)], "click": False, "dragged": False, "from_pin": from_pin,
                        "last_pos": QPointF(*start), "path": [tuple(start)], "target": None}
        self.draft.set([start])
        self.draft.show()

    def _wire_target(self, pos: QPointF):
        """Where the wire would end: a pin, a wire end, a point on a wire, or just the grid point."""
        pin = self.pin_at(pos)
        if pin:
            return pin[2], True
        end = self.wire_end_at(pos)
        if end:
            return end[0].points[end[1]], True
        p = _pt(pos)
        item = self.item_at(pos)
        if isinstance(item, WireItem):
            from ..model.circuit import on_segment
            if any(on_segment(p, a, b) for a, b in item.wire.segments()):
                return p, True
        return p, False

    def _update_wire(self, pos: QPointF):
        w = self._wiring
        w["last_pos"] = pos
        start = w["fixed"][-1]
        target, snapped = self._wire_target(pos)
        if target != start:
            w["dragged"] = True
        dx, dy = target[0] - start[0], target[1] - start[1]
        prefer = abs(dx) >= abs(dy)
        a, b = route(start, target, prefer), route(start, target, not prefer)
        leg = b if self._crossings(a) > self._crossings(b) else a
        path = w["fixed"][:-1] + leg
        w["path"] = path
        w["target"] = target if snapped else None
        self.draft.set(path, w["target"])

    def _crossings(self, pts) -> int:
        """How many part bodies a proposed wire would run through (so we can pick the better corner)."""
        n = 0
        bodies = []
        for it in self.comp_items.values():
            r = it._body.translated(it.pos())
            bodies.append(r.adjusted(2, 2, -2, -2))
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            seg = QRectF(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)).adjusted(-0.5, -0.5, 0.5, 0.5)
            n += sum(1 for r in bodies if r.intersects(seg))
        return n

    def _wiring_click(self, pos: QPointF):
        w = self._wiring
        self._update_wire(pos)
        target, snapped = self._wire_target(pos)
        if snapped and target != w["fixed"][0]:
            self._finish_wire(pos)
            return
        # add a corner here
        w["fixed"] = tidy(w["path"]) if len(w["path"]) > 1 else w["fixed"]
        if w["fixed"][-1] != target:
            w["fixed"].append(target)

    def _finish_wire(self, pos: QPointF, here=False):
        w = self._wiring
        self._update_wire(pos)
        pts = tidy(w["path"])
        self._wiring = None
        self.draft.hide()
        if len(pts) < 2:
            return
        wire = self.circuit.add_wire(pts)
        if wire:
            self._add_wire_item(wire)
            self.refresh_connections()
            self.edited.emit(tr("Add wire"))
        if self.mode == "wire":
            self.status.emit(tr("Wire added. Draw another, or press Esc."))

    # ================================================================== drag and drop from the gallery
    def dragEnterEvent(self, e):
        if self.sim_active():
            e.ignore()
            return
        if e.mimeData().hasFormat(MIME_PART):
            kind = bytes(e.mimeData().data(MIME_PART)).decode()
            self.start_placing(kind)
            self._move_ghost(e.scenePos())
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if self._ghost is not None:
            self._move_ghost(e.scenePos())
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        if self._ghost is not None:
            self._ghost.hide()

    def dropEvent(self, e):
        if self._ghost is not None:
            self._drop_ghost(e.scenePos())
            e.acceptProposedAction()

    # ================================================================== painting the sheet
    def drawBackground(self, p, rect: QRectF):
        p.fillRect(rect, QColor(theme.CANVAS))
        if self.exporting or not self.show_grid:
            return
        s = self.views()[0].transform().m11() if self.views() else 1.0
        step = P.GRID if s >= 0.9 else P.GRID * 2 if s >= 0.45 else P.GRID * 5
        x0 = int(rect.left() // step) * step
        y0 = int(rect.top() // step) * step
        minor, major = [], []
        y = y0
        while y <= rect.bottom():
            x = x0
            while x <= rect.right():
                (major if (x % 100 == 0 and y % 100 == 0) else minor).append(QPointF(x, y))
                x += step
            y += step
        pen = QPen(QColor(theme.GRID_DOT), max(1.2 / s, 1.0) * 1.0)
        pen.setCapStyle(Qt.RoundCap)
        pen.setCosmetic(True)
        pen.setWidthF(1.6 if s >= 0.9 else 1.3)
        p.setPen(pen)
        p.drawPoints(minor)
        pen.setColor(QColor(theme.GRID_DOT_MAJOR))
        pen.setWidthF(2.4)
        p.setPen(pen)
        p.drawPoints(major)

    def _draw_flow(self, p, live, rect):
        """Moving dots along the wires: conventional current, faster for bigger currents."""
        spacing = 16.0
        p.setPen(QPen(QColor(theme.FLOW_EDGE), 0.8))
        p.setBrush(QColor(theme.FLOW_DOT))
        vis = rect.adjusted(-20, -20, 20, 20)
        for (x1, y1), (x2, y2), phase, amps in live.flows:
            if abs(amps) < 1e-6:
                continue
            L = abs(x2 - x1) + abs(y2 - y1)
            if L < 1 or not vis.intersects(QRectF(min(x1, x2), min(y1, y2), abs(x2 - x1) + 1, abs(y2 - y1) + 1)):
                continue
            ux, uy = (x2 - x1) / L, (y2 - y1) / L
            off = phase % spacing
            r = 2.1 + 0.5 * min(1.0, abs(amps) / 0.05)
            d = off
            while d < L:
                p.drawEllipse(QPointF(x1 + ux * d, y1 + uy * d), r, r)
                d += spacing

    # readings: what a multimeter would show, written on the sheet
    NO_READING = {"ground", "note", "scope_probe", "logic_probe", "voltmeter", "ammeter"}
    SOURCES = {"cell", "battery", "dc_supply", "ac_supply", "rail_pos", "signal_gen"}

    def _tag(self, p, x, y, text, pinned, anchor, key=None):
        """A small reading label at (x, y): anchor "above" sits it above the point, "right" beside it. If it has
        been dragged somewhere else, it's drawn there with a dashed line back to (x, y)."""
        from PySide6.QtGui import QFont, QFontMetricsF
        f = QFont()
        f.setPixelSize(8)
        p.setFont(f)
        w = QFontMetricsF(f).horizontalAdvance(text) + 8
        h = 12
        if anchor == "above":
            r = QRectF(x - w / 2, y - h - 4, w, h)
        elif anchor == "below":
            r = QRectF(x - w / 2, y + 3, w, h)
        elif anchor == "under":                  # left-aligned, just under (x, y)
            r = QRectF(x, y + 1, w, h)
        else:
            r = QRectF(x + 5, y - h / 2, w, h)
        dx, dy = self.tag_offsets.get(key, (0.0, 0.0))
        if dx or dy:
            r = r.translated(dx, dy)
            # a dashed line from what it belongs to, to the nearest point of the label
            px = min(max(x, r.left()), r.right())
            py = min(max(y, r.top()), r.bottom())
            if abs(px - x) + abs(py - y) > 4:
                pen = QPen(QColor(theme.ACCENT if pinned else theme.BORDER), 0.9, Qt.DashLine)
                p.setPen(pen)
                p.drawLine(QPointF(x, y), QPointF(px, py))
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(theme.ACCENT if pinned else theme.BORDER))
                p.drawEllipse(QPointF(x, y), 1.8, 1.8)
        if key is not None:
            self._tag_hits.append((QRectF(r), key))
        bg = QColor(theme.PANEL)
        bg.setAlpha(232)
        p.setPen(QPen(QColor(theme.ACCENT if pinned else theme.BORDER), 1.0 if pinned else 0.8))
        p.setBrush(bg)
        p.drawRoundedRect(r, 3, 3)
        p.setPen(QColor(theme.TEXT))
        p.drawText(r, Qt.AlignCenter, text)

    @staticmethod
    def power_only(comp) -> bool:
        """Chips (and parts with several separate legs): a voltage and current between their first two pins would
        mean nothing, so only their power is shown."""
        return comp.part.category == "Integrated circuits" or comp.kind in ("led_rgb", "led_bi3", "dpdt")

    def readings_text(self) -> str:
        """Every part's voltage, current and power as a table (tab-separated, so it pastes into a spreadsheet as
        columns). Empty when nothing is running."""
        if not self.sim_active():
            return ""
        live = self.sim.live
        if live is None:
            return ""

        def num(x, floor):
            x = abs(x)
            return f"{x:.4g}" if x >= floor else "0"

        def ref_key(c):
            m = re.match(r"([A-Za-z]*)(\d*)", c.ref or "")
            return (m.group(1), int(m.group(2) or 0), c.ref)

        rows = []
        for comp in sorted((it.comp for it in self.comp_items.values()), key=ref_key):
            if comp.kind in self.NO_READING:
                continue
            info = live.parts.get(comp.id)
            if not info or "v" not in info:
                continue
            power = num(info.get("p", 0.0), 1e-6) if comp.kind not in self.SOURCES else ""
            name = comp.part.tr_tile_name
            if self.power_only(comp):
                rows.append("\t".join((comp.ref, name, "", "", power)))
            else:
                rows.append("\t".join((comp.ref, name, num(info["v"], 1e-3), num(info["i"], 1e-6), power)))
        t = getattr(self.sim, "sim", None)
        when = tr("Readings at {t:.3g} s", t=t.t) if t is not None else tr("Readings")
        head = "\t".join((tr("Part"), tr("What"), tr("Voltage (V)"), tr("Current (A)"), tr("Power (W)")))
        return "\n".join([when, head] + rows) + "\n"

    def _draw_readings(self, p, live):
        from ..model.units import fmt
        show_all = self.show_readings
        net_of = {wid: net.name for net in self.sim.sim.nets for wid in net.wires} if self.sim else {}
        labelled = set()
        # wires carrying current first (they always get a label), then one voltage label per remaining net
        order = []
        for wid, it in self.wire_items.items():
            pinned = wid in self.pinned
            if not (show_all or pinned) or wid not in live.wire_v:
                continue
            w = it.wire
            a, b = max(w.segments(), key=lambda s: abs(s[1][0] - s[0][0]) + abs(s[1][1] - s[0][1]))
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            amps, arrow = self._wire_current(w, QPointF(mx, my))
            length = abs(b[0] - a[0]) + abs(b[1] - a[1])
            order.append((amps < 1e-6, -length, wid, pinned, a, b, mx, my, amps, arrow))
        order.sort(key=lambda t: (t[0], t[1]))
        for idle, _l, wid, pinned, a, b, mx, my, amps, arrow in order:
            net = net_of.get(wid)
            if idle and not pinned and net in labelled:
                continue                         # same voltage is already shown on this net
            labelled.add(net)
            vv = live.wire_v[wid]
            text = fmt(vv if abs(vv) >= 1e-3 else 0.0, "V")
            if amps >= 1e-6:
                text += f"   {fmt(amps, 'A')} {arrow}"
            self._tag(p, mx, my, text, pinned, "above" if a[1] == b[1] else "right", key=wid)
        for cid, it in self.comp_items.items():
            pinned = cid in self.pinned
            kind = it.comp.kind
            if not (pinned or (show_all and kind not in self.NO_READING)):
                continue
            info = live.parts.get(cid)
            if not info or "v" not in info:
                continue
            def tidy(x, floor):          # leakage (pA, nV) reads as 0, like a real meter
                x = abs(x)
                return x if x >= floor else 0.0
            if self.power_only(it.comp):
                bits = [fmt(tidy(info.get("p", 0.0), 1e-6), "W")]
            else:
                bits = [fmt(tidy(info["v"], 1e-3), "V"), fmt(tidy(info["i"], 1e-6), "A")]
                if abs(info.get("p", 0)) > 1e-6 and kind not in self.SOURCES:
                    bits.append(fmt(tidy(info["p"], 1e-6), "W"))
            # next to the part's own label (its name and value), so it's clear which part it belongs to
            lab, lines, align = it._label
            if lines:
                r = lab.translated(it.pos())
                if align == Qt.AlignLeft:            # label beside a standing part: reading underneath it
                    self._tag(p, r.left(), r.bottom(), "  ".join(bits), pinned, "under", key=cid)
                else:                                # label above a part lying flat: reading underneath it
                    sym = it._sym.translated(it.pos())
                    self._tag(p, sym.center().x(), sym.bottom() + (22 if "reading" in info else 0),
                              "  ".join(bits), pinned, "below", key=cid)
            else:
                sym = it._sym.translated(it.pos())
                y = sym.bottom() + (22 if "reading" in info else 0)
                self._tag(p, sym.center().x(), y, "  ".join(bits), pinned, "below", key=cid)

    def drawForeground(self, p, rect: QRectF):
        from PySide6.QtGui import QPainter
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        live = self.sim.live if (self.sim_active() and not self.exporting) else None
        for x, y in self._junctions:
            col = QColor(theme.WIRE)
            if live is not None and self.show_volts and (x, y) in self._junction_net:
                col = theme.volt_colour(live.net_v.get(self._junction_net[(x, y)], 0.0), live.vmax)
            p.setBrush(col)
            p.drawEllipse(QPointF(x, y), 3.8 if live else 3.6, 3.8 if live else 3.6)
        if self.exporting:
            return
        if live is not None and self.show_flow:
            self._draw_flow(p, live, rect)
        self._tag_hits = []
        if live is not None and (self.show_readings or self.pinned):
            self._draw_readings(p, live)
        if self.sim_active():
            return
        # pins with nothing attached: small open circles so you can see where to connect
        p.setBrush(QColor(theme.CANVAS))
        p.setPen(QPen(QColor(theme.PIN_OPEN), 1.3))
        for x, y in self._open_pins:
            p.drawEllipse(QPointF(x, y), 2.6, 2.6)
        if self._hover_pin and self._wiring is None and self._drag is None:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(theme.PIN_TARGET), 2))
            p.drawEllipse(QPointF(*self._hover_pin), 6, 6)
