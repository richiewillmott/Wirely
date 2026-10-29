"""Runs the solver while you watch: Play / Pause / Stop, speed, and what each frame should show."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QObject, QTimer, Signal

from ..model.units import fmt
from ..sim import devices as D
from ..sim.engine import Simulator
from ..sim.audio import SpeakerWatch, update_from_sim
from ..sim.flow import FlowNetwork

FRAME_MS = 33
SPEEDS = [("10× faster", 10.0), ("2× faster", 2.0), ("Real time", 1.0), ("½ speed", 0.5), ("⅕ speed", 0.2),
          ("1/10 speed", 0.1), ("1/100 speed", 0.01), ("1/1000 speed", 0.001)]
INTERACTIVE = {"switch", "push_make", "push_break", "spdt", "dpdt", "reed_switch", "tilt_switch", "hall", "rotary",
               "keypad"}
TOGGLES = {"switch": "closed", "reed_switch": "magnet", "tilt_switch": "tilted", "hall": "magnet"}
ADJUSTABLE = {"ldr": "light", "thermistor": "temperature", "var_resistor": "setting", "potentiometer": "setting",
              "moisture": "moisture", "phototransistor": "light"}


class Live:
    """Everything the sheet needs to draw one frame of a running simulation."""

    def __init__(self):
        self.wire_v = {}          # wire id -> volts
        self.net_v = {}           # net name -> volts
        self.parts = {}           # component id -> dict of display values
        self.flows = []           # [(a, b, phase, amps)]
        self.samples = []         # graph probe readings since the last frame: [(t, {channel: volts})]
        self.vmax = 1.0
        self.t = 0.0


class SimController(QObject):
    frame = Signal()
    stateChanged = Signal(str)        # "stopped" | "running" | "paused"
    message = Signal(str, str)        # (component id, text) — an LED popped etc.

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = "stopped"
        self.sim = None
        self.speed = 1.0
        D.Device.eye_window = 0.066
        self.behind = False
        self.live = Live()
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self._last = None
        self._phase = {}
        self._angle = {}
        self.sound = None          # SoundPlayer, set by the window
        self.watches = {}

    # ------------------------------------------------------------------ control
    def start(self, circuit):
        self.circuit = circuit
        self.sim = Simulator(circuit)
        self.sim.recording = True
        self.flow = FlowNetwork(circuit, self.sim.nets)
        self.wire_net = {wid: net.name for net in self.sim.nets for wid in net.wires}
        self._phase.clear()
        self._angle.clear()
        self.watches = {cid: SpeakerWatch() for cid in self.sim.speakers}
        self.live = Live()
        self.live.vmax = max([abs(getattr(d, "V", 0.0)) for d in self.sim.devices if isinstance(d, D.Source)]
                             + [1.0])
        self._last = time.perf_counter()
        self.state = "running"
        self._compute_frame(0.0)
        self._timer.start()
        self.stateChanged.emit(self.state)

    def pause(self):
        if self.state == "running":
            self._timer.stop()
            if self.sound is not None:
                self.sound.synth.silence_all()
            self.state = "paused"
            self.stateChanged.emit(self.state)

    def resume(self):
        if self.state == "paused":
            self._last = time.perf_counter()
            self._timer.start()
            self.state = "running"
            self.stateChanged.emit(self.state)

    def stop(self):
        self._timer.stop()
        self.sim = None
        self.state = "stopped"
        self.live = Live()
        self.stateChanged.emit(self.state)
        self.frame.emit()

    def is_broken(self, cid):
        """Has this part broken (popped, blown, burnt out)? Used to colour its message, whatever the language."""
        dev = self.sim.by_id.get(cid) if self.sim is not None else None
        return bool(getattr(dev, "blown", False))

    def active(self):
        return self.state != "stopped"

    def set_speed(self, s: float):
        self.speed = s
        D.Device.eye_window = 0.066 * s      # the eye's 1/15 s, in simulated time at this speed

    def set_value(self, cid, key, value):
        """A switch clicked / slider moved / value edited while running."""
        comp = self.circuit.components.get(cid)
        if comp is None:
            return
        comp.props[key] = value
        if self.sim is not None:
            self.sim.set_value(cid, key, value)
            if self.state == "paused":          # show the effect straight away
                self.sim.run_until(self.sim.t + 1e-4)
                self._compute_frame(0.0)

    # ------------------------------------------------------------------ the loop
    def _tick(self):
        now = time.perf_counter()
        wall = min(0.1, now - self._last)
        self._last = now
        target = self.sim.t + wall * self.speed
        self.sim.h_max = max(1e-4, wall * self.speed / 3)
        reached = self.sim.run_until(target, budget_s=FRAME_MS / 1000 * 0.7)
        self.behind = not reached
        self._compute_frame(wall)

    def _compute_frame(self, wall_dt):
        sim = self.sim
        live = self.live
        live.t = sim.t
        live.net_v = {net.name: sim.net_voltage(net.name) for net in sim.nets}
        live.wire_v = {wid: live.net_v.get(name, 0.0) for wid, name in self.wire_net.items()}
        parts = {}
        for d in sim.devices:
            info = {"blown": d.blown, "warn": d.warn}
            k = d.comp.kind
            extra = getattr(d, "live_extra", None)
            if extra is not None:            # parts that report their own look (RGB LEDs, solenoids …)
                info.update(extra())
            if k in ("led", "lamp"):
                info["_glow"] = d.take_glow()
            elif k == "motor":
                a = self._angle.get(d.cid, 0.0) + 360.0 * 1.5 * d.speed * wall_dt * min(self.speed, 1.0) ** 0.3
                self._angle[d.cid] = a % 360.0
                info["angle"] = self._angle[d.cid]
                info["speed"] = d.speed
                info["rpm"] = d.rpm
            elif k in ("relay", "relay_dpdt"):
                info["_on"] = d.on
            elif k == "optocoupler":
                info["_ir"] = d.take_glow()
            elif k == "ssr":
                info["_ir"] = d.take_glow()
                info["_on"] = d.drive > 0.5
            elif k == "buzzer":
                info["level"] = d.level()
            elif k == "sevenseg":
                info["_segs"] = d.take_lit()
            elif k == "logic_probe":
                vv, vl = getattr(d, "vd", 0.0), sim.vlogic
                info["_level"] = "H" if vv > 0.7 * vl else "L" if vv < 0.3 * vl else "?"
                info["reading_hint"] = f"{vv:.2f} V"
            r = d.reading()
            if r is not None:
                val, unit = r
                info["reading"] = fmt(round(val, 9) if abs(val) > 1e-9 else 0.0, unit, 3)
            if len(d.nodes) >= 2 and k not in ("ground",):
                names = [n for n, _x, _y in d.comp.part.pins]
                ia, ib = d.main_pins or (0, 1)       # transistors: the channel (C−E, D−S), not the control pin
                info["v"] = sim.node_voltage(d.nodes[ia]) - sim.node_voltage(d.nodes[ib])
                info["i"] = d.i_pins[ia]
                info["pins_v"] = {n: sim.node_voltage(d.nodes[i]) for i, n in enumerate(names[:len(d.nodes)])}
            power = getattr(d, "power", 0.0)
            if not power and not d.stores_energy and d.i_pins and len(d.i_pins) == len(d.nodes) and abs(sum(d.i_pins)) < 1e-6:
                # a part that didn't work its power out, wired fully through its pins: Σ voltage × current in
                power = sum(sim.node_voltage(n) * i for n, i in zip(d.nodes, d.i_pins))
            info["p"] = power
            parts[d.cid] = info
        live.parts = parts
        # current flow along the wires
        def pin_current(cid, pin):
            dev = sim.by_id.get(cid)
            if dev is None:
                return 0.0
            names = [n for n, _x, _y in dev.comp.part.pins]
            i = names.index(pin)
            return dev.i_pins[i] if i < len(dev.i_pins) else 0.0
        flows = []
        for a, b, amps in self.flow.solve(pin_current):
            key = (a, b)
            if abs(amps) < 1e-6:
                ph = self._phase.get(key, 0.0)
            else:
                # dots move faster for bigger currents (on a log scale: 1 µA slow … 1 A fast)
                spd = 18 + 16 * max(0.0, min(6.0, math.log10(abs(amps) / 1e-6)))
                ph = self._phase.get(key, 0.0) + math.copysign(spd, amps) * wall_dt
            self._phase[key] = ph
            flows.append((a, b, ph, amps))
        live.flows = flows
        live.samples, sim.record = sim.record, []
        for t, cid, vv in sim.spk_record:
            self.watches[cid].add(t, vv)
        sim.spk_record = []
        if self.sound is not None and self.state == "running":
            update_from_sim(self.sound.synth, sim, self.watches)
        for cid, text in sim.take_events():
            self.message.emit(cid, text)
        self.frame.emit()
