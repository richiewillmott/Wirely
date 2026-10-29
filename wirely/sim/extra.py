"""Models for the parts added in 1.4.0 (no Qt): bi-colour and RGB LEDs, the bridge rectifier, the thyristor,
voltage regulators, the transformer, the DPDT switch, the Hall effect sensor, the solenoid, the comparator and
the 4026 and 4060 counters.

Several of them are built from the solver's existing parts — the LEDs and the bridge from the Diode model, the
thyristor from two Ebers–Moll transistors — so they behave exactly like those do.
"""
from __future__ import annotations

import math

from ..i18n import tr
from .chips import Digital, Relay, SEGMENTS, frac_cross, numeric_stamp, softplus
from .devices import Diode, Device, R_OFF, R_ON, RsDiode as _RsDiode, spike_message, v


class _Sub:
    """Stands in for a placed part, so a part can be built from other parts' models (one LED of an RGB LED …)."""

    def __init__(self, parent, kind, props):
        self.kind, self.id, self._props = kind, "", props
        self.ref = parent.ref
        self.part = None

    def value(self, key):
        return self._props.get(key)


# ============================================================================================ LEDs
LED_MIX = {"Red": (255, 59, 48), "Green": (47, 209, 88), "Blue": (47, 123, 255)}


class MultiLED(Device):
    """Two or three LEDs in one package (bi-colour, RGB). Each is the ordinary LED model."""
    nonlinear = True
    LAYOUT = {  # colour, anode pin index, cathode pin index
        "led_bi2": (("Red", 0, 1), ("Green", 1, 0)),
        "led_bi3": (("Red", 0, 2), ("Green", 1, 2)),
        "led_rgb": (("Red", 0, 3), ("Green", 1, 3), ("Blue", 2, 3)),
    }

    # RGB LEDs use the same kind of chip for green as for blue (InGaN, about 3.1 V) — not the 2.1 V green of an
    # ordinary green LED. So with one shared resistor, red (lowest voltage) takes nearly all the current, while
    # green and blue share it.
    CHIP = {"led_rgb": {"Green": "True green"}}

    def update_params(self):
        imax = float(self.prop("max_current") or 0.03)
        self.layout = self.LAYOUT[self.comp.kind]
        self.n_internal = len(self.layout)
        chip = self.CHIP.get(self.comp.kind, {})
        self.leds = [Diode(_Sub(self.comp, "led", {"colour": chip.get(col, col), "max_current": imax}),
                           [self.nodes[a], self.nodes[k]]) for col, a, k in self.layout]

    def _wire(self):
        for led, node in zip(self.leds, self.internal):
            led.internal = [node]

    def begin_iter(self):
        for led in self.leds:
            led.begin_iter()

    def stamp(self, S, x, ctx):
        self._wire()
        for led in self.leds:
            led.stamp(S, x, ctx)

    def accept(self, x, ctx):
        self._wire()
        pins = [0.0] * len(self.nodes)
        self.power, warn = 0.0, None
        for led, (_c, a, k) in zip(self.leds, self.layout):
            led.accept(x, ctx)
            pins[a] += led.current
            pins[k] -= led.current
            self.power += led.power
            warn = warn or led.warn
            if led.event:
                self.event, led.event = led.event, None
        self.i_pins = pins
        self.warn = warn
        self.blown = any(led.blown for led in self.leds)

    def glows(self):
        return [led.glow() for led in self.leds]

    def light_now(self):
        return [led.light_now()[0] for led in self.leds]

    def live_extra(self):
        g = self.take_light()
        r = gg = b = 0.0
        for k, (col, _a, _k) in zip(g, self.layout):
            cr, cg, cb = LED_MIX[col]
            r, gg, b = r + k * cr, gg + k * cg, b + k * cb
        top = max(r, gg, b, 1.0)
        f = 255.0 / top
        mix = "#%02x%02x%02x" % (int(r * f), int(gg * f), int(b * f))
        return {"_glows": [round(k, 3) for k in g], "_glow": max(g + [0.0]), "_rgb": mix}


class Bridge(Device):
    """Bridge rectifier: four diodes. Pins AC1, AC2, +, −."""
    nonlinear = True
    n_internal = 4
    PAIRS = ((0, 2), (1, 2), (3, 0), (3, 1))        # (anode pin, cathode pin) of each diode

    def update_params(self):
        rating = float(self.prop("rating") or 1.0)
        self.diodes = []
        for a, k in self.PAIRS:
            d = Diode(_Sub(self.comp, "diode", {"model": "1N4001"}), [self.nodes[a], self.nodes[k]])
            d.imax = rating
            d.surge_time = 8e-3             # bridges are rated for a surge of ~30 × for a mains half-cycle
            self.diodes.append(d)

    def _wire(self):
        for d, node in zip(self.diodes, self.internal):
            d.internal = [node]

    def begin_iter(self):
        for d in self.diodes:
            d.begin_iter()

    G_LEAK = 1e-7       # 10 MΩ from each AC pin to −: when all four diodes are off (between the peaks, with a
    #                     smoothing capacitor) the AC side would otherwise float with nothing to fix its voltage

    def stamp(self, S, x, ctx):
        self._wire()
        for d in self.diodes:
            d.stamp(S, x, ctx)
        for k in (0, 1):
            S.g(self.nodes[k], self.nodes[3], self.G_LEAK)

    def accept(self, x, ctx):
        self._wire()
        pins = [0.0] * 4
        for k in (0, 1):
            il = (v(x, self.nodes[k]) - v(x, self.nodes[3])) * self.G_LEAK
            pins[k] += il
            pins[3] -= il
        self.power = 0.0
        warn = None
        for d, (a, k) in zip(self.diodes, self.PAIRS):
            d.accept(x, ctx)
            pins[a] += d.current
            pins[k] -= d.current
            self.power += d.power
            warn = warn or d.warn
            if d.event:
                self.event = tr("{ref} burnt out — one of its diodes carried more than its "
                                "{imax:g} A rating.",
                                ref=self.comp.ref, imax=d.imax)
                d.event = None
        self.i_pins = pins
        self.warn = warn
        self.blown = any(d.blown for d in self.diodes)


# ============================================================================================ thyristor
# type: max on-state current (A), max off-state voltage (V), gate trigger current (A), holding current (A)
SCRS = {
    "C106D": (4.0, 400.0, 0.2e-3, 3e-3),
    "2N5060": (0.8, 30.0, 0.2e-3, 5e-3),
    "TIC106D": (5.0, 400.0, 0.2e-3, 2e-3),
    "BT151": (12.0, 500.0, 2e-3, 7e-3),
}


class SCR(Device):
    """Thyristor: the gate–cathode is a junction (with a resistor across it inside); the anode–cathode is off
    until the gate current passes the trigger current, then it conducts like a diode (about 1 V) and stays on —
    with no gate current — until the anode current falls below the holding current. (The two-transistor picture
    of why it latches; modelled by its datasheet figures so it switches cleanly.) Pins A, K, G."""
    nonlinear = True
    n_internal = 2
    RGK = 1000.0

    def update_params(self):
        self.imax, self.vdrm, self.igt, self.ih = SCRS.get(self.prop("model"), SCRS["C106D"])
        self.main = Diode(_Sub(self.comp, "diode", {"model": "1N5408"}), [self.nodes[0], self.nodes[1]])
        self.main.imax = self.imax
        self.main.surge_time = 8e-3
        self.gate = Diode(_Sub(self.comp, "diode", {"model": "1N4148"}), [self.nodes[2], self.nodes[1]])
        self.gate.imax = 1.0
        if not hasattr(self, "on"):
            self.on = False
            self.changed = False

    def _wire(self):
        self.main.internal = [self.internal[0]]
        self.gate.internal = [self.internal[1]]

    def begin_iter(self):
        self.main.begin_iter()
        self.gate.begin_iter()

    def stamp(self, S, x, ctx):
        a, k, g = self.nodes
        self._wire()
        if self.blown:                               # burnt out: open circuit
            S.g(a, k, 1 / R_OFF)
            S.g(g, k, 1 / R_OFF)
            S.g(a, self.internal[0], 1.0)
            S.g(g, self.internal[1], 1.0)
            return
        S.g(g, k, 1 / self.RGK)
        self.gate.stamp(S, x, ctx)
        if self.on and not self.blown:
            self.main.stamp(S, x, ctx)
        else:
            S.g(a, k, 1 / R_OFF)
            S.g(a, self.internal[0], 1.0)            # keep the unused inside node tied down

    def accept(self, x, ctx):
        a, k, g = self.nodes
        self._wire()
        va, vk, vg = v(x, a), v(x, k), v(x, g)
        if self.blown:
            i_a, i_g = (va - vk) / R_OFF, (vg - vk) / R_OFF
            self.i_pins = [i_a, -(i_a + i_g), i_g]
            self.current, self.vd, self.power, self.on = i_a, va - vk, 0.0, False
            return
        self.gate.accept(x, ctx)
        i_g = self.gate.current + (vg - vk) / self.RGK
        if self.gate.event:                           # far too much gate current
            self.gate.event = None
            self.blown = self._told = True
            self.on = False
            self.event = tr("{ref} burnt out — {i_g:.1f} A into its gate. The gate only needs a few "
                            "milliamps: put a resistor (1 kΩ or so) in series with it.",
                            ref=self.comp.ref, i_g=abs(i_g))
            self.i_pins = [0.0, -i_g, i_g]
            return
        if self.on and not self.blown:
            self.main.accept(x, ctx)
            i_a = self.main.current
            if self.main.event:
                self.main.event = None
                self.blown = True
        else:
            i_a = (va - vk) / R_OFF
        self.i_pins = [i_a, -(i_a + i_g), i_g]
        self.current, self.vd = i_a, va - vk
        self.power = i_a * (va - vk) + i_g * (vg - vk)
        # latch on when triggered (or when the voltage across it breaks over its rating); let go below holding
        on = self.on
        if not on and (i_g >= self.igt or self.vd > self.vdrm) and self.vd > 0:
            on = True
        elif on and i_a < self.ih and i_g < self.igt:
            on = False          # lets go below its holding current — but not while the gate is still driven
            #                     (into a coil the current takes a moment to build up)
        if on != self.on:
            self.on = on
            self.changed = True
        model = self.prop("model")
        if self.blown:
            self.on = False
            if not getattr(self, "_told", False):
                self._told = True
                self.event = tr("{ref} burnt out — {i_a:.1f} A is more than a {model} can carry "
                                "({imax:g} A).",
                                ref=self.comp.ref, i_a=abs(i_a), model=model, imax=self.imax)
            return
        if abs(self.vd) > 1.2 * self.vdrm:
            self.blown = True
            self.event = spike_message(self.comp.ref, abs(self.vd), self.vdrm)
            return
        bad = abs(i_a) > self.imax
        self.warn = "over" if bad else None
        if self._overload(bad, ctx.h, 0.1, abs(i_a) > 5 * self.imax):
            self.blown = self._told = True
            self.on = False
            self.event = tr("{ref} burnt out — {i_a:.1f} A is more than a {model} can carry "
                            "({imax:g} A).",
                            ref=self.comp.ref, i_a=abs(i_a), model=model, imax=self.imax)

    def live_extra(self):
        return {"_on": bool(self.on and not self.blown)}


# ============================================================================================ regulators
# output voltage (relative to GND / ADJ), dropout (V), current limit (A), current out of the GND/ADJ pin (A),
# max input voltage (V)
REGS = {
    "7805": (5.0, 2.0, 1.5, 5e-3, 35.0),
    "7809": (9.0, 2.0, 1.5, 5e-3, 35.0),
    "7812": (12.0, 2.0, 1.5, 5e-3, 35.0),
    "LM1117-3.3": (3.3, 1.1, 0.8, 5e-3, 15.0),
    "LM317": (1.25, 1.8, 1.5, 50e-6, 40.0),
}


def smoothmin(a, b, s):
    return b - softplus(b - a, s)


class Regulator(Device):
    """Linear regulator (78xx, LM1117, LM317): a pass transistor that holds OUT at a set voltage above its GND
    (or ADJ) pin — as long as the input is enough higher (the dropout voltage) — and limits its current. The
    difference between input and output voltage, times the current, is turned into heat; too much and it shuts
    itself down until it cools (as real ones do). Pins IN, GND/ADJ, OUT."""
    nonlinear = True
    RO = 0.02           # output resistance (Ω)
    ISINK = 1e-3        # it can hardly sink current
    TAU = 3.0           # how quickly it heats up (s)

    def update_params(self):
        model = "LM317" if self.comp.kind == "reg_adj" else self.prop("model")
        self.model = model
        self.vreg, self.drop, self.ilim, self.iq, self.vin_max = REGS.get(model, REGS["7805"])
        self.pmax = 15.0 if self.prop("heatsink") else 1.5
        # dropout: about 60 % of the datasheet figure at no load, rising to all of it at the current limit
        self.drop0 = 0.6 * self.drop
        self.rdrop = 0.4 * self.drop / self.ilim
        # its inside protection path: current flows back from OUT to IN if OUT is ever higher (wired the wrong
        # way round, or a big output capacitor when the input is switched off)
        self.rev = _RsDiode(self.nodes[2], self.nodes[0], Rs=1.0)
        if not hasattr(self, "hot"):
            self.hot = False
            self.heat = 0.0
            self.mode = "lin"
            self.changed = False

    def _err(self, V):
        """How far the output is below where the regulator wants it (V)."""
        vin, vg, vo = V
        head = vin - vg - self.drop
        target = smoothmin(self.vreg, head, 0.05)
        target = softplus(target, 0.02)                 # never below its GND pin
        return target - (vo - vg)

    def _f(self, V):
        vin, vg, vo = V
        e = self._err(V)
        # the output stage is in one of four states, decided after each accepted step (like a real regulator's
        # dropout, current-limit and pass-transistor-off conditions); within each one the equations are smooth and
        # linear, so the solver converges easily
        if self.mode == "lin":                          # holding OUT at its set voltage
            i = (self.vreg - (vo - vg)) / self.RO
        elif self.mode == "drop":                       # input too low: the pass transistor is fully on
            i = (vin - vo - self.drop0) / self.rdrop
        elif self.mode == "lim":
            i = (1e-4 if self.hot else self.ilim) + e * 1e-6
        else:                                           # output above where it wants to be: pass transistor off
            i = e * 1e-6
        iq = self.iq * math.tanh(softplus(vin - vg, 0.05) / 1.0)
        if self.mode == "drop":                         # straight from IN to OUT (either way, for a moment)
            return [i + iq, -iq, -i]
        i_pos = 0.5 * (i + math.sqrt(i * i + 1e-12))
        i_neg = i - i_pos                               # sinking: flows from OUT to GND
        return [i_pos + iq, -iq - i_neg, -i]

    def stamp(self, S, x, ctx):
        nodes = self.nodes
        if self.blown:
            S.g(nodes[0], nodes[2], 1 / R_OFF)
            return
        V0 = [v(x, n) for n in nodes]
        numeric_stamp(S, nodes, V0, self._f)
        self.rev.stamp(S, x)

    def accept(self, x, ctx):
        V = [v(x, n) for n in self.nodes]
        if self.blown:
            i = (V[0] - V[2]) / R_OFF
            self.i_pins = [i, 0.0, -i]
            return
        e = self._err(V)
        ilim = 1e-4 if self.hot else self.ilim
        vin, vg, vo = V
        self.i_pins = self._f(V)                        # with the state this solution was found with
        self.rev.accept(x)
        self.i_pins[2] += self.rev.current
        self.i_pins[0] -= self.rev.current
        mode = self.mode
        # which state the output stage is in, from the state it was in (each has its own straight-line equation;
        # the small margins stop it flicking back and forth on a boundary)
        if mode == "lin":
            i = (self.vreg - (vo - vg)) / self.RO
            if i < -self.ISINK:                             # OUT is above where it should be: pass transistor off
                mode = "off"
            elif vin - vo - self.drop0 - self.rdrop * min(i, ilim) < -1e-3:      # not enough input to spare
                mode = "drop"
            elif i > ilim * 1.001:
                mode = "lim"
        elif mode == "drop":
            i = (vin - vo - self.drop0) / self.rdrop
            if i < -self.ISINK:                             # OUT above IN (wired the wrong way round, say)
                mode = "off"
            elif vo - vg > self.vreg + 1e-3:
                mode = "lin"
            elif i > ilim * 1.001:
                mode = "lim"
        elif mode == "lim":
            # the most it could give at the current limit, holding its voltage or with its input running out
            v_lin = vg + self.vreg - self.RO * ilim
            v_drop = vin - self.drop0 - self.rdrop * ilim
            if vo > min(v_lin, v_drop) + 1e-3:          # the load doesn't need the full current any more
                mode = "lin" if v_lin <= v_drop else "drop"
        elif mode == "off" and e > 1e-3 and vin - vo - self.drop0 > 1e-3:
            mode = "lin"            # OUT has fallen below where it should be, and there's input to spare to lift it
        if mode != self.mode:
            self.mode = mode
            self.changed = True
        iout = -self.i_pins[2]
        self.current = iout
        self.vd = V[0] - V[1]
        self.power = self.i_pins[0] * V[0] + self.i_pins[1] * V[1] + self.i_pins[2] * V[2]
        if self.vd > 1.1 * self.vin_max:
            self.blown = True
            self.event = tr("{ref} was destroyed — {vd:.0f} V on its input is more than a {model} "
                            "can take ({vin_max:g} V).",
                            ref=self.comp.ref, vd=self.vd, model=self.model, vin_max=self.vin_max)
            return
        if ctx.dc:
            self.heat = 0.0
        else:
            self.heat += (self.power - self.heat) * (1 - math.exp(-ctx.h / self.TAU))
        was = self.hot
        if not self.hot and self.heat > self.pmax:
            self.hot = True
            if not getattr(self, "_told", False):
                self._told = True
                if self.prop("heatsink"):
                    self.event = tr("{ref} got too hot and switched itself off — it's turning {power:.1f} W into "
                                    "heat (input − output voltage × current). Use a lower input voltage or a "
                                    "smaller load.", ref=self.comp.ref, power=self.power)
                else:
                    self.event = tr("{ref} got too hot and switched itself off — it's turning {power:.1f} W into "
                                    "heat (input − output voltage × current). Put it on a heatsink, or use a "
                                    "lower input voltage or a smaller load.", ref=self.comp.ref, power=self.power)
        elif self.hot and self.heat < 0.7 * self.pmax:
            self.hot = False
        if self.hot != was:
            self.changed = True
        self.warn = "hot" if (self.hot or self.heat > 0.8 * self.pmax) else None

    def after_dc(self):
        pass


# ============================================================================================ transformer
class Transformer(Device):
    """Transformer: the secondary (S1–S2) is the primary voltage divided by the turns ratio, behind its winding
    resistance, and the primary carries the matching current; plus the core's magnetising inductance across the
    primary — so on DC the primary is just a coil, and passes nothing across. Pins P1, P2, S1, S2."""
    reactive = True
    pin_groups = ((0, 1), (2, 3))          # the two windings are separate circuits
    RS = 0.5                               # winding resistance, seen from the secondary (Ω)
    LM = 10.0                              # magnetising inductance of the primary (H)
    RP = 1e6

    def update_params(self):
        self.n = max(1e-3, float(self.prop("ratio")))
        self.rating = float(self.prop("rating") or 5.0)
        if not hasattr(self, "i_prev"):
            self.i_prev = self.v_prev = 0.0
            self.heat = 0.0

    def companion(self, ctx):
        if ctx.method == "trap":
            G = ctx.h / (2 * self.LM)
            return G, self.i_prev + G * self.v_prev
        G = ctx.h / self.LM
        return G, self.i_prev

    def _rows(self):
        n, rs = self.n, self.RS
        s1 = [-1 / (n * rs), 1 / (n * rs), 1 / rs, -1 / rs]
        return [[-x / n for x in s1], [x / n for x in s1], s1, [-x for x in s1]]

    def stamp(self, S, x, ctx):
        p1, p2, s1, s2 = self.nodes
        J = self._rows()
        V0 = [v(x, n) for n in self.nodes]
        I0 = [sum(J[k][j] * V0[j] for j in range(4)) for k in range(4)]
        S.nonlinear(self.nodes, I0, J, V0)
        S.g(p1, p2, 1 / self.RP)
        if ctx.dc:
            S.g(p1, p2, 1e3)
            return
        G, Ieq = self.companion(ctx)
        S.g(p1, p2, G)
        S.i(p1, p2, Ieq)

    def accept(self, x, ctx):
        p1, p2, s1, s2 = self.nodes
        V = [v(x, n) for n in self.nodes]
        J = self._rows()
        I = [sum(J[k][j] * V[j] for j in range(4)) for k in range(4)]
        vp = V[0] - V[1]
        if ctx.dc:
            im = vp * 1e3
        else:
            G, Ieq = self.companion(ctx)
            im = G * vp + Ieq
        self.i_prev, self.v_prev = im, vp
        extra = im + vp / self.RP
        I[0] += extra
        I[1] -= extra
        self.i_pins = I
        self.vd = vp
        self.current = I[0]
        p_out = abs((V[2] - V[3]) * I[2])
        self.power = p_out
        h = 0.0 if ctx.dc else ctx.h
        self.heat += (p_out - self.heat) * (1 - math.exp(-h / 2.0)) if h else 0.0
        self.warn = "hot" if self.heat > self.rating else None
        if abs(im) > 2.0 and not getattr(self, "_dc_told", False):
            self._dc_told = True
            self.event = tr("{ref}: a transformer only works with AC — on DC its primary is just a coil of "
                            "wire, so it lets a big current through and passes nothing to the secondary.",
                            ref=self.comp.ref)
        if not self.blown and self._overload(self.heat > 2 * self.rating, h, 1.0):
            self.blown = True
            self.event = tr("{ref} overheated — {heat:.1f} W is far more than its "
                            "{rating:g} W rating.",
                            ref=self.comp.ref, heat=self.heat, rating=self.rating)

    def after_dc(self):
        pass


# ============================================================================================ switches & sensors
class DPDT(Device):
    """Two changeover switches worked together. Pins com1, a1, b1, com2, a2, b2."""

    def _g(self):
        to_a = self.prop("position") == "A"
        return (1 / (R_ON if to_a else R_OFF)), (1 / (R_OFF if to_a else R_ON))

    def stamp(self, S, x, ctx):
        ga, gb = self._g()
        for k in (0, 3):
            com, a, b = self.nodes[k:k + 3]
            S.g(com, a, ga)
            S.g(com, b, gb)

    def accept(self, x, ctx):
        ga, gb = self._g()
        pins = []
        for k in (0, 3):
            com, a, b = self.nodes[k:k + 3]
            ia = (v(x, com) - v(x, a)) * ga
            ib = (v(x, com) - v(x, b)) * gb
            pins += [ia + ib, -ia, -ib]
        self.i_pins = pins


class Hall(Device):
    """Hall effect switch (A3144 type): draws about 4 mA from its supply; with a magnet near (and at least
    4.5 V on VCC), its open-collector output pulls OUT down to GND. Pins VCC, GND, OUT."""
    R_SUPPLY = 2700.0
    R_SAT = 20.0
    IMAX = 0.025

    def update_params(self):
        if not hasattr(self, "on"):
            self.on = False
            self.changed = False

    def stamp(self, S, x, ctx):
        vcc, gnd, out = self.nodes
        S.g(vcc, gnd, 1 / self.R_SUPPLY)
        S.g(out, gnd, 1 / (self.R_SAT if (self.on and not self.blown) else R_OFF))

    def accept(self, x, ctx):
        vcc, gnd, out = self.nodes
        supply = v(x, vcc) - v(x, gnd)
        isup = supply / self.R_SUPPLY
        # the current that flowed in this step (with the output as it was during the step)
        iout = (v(x, out) - v(x, gnd)) / (self.R_SAT if (self.on and not self.blown) else R_OFF)
        on = bool(self.prop("magnet")) and supply >= 4.5
        if on != self.on:
            self.on = on
            self.changed = True
        self.i_pins = [isup, -isup - iout, iout]
        self.vd = supply
        self.current = iout
        self.power = supply * isup + (v(x, out) - v(x, gnd)) * iout
        if self.blown:
            return
        self.warn = "over" if iout > self.IMAX else None
        if supply > 28 or self._overload(iout > self.IMAX, ctx.h, 0.1, iout > 4 * self.IMAX):
            self.blown = True
            if supply > 28:
                self.event = tr("{ref} was destroyed — {supply:.0f} V is more than its 24 V limit.",
                                ref=self.comp.ref, supply=supply)
            else:
                self.event = tr("{ref} was destroyed — {iout:.0f} mA through its output is too much (max 25 mA): "
                                "use a bigger pull-up resistor.", ref=self.comp.ref, iout=iout * 1000)


class Solenoid(Device):
    """Solenoid: a coil (resistance + inductance) that pulls its plunger in above about 60 % of its rated
    current and lets go below 30 %. Like a relay coil, switching it off makes a big voltage spike."""
    n_internal = 1
    reactive = True
    RP = 100e3

    def update_params(self):
        self.V = float(self.prop("voltage"))
        self.Rc = max(1.0, self.V / 0.25)            # about 0.25 A (3 W at 12 V)
        self.L = self.Rc * 5e-3                       # time constant 5 ms
        self.i_pull = 0.6 * self.V / self.Rc
        self.i_drop = 0.3 * self.V / self.Rc
        if not hasattr(self, "on"):
            self.on = False
            self.i_prev = self.v_prev = 0.0
            self.clicks = 0
            self.changed = False

    def companion(self, ctx):
        if ctx.method == "trap":
            G = ctx.h / (2 * self.L)
            return G, self.i_prev + G * self.v_prev
        G = ctx.h / self.L
        return G, self.i_prev

    def stamp(self, S, x, ctx):
        a, c = self.nodes
        k = self.internal[0]
        S.g(a, c, 1 / self.RP)
        if self.blown:
            S.g(a, k, 1 / R_OFF)
            S.g(k, c, 1.0)
            return
        S.g(a, k, 1 / self.Rc)
        if ctx.dc:
            S.g(k, c, 1e3)
        else:
            G, Ieq = self.companion(ctx)
            S.g(k, c, G)
            S.i(k, c, Ieq)

    def accept(self, x, ctx):
        a, c = self.nodes
        k = self.internal[0]
        if self.blown:
            i = 0.0
        elif ctx.dc:
            i = (v(x, k) - v(x, c)) * 1e3
        else:
            G, Ieq = self.companion(ctx)
            i = G * (v(x, k) - v(x, c)) + Ieq
        self.i_prev, self.v_prev = i, v(x, k) - v(x, c)
        on = (abs(i) >= self.i_pull) if not self.on else (abs(i) > self.i_drop)
        if on != self.on:
            self.on = on
            self.changed = True
            self.clicks += 1
        vd = v(x, a) - v(x, c)
        tot = i + vd / self.RP
        self.i_pins = [tot, -tot]
        self.vd, self.current = vd, i
        self.power = vd * tot
        if self.blown:
            return
        h = 0.0 if ctx.dc else ctx.h
        self.warn = "hot" if abs(vd) > 1.3 * self.V else None
        if self._overload(abs(vd) > 1.5 * self.V, h, 2.0, abs(vd) > 4 * self.V):
            self.blown = True
            self.on = False
            self.event = tr("{ref} burnt out — {vd:.0f} V is too much for a {V:g} V solenoid: "
                            "its coil overheated.",
                            ref=self.comp.ref, vd=abs(vd), V=self.V)

    def after_dc(self):
        pass

    def live_extra(self):
        return {"_on": self.on}


# ============================================================================================ comparator
# on-resistance of the output (Ω), most current it can sink (A)
COMPARATORS = {"LM393": (60.0, 0.016), "LM311": (20.0, 0.05)}


class Comparator(Device):
    """Comparator with an open-collector output: when − is above +, OUT is pulled to 0 V (through a small
    resistance, with the chip's current limit); otherwise OUT is off. It switches the moment the inputs cross
    (the engine lands a time step there), like a real one. Pins +, −, OUT."""
    nonlinear = True
    R_IN = 10e6

    def update_params(self):
        self.ron, self.isc = COMPARATORS.get(self.prop("model"), COMPARATORS["LM393"])
        if not hasattr(self, "low"):
            self.low = False
            self.changed = False

    def _iout(self, vo):
        if not self.low or self.blown:
            return vo / R_OFF, 1 / R_OFF
        return vo / self.ron, 1 / self.ron

    def stamp(self, S, x, ctx):
        p, m, o = self.nodes
        S.g(p, -1, 1 / self.R_IN)
        S.g(m, -1, 1 / self.R_IN)
        vo = v(x, o)
        i, g = self._iout(vo)
        S.g(o, -1, g)
        S.i(o, -1, i - g * vo)

    def crossing(self, xo, xn, t0, t1):
        p, m, _o = self.nodes
        d0, d1 = v(xo, m) - v(xo, p), v(xn, m) - v(xn, p)
        return frac_cross(d0, d1, 0.0, not self.low)

    def accept(self, x, ctx):
        p, m, o = self.nodes
        d = v(x, m) - v(x, p)
        vo = v(x, o)
        i, _g = self._iout(vo)                  # (as it was during this step)
        low = d > 0.0005 if not self.low else d > -0.0005
        if low != self.low:
            self.low = low
            self.changed = True
        self.i_pins = [v(x, p) / self.R_IN, v(x, m) / self.R_IN, i]
        self.vd = vo
        self.current = i
        self.power = vo * i
        if self.blown:
            return
        bad = abs(i) > self.isc
        self.warn = "over" if bad else None
        if self._overload(bad, ctx.h, 0.2, abs(i) > 6 * self.isc):
            self.blown = True
            self.event = tr("{ref} burnt out — its output had to sink {i:.0f} mA (a "
                            "{model} can take {isc:.0f} mA). Use a bigger pull-up resistor.",
                            ref=self.comp.ref, i=abs(i) * 1000, model=self.prop('model'), isc=self.isc * 1000)


# ============================================================================================ counters
class Counter4026(Digital):
    """4026: decade counter with outputs for a 7-segment display. Counts on rising CLK (unless INH is high),
    RST high resets to 0. CO is high for counts 0–4, so it rises as the count goes 9 → 0 (to clock the tens)."""
    inputs = ("CLK", "INH", "RST")
    outputs = tuple("abcdefg") + ("CO",)

    def reset_state(self):
        self.count = 0

    def clock(self, rising):
        if self.level["RST"]:
            self.count = 0
        elif rising.get("CLK") and not self.level["INH"]:
            self.count = (self.count + 1) % 10

    def compute(self):
        lit = SEGMENTS[self.count]
        out = {s: s in lit for s in "abcdefg"}
        out["CO"] = self.count < 5
        return out


class Counter4060(Digital):
    """4060: 14-stage binary counter with an oscillator. φI is a Schmitt-trigger input, φO is its inverse and φO̅
    the inverse of that, so a resistor and capacitor round them oscillate. The counter moves on each falling edge
    of φI; Q4 … Q14 (Q11 isn't brought out) divide it by 16 … 16384. MR high resets it. (Its small input
    hysteresis gives about the datasheet's frequency, 1 ÷ (2.3 R C).)"""
    inputs = ("PI", "MR")
    outputs = ("PO", "POn", "Q4", "Q5", "Q6", "Q7", "Q8", "Q9", "Q10", "Q12", "Q13", "Q14")

    def reset_state(self):
        self.count = 0
        self.last_pi = False

    def thresholds(self):
        return 0.52 * self.vlogic, 0.48 * self.vlogic

    def clock(self, rising):
        pi = self.level["PI"]
        if self.level["MR"]:
            self.count = 0
        elif self.last_pi and not pi:
            self.count = (self.count + 1) % 16384
        self.last_pi = pi

    def compute(self):
        pi = self.level["PI"]
        out = {"PO": not pi, "POn": pi}
        for n in (4, 5, 6, 7, 8, 9, 10, 12, 13, 14):
            out[f"Q{n}"] = bool((self.count >> (n - 1)) & 1)
        return out



class RelayDPDT(Relay):
    """A relay with two changeover contact sets worked by one coil: COM1–NC1/NO1 and COM2–NC2/NO2."""
    pin_groups = ((0, 1), (2, 3, 4), (5, 6, 7))

    def stamp(self, S, x, ctx):
        c1, c2 = self.nodes[0], self.nodes[1]
        k = self.internal[0]
        S.g(c1, k, 1 / self.Rc)
        S.g(c1, c2, 1 / self.RP)
        if ctx.dc:
            S.g(k, c2, 1e3)
        else:
            G, Ieq = self.companion(ctx)
            S.g(k, c2, G)
            S.i(k, c2, Ieq)
            self._G, self._Ieq = G, Ieq
        r_no, r_nc = (R_ON, R_OFF) if self.on else (R_OFF, R_ON)
        for com, nc, no in (self.nodes[2:5], self.nodes[5:8]):
            S.g(com, no, 1 / r_no)
            S.g(com, nc, 1 / r_nc)

    def accept(self, x, ctx):
        c1, c2 = self.nodes[0], self.nodes[1]
        k = self.internal[0]
        i = self.coil_current(x, ctx)
        self.i_prev, self.v_prev = i, v(x, k) - v(x, c2)
        icoil = i + (v(x, c1) - v(x, c2)) / self.RP
        r_no, r_nc = (R_ON, R_OFF) if self.on else (R_OFF, R_ON)        # contacts as they were for this step
        pins = [icoil, -icoil]
        for com, nc, no in (self.nodes[2:5], self.nodes[5:8]):
            ino = (v(x, com) - v(x, no)) / r_no
            inc = (v(x, com) - v(x, nc)) / r_nc
            pins += [ino + inc, -inc, -ino]
        self.i_pins = pins
        on = (abs(i) >= self.i_pull) if not self.on else (abs(i) > self.i_drop)
        if on != self.on:
            self.on = on
            self.changed = True
            self.clicks += 1
        self.current = i
        self.vd = v(x, c1) - v(x, c2)


# ============================================================================================ motor driver
class L293D(Device):
    """L293D quadruple half-H driver. Each output Y follows its input A (TTL levels: high above about 2 V)
    while its enable is high, and is switched off (high impedance) when the enable is low. A high output is a
    transistor to VCC2 and a low output a transistor to GND — each drops about 1.2–1.4 V at 0.6 A, like the
    real chip — and each output has the "D" version's clamp diodes to VCC2 and GND to catch a motor's spikes.
    The logic runs from VCC1 (4.5–7 V). It shuts down when it gets too hot. Pins: EN1,2  1A  2A  EN3,4  3A  4A
    1Y  2Y  3Y  4Y  VCC1  VCC2  GND."""
    nonlinear = True
    IMAX = 1.2              # peak output current (A); 0.6 A continuous
    VMAX = 36.0
    PMAX = 2.0              # what the DIP package can get rid of (W) before thermal shutdown
    TAU = 1.0
    G_LEAK = 1e-7
    R_VCC1 = 300.0          # about 16 mA logic supply current at 5 V
    VIH, VIL = 2.0, 1.8
    IN_NAMES = ("EN12", "1A", "2A", "EN34", "3A", "4A")

    def update_params(self):
        n = self.nodes
        vcc2, gnd = n[11], n[12]
        self.ys = [n[6], n[7], n[8], n[9]]
        self.hi = [_RsDiode(vcc2, y, Rs=0.5) for y in self.ys]       # the output transistors (when switched on)
        self.lo = [_RsDiode(y, gnd, Rs=0.4) for y in self.ys]
        self.clamp = [_RsDiode(y, vcc2, Rs=0.3) for y in self.ys] + [_RsDiode(gnd, y, Rs=0.3) for y in self.ys]
        if not hasattr(self, "drive"):
            self.level = {k: False for k in self.IN_NAMES}
            self.drive = [None] * 4             # None = off, True = high, False = low
            self.hot = False
            self.heat = 0.0
            self.changed = False

    def _compute(self, vcc1_ok):
        out = []
        for ch in range(4):
            en = self.level["EN12" if ch < 2 else "EN34"]
            a = self.level["1A 2A 3A 4A".split()[ch]]
            out.append(a if (en and vcc1_ok and not self.hot and not self.blown) else None)
        return out

    def stamp(self, S, x, ctx):
        n = self.nodes
        gnd = n[12]
        for i in range(6):
            S.g(n[i], gnd, 1 / 10e6)
        S.g(n[10], gnd, 1 / self.R_VCC1)
        for ch, y in enumerate(self.ys):
            S.g(y, gnd, self.G_LEAK)
            for d, on in ((self.hi[ch], self.drive[ch] is True), (self.lo[ch], self.drive[ch] is False)):
                if on:
                    d.stamp(S, x)
                else:
                    S.g(d.a, d.k, 1 / R_OFF)
        for d in self.clamp:
            d.stamp(S, x)

    def crossing(self, xo, xn, t0, t1):
        gnd = self.nodes[12]
        best = None
        for name, i in zip(self.IN_NAMES, range(6)):
            n = self.nodes[i]
            old = self.level[name]
            f = frac_cross(v(xo, n) - v(xo, gnd), v(xn, n) - v(xn, gnd), self.VIL if old else self.VIH, not old)
            if f is not None and (best is None or f < best):
                best = f
        return best

    def accept(self, x, ctx):
        n = self.nodes
        gnd = n[12]
        vg = v(x, gnd)
        pins = [0.0] * 13

        def flow(i_from, i_to, amps):          # current through the chip from one pin to another
            pins[i_from] += amps
            pins[i_to] -= amps

        for i, name in enumerate(self.IN_NAMES):
            vi = v(x, n[i]) - vg
            flow(i, 12, vi / 10e6)
            old = self.level[name]
            self.level[name] = bool(vi >= self.VIH if not old else vi > self.VIL)
        vcc1 = v(x, n[10]) - vg
        flow(10, 12, vcc1 / self.R_VCC1)
        self.power = vcc1 * vcc1 / self.R_VCC1
        worst = 0.0
        for ch, y in enumerate(self.ys):
            py = 6 + ch
            flow(py, 12, (v(x, y) - vg) * self.G_LEAK)
            if self.drive[ch] is True:
                d = self.hi[ch]
                d.accept(x)
                flow(11, py, d.current)
            elif self.drive[ch] is False:
                d = self.lo[ch]
                d.accept(x)
                flow(py, 12, d.current)
            else:
                d = None
            if d is not None:
                self.power += d.power
                worst = max(worst, abs(d.current))
            up, down = self.clamp[ch], self.clamp[4 + ch]
            up.accept(x)
            down.accept(x)
            flow(py, 11, up.current)
            flow(12, py, down.current)
            self.power += up.power + down.power
        self.i_pins = pins
        # heat, current and voltage limits
        if ctx.dc:
            self.heat = 0.0
        else:
            self.heat += (self.power - self.heat) * (1 - math.exp(-ctx.h / self.TAU))
        if not self.hot and self.heat > self.PMAX and not ctx.dc:
            self.hot = True
            if not getattr(self, "_told_hot", False):
                self._told_hot = True
                self.event = tr("{ref} got too hot and switched its outputs off — it's turning "
                                "{power:.1f} W into heat. An L293D can drive about 0.6 A per output; use a "
                                "smaller motor or a bigger driver.",
                                ref=self.comp.ref, power=self.power)
        elif self.hot and self.heat < 0.7 * self.PMAX:
            self.hot = False
        vcc2 = v(x, n[11]) - vg
        if not self.blown and not ctx.dc and (vcc2 > self.VMAX * 1.1 or vcc1 > 7.5 + 0.5):
            self.blown = True
            what, lim = ("VCC2", self.VMAX) if vcc2 > self.VMAX * 1.1 else ("VCC1", 7.0)
            self.event = tr("{ref} was destroyed — {volts:.0f} V on {what} is more than its "
                            "{lim:g} V limit.",
                            ref=self.comp.ref, volts=max(vcc1, vcc2), what=what, lim=lim)
        if not self.blown and self._overload(worst > 2 * self.IMAX, ctx.h, 0.1, worst > 5 * self.IMAX):
            self.blown = True
            self.event = tr("{ref} burnt out — an output carried {worst:.1f} A, more than the "
                            "{IMAX:g} A an L293D can take. (Is an output shorted, or a motor stalled?)",
                            ref=self.comp.ref, worst=worst, IMAX=self.IMAX)
        self.warn = "hot" if (self.hot or self.heat > 0.8 * self.PMAX or worst > 0.6) else None
        drive = self._compute(vcc1 >= 4.0)
        if drive != self.drive:
            self.drive = drive
            self.changed = True

    def live_extra(self):
        return {}


# ============================================================================================ logic and clocks
class JKFlipFlop(Digital):
    """JK flip-flop (half a 4027): on a rising clock edge J=1,K=0 sets Q, J=0,K=1 resets it, J=K=1 toggles it,
    J=K=0 keeps it. S and R (active high) set or reset it at once."""
    inputs = ("J", "CLK", "K", "S", "R")
    outputs = ("Q", "Qn")

    def reset_state(self):
        self.q = False

    def clock(self, rising):
        lv = self.level
        if lv["S"] or lv["R"]:                          # set / reset straight away, whatever the clock does
            if lv["S"] != lv["R"]:
                self.q = bool(lv["S"])
            return
        if rising.get("CLK"):
            j, k = lv["J"], lv["K"]
            if j and k:
                self.q = not self.q
            elif j:
                self.q = True
            elif k:
                self.q = False

    def compute(self):
        both = self.level["S"] and self.level["R"]          # both forced: the 4027 makes Q and Q̄ both high
        return {"Q": True if both else self.q, "Qn": True if both else not self.q}


class CrystalClock(Digital):
    """A crystal oscillator module with a divider: a square wave at exactly the set frequency, 0 V or the logic
    supply. Steps land exactly on its edges."""
    inputs = ()
    outputs = ("OUT",)

    def update_params(self):
        self.freq = max(1e-6, float(self.prop("frequency")))
        self.t_now = getattr(self, "t_now", 0.0)
        super().update_params()

    def compute(self):
        return {"OUT": ((self.t_now * self.freq) % 1.0) < 0.5}

    def crossing(self, xo, xn, t0, t1):
        half = 0.5 / self.freq
        n = math.floor(t0 / half + 1e-9)
        te = (n + 1) * half
        if t0 < te < t1 - 1e-12 * half:
            return (te - t0) / (t1 - t0)
        return None

    def accept(self, x, ctx):
        # nudge just past an edge it landed on, so the edge counts as having happened
        self.t_now = ctx.t + 1e-9 / self.freq
        super().accept(x, ctx)


# ============================================================================================ stepper motor
class Stepper(Device):
    """Bipolar stepper motor: two coils (A1–A2, B1–B2), each a resistance and inductance. The rotor's magnet
    turns to line up with the coils' field — the direction (I_A, I_B) — so energising A, B, −A, −B in turn moves
    it one step each time (a quarter of an electrical turn). It follows within a few milliseconds; step it faster
    than it can follow and it falls behind. (No back-EMF: it's a slow-stepping model.)"""
    reactive = True
    n_internal = 2
    RP = 100e3
    TAU = 4e-3                  # how quickly the rotor follows the field (s)

    def update_params(self):
        self.V = float(self.prop("voltage"))
        self.R = max(1.0, self.V / 0.3)          # about 0.3 A per coil at its rated voltage
        self.L = self.R * 2e-3
        self.nsteps = int(self.prop("steps") or 48)
        if not hasattr(self, "theta"):
            self.theta = 0.0                     # electrical angle (rad): a full step is π/2
            self.i_prev = [0.0, 0.0]
            self.v_prev = [0.0, 0.0]

    def _companion(self, ctx, k):
        if ctx.method == "trap":
            G = ctx.h / (2 * self.L)
            return G, self.i_prev[k] + G * self.v_prev[k]
        G = ctx.h / self.L
        return G, self.i_prev[k]

    def stamp(self, S, x, ctx):
        for k, (a, b) in enumerate(((0, 1), (2, 3))):
            na, nb, m = self.nodes[a], self.nodes[b], self.internal[k]
            S.g(na, nb, 1 / self.RP)
            if self.blown:
                S.g(na, m, 1 / R_OFF)
                S.g(m, nb, 1.0)
                continue
            S.g(na, m, 1 / self.R)
            if ctx.dc:
                S.g(m, nb, 1e3)
            else:
                G, Ieq = self._companion(ctx, k)
                S.g(m, nb, G)
                S.i(m, nb, Ieq)

    def accept(self, x, ctx):
        pins, cur = [], []
        self.power = 0.0
        for k, (a, b) in enumerate(((0, 1), (2, 3))):
            na, nb, m = self.nodes[a], self.nodes[b], self.internal[k]
            vl = v(x, m) - v(x, nb)
            if self.blown:
                i = 0.0
            elif ctx.dc:
                i = vl * 1e3
            else:
                G, Ieq = self._companion(ctx, k)
                i = G * vl + Ieq
            self.i_prev[k], self.v_prev[k] = i, vl
            tot = i + (v(x, na) - v(x, nb)) / self.RP
            pins += [tot, -tot]
            cur.append(i)
            self.power += i * i * self.R
        self.i_pins = pins
        self.current = math.hypot(*cur)
        self.ia, self.ib = cur
        # the rotor turns towards the field (the shorter way round), if there's enough current to pull it
        h = 0.0 if ctx.dc else ctx.h
        irated = self.V / self.R
        if self.current > 0.15 * irated and h > 0:
            target = math.atan2(cur[1], cur[0])
            d = (target - self.theta + math.pi) % (2 * math.pi) - math.pi
            if abs(abs(d) - math.pi) > 1e-3:     # exactly opposite: no pull either way
                self.theta += d * (1 - math.exp(-h / self.TAU))
        self.vd = v(x, self.nodes[0]) - v(x, self.nodes[1])
        self.warn = "hot" if self.current > 1.5 * irated else None
        if self._overload(self.current > 2.5 * irated, h, 1.0):
            self.blown = True
            self.event = tr("{ref} burnt out — {current:.1f} A is far more than its coils can take "
                            "({irated:.2f} A at {V:g} V).",
                            ref=self.comp.ref, current=self.current, irated=irated, V=self.V)

    def after_dc(self):
        pass

    @property
    def angle(self):
        """Shaft angle in degrees (a full step is 360 / steps per turn)."""
        return math.degrees(self.theta) * 4 / (self.nsteps)

    @property
    def step_count(self):
        return round(self.theta / (math.pi / 2))

    def reading(self):
        return (self.step_count, " steps")

    def live_extra(self):
        return {"_angle": self.angle % 360.0, "_steps": self.step_count}


# ============================================================================================ rotary switch, keypad
class Rotary(Device):
    """1-pole, 4-way rotary switch: COM to the selected contact. Pins COM, 1, 2, 3, 4."""

    def _sel(self):
        try:
            return int(self.prop("position")) - 1
        except (TypeError, ValueError):
            return 0

    def stamp(self, S, x, ctx):
        sel = self._sel()
        com = self.nodes[0]
        for k in range(4):
            S.g(com, self.nodes[1 + k], 1 / (R_ON if k == sel else R_OFF))

    def accept(self, x, ctx):
        sel = self._sel()
        com = self.nodes[0]
        pins = [0.0] * 5
        for k in range(4):
            i = (v(x, com) - v(x, self.nodes[1 + k])) / (R_ON if k == sel else R_OFF)
            pins[0] += i
            pins[1 + k] -= i
        self.i_pins = pins
        self.current = pins[0]


KEYS = ("1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "0", "#")


class Keypad(Device):
    """12-key matrix keypad: a pressed key joins its row (R1–R4) to its column (C1–C3)."""

    def _pair(self):
        key = str(self.comp.props.get("_key") or "")
        if key not in KEYS:
            return None
        n = KEYS.index(key)
        return n // 3, 4 + n % 3            # row pin index, column pin index

    def stamp(self, S, x, ctx):
        pair = self._pair()
        for r in range(4):
            for c in range(4, 7):
                S.g(self.nodes[r], self.nodes[c], 1 / (R_ON if pair == (r, c) else R_OFF))

    def accept(self, x, ctx):
        pair = self._pair()
        pins = [0.0] * 7
        for r in range(4):
            for c in range(4, 7):
                i = (v(x, self.nodes[r]) - v(x, self.nodes[c])) / (R_ON if pair == (r, c) else R_OFF)
                pins[r] += i
                pins[c] -= i
        self.i_pins = pins

    def live_extra(self):
        return {"_key": str(self.comp.props.get("_key") or "")}

FACTORY = {
    "led_bi2": MultiLED, "led_bi3": MultiLED, "led_rgb": MultiLED, "bridge": Bridge, "scr": SCR,
    "reg_fixed": Regulator, "reg_adj": Regulator, "transformer": Transformer, "dpdt": DPDT, "hall": Hall,
    "solenoid": Solenoid, "comparator": Comparator, "ic4026": Counter4026, "relay_dpdt": RelayDPDT, "l293d": L293D, "jkff": JKFlipFlop, "xtal_clock": CrystalClock,
    "stepper": Stepper, "rotary": Rotary, "keypad": Keypad, "ic4060": Counter4060,
}
