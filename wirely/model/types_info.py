"""What each part type (model number) is good for: shown under the Type box when you double-click a part,
so you can tell, say, why you'd pick an AO3400 over a 2N7002. Figures are typical datasheet values."""

from ..i18n import tr

TYPE_INFO = {
    # ---------------------------------------------------------------- diodes
    "1N4001": "General-purpose rectifier: 1 A, 50 V. For power supplies and reverse-polarity protection.",
    "1N4007": "Same as the 1N4001 but rated to 1000 V — the usual choice for mains rectifiers.",
    "1N4148": "Small fast signal diode: 0.3 A, 100 V. For logic, signals and catching small relay coil spikes.",
    "1N5408": "Big rectifier: 3 A, 1000 V. For higher-current power supplies.",
    "1N5819": "Schottky: only about 0.4 V drop and very fast. For switch-mode supplies and low-voltage protection.",

    # ---------------------------------------------------------------- NPN
    "BC548": "Small-signal NPN: 100 mA, 30 V, gain about 290. The classic for switching LEDs and small relays.",
    "BC547": "Like the BC548 but rated to 45 V.",
    "BC337": "Medium-current NPN: up to 800 mA, 45 V. For relays, small motors and buzzers.",
    "2N3904": "Small-signal NPN: 200 mA, 40 V. The common US equivalent of the BC548.",
    "2N2222": "Medium-current NPN: up to 800 mA, 40 V. A very common general-purpose switch.",
    "BD139": "Power NPN: 1.5 A, 80 V, in a package you can bolt to a heatsink. For motors and audio.",
    "TIP31": "Power NPN: 3 A, 40 V. For motors, lamps and solenoids.",
    "TIP120": "Darlington NPN: gain about 1000 and 5 A, so a tiny base current switches a big load — but it drops "
              "about 1 V even when fully on, so it runs warm.",

    # ---------------------------------------------------------------- PNP
    "BC558": "Small-signal PNP: 100 mA, 30 V. Turns on when the base is pulled low; the partner of the BC548.",
    "BC557": "Like the BC558 but rated to 45 V; the partner of the BC547.",
    "BC327": "Medium-current PNP: up to 800 mA, 45 V; the partner of the BC337.",
    "2N3906": "Small-signal PNP: 200 mA, 40 V; the partner of the 2N3904.",
    "2N2907": "Medium-current PNP: up to 600 mA, 40 V; the partner of the 2N2222.",
    "BD140": "Power PNP: 1.5 A, 80 V; the partner of the BD139.",
    "TIP125": "Darlington PNP: gain about 1000, 5 A; the partner of the TIP120.",

    # ---------------------------------------------------------------- N-channel MOSFETs
    "2N7000": "Small N-channel MOSFET (through-hole): 200 mA, 60 V, about 1.2 Ω when on with a 10 V gate. "
              "Fine for LEDs and small relays; only partly on from a 3.3 V logic pin.",
    "2N7002": "The surface-mount (SOT-23) version of the 2N7000: about 0.3 A, 60 V, roughly 1 Ω. For small loads "
              "and logic level shifting, not for motors.",
    "BS170": "Small N-channel MOSFET (through-hole): 500 mA, 60 V, about 1.2 Ω. Like a 2N7000 with a bit "
             "more current.",
    "AO3400": "Small surface-mount MOSFET that's fully on from just 2.5 V on the gate: 5.7 A, 30 V, about 20 mΩ. "
              "Pick it over a 2N7002 to switch real loads (motors, LED strips) straight from a 3.3 V "
              "microcontroller: it has about 50× less resistance.",
    "IRLZ44N": "Logic-level power MOSFET (TO-220): fully on from about 5 V, 47 A, 55 V, about 20 mΩ. The go-to "
               "for switching motors and LED strips from a 5 V Arduino.",
    "IRF530": "Power MOSFET: 14 A, 100 V, about 0.12 Ω — but it needs about 10 V on the gate to turn fully on.",
    "IRF540": "Power MOSFET: 28 A, 100 V, about 60 mΩ — needs about 10 V on the gate (not logic-level: only "
              "partly on from 5 V).",
    "IRF3205": "Very low-resistance power MOSFET: 110 A, 55 V, about 6.5 mΩ. For big motors and high-current "
               "switching; needs about 10 V on the gate.",

    # ---------------------------------------------------------------- P-channel MOSFETs
    "BS250": "Small P-channel MOSFET: 230 mA, 45 V, about 10 Ω. For switching small loads on the + side.",
    "IRF9530": "Power P-channel MOSFET: 12 A, 100 V, about 0.2 Ω. Switches the + side of a load; needs about "
               "−10 V gate-to-source.",
    "IRF9540": "Power P-channel MOSFET: 19 A, 100 V, about 0.15 Ω. The partner of the IRF540.",
    "FQP27P06": "Power P-channel MOSFET: 27 A, 60 V, about 55 mΩ. A popular high-side switch for 12 V systems.",
    "IRLML6402": "Tiny surface-mount P-channel MOSFET, fully on from −2.5 V: 3.7 A, 20 V, about 50 mΩ. For "
                 "battery switching and reverse-polarity protection in 3.3–5 V circuits.",

    # ---------------------------------------------------------------- op-amps
    "741": "The classic op-amp: needs a split (±) supply of at least ±5 V, output stops about 1 V short of each "
           "rail. Fine for learning; slow (0.5 V/µs).",
    "LM358": "Cheap dual op-amp that works on a single supply (3–32 V) and whose inputs and output reach 0 V — "
             "but not the top rail. Great for 5–12 V sensor circuits.",
    "TL071": "JFET-input op-amp: almost no input current (30 pA) and fast (13 V/µs). For audio and very "
             "high-resistance circuits; best on ±5 V or more.",
    "Rail-to-rail": "A modern CMOS op-amp whose output reaches both supply rails. Best on 3.3–5 V supplies.",

    # ---------------------------------------------------------------- optoisolators and relays
    "PC817": "The common optoisolator: current gain (CTR) about 130 %, 35 V output. For isolating a "
             "microcontroller from another circuit.",
    "4N25": "Older optoisolator with lower gain (about 50 %): give its LED more current.",
    "4N35": "Like the 4N25 with higher gain (about 100 %).",
    "TLP521": "Optoisolator with a 55 V output: gain about 100 %.",
    "6N139": "Darlington-output optoisolator: very high gain, so a small LED current switches a bigger load.",
    "TLP3122A": "Photo-MOSFET solid-state relay: about 1 mA in its LED switches up to 1.4 A at 60 V, AC or DC, "
                "with no clicking and no contacts to wear out. About 0.25 Ω when on.",

    # ---------------------------------------------------------------- shunt regulators
    "TL431": "Adjustable precision reference: holds its REF pin at 2.495 V by sinking current at its cathode. "
             "Two resistors set any voltage from 2.5 to 36 V; up to 100 mA.",
    "TLV431": "Low-voltage version of the TL431: 1.24 V reference, so it works in 1.24–6 V circuits "
              "(3.3 V rails); up to 15 mA.",

    # ---------------------------------------------------------------- analogue multiplexers
    "CD4051B": "8-channel analogue switch (4000 series): runs on 3–18 V, about 470 Ω on at 5 V and 125 Ω at 15 V.",
    "74HC4051": "8-channel analogue switch (74HC): faster and lower resistance (about 100 Ω at 5 V) but only for "
                "2–10 V supplies.",

    # ---------------------------------------------------------------- thyristors (1.4.0)
    "C106D": "Small, sensitive thyristor: 4 A, 400 V, triggers from about 0.2 mA of gate current. The usual "
             "choice for latching alarms and school projects.",
    "2N5060": "Tiny sensitive thyristor (TO-92): 0.8 A, 30 V, triggers from 0.2 mA. For low-power latches.",
    "TIC106D": "Like the C106D in a bigger package: 5 A, 400 V, sensitive gate.",
    "BT151": "Power thyristor: 12 A, 500 V, but it needs a few mA into its gate and more current to stay on.",

    # ---------------------------------------------------------------- regulators
    "7805": "Fixed 5 V regulator, up to 1.5 A. Needs at least about 7 V in. The classic for powering logic "
            "and microcontrollers from a 9–12 V supply.",
    "7809": "Fixed 9 V regulator, up to 1.5 A. Needs at least about 11 V in.",
    "7812": "Fixed 12 V regulator, up to 1.5 A. Needs at least about 14 V in.",
    "LM1117-3.3": "Low-dropout 3.3 V regulator, up to 0.8 A: works from as little as about 4.4 V in — for 3.3 V "
                  "microcontrollers running from 5 V. Maximum 15 V in.",

    # ---------------------------------------------------------------- comparators
    "LM393": "Dual comparator for single supplies (2–36 V): inputs work down to 0 V, open-collector output "
             "that can sink about 16 mA.",
    "LM311": "Faster comparator with a stronger output: sinks up to 50 mA, enough for a relay or a small lamp.",
}


def describe(model: str) -> str:
    text = TYPE_INFO.get(str(model), "")
    return tr(text) if text else ""
