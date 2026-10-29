# Wirely

**A free, open-source circuit design and simulation app for Windows, Mac and Linux — and in your web browser.**
Draw a circuit, press play, and watch it work — LEDs light, motors spin, relays click, meters read and wires
show their voltage. For the workplace, the classroom and the workbench, all on your own computer, with no cloud
and no account.

**▶ [Try it in your browser](https://wirely-app.github.io/)** — nothing to install, and it works on
Chromebooks. Or [download the app](#download-and-install) for Windows, Mac and Linux.

Under the hood is a real circuit solver, using the same method as SPICE, checked against hand calculations and
against ngspice. So the numbers it shows are the numbers you'd measure.

![Wirely demo: place a battery, switch, resistor and LED, wire them up, press play, switch on and hover a wire to read its voltage and current](docs/images/demo.gif)

## Why I made it

I wanted to try circuits out before building them — at work and at home — in something that's quick and
friendly to use. The friendly drag-and-drop simulators are mostly paid-for and aimed only at schools, and the
free professional tools, such as LTspice and ngspice, are powerful but you spend your time on netlists,
models and graph settings rather than on the circuit.

I wanted something in between: a simulator that is **as easy as drawing the circuit**, but **free**, **runs
locally**, and is **accurate enough to trust at work** —

- sketch a circuit and **see straight away** whether it works: what lights, what's too hot, what pops,
- **click switches and drag sliders** while it runs, and **hover over any wire** to read its voltage and current,
- look at signals on a **graph (oscilloscope)** — 555 timers, filters, PWM, a buck converter,
- use real part numbers (**BC547, 2N2222, TIP31, IRF540, IRLZ44N, LM358, TL071, PC817, 1N4148, 1N4007 …**),
- **export** clean diagrams for reports, documentation and worksheets.

So I built Wirely (with a lot of help from Claude, an AI assistant), testing every revision against known
answers.

## What it does

- **Schematic editor** — a parts gallery of 84 parts with British (IEC) or US symbols, drag-and-drop, wiring by
  dragging pin to pin, junctions, rotate and flip, undo/redo, copy/paste, text notes, autosave and crash
  recovery.
- **Live simulation** — glowing LEDs and lamps (PWM dims them, as in real life), motors with back-EMF that slow under load, relays that click,
  buzzers and loudspeakers you can hear, meters with live readouts, voltage-coloured wires and moving current
  flow.
- **Interactive** — switches, push buttons, reed and tilt switches, potentiometers, light and temperature
  sensors: click and drag them while the circuit runs.
- **Things break, like the real thing** — LEDs without a resistor, overloaded resistors, reversed
  electrolytics, transistors killed by a coil's voltage spike: they pop and tell you why.
- **Readings** — one button shows the voltage and current on every wire and the voltage, current and power of
  every part while it runs; click any wire or part to pin just its reading; or **Copy readings** to paste
  them all into a spreadsheet.
- **Graph and logic probe** — up to four probes, frequency read-outs, adjustable time and volts per division.
- **Chips** — 555 timer, op-amps, comparators (LM393, LM311), the L293D motor driver, logic gates, 4017, 4026 and 4060 counters,
  4511 decoder, 7-segment display, 7805/7809/7812/LM1117 and LM317 voltage regulators,
  74HC164/165/595/597 shift registers, the 4051 analogue switch, TL431/TLV431 references,
  optoisolators (PC817, 4N25, 4N35, TLP521, 6N139), solid-state relays (TLP3122A), MOSFETs,
  transistors, thyristors (SCRs), relays, signal generator with PWM.
- **More parts** — bi-colour and RGB LEDs, bridge rectifier, transformer, DPDT switch and relay, Hall effect sensor,
  solenoid, stepper motor, rotary switch, 12-key keypad, crystal clock, JK flip-flop and Schmitt NAND (4093).
- **Every part type explained** — double-click a part and choose its type: a line underneath says what it's
  good for (e.g. why you'd pick an AO3400 over a 2N7002).
- **Export** — PNG, SVG and PDF (always on white paper), and a parts list you can copy or save as CSV.
- **In your language** — a **Language** menu switches the whole program, live, between English, Español, Deutsch
  and 日本語 (desktop app and website). Saved circuits work in any language.
- **Feels modern** — a flat look with light and dark themes, a splash screen, and an installer that makes
  `.wirely` files open in Wirely with their own icon.

| Editor and parts gallery | Hover to read any wire | Buck converter on the graph | Dark theme |
|---|---|---|---|
| ![](docs/images/editor.png) | ![](docs/images/hover_reading.png) | ![](docs/images/buck_converter.png) | ![](docs/images/dark_theme.png) |

## Download and install

Get it from the [**latest release**](https://github.com/wirely-app/wirely-app.github.io/releases/latest) — no Python or
anything else needed:

- **Windows:** `Wirely-Setup-<version>.exe` — run it and follow the installer. It adds Wirely to the Start menu and
  makes `.wirely` files open in Wirely. Windows SmartScreen may warn the first time because the installer
  isn't code-signed yet: click **More info → Run anyway**.
- **Mac (Apple Silicon, M1 or newer):** `Wirely-<version>-mac-arm64.dmg` — open it and drag Wirely into
  Applications. It isn't signed by Apple yet, so the first time: right-click Wirely in Applications →
  **Open** → **Open**.
- **Linux:** `Wirely-<version>-x86_64.AppImage` — make it executable and run it:
  `chmod +x Wirely-*-x86_64.AppImage && ./Wirely-*-x86_64.AppImage`
  (or right-click → Properties → "Allow executing as program", then double-click). If it says FUSE is
  missing, run it with `--appimage-extract-and-run`, or install `libfuse2` (Ubuntu: `sudo apt install libfuse2t64`).
  To add it to your app menu: `bash packaging/linux/install-desktop.sh Wirely-<version>-x86_64.AppImage`.

<p align="center"><img src="docs/images/splash.png" width="480" alt="Wirely starting up"></p>

### Or use it in a web browser (Chromebooks, school computers)

Open **[wirely-app.github.io](https://wirely-app.github.io/)** in Chrome, Edge, Firefox or
Safari — nothing to install and no account. It's the same Wirely: the same parts, symbols, examples and
simulator, running inside the browser (the desktop app's own Python code, run by
[Pyodide](https://pyodide.org)). Your circuits stay on your computer — nothing is uploaded. (The website counts
visits with [GoatCounter](https://www.goatcounter.com): no cookies and no personal data.)

- **Save** gives you a `.wirely` file, which opens in the browser version and the desktop app alike.
- **File → Copy a link to this circuit** makes a link with the circuit inside it — paste it into Google
  Classroom or Teams and everyone who opens it gets their own copy.
- After the first visit it **works offline**, and Chrome can **install it as an app** (the install button in the
  address bar), so it appears in a Chromebook's launcher.
- On a touchpad, two-finger scroll moves around and pinch zooms; on a touch screen, drag the sheet with one finger.

<p align="center"><img src="docs/images/web.png" width="760" alt="Wirely running in a web browser"></p>

The browser version is a little slower than the desktop app, and it can't export SVG or PDF (it saves PNG pictures).

Want to run it from the source code, change it, or build the installers yourself? See
**[BUILDING.md](BUILDING.md)**, or the short version under [For developers](#for-developers) below.

## See it working

| A 555 and a 4017 make an LED chaser | Drag the light sensor's slider: the night light comes on |
|---|---|
| ![](docs/images/chaser.gif) | ![](docs/images/night_light.gif) |

| A motor takes a big current to start, then less | No resistor? The LED pops and says why |
|---|---|
| ![](docs/images/motor.gif) | ![](docs/images/pop.gif) |

![A 555 flasher with graph probes on the output and the timing capacitor](docs/images/graph.gif)

## How it works

### Drawing a circuit

![The parts gallery and editor](docs/images/editor.png)

| To… | Do this |
|---|---|
| Add a part | Click it in the gallery, then click on the sheet — or drag it across. Type in the search box to find one (`555`, `LED`, `relay`) |
| Wire up | Drag from one pin to another. Or click a pin, click to add corners, then click the end pin |
| Branch off a wire | Press **W** (wire tool), then press on the wire and drag — a junction dot appears |
| Change a value | Double-click the part and type, e.g. `10k`, `4k7`, `100n`, `4.7µ`, `2M2` |
| Choose a real part | Double-click a transistor, MOSFET, diode, LED or op-amp and pick its type |
| Rotate / flip | **R** / **Shift+R** / **F** |
| Move things | Drag parts (their wires follow), drag a wire sideways, or drag a wire's loose end |
| Zoom / pan | Mouse wheel / middle-drag (or hold Space and drag). **Ctrl+0** fits the whole circuit |
| Notes | Add a **Text note** (under *Labels*) to explain your circuit |
| Right-click | A menu for whatever is under the mouse |

Values understand engineering shorthand: `4k7` is 4.7 kΩ, `2M2` is 2.2 MΩ, `4R7` is 4.7 Ω, `100n` is 100 nF.

| Double-click a part to change it | Parts list (copy it, or save as CSV) |
|---|---|
| ![](docs/images/properties.png) | ![](docs/images/parts_list.png) |

### Running it

Press **Play** (F5). Wires turn the colour of their voltage (blue at 0 V up to red at the highest supply — the
scale is in the corner) and dots flow along them to show the current. While it runs:

- **click** switches, and **hold** push switches,
- **drag the sliders** that appear under potentiometers, variable resistors and sensors (or use the mouse wheel),
- **hover over any wire or part** to read its voltage, current (with direction) and power,
- press **Readings** to show them all at once, or **click** a wire or part to pin its reading on the sheet
  (drag a reading to move it out of the way),
- change the **speed** — from 10× faster down to 1/1000 speed, for slow motion.

**Stop** (Shift+F5) goes back to editing, and anything that popped is mended.

![Hover over a wire to read its voltage and current](docs/images/hover_reading.png)

### The graph

Put **graph probes** (A–D, under *Meters & probes*) on wires and press Play — the graph opens underneath, like
an oscilloscope. Each probe shows its voltage and frequency; set the time and volts per division, or leave them
on Auto. Hover over the graph to read values, and **Save picture…** to keep it. **Ctrl+G** shows or hides it.

| RC low-pass filter | Buck converter (12 V in, about 5.7 V out) |
|---|---|
| ![](docs/images/rc_filter.png) | ![](docs/images/buck_converter.png) |

### Sound

Buzzers buzz, loudspeakers play the **simulated** signal (a 555 at 690 Hz sounds at 690 Hz even when the
simulation has to run slower than real time), motors hum and relays click. Turn it off with the speaker button.

### Things that break

Like the real parts, things fail when you push them too far — and Wirely tells you why:

- an LED straight across a battery (too much current — add a resistor),
- a resistor carrying more than its power rating,
- an electrolytic capacitor connected the wrong way round,
- a transistor switching a relay coil without a flyback diode (the voltage spike kills it — a power MOSFET can
  absorb a small spike by breaking down briefly, as the real ones are rated to, but a small one can't),
- a MOSFET with more voltage across it than it's rated for, or a motor on far too much voltage,
- a fuse blowing, or a supply short-circuited.

### Logic and chips

Logic gates, the 4017 counter, 4511 decoder and 7-segment display, the 555 and op-amps all work while it runs.
**Logic probes** show high and low. Chips and op-amps with their supply pins left unconnected are powered from
the circuit's highest supply automatically, so quick sketches work.

| Logic gates with logic probes | Binary to 7-segment | Op-amp dark sensor |
|---|---|---|
| ![](docs/images/logic_gates.png) | ![](docs/images/seven_segment.png) | ![](docs/images/opamp.png) |

| Burglar alarm (reed switch) | Rain alarm (moisture sensor) |
|---|---|
| ![](docs/images/burglar_alarm.png) | ![](docs/images/rain_alarm.png) |

### Exporting

**File → Export diagram** saves PNG, SVG or PDF — always on white paper, ready for a report or a worksheet —
and **Copy diagram as picture** (Ctrl+Shift+C) puts it straight on the clipboard. **File → Bill of materials**
gives the parts list.

![An exported diagram](docs/images/export.png)

### Examples

**File → Open example** has 22 circuits to open and play with, from an LED and resistor, through 555 timers, logic,
op-amps, relays and motors, up to a buck converter.

**Dark mode** — the moon button at the top right. Press **F1** in the app for every mouse and keyboard shortcut.

## How accurate is it?

Wirely has its own circuit solver (`wirely/sim`), using the same core method as SPICE: nodal equations,
Newton–Raphson for diodes, LEDs, transistors and MOSFETs (with SPICE-style limiting), and integration over time
with automatic step-size control. Chips that switch (the 555, logic, square waves) tell the solver exactly when
they will switch, so it lands a time step on that moment — that keeps timing accurate.

**MOSFETs are fitted to their datasheets.** Each type's threshold voltage and on-resistance at the datasheet's
gate voltages are matched, and each has its body diode, internal gate resistance, and gate–source,
gate–drain (Miller) and drain–source capacitances that change with voltage as the real ones do. So switching
takes real time, and the gate shows the Miller plateau:

| | Wirely | Datasheet |
|---|---|---|
| AO3400 gate charge (to 4.5 V, 15 V, 5.7 A) | 6.1 nC | 6 nC |
| FQP27P06 gate charge (to −10 V, −48 V, −27 A) | 32.3 nC | 33 nC |
| On-resistance at each datasheet test point (12 types) | within 2 % (IRLZ44N: 11 %) | |
| Drain current at Vgs(th) (12 types) | within 3 % of the test current | |

**Op-amps are fitted to theirs too:** open-loop gain, gain-bandwidth, slew rate, input bias current, input
resistance, supply current, output swing that falls short further under heavier loads (a 741 on ±15 V: ±14 V
into 10 kΩ, ±13 V into 2 kΩ), the LM358 reaching 0 V but not the top rail, and current limits. The output
current really comes from the supply pins, and too much supply voltage destroys the chip.

The automatic tests (425 of them) check it against answers worked out by hand — voltage dividers, the diode
equation, LED current, transistor gain and saturation, Zener regulation, RC and RL curves, a half-wave
rectifier, 555 astable and monostable timing, op-amp gains, bandwidth, slew rate and bias currents, a
Schmitt-trigger oscillator, logic truth tables and counters — against the datasheets above, and against
**ngspice** running the same models. For example:

| | Wirely | ngspice |
|---|---|---|
| Buck converter output voltage | 5.750 V | 5.759 V |
| Buck converter output ripple | 0.391 V | 0.391 V |
| Buck converter inductor ripple current | 0.315 A | 0.315 A |
| IRF540 switching: turn-on / turn-off delay (100 Ω gate resistor) | 122 / 569 ns | 122 / 566 ns |

Filament lamps get hotter and their resistance rises with the voltage, so their current–voltage graph curves
over (current ∝ V^0.6, as real lamps measure) — and a cold lamp takes a surge of about 11× its running current
when switched on. Motors have back-EMF, relays have a coil with inductance that pulls in at 75 % and lets go at 30 % of its
rated current, and switching an inductive load without a flyback diode makes a real voltage spike.

## Honest limits

Wirely is for trying circuits out quickly and seeing how they behave. It isn't a replacement for a full SPICE
package or for testing the real thing:

- **No PCB or breadboard layout** — it's for the schematic and the simulation.
- **No SPICE model import or netlist export yet.** Parts use built-in models of common real parts (you choose
  from a list), fitted to typical datasheet values. There are no temperature effects, op-amp offset voltage
  or noise, and op-amps have a single pole (so no ringing with capacitive loads).
- **No AC (frequency-sweep), noise or Monte-Carlo analysis** — the graph is time-based, like an oscilloscope.
- **Logic is simple** — gates, the 4017, the 4511 and D flip-flops; no microcontrollers.
- Fast-switching circuits (like the buck converter at 1 kHz) run **slower than real time** — the time label
  says "slowed". The answers are still right; they just take longer to arrive.
- Sound depends on your computer's sound system; if it can't be opened, Wirely simply stays quiet.
- The browser version needs a recent browser, takes a few seconds to start the first time (it downloads about
  14 MB), and saves pictures as PNG only.

## For developers

```
python -m pip install PySide6 numpy pytest
python -m pytest tests              # model, solver and editor tests (no screen needed)
python -m wirely "examples/Night light.wirely"
```

Or double-click `run_wirely.bat` (Windows) / run `./run_wirely.sh` (Mac and Linux) — the first start sets up
its own Python environment. If Windows *Smart App Control* blocks the `.bat`, double-click **`start.py`**
instead.

The circuit model (`wirely/model`) and the solver (`wirely/sim`) are plain Python with no Qt, so they can be
tested on their own; the user interface is in `wirely/ui`. The README pictures are made by
`tools/readme_media.py`. Translations are plain JSON catalogues in `wirely/locale/` (the English text in the code
is the key); `python tools/i18n.py` lists anything missing, and to add a language you add a catalogue and one line
in `wirely/i18n.py`. The browser version lives in `web/`: `web/py/qtshim.py` stands in for the parts of Qt the
sheet and drawing code use (recording the drawing for the page to replay on a canvas), and
`python tools/build_web.py` builds the site (see BUILDING.md). See [BUILDING.md](BUILDING.md) for building the installers and how the automatic
GitHub builds work, and [CHANGES.md](CHANGES.md) for what's new.

## Licence

Wirely is free software: you can redistribute it and/or modify it under the terms of the
**GNU General Public License version 3** (or any later version) — see [LICENSE](LICENSE).
In short: use it for anything, including at work, share it, change it — and if you share a changed version,
share its source code under the GPL too.

Copyright © 2026 Richard Willmott.

It is built on open-source libraries — Qt / PySide6 (LGPL) and numpy (BSD); see
[THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt). All icons and symbols were drawn for Wirely. Wirely is an
independent project and isn't connected to any other circuit simulator or its makers.
