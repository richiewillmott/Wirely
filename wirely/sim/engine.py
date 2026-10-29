"""The circuit solver: turns a Circuit into equations and steps it through time (no Qt).

    sim = Simulator(circuit)
    sim.run_until(0.5)                 # simulate the first half second
    sim.net_voltage("N3"), sim.device(led.id).i_pins[0]

How it works (the same core method as SPICE):
  * every net becomes a node; a 0 V symbol makes a node 0 V. A separate circuit with no 0 V symbol gets the
    negative side of its battery as its 0 V, so its voltages read naturally;
  * each step solves the nodal equations with Newton–Raphson (for diodes / LEDs / transistors);
  * capacitors use the trapezoidal rule, with a backward-Euler step after anything jumps (a switch clicked,
    a part blowing) so nothing rings;
  * the time step grows while things change slowly and shrinks when they change fast, and a step that
    changes voltages too much is thrown away and redone smaller.
"""
from __future__ import annotations

import time

import numpy as np

from ..i18n import tr
from ..model.circuit import Circuit
from . import chips as CH
from . import devices as D
from . import extra as EX

D.FACTORY.update(CH.FACTORY)
D.FACTORY.update(EX.FACTORY)

GSHUNT = 1e-12


class ConvergenceError(RuntimeError):
    pass


class Simulator:
    MAX_ITER = 60
    ABSTOL, RELTOL = 1e-6, 1e-4

    def __init__(self, circuit: Circuit):
        self.circuit = circuit
        self.ctx = D.Ctx()
        self.t = 0.0
        self.events: list[tuple[str, str]] = []
        self.h = 1e-6
        self.h_max = 1e-3
        self.struggling = False
        self._jump = True            # next step must be backward Euler
        self._build()

    # ========================================================================================== netlist
    def _build(self):
        c = self.circuit
        self.nets = c.nets()
        pin_net = {}
        for net in self.nets:
            for cid, pin in net.pins:
                pin_net[(cid, pin)] = net.name
        # nets -> raw node numbers; every "0" net is ground (-1)
        names = sorted({n.name for n in self.nets if n.name != "0"})
        raw = {name: i for i, name in enumerate(names)}
        raw["0"] = -1
        self.devices: list[D.Device] = []
        self.by_id: dict[str, D.Device] = {}
        dev_raw_nodes = []
        for comp in c.components.values():
            cls = D.FACTORY.get(comp.kind)
            if cls is None:
                continue
            nodes = [raw[pin_net[(comp.id, name)]] for name, _x, _y in comp.part.pins]
            if comp.kind == "rail_pos":
                nodes = [nodes[0], -1]
            dev_raw_nodes.append((comp, cls, nodes))
        # find separate circuits ("islands") and give each one without 0 V a reference node
        parent = list(range(len(names)))

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        grounded = set()
        for comp, cls, nodes in dev_raw_nodes:
            # parts with electrically separate sides (an optoisolator's LED and transistor, a relay's coil and
            # contacts) only join up the pins within each side
            for group in getattr(cls, "pin_groups", None) or (tuple(range(len(nodes))),):
                gnodes = [nodes[i] for i in group if i < len(nodes)]
                real = [n for n in gnodes if n >= 0]
                if len(real) < len(gnodes):
                    for n in real:
                        grounded.add(n)
                for n in real[1:]:
                    ra, rb = find(real[0]), find(n)
                    if ra != rb:
                        parent[ra] = rb
        grounded_roots = {find(n) for n in grounded}
        ref_of_root = {}
        # prefer the negative terminal of a supply as the island's 0 V
        for comp, cls, nodes in dev_raw_nodes:
            if cls is D.Source and len(nodes) == 2 and nodes[1] >= 0:
                r = find(nodes[1])
                if r not in grounded_roots:
                    ref_of_root.setdefault(r, nodes[1])
        for n in range(len(names)):
            r = find(n)
            if r not in grounded_roots:
                ref_of_root.setdefault(r, n)
        refs = set(ref_of_root.values())
        # final numbering: references become ground
        index = {}
        k = 0
        for n in range(len(names)):
            if n in refs:
                index[n] = -1
            else:
                index[n] = k
                k += 1
        index[-1] = -1
        self.net_index = {name: index[raw[name]] for name in raw}
        self.n_nodes = k
        for comp, cls, nodes in dev_raw_nodes:
            dev = cls(comp, [index[n] for n in nodes])
            if dev.n_internal:
                dev.internal = list(range(k, k + dev.n_internal))
                k += dev.n_internal
            self.devices.append(dev)
            self.by_id[comp.id] = dev
        self.N = k
        # logic chips (and op-amps with unconnected supply pins) run from the highest supply voltage
        srcs = [d for d in self.devices if isinstance(d, D.Source)]
        self.vlogic = max([d.V for d in srcs if not isinstance(d, CH.SignalGen)]
                          + [d.off + d.amp for d in srcs if isinstance(d, CH.SignalGen)] + [0.0]) or 5.0
        lonely = {(cid, pin) for net in self.nets if len(net.pins) == 1 for cid, pin in net.pins}
        for d in self.devices:
            if hasattr(d, "vlogic"):
                d.vlogic = self.vlogic
            if isinstance(d, CH.Digital):
                d.out = d.compute()
            if isinstance(d, CH.OpAmp):
                d.auto_pos = (d.cid, "V+") in lonely
                d.auto_neg = (d.cid, "V-") in lonely
        self.switchers = [d for d in self.devices if hasattr(d, "crossing")]
        self.probe_nodes = {}
        for d in self.devices:
            if d.comp.kind == "scope_probe":
                self.probe_nodes[d.comp.value("channel")] = d.nodes[0]
        self.recording = False
        self.record = []
        self.speakers = {d.cid: (d.nodes[0], d.nodes[1]) for d in self.devices if d.comp.kind == "speaker"}
        self.spk_record = []
        self.x = np.zeros(self.N)
        self.nonlinear = any(d.nonlinear for d in self.devices)
        self.reactive = any(d.reactive or d.n_internal and isinstance(d, CH.OpAmp) for d in self.devices) or \
            any(isinstance(d, (CH.Digital, CH.Timer555, CH.SignalGen)) for d in self.devices)
        self.ac_freq = max([getattr(d, "freq", 0.0) for d in self.devices] + [0.0])
        for d in self.devices:
            d.accept(self.x, self.ctx)
            d.event = None
        # parts that give out light: the eye averages it (so PWM dims them, as in real life)
        self.lights = [d for d in self.devices if d.light_now() is not None]

    # ========================================================================================== solving
    def _solve_once(self, x0, ctx):
        """Newton–Raphson at one moment in time. Returns the solution or raises ConvergenceError."""
        x = x0.copy()
        N = self.N
        for d in self.devices:
            d.begin_iter()
        for it in range(self.MAX_ITER):
            # the equations are built in plain Python lists (much faster for many small additions than
            # numpy, element by element), then handed to numpy in one go for the solve
            A = [[0.0] * N for _ in range(N)]
            for k in range(N):
                A[k][k] = GSHUNT
            b = [0.0] * N
            S = D.Stamper(A, b)
            ctx.limited = False
            xl = x.tolist()
            for d in self.devices:
                d.stamp(S, xl, ctx)
            A = np.array(A)
            b = np.array(b)
            try:
                xn = np.linalg.solve(A, b)
            except np.linalg.LinAlgError:
                xn = np.linalg.lstsq(A, b, rcond=None)[0]
            if not np.all(np.isfinite(xn)):
                raise ConvergenceError(tr("numbers ran away"))
            dx = np.abs(xn - x)
            x = xn
            if not self.nonlinear:
                return x
            if not ctx.limited and np.all(dx <= self.ABSTOL + self.RELTOL * np.abs(x)):
                return x
        raise ConvergenceError(tr("no convergence"))

    def dc(self):
        """Steady DC answer with capacitors as open circuits (used by tests and for starting points)."""
        ctx = self.ctx
        ctx.dc, ctx.t = True, self.t
        try:
            try:
                x = self._solve_once(self.x, ctx)
            except ConvergenceError:
                # source stepping: bring the supplies up gradually
                x = np.zeros(self.N)
                for s in np.linspace(0.1, 1.0, 10):
                    ctx.source_scale = s
                    x = self._solve_once(x, ctx)
                ctx.source_scale = 1.0
            self.x = x
            for d in self.devices:
                d.accept(x, ctx)
                if hasattr(d, "after_dc"):
                    d.after_dc()
                elif d.reactive:
                    d.v_prev = getattr(d, "vd", 0.0)
                    d.i_prev = 0.0
            # logic outputs may have changed: solve again until everything agrees
            for _ in range(20):
                if not any(getattr(d, "changed", False) for d in self.devices):
                    break
                for d in self.devices:
                    if hasattr(d, "changed"):
                        d.changed = False
                x = self._solve_once(self.x, ctx)
                self.x = x
                for d in self.devices:
                    d.accept(x, ctx)
        finally:
            ctx.dc = False
            ctx.source_scale = 1.0
        return self.x

    def _span(self):
        vs = [abs(getattr(d, "V", 0.0)) for d in self.devices if isinstance(d, D.Source)]
        return max(vs + [1.0])

    def step(self, h_limit=None):
        """Take one accepted time step (shrinking it until it works). Returns the step size used."""
        ctx = self.ctx
        h = min(self.h, self.h_max, h_limit or 1e9)
        dv_max = 0.04 * self._span()
        tries = 0
        while True:
            ctx.h = h
            ctx.t = self.t + h
            ctx.method = "be" if self._jump else "trap"
            try:
                x = self._solve_once(self.x, ctx)
                dv = float(np.max(np.abs(x[:self.n_nodes] - self.x[:self.n_nodes]))) if self.n_nodes else 0.0
                if self.reactive and dv > 2 * dv_max and h > 1e-9 and not self._jump:
                    raise ConvergenceError(tr("too big a change"))
                # something switches inside this step: shorten the step to land on the switching moment
                if self.switchers and tries < 6 and h > 2e-9:
                    fr = [f for f in (d.crossing(self.x, x, self.t, self.t + h) for d in self.switchers)
                          if f is not None]
                    if fr and min(fr) < 0.995:
                        tries += 1
                        h = max(h * min(fr) * 1.0005, 1e-9)
                        continue
                break
            except ConvergenceError:
                if h <= 1e-10:
                    self.struggling = True
                    # give up on accuracy for this step rather than freezing
                    x = self.x
                    dv = 0.0
                    break
                h *= 0.25
        self.x = x
        self.t += h
        switched = False
        for d in self.devices:
            d.accept(x, ctx)
            ev = getattr(d, "event", None)
            if ev:
                self.events.append((d.cid, ev))
                d.event = None
                self._jump = True
            if getattr(d, "changed", False):
                d.changed = False
                switched = True
        for d in self.lights:
            d.see(h)
        if self.recording and self.speakers:
            for cid, (a, b) in self.speakers.items():
                self.spk_record.append((self.t, cid, (float(x[a]) if a >= 0 else 0.0) - (float(x[b]) if b >= 0 else 0.0)))
        if self.recording and self.probe_nodes:
            self.record.append((self.t, {ch: float(x[n]) if n >= 0 else 0.0 for ch, n in self.probe_nodes.items()}))
        was_jump = self._jump
        self._jump = False
        # choose the next step
        if self.reactive or self.ac_freq:
            if dv < 0.05 * dv_max and not was_jump:
                self.h = min(h * 4.0, self.h_max)      # almost nothing changing (e.g. just after a switch): catch up
            elif dv < 0.5 * dv_max or was_jump:
                self.h = min(h * 1.8, self.h_max)
            elif dv > dv_max:
                self.h = max(h * 0.5, 1e-9)
            else:
                self.h = h
        else:
            self.h = self.h_max
        if switched:            # a chip switched: take small steps for a moment to follow what happens next
            self._jump = True
            self.h = min(self.h, 1e-6)
        return h

    def run_until(self, t_end: float, budget_s: float | None = None) -> bool:
        """Advance to t_end. With a time budget (seconds of real time), stop early when it runs out
        and return False (the circuit is too busy to keep up in real time)."""
        start = time.perf_counter()
        if self.ac_freq:
            self.h_max = min(self.h_max, 1.0 / (self.ac_freq * 40))
        while self.t < t_end - 1e-15:
            self.step(t_end - self.t)
            if budget_s is not None and time.perf_counter() - start > budget_s:
                return False
        return True

    def transient(self, t_end: float, h_max: float, probe):
        """Run from now to t_end and record probe() after every step: [(t, value), …] (for tests)."""
        self.h_max = h_max
        out = [(self.t, probe(self))]
        while self.t < t_end - 1e-15:
            self.step(t_end - self.t)
            out.append((self.t, probe(self)))
        return out

    # ========================================================================================== live changes
    def set_value(self, cid: str, key: str, value):
        """A switch was clicked or a slider moved while running."""
        d = self.by_id.get(cid)
        if d is None:
            return
        d.comp.props[key] = value
        d.update_params()
        self._jump = True
        self.h = min(self.h, max(self.h_max / 50, 1e-7))

    # ========================================================================================== results
    def node_voltage(self, idx: int) -> float:
        return float(self.x[idx]) if idx >= 0 else 0.0

    def net_voltage(self, name: str) -> float:
        return self.node_voltage(self.net_index.get(name, -1))

    def pin_voltage(self, cid: str, pin: str) -> float:
        d = self.by_id[cid]
        names = [n for n, _x, _y in d.comp.part.pins]
        return self.node_voltage(d.nodes[names.index(pin)])

    def device(self, cid: str) -> D.Device:
        return self.by_id[cid]

    def take_events(self):
        ev, self.events = self.events, []
        return ev
