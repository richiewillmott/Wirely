"""Electrical models of every part, for the circuit solver (no Qt).

Each device "stamps" its contribution into the nodal equations A·x = b, the same way SPICE does:
  - linear parts (resistors, batteries) stamp conductances and current sources,
  - capacitors use a companion model (a conductance plus a current source that remembers the last step),
  - diodes, LEDs and transistors are non-linear: they are linearised around the current guess and the
    solver repeats (Newton–Raphson) until the answer stops changing. Junction voltage steps are limited
    the SPICE way (pnjlim) so the exponentials never run away.

Node index -1 is 0 V (ground).
"""
from __future__ import annotations

import math

from ..i18n import tr

VT = 0.025852          # thermal voltage at 300 K
GMIN = 1e-12           # tiny conductance across every junction (as SPICE)
R_ON, R_OFF = 0.01, 1e12      # an open switch leaks only a few picoamps

# ------------------------------------------------------------------------------------------- model data
DIODES = {  # Is, n, Rs, max current (A)
    "1N4001": (14.11e-9, 1.984, 0.0339, 1.0),
    "1N4007": (14.11e-9, 1.984, 0.0339, 1.0),
    "1N4148": (2.52e-9, 1.752, 0.568, 0.3),
    "1N5408": (1.4e-8, 1.9, 0.02, 3.0),
    "1N5819": (7.7e-7, 1.1, 0.05, 1.0),       # Schottky: about 0.4 V drop
}
LED_VF = {"Red": 1.95, "Orange": 2.0, "Yellow": 2.05, "Green": 2.15, "Blue": 3.1, "White": 3.1,
          "True green": 3.1}       # the InGaN green in RGB LEDs (about the same as blue)
LED_N, LED_RS = 2.0, 4.0
BJTS = {  # polarity, Is, BF, BR, max Ic (A), max power (W)
    "BC548": (1, 1.8e-14, 290.0, 7.5, 0.1, 0.5),
    "2N3904": (1, 6.734e-15, 416.4, 0.737, 0.2, 0.625),
    "BD139": (1, 2e-13, 120.0, 5.0, 1.5, 1.25),
    "TIP31": (1, 1e-12, 50.0, 5.0, 3.0, 2.0),
    "BC558": (-1, 1e-14, 290.0, 7.0, 0.1, 0.5),
    "2N3906": (-1, 1.41e-15, 180.7, 4.977, 0.2, 0.625),
    "BD140": (-1, 2e-13, 120.0, 5.0, 1.5, 1.25),
    "BC547": (1, 1.8e-14, 290.0, 7.5, 0.1, 0.5),
    "BC337": (1, 4.1e-14, 300.0, 10.0, 0.8, 0.625),
    "2N2222": (1, 1.4e-14, 200.0, 6.0, 0.8, 0.5),
    "TIP120": (1, 1e-17, 1000.0, 5.0, 5.0, 2.0),       # Darlington (behaves like a very high-gain transistor)
    "BC557": (-1, 1e-14, 290.0, 7.0, 0.1, 0.5),
    "BC327": (-1, 4e-14, 300.0, 10.0, 0.8, 0.625),
    "2N2907": (-1, 1.1e-14, 200.0, 6.0, 0.6, 0.4),
    "TIP125": (-1, 1e-17, 1000.0, 5.0, 5.0, 2.0),
}
VCEO = {"BC548": 30, "BC547": 45, "BC337": 45, "2N3904": 40, "2N2222": 40, "BD139": 80, "TIP31": 40, "TIP120": 60,
        "BC558": 30, "BC557": 45, "BC327": 45, "2N3906": 40, "2N2907": 40, "BD140": 80, "TIP125": 60}
R_INT = {"cell": 0.2, "battery": 1.5, "dc_supply": 0.02, "ac_supply": 0.1, "rail_pos": 0.01}


def led_is(colour: str) -> float:
    """Saturation current chosen so the LED drops its typical voltage at 20 mA."""
    vf = LED_VF.get(colour, 2.0)
    vj = vf - 0.02 * LED_RS
    return 0.02 / math.exp(vj / (LED_N * VT))


def sexp(x: float) -> float:
    """exp() that carries on in a straight line above 80 instead of overflowing."""
    if x > 80.0:
        return math.exp(80.0) * (1.0 + x - 80.0)
    return math.exp(x)


def pnjlim(vnew: float, vold: float, vt: float, vcrit: float) -> float:
    """SPICE junction voltage limiting: stops Newton jumping far up the exponential in one go."""
    if vnew > vcrit and abs(vnew - vold) > 2 * vt:
        if vold > 0:
            arg = 1 + (vnew - vold) / vt
            vnew = vold + vt * math.log(arg) if arg > 0 else vcrit
        else:
            vnew = vt * math.log(max(vnew / vt, 1e-30))
    return vnew


class Stamper:
    """Collects the equations for one Newton iteration."""

    def __init__(self, A, b):
        self.A, self.b = A, b

    def g(self, a, c, G):
        """Conductance G between nodes a and c."""
        A = self.A
        if a >= 0:
            A[a][a] += G
            if c >= 0:
                A[c][c] += G
                A[a][c] -= G
                A[c][a] -= G
        elif c >= 0:
            A[c][c] += G

    def i(self, a, c, I):
        """Current I flowing out of node a, through the device, into node c."""
        if a >= 0:
            self.b[a] -= I
        if c >= 0:
            self.b[c] += I

    def nonlinear(self, nodes, I0, J, V0):
        """Terminal currents I_k (into the device) linearised: I_k ≈ I0_k + Σ J_kj (V_j − V0_j)."""
        A, b = self.A, self.b
        n = len(nodes)
        for k in range(n):
            a = nodes[k]
            if a < 0:
                continue
            rhs = -I0[k]
            row = A[a]
            for j in range(n):
                rhs += J[k][j] * V0[j]
                c = nodes[j]
                if c >= 0:
                    row[c] += J[k][j]
            b[a] += rhs


class Ctx:
    """What the devices need to know about the current step."""

    def __init__(self):
        self.t = 0.0
        self.h = 1e-6
        self.method = "be"      # "be" (backward Euler, after a jump) or "trap" (trapezoidal)
        self.dc = False         # True: capacitors are open circuits (DC operating point)
        self.source_scale = 1.0
        self.limited = False    # a junction voltage was limited in this iteration (not converged yet)


def v(x, n):
    return x[n] if n >= 0 else 0.0


# =========================================================================================== devices
class Device:
    """Base class. `nodes` are the external pins (in the part's pin order); extra internal nodes are added
    by the engine when `n_internal` > 0."""
    n_internal = 0
    nonlinear = False
    reactive = False
    stores_energy = False    # V×I is energy going into / out of storage, not heat: never derive power from it
    main_pins = None         # (first, second) pin indices whose voltage and current the readout shows; None = pins 0, 1

    def __init__(self, comp, nodes):
        self.comp = comp
        self.cid = comp.id if comp is not None else ""
        self.nodes = list(nodes)
        self.internal = []
        self.blown = False
        self.warn = None         # short text while something is wrong (e.g. "too much current")
        self.i_pins = [0.0] * len(nodes)   # current INTO the device at each pin, after the last step
        self.power = 0.0
        self._over = 0.0         # how long it has been overloaded (s)
        self.event = None        # message for the user when something happens (an LED pops …)
        self.update_params()

    def update_params(self):
        pass

    def prop(self, key):
        return self.comp.value(key)

    def stamp(self, S: Stamper, x, ctx: Ctx):
        raise NotImplementedError

    def accept(self, x, ctx: Ctx):
        """Called once a time step is accepted: update memory, readings and overload checks."""

    def begin_iter(self):
        pass

    def reading(self):
        """Text shown on meters during the simulation, or None."""
        return None

    # ---- light that people see (LEDs, bulbs, displays)
    GAMMA = 0.6          # how bright light looks: the eye isn't linear, half the light looks more than half as bright

    def light_now(self):
        """Light given out right now, 0..1 for each lit thing in the part (a list), or None if it gives none."""
        return None

    def see(self, h):
        """Add one time step of light to what the eye has collected since the screen was last drawn."""
        now = self.light_now()
        e = self.__dict__.get("_eye")
        if e is None or len(e[0]) != len(now):
            e = self._eye = [[0.0] * len(now), 0.0, None]
        sums = e[0]
        for k, v in enumerate(now):
            sums[k] += v * h
        e[1] += h

    # how much simulated time the eye averages over: about 1/15 s at real-time speed. The app sets it from the
    # speed you choose (slow motion: a shorter stretch, so you see the flicker), not from how fast the computer
    # actually keeps up — so a busy circuit running slower than real time still looks right.
    eye_window = 0.066

    def take_light(self):
        """How bright it looks: like an eye, averaged over the last moment, so a part switched on and off quickly
        (PWM, a multiplexed display) looks steadily dimmer instead of flickering."""
        now = self.light_now() or []
        e = self.__dict__.get("_eye")
        if e is not None and e[1] > 0:
            hist = self.__dict__.setdefault("_eye_hist", [])
            if hist and len(hist[0][0]) != len(e[0]):
                hist.clear()
            hist.append((e[0], e[1]))
            total = sum(t for _s, t in hist)
            while len(hist) > 1 and total - hist[0][1] >= self.eye_window:
                total -= hist.pop(0)[1]
            # the oldest frame counts only as far as it lies inside the window (all of it if it's the only one)
            w0 = 1.0 if len(hist) == 1 else min(1.0, (self.eye_window - (total - hist[0][1])) / hist[0][1])
            span = total - hist[0][1] * (1.0 - w0)
            vals = [(w0 * hist[0][0][k] + sum(sums[k] for sums, _t in hist[1:])) / span for k in range(len(e[0]))]
            self._eye = [[0.0] * len(vals), 0.0, vals]
        elif e is not None and e[2] is not None:     # paused: nothing new to see
            vals = e[2]
        else:
            vals = now
        if self.blown:
            return [0.0] * len(vals)
        return [float(max(0.0, min(1.0, v))) ** self.GAMMA for v in vals]

    def _overload(self, bad: bool, h: float, limit_s: float, instant: bool = False) -> bool:
        """True when a part has been overloaded long enough to fail."""
        if instant:
            return True
        self._over = self._over + h if bad else 0.0
        return self._over >= limit_s


class Resistive(Device):
    """Anything that behaves as a plain resistor between its two pins."""

    def resistance(self) -> float:
        return 1.0

    def stamp(self, S, x, ctx):
        R = R_OFF if self.blown else max(self.resistance(), 1e-6)
        S.g(self.nodes[0], self.nodes[1], 1.0 / R)

    def accept(self, x, ctx):
        R = R_OFF if self.blown else max(self.resistance(), 1e-6)
        vd = v(x, self.nodes[0]) - v(x, self.nodes[1])
        i = vd / R
        self.i_pins = [i, -i]
        self.power = vd * i
        self.vd = vd
        self.after(ctx)

    def after(self, ctx):
        pass


class Resistor(Resistive):
    def update_params(self):
        self.R = float(self.prop("resistance"))
        self.rating = float(self.prop("power") or 0.25)

    def resistance(self):
        return self.R

    TAU = 1.0       # how quickly a resistor heats up (s): short surges are fine, lasting overloads are not

    def after(self, ctx):
        if self.blown:
            return
        # heat in the resistor, as the power that would hold it at its present temperature
        if ctx.dc:
            self.heat = self.power
        else:
            self.heat = getattr(self, "heat", 0.0)
            self.heat += (self.power - self.heat) * (1 - math.exp(-ctx.h / self.TAU))
        self.warn = "hot" if self.heat > self.rating else None
        if self.heat > 2 * self.rating or self.power > 1000 * self.rating:
            self.blown = True
            self.event = tr("{ref} burnt out — {power:.2f} W is far more than its "
                            "{rating:g} W rating.",
                            ref=self.comp.ref, power=self.power, rating=self.rating)


class VarResistor(Resistive):
    def update_params(self):
        self.R = max(1.0, float(self.prop("resistance")) * float(self.prop("setting")) / 100.0)

    def resistance(self):
        return self.R


class LDR(Resistive):
    def update_params(self):
        lux = max(0.0, float(self.prop("light")))
        r = 15e3 * (max(lux, 1e-3) / 10.0) ** -0.7 if lux > 0 else 2e6
        self.R = min(2e6, max(100.0, r))

    def resistance(self):
        return self.R


class Moisture(Resistive):
    """Two probes in soil: 1 MΩ when dry down to 1 kΩ when soaking (evenly on a log scale)."""

    def update_params(self):
        m = min(100.0, max(0.0, float(self.prop("moisture"))))
        self.R = 1e6 * 10 ** (-3 * m / 100.0)

    def resistance(self):
        return self.R


class Thermistor(Resistive):
    B = 3950.0

    def update_params(self):
        t = float(self.prop("temperature")) + 273.15
        self.R = float(self.prop("r25")) * math.exp(self.B * (1.0 / t - 1.0 / 298.15))

    def resistance(self):
        return self.R


class Fuse(Resistive):
    def update_params(self):
        self.rating = float(self.prop("rating"))

    def resistance(self):
        return 0.05

    def after(self, ctx):
        i = abs(self.i_pins[0])
        if not self.blown and self._overload(i > self.rating, ctx.h, 0.02, i > 3 * self.rating):
            self.blown = True
            self.event = tr("{ref} blew — {i:.2f} A is more than its {rating:g} A rating.",
                            ref=self.comp.ref, i=i, rating=self.rating)


class Switch(Resistive):
    """On/off switch, push switches, reed and tilt switches. `closed()` decides."""

    def closed(self):
        k = self.comp.kind
        if k == "switch":
            return bool(self.prop("closed"))
        if k == "reed_switch":
            return bool(self.prop("magnet"))
        if k == "tilt_switch":
            return bool(self.prop("tilted"))
        if k == "push_make":
            return bool(self.prop("pressed"))
        if k == "push_break":
            return not bool(self.prop("pressed"))
        return False

    def resistance(self):
        return R_ON if self.closed() else R_OFF


class SPDT(Device):
    """Changeover switch: common to A or to B."""

    def stamp(self, S, x, ctx):
        com, a, b = self.nodes
        to_a = self.prop("position") == "A"
        S.g(com, a, 1 / (R_ON if to_a else R_OFF))
        S.g(com, b, 1 / (R_OFF if to_a else R_ON))

    def accept(self, x, ctx):
        com, a, b = self.nodes
        to_a = self.prop("position") == "A"
        ia = (v(x, com) - v(x, a)) / (R_ON if to_a else R_OFF)
        ib = (v(x, com) - v(x, b)) / (R_OFF if to_a else R_ON)
        self.i_pins = [ia + ib, -ia, -ib]


class Potentiometer(Device):
    def update_params(self):
        R = float(self.prop("resistance"))
        s = min(1.0, max(0.0, float(self.prop("setting")) / 100.0))
        self.R1 = max(0.5, R * s)           # pin 1 to wiper
        self.R2 = max(0.5, R * (1 - s))     # wiper to pin 2

    def stamp(self, S, x, ctx):
        n1, n2, w = self.nodes
        S.g(n1, w, 1 / self.R1)
        S.g(w, n2, 1 / self.R2)

    def accept(self, x, ctx):
        n1, n2, w = self.nodes
        i1 = (v(x, n1) - v(x, w)) / self.R1
        i2 = (v(x, w) - v(x, n2)) / self.R2
        self.i_pins = [i1, -i2, i2 - i1]
        self.power = i1 * i1 * self.R1 + i2 * i2 * self.R2


class Source(Device):
    """A voltage source with a little internal resistance (Norton form): batteries, supplies, rails.
    Pins: + then − (a rail's − is 0 V)."""

    def update_params(self):
        self.V = float(self.prop("voltage"))
        self.Rint = R_INT.get(self.comp.kind, 0.05)
        self.freq = float(self.prop("frequency")) if self.comp.kind == "ac_supply" else 0.0

    def emf(self, t):
        if self.freq > 0:
            return self.V * math.sin(2 * math.pi * self.freq * t)
        return self.V

    def stamp(self, S, x, ctx):
        p, n = self.nodes
        G = 1.0 / self.Rint
        S.g(p, n, G)
        S.i(n, p, self.emf(ctx.t) * ctx.source_scale * G)     # pushes current out of + into the circuit

    def accept(self, x, ctx):
        p, n = self.nodes
        G = 1.0 / self.Rint
        i_out = (self.emf(ctx.t) - (v(x, p) - v(x, n))) * G     # current leaving + into the circuit
        self.i_pins = [-i_out, i_out]
        self.power = -(v(x, p) - v(x, n)) * i_out               # negative: it delivers power
        short = abs(i_out) > 0.5 * abs(self.V) / self.Rint and abs(self.V) > 0
        self.warn = "short" if short else None
        if short and not getattr(self, "_short_told", False):
            self._short_told = True
            self.event = tr("{ref} is short-circuited — current is flowing straight from + to − "
                            "({i_out:.1f} A).",
                            ref=self.comp.ref, i_out=abs(i_out))


class Capacitor(Device):
    reactive = True
    stores_energy = True     # an ideal capacitor dissipates nothing: V×I just charges or discharges it

    def update_params(self):
        self.C = float(self.prop("capacitance"))
        self.vmax = float(self.prop("max_voltage")) if self.comp.kind == "electrolytic" else None

    def reset(self):
        self.v_prev = 0.0
        self.i_prev = 0.0

    def __init__(self, comp, nodes):
        super().__init__(comp, nodes)
        self.reset()

    def _geq(self, ctx):
        return (2.0 if ctx.method == "trap" else 1.0) * self.C / ctx.h

    def stamp(self, S, x, ctx):
        a, c = self.nodes
        if self.blown or ctx.dc:
            S.g(a, c, GMIN)
            return
        G = self._geq(ctx)
        Ieq = G * self.v_prev + (self.i_prev if ctx.method == "trap" else 0.0)
        S.g(a, c, G)
        S.i(c, a, Ieq)          # i = G·v − Ieq, from a to c

    def accept(self, x, ctx):
        a, c = self.nodes
        vd = v(x, a) - v(x, c)
        if self.blown or ctx.dc:
            i = 0.0
        else:
            G = self._geq(ctx)
            i = G * vd - (G * self.v_prev + (self.i_prev if ctx.method == "trap" else 0.0))
        self.v_prev, self.i_prev = vd, i
        self.i_pins = [i, -i]
        self.vd = vd
        self.power = 0.0
        if self.vmax is not None and not self.blown:
            bad = vd < -1.0 or vd > 1.2 * self.vmax
            if self._overload(bad, ctx.h, 0.1):
                self.blown = True
                why = tr("it's connected the wrong way round") if vd < 0 else tr("{vd:.1f} V is over its rating", vd=vd)
                self.event = tr("{ref} popped — {why}.", ref=self.comp.ref, why=why)


class RsDiode:
    """A junction with a series resistance, worked out on the spot (no inside node): for the voltage across it,
    find how it splits between the junction and the resistance, then stamp the combined current and slope.
    With the resistance in series the current only rises in a straight line at high voltage, so Newton needs no
    limiting. Used for the many diodes in a driver chip, where inside nodes would make every step slower."""

    def __init__(self, a, k, Is=14.11e-9, n=1.984, Rs=0.5):
        self.a, self.k, self.Is, self.nvt, self.Rs = a, k, Is, n * VT, Rs
        self.current = self.power = 0.0

    def _solve(self, vd):
        Is, nvt, Rs = self.Is, self.nvt, self.Rs
        if vd < 0.3:                    # hardly any current: the resistance makes no difference
            vj = vd
        else:
            vj = min(vd, nvt * math.log(vd / (Rs * Is) + 1.0))      # start above the answer
            for _ in range(60):
                e = math.exp(vj / nvt)
                f = vj + Rs * Is * (e - 1.0) - vd
                df = 1.0 + Rs * Is * e / nvt
                dv = f / df
                vj -= dv
                if abs(dv) < 1e-12:
                    break
        e = math.exp(min(vj / nvt, 700.0))
        i = Is * (e - 1.0)
        gj = Is * e / nvt
        return i + GMIN * vd, gj / (1.0 + gj * Rs) + GMIN

    def stamp(self, S, x):
        vd = v(x, self.a) - v(x, self.k)
        i, g = self._solve(vd)
        S.g(self.a, self.k, g)
        S.i(self.a, self.k, i - g * vd)

    def accept(self, x):
        vd = v(x, self.a) - v(x, self.k)
        self.current = self._solve(vd)[0]
        self.power = self.current * vd


class Diode(Device):
    """Shockley diode with series resistance (via an internal node) and, for Zeners, reverse breakdown."""
    n_internal = 1
    nonlinear = True

    def update_params(self):
        k = self.comp.kind
        self.bv = None
        if k == "led":
            self.Is, self.n, self.Rs = led_is(self.prop("colour")), LED_N, LED_RS
            self.imax = float(self.prop("max_current"))
        elif k == "zener":
            self.Is, self.n, self.Rs = 1e-14, 1.0, 2.0
            self.bv = float(self.prop("voltage"))
            self.imax = 0.5
        else:
            Is, n, Rs, imax = DIODES.get(self.prop("model"), DIODES["1N4001"])
            self.Is, self.n, self.Rs, self.imax = Is, n, Rs, imax
        self.nvt = self.n * VT
        self.vcrit = self.nvt * math.log(self.nvt / (math.sqrt(2) * self.Is))
        self.vd_last = self.vd_acc = 0.0
        self._surge = 0.0

    def begin_iter(self):
        self.vd_last = self.vd_acc

    def junction(self, vd):
        """Current and conductance of the junction at voltage vd."""
        e = sexp(vd / self.nvt)
        i = self.Is * (e - 1.0)
        g = self.Is * e / self.nvt
        if self.bv is not None and vd < -self.bv + 10 * VT * 5:
            # reverse breakdown: 1 mA at −BV, rising steeply
            u = -(vd + self.bv) / VT
            eb = sexp(u)
            i -= 1e-3 * eb
            g += 1e-3 * eb / VT
        return i + GMIN * vd, g + GMIN

    def stamp(self, S, x, ctx):
        a, c = self.nodes
        k = self.internal[0]
        if self.blown:
            S.g(a, c, 1 / R_OFF)
            S.g(a, k, 1.0)
            return
        S.g(a, k, 1.0 / self.Rs)
        vd = v(x, k) - v(x, c)
        vl = pnjlim(vd, self.vd_last, self.nvt, self.vcrit)
        if self.bv is not None and vd < -self.bv:      # limit in the breakdown direction too
            vl = -self.bv - pnjlim(-vd - self.bv, -self.vd_last - self.bv, VT, 0.6)
        if abs(vl - vd) > 1e-9:
            ctx.limited = True
        self.vd_last = vl
        i, g = self.junction(vl)
        S.g(k, c, g)
        S.i(k, c, i - g * vl)

    def accept(self, x, ctx):
        a, c = self.nodes
        k = self.internal[0]
        if self.blown:
            i = (v(x, a) - v(x, c)) / R_OFF
        else:
            vd = v(x, k) - v(x, c)
            i, _g = self.junction(vd)
            self.vd_last = self.vd_acc = vd
        self.i_pins = [i, -i]
        self.vd = v(x, a) - v(x, c)
        self.power = self.vd * i
        self.current = i
        if self.blown:
            return
        over = abs(i) > self.imax
        self.warn = "over" if over else None
        # real diodes ride out short surges: 3× their rating for a millisecond, about 30× for an instant
        self._surge = self._surge + ctx.h if abs(i) > 3 * self.imax else 0.0
        if self._overload(over, ctx.h, 0.03, abs(i) > 30 * self.imax or
                          self._surge > getattr(self, "surge_time", 1e-3)):
            self.blown = True
            if self.comp.kind == "led":
                self.event = tr("{ref} popped! {i:.0f} mA is too much for this LED (max {imax:.0f} mA). "
                                "Add a resistor in series to limit the current.",
                                ref=self.comp.ref, i=abs(i) * 1000, imax=self.imax * 1000)
            else:
                self.event = tr("{ref} popped! {i:.0f} mA is too much for this diode (max {imax:.0f} mA).",
                                ref=self.comp.ref, i=abs(i) * 1000, imax=self.imax * 1000)

    def light_now(self):
        if self.comp is None or self.comp.kind != "led":
            return None
        if self.blown:
            return [0.0]
        # LEDs give no visible light below about 0.1 mA, and look fully lit from about 15 mA
        return [max(0.0, min(1.0, (getattr(self, "current", 0.0) - 1e-4) / 0.015))]

    def glow(self):
        if self.blown or self.comp.kind != "led":
            return 0.0
        return self.light_now()[0] ** self.GAMMA

    def take_glow(self):
        return self.take_light()[0] if self.comp.kind == "led" else 0.0


class BJT(Device):
    """Ebers–Moll transistor. Pins B, C, E. PNP handled by flipping all polarities."""
    nonlinear = True
    main_pins = (1, 2)       # readout: V(C−E) and the collector current

    def update_params(self):
        pol, Is, bf, br, icmax, pmax = BJTS.get(self.prop("model"), BJTS["BC548"])
        if (self.comp.kind == "pnp") != (pol < 0):     # model list mixes types: follow the symbol
            pol = -1 if self.comp.kind == "pnp" else 1
        self.pol, self.Is, self.bf, self.br, self.icmax, self.pmax = pol, Is, bf, br, icmax, pmax
        self.vcrit = VT * math.log(VT / (math.sqrt(2) * Is))
        self.vbe_last = self.vbc_last = 0.0
        self.vbe_acc = self.vbc_acc = 0.0
        self.ic = self.ib = 0.0

    def begin_iter(self):
        self.vbe_last, self.vbc_last = self.vbe_acc, self.vbc_acc

    def currents(self, vbe, vbc):
        """Currents into C and B (for an NPN) and their derivatives against vbe and vbc."""
        ef, er = sexp(vbe / VT), sexp(vbc / VT)
        If, Ir = self.Is * (ef - 1), self.Is * (er - 1)
        gf, gr = self.Is * ef / VT, self.Is * er / VT
        ic = If - Ir * (1 + 1 / self.br)
        ib = If / self.bf + Ir / self.br
        dic = (gf, -gr * (1 + 1 / self.br))
        dib = (gf / self.bf, gr / self.br)
        # tiny conductances across the junctions keep things solvable
        ib += GMIN * (vbe + vbc)
        dib = (dib[0] + GMIN, dib[1] + GMIN)
        ic -= GMIN * vbc
        dic = (dic[0], dic[1] - GMIN)
        return ic, ib, dic, dib

    def stamp(self, S, x, ctx):
        b, c, e = self._bce()
        if self.blown:
            for a1, a2 in ((b, e), (b, c), (c, e)):
                S.g(a1, a2, 1 / R_OFF)
            return
        p = self.pol
        vb, vc, ve = v(x, b), v(x, c), v(x, e)
        vbe, vbc = p * (vb - ve), p * (vb - vc)
        vbe_l = pnjlim(vbe, self.vbe_last, VT, self.vcrit)
        vbc_l = pnjlim(vbc, self.vbc_last, VT, self.vcrit)
        if abs(vbe_l - vbe) > 1e-9 or abs(vbc_l - vbc) > 1e-9:
            ctx.limited = True
        self.vbe_last, self.vbc_last = vbe_l, vbc_l
        ic, ib, dic, dib = self.currents(vbe_l, vbc_l)
        ie = -(ic + ib)
        # node voltages that correspond to the limited junction voltages (keep vb, move c and e)
        vc0, ve0 = vb - p * vbc_l, vb - p * vbe_l
        # derivatives of terminal currents (into the device) w.r.t. node voltages [B, C, E]
        def row(d):
            dbe, dbc = d
            return [dbe + dbc, -dbc, -dbe]
        Jc, Jb = row(dic), row(dib)
        Je = [-(Jc[i] + Jb[i]) for i in range(3)]
        S.nonlinear([b, c, e], [p * ib, p * ic, p * ie], [Jb, Jc, Je], [vb, vc0, ve0])

    def _bce(self):
        return self.nodes

    def accept(self, x, ctx):
        b, c, e = self._bce()
        p = self.pol
        vb, vc, ve = v(x, b), v(x, c), v(x, e)
        if self.blown:
            self.ic = self.ib = 0.0
        else:
            ic, ib, _d1, _d2 = self.currents(p * (vb - ve), p * (vb - vc))
            self.ic, self.ib = p * ic, p * ib
            self.vbe_acc, self.vbc_acc = p * (vb - ve), p * (vb - vc)
        self.i_pins = [self.ib, self.ic, -(self.ib + self.ic)]
        self.power = self.ic * (vc - ve) + self.ib * (vb - ve)
        if self.blown:
            return
        vmax = VCEO.get(self.prop("model"), 40) if self.comp.kind in ("npn", "pnp") else 30
        if abs(vc - ve) > 1.5 * vmax:
            self.blown = True
            self.event = spike_message(self.comp.ref, abs(vc - ve), vmax)
            return
        bad = abs(self.ic) > 1.5 * self.icmax or self.power > 1.5 * self.pmax
        self.warn = "over" if (abs(self.ic) > self.icmax or self.power > self.pmax) else None
        if self._overload(bad, ctx.h, 0.2, abs(self.ic) > 5 * self.icmax):
            self.blown = True
            self.event = tr("{ref} burnt out — {ic:.0f} mA / {power:.2f} W is "
                            "too much for a {model} (max {icmax:.0f} mA). "
                            "Add a resistor to its base or load.",
                            ref=self.comp.ref, ic=abs(self.ic) * 1000, power=self.power, model=self.prop('model'),
                            icmax=self.icmax * 1000)


def spike_message(ref, volts, vmax):
    return tr("{ref} was destroyed by a {volts:.0f} V spike — more than its {vmax:.0f} V limit. If it switches a "
              "relay coil, motor or inductor, put a diode across the coil (pointing towards +) to catch the spike.",
              ref=ref, volts=volts, vmax=vmax)


class Lamp(Device):
    """Filament lamp. The tungsten filament's resistance is proportional to its temperature: cold, it's about a
    twelfth of its hot (rated) resistance, so a lamp takes a big surge of current when first switched on, and
    its current–voltage graph curves over instead of being a straight line.

    The filament heats up with the power put in and loses heat by radiation (∝ T⁴, Stefan–Boltzmann), so at a
    steady voltage T ∝ P^¼ and the current goes as V^0.6 — as real lamps measure. It takes a moment to heat up
    and to cool down (about 50 ms near full brightness)."""
    nonlinear = True
    reactive = True
    COLD = 1 / 12          # cold resistance as a fraction of the hot (rated) resistance
    TAU = 0.05             # cooling time constant near full brightness (s)

    def update_params(self):
        V, P = float(self.prop("voltage")), float(self.prop("power"))
        self.Vr = max(V, 1e-3)
        self.Prated = P if P > 0 else 0.36
        self.R = self.Vr * self.Vr / self.Prated          # hot resistance, at its rated voltage
        self.Rc = self.R * self.COLD
        self.Ir = self.Vr / self.R
        self.Vk = self.Vr * self.COLD ** 2.5                # below this the filament is effectively cold
        self.Cth = 4 * self.Prated * self.TAU               # heat capacity (in "rated watts" per unit θ)
        if not hasattr(self, "theta"):
            self.theta = self.COLD                          # filament temperature as a fraction of its hot one
            self.current = 0.0

    # --- the steady state (filament at the temperature its power gives it): I = Ir·(V/Vr)^0.6
    def _steady(self, vd):
        av = abs(vd)
        if av <= self.Vk:
            return vd / self.Rc, 1.0 / self.Rc
        i = self.Ir * (av / self.Vr) ** 0.6
        return math.copysign(i, vd), 0.6 * i / av

    def hot_resistance(self):
        return self.R * self.theta                          # R ∝ T

    def radiated(self):
        """Power the filament is radiating (light and heat), as a fraction of its rating."""
        c4 = self.COLD ** 4
        return max(0.0, (self.theta ** 4 - c4) / (1 - c4))

    def stamp(self, S, x, ctx):
        a, c = self.nodes
        if self.blown:
            S.g(a, c, 1 / R_OFF)
            return
        if ctx.dc:
            vd = v(x, a) - v(x, c)
            i, g = self._steady(vd)
            S.g(a, c, g)
            S.i(a, c, i - g * vd)
        else:
            S.g(a, c, 1.0 / self.hot_resistance())

    def accept(self, x, ctx):
        a, c = self.nodes
        vd = v(x, a) - v(x, c)
        if self.blown:
            i = vd / R_OFF
        elif ctx.dc:
            i = self._steady(vd)[0]
        else:
            i = vd / self.hot_resistance()
        self.vd, self.current = vd, i
        self.i_pins = [i, -i]
        self.power = vd * i
        if self.blown:
            self.theta = self.COLD
            return
        if ctx.dc:
            self.theta = max(self.COLD, abs(vd / i) / self.R) if abs(i) > 1e-15 else self.COLD
        else:
            # heat the filament through the step in small slices (it changes fast while it's cold)
            n = max(1, min(400, int(math.ceil(ctx.h / 2e-4))))
            dt = ctx.h / n
            v2 = vd * vd
            th = self.theta
            c4 = self.COLD ** 4
            for _ in range(n):
                p_in = v2 / (self.R * th)
                p_out = self.Prated * (th ** 4 - c4) / (1 - c4)
                th = max(self.COLD, th + dt * (p_in - p_out) / self.Cth)
            self.theta = th
        h = 0.0 if ctx.dc else ctx.h
        rad = self.radiated()
        if self._overload(rad > 1.6, h, 0.2, rad > 4.0):
            self.blown = True
            self.event = tr("{ref} blew — its filament can't take {watts:.1f} W.",
                            ref=self.comp.ref, watts=rad * self.Prated)

    def after_dc(self):
        pass

    def glow(self):
        """How bright it looks: visible light rises very steeply with filament temperature (about T¹⁰), so a
        lamp on half power looks much dimmer than half, and goes dark quickly as it cools."""
        if self.blown:
            return 0.0
        return self.light_now()[0] ** self.GAMMA

    GAMMA = 0.5

    def light_now(self):
        if self.blown:
            return [0.0]
        return [max(0.0, min(1.0, (self.theta ** 10 - 0.003) / 0.997))]

    def take_glow(self):
        return self.take_light()[0]


class Buzzer(Resistive):
    def update_params(self):
        self.V = float(self.prop("voltage"))
        self.R = max(1.0, self.V / 0.015)

    def resistance(self):
        return self.R

    def level(self):
        """0..1 loudness (only when connected the right way round)."""
        vd = getattr(self, "vd", 0.0)
        return 0.0 if vd < 0.3 * self.V else min(1.0, vd / self.V)


class Speaker(Resistive):
    def update_params(self):
        self.R = float(self.prop("impedance"))

    def resistance(self):
        return self.R


class Motor(Device):
    """DC motor: winding resistance R in series with a back-EMF k·ω. The rotor speeds up until the back-EMF
    nearly balances the supply, so it takes a big current when starting and much less once running.
    Load (friction plus what it drives) slows it down and makes it take more current."""
    I_STALL = 1.0              # A at rated voltage, stopped
    W0 = 2 * math.pi * 100     # rad/s with no load at rated voltage (6000 rpm)
    LOADS = {"None": 0.0, "Light": 0.2, "Medium": 0.45, "Heavy": 0.8}

    def update_params(self):
        self.V = max(0.1, float(self.prop("voltage")))
        self.R = self.V / self.I_STALL
        self.k = self.V / self.W0
        self.b = 0.1 * self.k * self.I_STALL / self.W0           # no-load current about 10 % of stall
        self.J = 0.1 * self.k * self.k / self.R                    # spins up in about 0.1 s
        self.TL = self.LOADS.get(self.prop("load"), 0.0) * self.k * self.I_STALL
        if not hasattr(self, "w"):
            self.w = 0.0
            self.speed = 0.0
            self.current = 0.0

    def stamp(self, S, x, ctx):
        a, c = self.nodes
        if self.blown:
            S.g(a, c, 1 / R_OFF)
            return
        G = 1.0 / self.R
        S.g(a, c, G)
        S.i(c, a, G * self.k * self.w)          # the back-EMF pushes against the supply

    def accept(self, x, ctx):
        a, c = self.nodes
        vd = v(x, a) - v(x, c)
        h = 0.0 if ctx.dc else ctx.h
        if self.blown:
            self.w = self.speed = self.rpm = 0.0
            self.current = vd / R_OFF
            self.vd = vd
            self.i_pins = [self.current, -self.current]
            self.power = 0.0
            return
        # the current this step's solution was found with (the back-EMF of the speed before this step)
        i = (vd - self.k * self.w) / self.R
        # rotor: J dω/dt = k·i − b·ω − load, with i = (v − kω)/R (solved implicitly: always stable)
        drive = self.k * vd / self.R
        if abs(self.w) < 1e-3 and abs(drive) <= self.TL:
            self.w = 0.0                         # not enough torque to get going against the load
        elif h > 0:
            sgn = 1.0 if (self.w if abs(self.w) > 1e-3 else drive) > 0 else -1.0
            self.w = (self.w + h / self.J * (drive - self.TL * sgn)) / \
                (1 + h * (self.b + self.k * self.k / self.R) / self.J)
        self.current = i
        self.vd = vd
        self.i_pins = [i, -i]
        self.power = vd * i
        self.speed = self.w / self.W0
        self.rpm = self.w * 60 / (2 * math.pi)
        self.warn = "fast" if abs(self.speed) > 1.5 else ("stalled" if self.TL > 0 and self.w == 0 and
                                                           abs(i) > 0.5 * self.I_STALL else None)
        # too much voltage: it spins far too fast and the brushes and windings overheat
        if self._overload(abs(vd) > 2.0 * self.V, h, 1.0, abs(vd) > 6.0 * self.V and self._over > 0.05):
            self.blown = True
            self.event = tr("{ref} burnt out — {vd:.0f} V is far too much for a {V:g} V motor: "
                            "it spun much too fast and overheated.",
                            ref=self.comp.ref, vd=abs(vd), V=self.V)


class Voltmeter(Resistive):
    def resistance(self):
        return 10e6

    def reading(self):
        return getattr(self, "vd", 0.0), "V"


class Ammeter(Resistive):
    def resistance(self):
        return 1e-3

    def reading(self):
        return self.i_pins[0], "A"


class Nothing(Device):
    """Parts with no electrical effect (0 V symbol)."""

    def stamp(self, S, x, ctx):
        pass


FACTORY = {
    "resistor": Resistor, "var_resistor": VarResistor, "ldr": LDR, "thermistor": Thermistor, "fuse": Fuse,
    "switch": Switch, "push_make": Switch, "push_break": Switch, "reed_switch": Switch, "tilt_switch": Switch,
    "moisture": Moisture, "spdt": SPDT, "potentiometer": Potentiometer,
    "cell": Source, "battery": Source, "dc_supply": Source, "ac_supply": Source, "rail_pos": Source,
    "capacitor": Capacitor, "electrolytic": Capacitor,
    "diode": Diode, "led": Diode, "zener": Diode, "npn": BJT, "pnp": BJT,
    "lamp": Lamp, "buzzer": Buzzer, "speaker": Speaker, "motor": Motor,
    "voltmeter": Voltmeter, "ammeter": Ammeter, "ground": Nothing,
}
