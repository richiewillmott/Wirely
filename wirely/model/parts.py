"""The parts library: what every component is called, where its pins are and which values it has.

Coordinates are in "sheet units" with the part's centre at (0, 0) and y pointing down. One grid square is
GRID units, and every pin sits exactly on a grid point so wires always meet them.

The drawings themselves live in ui/symbols.py; this file is plain data so the model and the simulator
can use it without Qt.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..i18n import language, tr

GRID = 10


@dataclass(frozen=True)
class Prop:
    key: str
    label: str
    default: object
    unit: str = ""
    kind: str = "number"            # number | choice | bool | text
    choices: tuple = ()
    on_label: bool = False          # shown next to the part on the diagram
    min: float | None = None
    max: float | None = None
    help: str = ""

    # What the person reads: the English above, in the language they chose. The English stays the key that is
    # saved in circuit files, so these are for showing only.
    @property
    def tr_label(self):
        return tr(self.label)

    @property
    def tr_help(self):
        return tr(self.help) if self.help else ""


@dataclass(frozen=True)
class PartDef:
    key: str
    name: str
    category: str
    prefix: str                     # reference letter(s): R1, C1, LED1 …
    pins: tuple                     # ((name, x, y), …)
    props: tuple = ()
    box: tuple = (-30, -15, 60, 30)  # x, y, w, h: the clickable body (local)
    description: str = ""
    keywords: str = ""
    short: str = ""                 # shorter name for the gallery tile

    @property
    def tile_name(self):
        return self.short or self.name

    # shown to the person, in their language (the English fields stay the keys used in saved files)
    @property
    def tr_name(self):
        return tr(self.name)

    @property
    def tr_name_lower(self):
        """The name for the middle of a sentence: lower case in English and Spanish, as written in German (nouns
        keep their capital) and Japanese (no case)."""
        return self.tr_name.lower() if language() in ("en", "es") else self.tr_name

    @property
    def tr_tile_name(self):
        return tr(self.tile_name)

    @property
    def tr_description(self):
        return tr(self.description)

    @property
    def tr_category(self):
        return tr(self.category)

    @property
    def search_text(self):
        """Everything the gallery search matches: the names in English and in the chosen language, and keywords."""
        return " ".join([self.name, self.tile_name, tr(self.name), tr(self.tile_name), self.keywords]).lower()

    def prop(self, key):
        for p in self.props:
            if p.key == key:
                return p
        return None

    def defaults(self) -> dict:
        return {p.key: p.default for p in self.props}


CATEGORIES = [
    "Power supplies",
    "Resistors",
    "Capacitors & inductors",
    "Switches",
    "Input sensors",
    "Diodes & LEDs",
    "Transistors",
    "Logic gates",
    "Integrated circuits",
    "Output devices",
    "Meters & probes",
    "Labels",
]

LED_COLOURS = ("Red", "Green", "Yellow", "Blue", "White", "Orange")


def choice_text(value):
    """A choice value ("Red", "Sine", "BC547" …) as shown to the person. Part numbers stay as they are."""
    return tr(str(value))

TWO = (("1", -30, 0), ("2", 30, 0))           # standard two-pin part, 60 units long
TWO_POL = (("+", -30, 0), ("-", 30, 0))       # polarised: + on the left


def _p(*a, **k):
    return Prop(*a, **k)


_PARTS = [
    # ---------------------------------------------------------------- power supplies
    PartDef("cell", "Cell", "Power supplies", "B", TWO_POL,
            (_p("voltage", "Voltage", 1.5, "V", on_label=True, min=0, max=1000),),
            (-30, -20, 60, 40), "A single cell, e.g. an AA (1.5 V). The long plate is +.", "battery aa"),
    PartDef("battery", "Battery", "Power supplies", "B", TWO_POL,
            (_p("voltage", "Voltage", 9.0, "V", on_label=True, min=0, max=1000),),
            (-30, -20, 60, 40), "A battery of cells, e.g. 9 V PP3. The long plate is +.", "pp3 cell"),
    PartDef("dc_supply", "DC power supply", "Power supplies", "PSU", TWO_POL,
            (_p("voltage", "Voltage", 5.0, "V", on_label=True, min=0, max=1000),),
            (-30, -20, 60, 40), "A bench power supply giving a steady DC voltage.", "psu bench", short="DC supply"),
    PartDef("ac_supply", "AC power supply", "Power supplies", "AC", TWO,
            (_p("voltage", "Voltage (peak)", 6.0, "V", on_label=True, min=0, max=1000),
             _p("frequency", "Frequency", 50.0, "Hz", on_label=True, min=0)),
            (-30, -20, 60, 40), "An alternating supply (sine wave).", "sine mains", short="AC supply"),
    PartDef("rail_pos", "Supply rail (+V)", "Power supplies", "V", (("1", 0, 0),),
            (_p("voltage", "Voltage", 9.0, "V", on_label=True, min=-1000, max=1000),),
            (-15, -30, 30, 32), "A connection to the positive supply, measured from 0 V.", "vcc vdd terminal", short="+V rail"),
    PartDef("ground", "0 V (ground)", "Power supplies", "GND", (("1", 0, 0),), (),
            (-15, -2, 30, 22), "The 0 V reference that all voltages are measured from.", "earth gnd 0v", short="0 V"),

    # ---------------------------------------------------------------- resistors
    PartDef("resistor", "Resistor", "Resistors", "R", TWO,
            (_p("resistance", "Resistance", 1000.0, "Ω", on_label=True, min=1e-3),
             _p("power", "Power rating", 0.25, "W", min=0.0)),
            (-30, -10, 60, 20), "A fixed resistor.", "ohm"),
    PartDef("var_resistor", "Variable resistor", "Resistors", "VR", TWO,
            (_p("resistance", "Maximum resistance", 10000.0, "Ω", on_label=True, min=1e-3),
             _p("setting", "Setting", 50.0, "%", min=0, max=100)),
            (-30, -15, 60, 30), "A resistor you can adjust while the circuit runs.", "rheostat preset", short="Variable resistor"),
    PartDef("potentiometer", "Potentiometer", "Resistors", "VR",
            (("1", -30, 0), ("2", 30, 0), ("wiper", 0, -30)),
            (_p("resistance", "Resistance", 10000.0, "Ω", on_label=True, min=1e-3),
             _p("setting", "Wiper position", 50.0, "%", min=0, max=100)),
            (-30, -30, 60, 40), "Three-terminal variable resistor (volume knob).", "pot wiper"),
    PartDef("fuse", "Fuse", "Resistors", "F", TWO,
            (_p("rating", "Rating", 1.0, "A", on_label=True, min=0),),
            (-30, -8, 60, 16), "Melts and breaks the circuit if the current is too high.", "protection"),

    # ---------------------------------------------------------------- capacitors
    PartDef("capacitor", "Capacitor", "Capacitors & inductors", "C", (("1", -20, 0), ("2", 20, 0)),
            (_p("capacitance", "Capacitance", 100e-9, "F", on_label=True, min=1e-15),),
            (-20, -15, 40, 30), "A non-polarised capacitor (ceramic / film).", "ceramic film"),
    PartDef("electrolytic", "Electrolytic capacitor", "Capacitors & inductors", "C", (("+", -20, 0), ("-", 20, 0)),
            (_p("capacitance", "Capacitance", 100e-6, "F", on_label=True, min=1e-15),
             _p("max_voltage", "Voltage rating", 25.0, "V", min=0)),
            (-20, -15, 40, 30), "A polarised capacitor for large values. Mind the + side!", "polarised", short="Electrolytic"),

    # ---------------------------------------------------------------- switches
    PartDef("switch", "On/off switch", "Switches", "S", TWO,
            (_p("closed", "Switched on", False, kind="bool"),),
            (-30, -15, 60, 25), "Toggle switch (SPST). Click it during the simulation.", "spst toggle"),
    PartDef("push_make", "Push switch (push to make)", "Switches", "S", TWO,
            (_p("pressed", "Pressed", False, kind="bool"),),
            (-30, -20, 60, 28), "Connects only while you hold it down.", "button ptm", short="Push to make"),
    PartDef("push_break", "Push switch (push to break)", "Switches", "S", TWO,
            (_p("pressed", "Pressed", False, kind="bool"),),
            (-30, -20, 60, 28), "Disconnects while you hold it down.", "button ptb", short="Push to break"),
    PartDef("spdt", "Changeover switch (SPDT)", "Switches", "S",
            (("com", -30, 0), ("a", 30, -10), ("b", 30, 10)),
            (_p("position", "Position", "A", kind="choice", choices=("A", "B")),),
            (-30, -18, 60, 36), "Connects the common terminal to A or to B.", "two way", short="Changeover"),

    # ---------------------------------------------------------------- input sensors
    PartDef("ldr", "Light dependent resistor (LDR)", "Input sensors", "LDR", TWO,
            (_p("light", "Light level", 500.0, "lux", min=0, max=100000,
                help="Bright room ≈ 500 lux, dark ≈ 1 lux"),),
            (-30, -24, 60, 48), "Resistance falls as the light gets brighter.", "light sensor", short="LDR"),
    PartDef("thermistor", "Thermistor (NTC)", "Input sensors", "TH", TWO,
            (_p("r25", "Resistance at 25°C", 10000.0, "Ω", on_label=True, min=1e-3),
             _p("temperature", "Temperature", 25.0, "°C", min=-50, max=200)),
            (-30, -16, 60, 32), "Resistance falls as it gets hotter.", "temperature sensor ntc", short="Thermistor"),

    # ---------------------------------------------------------------- diodes
    PartDef("diode", "Diode", "Diodes & LEDs", "D", (("A", -30, 0), ("K", 30, 0)),
            (_p("model", "Type", "1N4001", kind="choice", choices=("1N4001", "1N4007", "1N4148", "1N5408", "1N5819")),),
            (-30, -12, 60, 24), "Lets current flow one way only (anode → cathode).", "rectifier"),
    PartDef("led", "LED", "Diodes & LEDs", "LED", (("A", -30, 0), ("K", 30, 0)),
            (_p("colour", "Colour", "Red", kind="choice", choices=LED_COLOURS, on_label=True),
             _p("max_current", "Maximum current", 0.03, "A", min=0)),
            (-30, -24, 60, 36), "Light-emitting diode. Needs a series resistor or it will pop!", "light emitting"),
    PartDef("zener", "Zener diode", "Diodes & LEDs", "D", (("A", -30, 0), ("K", 30, 0)),
            (_p("voltage", "Zener voltage", 5.1, "V", on_label=True, min=0.5),),
            (-30, -12, 60, 24), "Conducts backwards at a set voltage — used as a voltage reference.", "regulator"),

    # ---------------------------------------------------------------- transistors
    PartDef("npn", "NPN transistor", "Transistors", "Q",
            (("B", -30, 0), ("C", 10, -30), ("E", 10, 30)),
            (_p("model", "Type", "BC548", kind="choice", choices=("BC548", "BC547", "BC337", "2N3904", "2N2222", "BD139", "TIP31", "TIP120")),),
            (-30, -30, 50, 60), "A small current into the base switches a bigger current.", "bjt bc548", short="NPN"),
    PartDef("pnp", "PNP transistor", "Transistors", "Q",
            (("B", -30, 0), ("C", 10, 30), ("E", 10, -30)),
            (_p("model", "Type", "BC558", kind="choice", choices=("BC558", "BC557", "BC327", "2N3906", "2N2907", "BD140", "TIP125")),),
            (-30, -30, 50, 60), "Like NPN but turns on when the base is pulled low.", "bjt bc558", short="PNP"),

    # ---------------------------------------------------------------- outputs
    PartDef("lamp", "Lamp", "Output devices", "L", TWO,
            (_p("voltage", "Rated voltage", 6.0, "V", on_label=True, min=0),
             _p("power", "Rated power", 0.36, "W", min=0)),
            (-30, -15, 60, 30), "A filament bulb.", "bulb light"),
    PartDef("buzzer", "Buzzer", "Output devices", "BZ", TWO_POL,
            (_p("voltage", "Rated voltage", 6.0, "V", on_label=True, min=0),),
            (-30, -20, 60, 32), "Beeps when current flows.", "sounder beeper"),
    PartDef("speaker", "Loudspeaker", "Output devices", "LS", TWO,
            (_p("impedance", "Impedance", 8.0, "Ω", on_label=True, min=0.1),),
            (-30, -20, 60, 32), "Plays the signal as sound — try a 555 or a signal generator at 100 Hz–5 kHz.",
            "loudspeaker sound"),
    PartDef("motor", "Motor", "Output devices", "M", TWO,
            (_p("voltage", "Rated voltage", 6.0, "V", on_label=True, min=0),
             _p("load", "Load", "None", kind="choice", choices=("None", "Light", "Medium", "Heavy"),
                help="How hard the motor has to work: more load, slower and more current")),
            (-30, -15, 60, 30), "A DC motor: draws a big current when starting, less once up to speed. "
            "Its speed depends on the voltage and how much load it drives.", "dc"),

    # ---------------------------------------------------------------- meters
    PartDef("voltmeter", "Voltmeter", "Meters & probes", "VM", TWO_POL, (),
            (-30, -15, 60, 30), "Measures the voltage across two points. Connect it in parallel.", "meter volts"),
    PartDef("ammeter", "Ammeter", "Meters & probes", "AM", TWO_POL, (),
            (-30, -15, 60, 30), "Measures the current through it. Connect it in series.", "meter amps current"),
]

# ------------------------------------------------------------------------------------------------ r3 parts
GATE2 = (("A", -40, -10), ("B", -40, 10), ("Y", 40, 0))
GATE1 = (("A", -40, 0), ("Y", 40, 0))
LOGIC_NOTE = " Logic chips are powered automatically from the circuit's supply."
SR_NOTE = " Unconnected active-low control pins (MR, OE, PL, CE) count as not active."

_PARTS += [
    PartDef("signal_gen", "Signal generator", "Power supplies", "SG", TWO_POL,
            (_p("waveform", "Waveform", "Square", kind="choice", choices=("Square", "Sine", "Triangle"),
                on_label=True),
             _p("frequency", "Frequency", 1.0, "Hz", on_label=True, min=1e-3, max=1e6),
             _p("amplitude", "Amplitude (peak)", 5.0, "V", min=0, max=1000),
             _p("offset", "Offset", 0.0, "V", min=-1000, max=1000),
             _p("duty", "Duty cycle (square)", 50.0, "%", min=1, max=99,
                help="How much of each cycle a square wave spends high — for PWM")),
            (-30, -20, 60, 40), "Makes square, sine or triangle waves — great with the graph.",
            "function generator clock pulse square wave", short="Signal generator"),

    PartDef("xtal_clock", "Crystal clock", "Power supplies", "X", (("OUT", 40, 0),),
            (_p("frequency", "Frequency", 1.0, "Hz", on_label=True, min=0.01, max=1e6),),
            (-30, -18, 60, 36), "A steady, accurate clock for logic: a quartz crystal oscillator (with a divider "
            "inside), so it keeps exact time — unlike a 555. OUT switches between 0 V and the supply."
            + LOGIC_NOTE, "crystal quartz oscillator clock pulse 32768 timer", short="Crystal clock"),
    PartDef("nmos", "N-channel MOSFET", "Transistors", "Q", (("G", -30, 0), ("D", 10, -30), ("S", 10, 30)),
            (_p("model", "Type", "2N7000", kind="choice", choices=("2N7000", "2N7002", "BS170", "AO3400", "IRLZ44N", "IRF530", "IRF540", "IRF3205")),),
            (-30, -30, 50, 60), "Switched on by voltage at the gate — almost no gate current.",
            "mosfet fet 2n7000 irf540", short="N-MOSFET"),
    PartDef("pmos", "P-channel MOSFET", "Transistors", "Q", (("G", -30, 0), ("D", 10, 30), ("S", 10, -30)),
            (_p("model", "Type", "BS250", kind="choice", choices=("BS250", "IRF9530", "IRF9540", "FQP27P06", "IRLML6402")),),
            (-30, -30, 50, 60), "Like N-channel, but turns on when the gate is pulled low.",
            "mosfet fet bs250", short="P-MOSFET"),

    PartDef("not", "NOT gate", "Logic gates", "U", GATE1, (), (-30, -15, 70, 30),
            "Output is the opposite of the input." + LOGIC_NOTE, "inverter", short="NOT"),
    PartDef("and", "AND gate", "Logic gates", "U", GATE2, (), (-30, -20, 70, 40),
            "Output high only when A and B are both high." + LOGIC_NOTE, short="AND"),
    PartDef("or", "OR gate", "Logic gates", "U", GATE2, (), (-30, -20, 70, 40),
            "Output high when A or B (or both) is high." + LOGIC_NOTE, short="OR"),
    PartDef("nand", "NAND gate", "Logic gates", "U", GATE2, (), (-30, -20, 70, 40),
            "AND followed by NOT." + LOGIC_NOTE, short="NAND"),
    PartDef("nor", "NOR gate", "Logic gates", "U", GATE2, (), (-30, -20, 70, 40),
            "OR followed by NOT." + LOGIC_NOTE, short="NOR"),
    PartDef("xor", "XOR gate", "Logic gates", "U", GATE2, (), (-30, -20, 70, 40),
            "Output high when A and B are different." + LOGIC_NOTE, "exclusive", short="XOR"),
    PartDef("schmitt_not", "Schmitt NOT gate", "Logic gates", "U", GATE1, (), (-30, -15, 70, 30),
            "Inverter with hysteresis: switches cleanly even on slow signals (40106)." + LOGIC_NOTE,
            "40106 schmitt trigger", short="Schmitt NOT"),
    PartDef("dff", "D-type flip-flop", "Logic gates", "U",
            (("D", -50, -20), ("CLK", -50, 0), ("R", -50, 20), ("Q", 50, -20), ("Qn", 50, 20)), (),
            (-30, -40, 60, 80), "Copies D to Q on each rising clock edge. R resets Q to 0." + LOGIC_NOTE,
            "4013 latch memory clock", short="D flip-flop"),
    PartDef("schmitt_nand", "Schmitt NAND gate", "Logic gates", "U", GATE2, (), (-30, -20, 70, 40),
            "NAND gate with hysteresis (4093): switches cleanly even on slow signals, so with a resistor and "
            "capacitor it makes an oscillator you can turn on and off." + LOGIC_NOTE,
            "4093 schmitt trigger nand oscillator", short="Schmitt NAND"),
    PartDef("jkff", "JK flip-flop", "Logic gates", "U",
            (("J", -50, -20), ("CLK", -50, 0), ("K", -50, 20), ("S", 0, -60), ("R", 0, 60),
             ("Q", 50, -20), ("Qn", 50, 20)), (),
            (-30, -40, 60, 80), "On each rising clock edge: J=1 sets Q to 1, K=1 resets it to 0, both 1 toggles it "
            "(so it divides the clock by 2), both 0 keeps it. S and R set or reset it straight away (4027)."
            + LOGIC_NOTE, "4027 jk flip flop toggle divide counter", short="JK flip-flop"),

    PartDef("timer555", "555 timer", "Integrated circuits", "IC",
            (("GND", -20, 60), ("TRIG", -60, 20), ("OUT", 60, 0), ("RESET", -20, -60), ("CTRL", 20, 60),
             ("THR", -60, 0), ("DIS", -60, -20), ("VCC", 20, -60)), (),
            (-40, -40, 80, 80), "The classic timer chip: flashers (astable) and one-shot timers (monostable).",
            "ne555 astable monostable timer clock", short="555 timer"),
    PartDef("opamp", "Op-amp", "Integrated circuits", "IC",
            (("-", -40, -10), ("+", -40, 10), ("out", 40, 0), ("V+", 0, -30), ("V-", 0, 30)),
            (_p("model", "Type", "741", kind="choice", choices=("741", "LM358", "TL071", "Rail-to-rail")),),
            (-30, -30, 60, 60), "Amplifier / comparator. If its supply pins are left unconnected it is "
            "powered automatically from the circuit's supply.", "741 lm358 comparator amplifier",
            short="Op-amp"),
    PartDef("counter4017", "Decade counter (4017)", "Integrated circuits", "IC",
            (("CLK", -60, -20), ("RST", -60, 0)) + tuple((f"Q{i}", 60, -50 + 10 * i) for i in range(10))
            + (("CO", 60, 50),), (),
            (-40, -60, 80, 120), "Each rising clock pulse moves the high output along: Q0, Q1 … Q9." + LOGIC_NOTE,
            "4017 johnson chaser sequencer", short="4017 counter"),
    PartDef("decoder4511", "7-segment decoder (4511)", "Integrated circuits", "IC",
            (("A", -60, -30), ("B", -60, -10), ("C", -60, 10), ("D", -60, 30))
            + tuple((s_, 60, -30 + 10 * i) for i, s_ in enumerate("abcdefg")), (),
            (-40, -40, 80, 80), "Turns a binary number (D C B A) into the segments for 0–9." + LOGIC_NOTE,
            "4511 bcd seven segment driver", short="4511 decoder"),

    PartDef("sevenseg", "7-segment display", "Output devices", "DS",
            tuple((s_, -50, -30 + 10 * i) for i, s_ in enumerate("abcdefg")) + (("COM", 0, 60),),
            (_p("colour", "Colour", "Red", kind="choice", choices=LED_COLOURS, on_label=False),),
            (-30, -50, 60, 100), "Common-cathode display with built-in resistors: a segment lights when "
            "its pin is high.", "seven segment led digit", short="7-segment"),

    PartDef("scope_probe", "Graph probe", "Meters & probes", "P", (("1", 0, 0),),
            (_p("channel", "Channel", "A", kind="choice", choices=("A", "B", "C", "D"), on_label=True),),
            (-12, -32, 24, 34), "Put it on a wire to plot that wire's voltage on the graph while running.",
            "oscilloscope scope graph trace plot", short="Graph probe"),
    PartDef("logic_probe", "Logic probe", "Meters & probes", "LP", (("1", 0, 0),), (),
            (-14, -40, 28, 42), "Shows H (high), L (low) or ? on whatever it touches.",
            "high low tester", short="Logic probe"),
]


# ------------------------------------------------------------------------------------------------ r4 parts
_PARTS += [
    PartDef("inductor", "Inductor", "Capacitors & inductors", "L", TWO,
            (_p("inductance", "Inductance", 10e-3, "H", on_label=True, min=1e-9),),
            (-30, -10, 60, 18), "A coil: resists changes in current (stores energy in a magnetic field).",
            "coil choke"),
    PartDef("relay", "Relay", "Switches", "RL",
            (("C1", -20, -30), ("C2", -20, 30), ("COM", 20, 30), ("NC", 10, -30), ("NO", 30, -30)),
            (_p("voltage", "Coil voltage", 6.0, "V", on_label=True, min=0.5),),
            (-30, -30, 70, 60), "A switch worked by an electromagnet. Current in the coil (C1–C2) flips COM from "
            "NC to NO. Put a diode across the coil!", "electromagnet switch coil spdt"),
    PartDef("reed_switch", "Reed switch", "Input sensors", "S", TWO,
            (_p("magnet", "Magnet nearby", False, kind="bool"),),
            (-30, -12, 60, 24), "Closes when a magnet is near. Click it while running to bring the magnet close.",
            "magnet door alarm", short="Reed switch"),
    PartDef("tilt_switch", "Tilt switch", "Input sensors", "S", TWO,
            (_p("tilted", "Tilted", False, kind="bool"),),
            (-30, -14, 60, 28), "A ball inside connects the contacts when it's tilted. Click it while running.",
            "ball mercury", short="Tilt switch"),
    PartDef("moisture", "Moisture sensor", "Input sensors", "MS", TWO,
            (_p("moisture", "Moisture", 0.0, "%", min=0, max=100, help="0 % = dry, 100 % = soaking wet"),),
            (-30, -20, 60, 34), "Two probes: the wetter the soil, the lower the resistance.",
            "water rain soil probe", short="Moisture"),
    PartDef("phototransistor", "Phototransistor", "Input sensors", "Q", (("C", 10, -30), ("E", 10, 30)),
            (_p("light", "Light level", 500.0, "lux", min=0, max=100000),),
            (-25, -30, 45, 60), "A transistor turned on by light instead of a base current. Collector at the top.",
            "light sensor photo", short="Phototransistor"),
    PartDef("optocoupler", "Optoisolator", "Transistors", "U",
            (("A", -40, -20), ("K", -40, 20), ("C", 40, -20), ("E", 40, 20)),
            (_p("model", "Type", "PC817", kind="choice", choices=("PC817", "4N25", "4N35", "TLP521", "6N139"),
                on_label=True),),
            (-40, -32, 80, 64), "An LED shining on a phototransistor inside one package: current through A–K "
            "switches C–E on, with no electrical connection between the two sides. Needs a resistor in series "
            "with the LED.", "optocoupler opto isolator coupler pc817 4n25 4n35 tlp521 6n139 isolation",
            short="Optoisolator"),
    # ---------------------------------------------------------------- requested by users (1.3.0)
    PartDef("shunt_ref", "Shunt regulator (TL431)", "Diodes & LEDs", "U",
            (("K", 0, -30), ("A", 0, 30), ("REF", -30, 0)),
            (_p("model", "Type", "TL431", kind="choice", choices=("TL431", "TLV431"), on_label=True),),
            (-30, -30, 50, 60), "An adjustable precision reference: it sinks current at its cathode (K) to hold "
            "its REF pin at 2.495 V (TL431) or 1.24 V (TLV431). Feed it through a resistor, set the output with "
            "two resistors: Vout = Vref × (1 + R1 / R2).",
            "tl431 tlv431 reference zener regulator shunt adjustable", short="TL431"),
    PartDef("ssr", "Solid-state relay", "Switches", "K",
            (("A", -40, -20), ("K", -40, 20), ("O1", 40, -20), ("O2", 40, 20)),
            (_p("model", "Type", "TLP3122A", kind="choice", choices=("TLP3122A",), on_label=True),),
            (-40, -32, 80, 64), "A relay with no moving parts: a small current through its LED (A–K) turns on "
            "MOSFETs between O1 and O2 — AC or DC, silent, and isolated from the LED side. Needs a resistor in "
            "series with the LED.", "ssr photomos photorelay tlp3122a solid state relay", short="SSR"),
    PartDef("mux4051", "8-channel analogue switch (4051)", "Integrated circuits", "IC",
            (("COM", -60, -40), ("A", -60, 0), ("B", -60, 10), ("C", -60, 20), ("INH", -60, 30))
            + tuple((f"Y{i}", 60, -40 + 10 * i) for i in range(8)),
            (_p("model", "Type", "CD4051B", kind="choice", choices=("CD4051B", "74HC4051"), on_label=True),),
            (-40, -50, 80, 90), "Connects COM to one of Y0–Y7, picked by the binary number on C B A — an "
            "analogue switch, so signals can go either way. INH high turns all the switches off."
            + LOGIC_NOTE, "mux multiplexer demultiplexer 4051 cd4051 74hc4051 analog switch", short="4051 mux"),
    PartDef("sr164", "Shift register (74HC164)", "Integrated circuits", "IC",
            (("DSA", -60, -30), ("DSB", -60, -10), ("CP", -60, 10), ("MR", -60, 30))
            + tuple((f"Q{i}", 60, -40 + 10 * i) for i in range(8)), (),
            (-40, -50, 80, 90), "Serial in, parallel out: on each rising clock (CP) the bits move along Q0 → Q7 "
            "and Q0 takes DSA AND DSB. MR low clears it. 74HC: for 2–6 V circuits." + LOGIC_NOTE
            + SR_NOTE, "74hc164 164 shift register sipo serial", short="74HC164"),
    PartDef("sr595", "Shift register with latch (74HC595)", "Integrated circuits", "IC",
            (("DS", -60, -40), ("SHCP", -60, -20), ("STCP", -60, 0), ("MR", -60, 20), ("OE", -60, 40))
            + tuple((f"Q{i}", 60, -40 + 10 * i) for i in range(8)) + (("Q7S", 60, 40),), (),
            (-40, -50, 80, 100), "Serial in, parallel out, with a latch: clock bits in with SHCP, then a rising "
            "STCP copies them to Q0–Q7 all at once. Q7S passes the data on to the next chip. OE high switches "
            "the outputs off; MR low clears the shift register. 74HC: for 2–6 V circuits."
            + LOGIC_NOTE + SR_NOTE, "74hc595 595 shift register latch sipo", short="74HC595"),
    PartDef("sr165", "Shift register (74HC165)", "Integrated circuits", "IC",
            tuple((f"D{i}", -60, -60 + 10 * i) for i in range(8))
            + (("DS", -60, 20), ("CP", -60, 30), ("CE", -60, 40), ("PL", -60, 50))
            + (("Q7", 60, -10), ("Q7N", 60, 10)), (),
            (-40, -70, 80, 130), "Parallel in, serial out: PL low loads D0–D7, then each rising clock (CP, with "
            "CE low) shifts the bits out of Q7, with DS coming in behind. For reading lots of buttons with few "
            "pins. 74HC: for 2–6 V circuits." + LOGIC_NOTE + SR_NOTE,
            "74hc165 165 shift register piso parallel load", short="74HC165"),
    PartDef("sr597", "Shift register with input latch (74HC597)", "Integrated circuits", "IC",
            tuple((f"D{i}", -60, -60 + 10 * i) for i in range(8))
            + (("DS", -60, 20), ("SHCP", -60, 30), ("STCP", -60, 40), ("PL", -60, 50), ("MR", -60, 60))
            + (("Q7", 60, 0),), (),
            (-40, -70, 80, 140), "Parallel in, serial out, with an input latch: a rising STCP captures D0–D7, "
            "PL low copies them into the shift register, and each rising SHCP shifts them out of Q7. MR low "
            "clears the shift register. 74HC: for 2–6 V circuits." + LOGIC_NOTE + SR_NOTE,
            "74hc597 597 shift register piso latch", short="74HC597"),
    # ---------------------------------------------------------------- 1.4.0
    PartDef("led_bi2", "Bi-colour LED (2 legs)", "Diodes & LEDs", "LED", (("A", -30, 0), ("B", 30, 0)),
            (_p("max_current", "Maximum current", 0.03, "A", min=0),),
            (-30, -28, 60, 48), "A red and a green LED back to back in one package: current from A to B lights "
            "it red, from B to A green. Swap the direction quickly (or use AC) and it looks yellow. Needs a "
            "resistor in series.", "bicolour bicolor two colour dual red green led", short="Bi-colour LED"),
    PartDef("led_bi3", "Bi-colour LED (3 legs)", "Diodes & LEDs", "LED",
            (("R", -30, -10), ("G", -30, 10), ("K", 30, 0)),
            (_p("max_current", "Maximum current", 0.03, "A", min=0),),
            (-30, -30, 60, 54), "A red and a green LED sharing one cathode (K): R lights red, G lights green, "
            "both together look yellow. Each anode needs its own resistor.",
            "bicolour bicolor dual three leg common cathode red green led", short="Bi-colour LED (3)"),
    PartDef("led_rgb", "RGB LED", "Diodes & LEDs", "LED",
            (("R", -30, -20), ("G", -30, 0), ("B", -30, 20), ("K", 30, 0)),
            (_p("max_current", "Maximum current", 0.03, "A", min=0),),
            (-30, -40, 60, 68), "Red, green and blue LEDs sharing one cathode (K). Mix them to make other "
            "colours: red + green = yellow, all three = white. Each anode needs its own resistor; use PWM "
            "(a signal generator) for in-between brightness.", "rgb colour mixing common cathode led",
            short="RGB LED"),
    PartDef("bridge", "Bridge rectifier", "Diodes & LEDs", "BR",
            (("AC1", 0, -40), ("AC2", 0, 40), ("+", 40, 0), ("-", -40, 0)),
            (_p("rating", "Current rating", 1.0, "A", on_label=True, min=0.01),),
            (-30, -30, 60, 60), "Four diodes in one package: turns AC into DC (full-wave), so + is always "
            "positive whichever way round the AC is. Add a big capacitor across + and − to smooth it.",
            "rectifier diode bridge full wave ac dc w01 db107", short="Bridge rectifier"),
    PartDef("scr", "Thyristor (SCR)", "Transistors", "SCR", (("A", -30, 0), ("K", 30, 0), ("G", 10, 30)),
            (_p("model", "Type", "C106D", kind="choice", choices=("C106D", "2N5060", "TIC106D", "BT151")),),
            (-30, -20, 60, 50), "A switch that latches: a small current into the gate (G) turns it on, and it "
            "stays on — even when the gate current stops — until the current through it (A → K) stops. The "
            "classic alarm that keeps sounding after the trigger has gone: reset it by breaking the circuit.",
            "thyristor scr latch c106 2n5060 tic106 bt151 alarm", short="Thyristor"),
    PartDef("reg_fixed", "Voltage regulator (78xx)", "Power supplies", "IC",
            (("IN", -50, 0), ("GND", 0, 30), ("OUT", 50, 0)),
            (_p("model", "Type", "7805", kind="choice", choices=("7805", "7809", "7812", "LM1117-3.3"),
                on_label=True),
             _p("heatsink", "On a heatsink", False, kind="bool",
                help="Without a heatsink it can only get rid of about 1.5 W before it overheats")),
            (-40, -20, 80, 40), "Gives a steady output voltage (5 V for a 7805) from a higher, rougher input. "
            "The input must be about 2 V above the output. The extra voltage is turned into heat, so it "
            "shuts down if it gets too hot.", "regulator 7805 7809 7812 lm7805 1117 ldo 5v power supply",
            short="78xx regulator"),
    PartDef("reg_adj", "Adjustable regulator (LM317)", "Power supplies", "IC",
            (("IN", -50, 0), ("ADJ", 0, 30), ("OUT", 50, 0)),
            (_p("heatsink", "On a heatsink", False, kind="bool",
                help="Without a heatsink it can only get rid of about 1.5 W before it overheats"),),
            (-40, -20, 80, 40), "A regulator you set with two resistors: it holds OUT 1.25 V above ADJ, so with "
            "R1 from OUT to ADJ and R2 from ADJ to 0 V, Vout = 1.25 V × (1 + R2 / R1). Typically R1 = 240 Ω.",
            "regulator lm317 adjustable variable power supply", short="LM317"),
    PartDef("transformer", "Transformer", "Power supplies", "T",
            (("P1", -40, -30), ("P2", -40, 30), ("S1", 40, -30), ("S2", 40, 30)),
            (_p("ratio", "Turns ratio (primary ÷ secondary)", 10.0, "", on_label=True, min=0.01, max=1000,
                help="10 means the secondary gives a tenth of the primary voltage"),
             _p("rating", "Power rating", 5.0, "W", min=0.01)),
            (-30, -30, 60, 60), "Two coils on one core: AC on the primary (P1–P2) makes AC on the secondary "
            "(S1–S2), stepped down (or up) by the turns ratio. The two sides aren't connected. Only works with AC.",
            "transformer step down step up mains coil isolation", short="Transformer"),
    PartDef("dpdt", "Double changeover switch (DPDT)", "Switches", "S",
            (("com1", -30, -20), ("a1", 30, -30), ("b1", 30, -10),
             ("com2", -30, 20), ("a2", 30, 10), ("b2", 30, 30)),
            (_p("position", "Position", "A", kind="choice", choices=("A", "B")),),
            (-30, -38, 60, 76), "Two changeover switches worked together: both commons go to A, or both to B. "
            "Used to reverse a motor. Click it while running.", "dpdt double pole reversing motor two way",
            short="DPDT switch"),
    PartDef("rotary", "Rotary switch", "Switches", "S",
            (("COM", -30, 0), ("1", 30, -30), ("2", 30, -10), ("3", 30, 10), ("4", 30, 30)),
            (_p("position", "Position", "1", kind="choice", choices=("1", "2", "3", "4")),),
            (-30, -38, 60, 76), "Connects COM to one of four contacts. Click it while running to turn it to the "
            "next position.", "rotary selector switch way position knob", short="Rotary switch"),
    PartDef("keypad", "Keypad (12 keys)", "Switches", "KP",
            tuple((f"R{i + 1}", -30 + 10 * i, 70) for i in range(4)) + tuple((f"C{i + 1}", 10 + 10 * i, 70)
                                                                             for i in range(3)), (),
            (-40, -55, 80, 110), "Like a phone or door-lock keypad: each key joins its row (R1–R4) to its column "
            "(C1–C3) while it's pressed. Click and hold a key while running.",
            "keypad keyboard matrix buttons door lock code", short="Keypad"),
    PartDef("relay_dpdt", "DPDT relay", "Switches", "RL",
            (("C1", -40, -30), ("C2", -40, 30), ("COM1", 0, -20), ("NC1", 40, -30), ("NO1", 40, -10),
             ("COM2", 0, 20), ("NC2", 40, 10), ("NO2", 40, 30)),
            (_p("voltage", "Coil voltage", 6.0, "V", on_label=True, min=0.5),),
            (-50, -38, 100, 76), "A relay with two changeover switches: current in the coil (C1–C2) flips both "
            "COMs from NC to NO together. Used to reverse a motor or switch two circuits at once. Put a diode "
            "across the coil!", "relay double pole dpdt reversing motor electromagnet two changeover",
            short="DPDT relay"),
    PartDef("hall", "Hall effect sensor", "Input sensors", "U",
            (("VCC", 0, -30), ("GND", 0, 30), ("OUT", 30, 0)),
            (_p("magnet", "Magnet nearby", False, kind="bool"),),
            (-25, -30, 55, 60), "Senses a magnet (A3144 type). Its output is an open collector: it pulls OUT down "
            "to 0 V when a magnet is near, so use a pull-up resistor from OUT to +. Needs 4.5–24 V on VCC. Click "
            "it while running to bring the magnet close.", "hall effect magnet sensor a3144 switch",
            short="Hall sensor"),
    PartDef("stepper", "Stepper motor", "Output devices", "M",
            (("A1", -40, -10), ("A2", -40, 10), ("B1", 40, -10), ("B2", 40, 10)),
            (_p("voltage", "Rated voltage", 12.0, "V", on_label=True, min=1),
             _p("steps", "Steps per turn", "48", kind="choice", choices=("48", "200"))),
            (-28, -28, 56, 56), "Turns in exact steps: current through one coil (A1–A2 or B1–B2) pulls the shaft "
            "to the next position. Energise A, B, then A and B the other way round (e.g. with an L293D) and it turns "
            "step by step. 48 steps is 7.5° a step; 200 is 1.8°.", "stepper motor step bipolar l293d",
            short="Stepper motor"),
    PartDef("solenoid", "Solenoid", "Output devices", "SOL", TWO,
            (_p("voltage", "Rated voltage", 12.0, "V", on_label=True, min=0.5),),
            (-30, -16, 60, 32), "An electromagnet that pulls a metal plunger in — for door locks and valves. "
            "Like a relay coil, it makes a big voltage spike when switched off: put a diode across it.",
            "solenoid plunger actuator lock valve coil electromagnet"),
    PartDef("comparator", "Comparator", "Integrated circuits", "IC",
            (("+", -40, -10), ("-", -40, 10), ("OUT", 40, 0)),
            (_p("model", "Type", "LM393", kind="choice", choices=("LM393", "LM311"), on_label=True),),
            (-30, -30, 70, 60), "Compares two voltages: when + is lower than −, OUT is pulled to 0 V; when + is "
            "higher, OUT is switched off (open collector), so add a pull-up resistor from OUT to +. Switches more "
            "cleanly than an op-amp." + LOGIC_NOTE, "comparator lm393 lm311 lm339 compare threshold",
            short="Comparator"),
    PartDef("ic4026", "Counter and display driver (4026)", "Integrated circuits", "IC",
            (("CLK", -60, -30), ("INH", -60, -10), ("RST", -60, 10))
            + tuple((s_, 60, -30 + 10 * i) for i, s_ in enumerate("abcdefg")) + (("CO", 60, 50),), (),
            (-40, -40, 80, 100), "Counts rising clock pulses 0–9 and drives a 7-segment display directly. CO "
            "goes high after 9, to clock the next 4026 for tens. RST high resets it to 0; INH high pauses it."
            + LOGIC_NOTE, "4026 counter decade seven segment display driver", short="4026 counter"),
    PartDef("l293d", "Motor driver (L293D)", "Integrated circuits", "IC",
            (("EN12", -60, -40), ("1A", -60, -30), ("2A", -60, -20), ("EN34", -60, 10), ("3A", -60, 20),
             ("4A", -60, 30), ("1Y", 60, -30), ("2Y", 60, -20), ("3Y", 60, 20), ("4Y", 60, 30),
             ("VCC1", -20, -80), ("VCC2", 20, -80), ("GND", 0, 70)), (),
            (-40, -60, 80, 110), "Four half-H drivers: each output Y follows its input A while its enable (EN) is "
            "high, so 1Y and 2Y together drive a motor forwards, backwards or stopped. VCC1 is the logic supply "
            "(5 V); VCC2 powers the motor (up to 36 V). About 0.6 A per output, with spike-catching diodes "
            "built in.", "l293d l293 h bridge h-bridge motor driver reverse stepper", short="L293D"),
    PartDef("ic4060", "Counter and oscillator (4060)", "Integrated circuits", "IC",
            (("PI", -60, -40), ("PO", -60, -20), ("POn", -60, 0), ("MR", -60, 30))
            + tuple((f"Q{n}", 60, -50 + 10 * i) for i, n in enumerate((4, 5, 6, 7, 8, 9, 10, 12, 13, 14))), (),
            (-40, -60, 80, 110), "A 14-stage counter with its own oscillator — for long, accurate timers. Connect "
            "a capacitor C from CTC to a point X, a resistor R from RTC to X, and about 10 × R from X to RS: it "
            "oscillates at about 1 ÷ (2.3 R C), and Q4 … Q14 divide that by 16 … 16384. MR high resets it."
            + LOGIC_NOTE, "4060 counter oscillator timer divider binary", short="4060 counter"),
    PartDef("note", "Text note", "Labels", "T", (),
            (_p("text", "Text", "Note", kind="text"),),
            (-40, -10, 80, 20), "A note on the diagram — for reports, documentation or worksheets. Double-click to change the text.",
            "label annotation text comment", short="Text note"),
]

PARTS: dict[str, PartDef] = {p.key: p for p in _PARTS}


def by_category() -> list[tuple[str, list[PartDef]]]:
    return [(c, [p for p in _PARTS if p.category == c]) for c in CATEGORIES
            if any(p.category == c for p in _PARTS)]


def get(key: str) -> PartDef:
    try:
        return PARTS[key]
    except KeyError:
        raise KeyError(f"Unknown part type '{key}'") from None
