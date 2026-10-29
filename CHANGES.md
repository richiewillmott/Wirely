# Changes

## 1.5.4 — Wirely in Spanish, German and Japanese
- **New Language menu** (between View and Help) in the desktop app and on the website: choose English, Español,
  Deutsch or 日本語. The whole program changes straight away, with no restart, and your choice is remembered
  (on the website you can also use `?lang=ja`, `?lang=de` or `?lang=es` in the address).
- **Everything is translated:** menus, toolbar tips, the parts gallery (names, categories and descriptions),
  the properties dialogs, readings and hover text, the graph, the shortcut list, the About box, status messages,
  the messages that explain why a part has failed, the 35 example circuits (names and their notes), and the
  website's start-up and error messages. Qt's own buttons and dialogs (Open, Save, Cancel …) follow too.
- **Saved circuits don't depend on the language.** Parts, settings and choices (such as an LED's colour) are saved
  the same way whatever language you were using, so a circuit made in German opens fine in Japanese or English.
- A part's choices, such as the LED colour, are now also translated where they are shown beside the part.
- Behind the scenes: the English text in the code is the key to a catalogue file per language
  (`wirely/locale/es.json`, `de.json`, `ja.json`); anything without a translation simply shows in English.
  `python tools/i18n.py` lists anything missing or broken in a catalogue, and a new test fails if one is incomplete.
  The website and the installers include the catalogues.
- Failure messages now decide "broken" from the part's real state rather than from English words, so they colour
  correctly in every language.
- The translations are new; if you spot a wrong or awkward phrase, please open an issue.

## 1.5.3 — Readings that make sense for capacitors, inductors and transistors
- **Capacitors no longer show power.** A capacitor charging or discharging takes in or gives back energy but
  doesn't turn any of it into heat, so the "mW" reading beside it (voltage × current) was misleading. An ideal
  capacitor now shows only its voltage and current.
- **Inductors show only what they really dissipate** (the small loss in the coil), not the energy going into and
  out of their magnetic field.
- **MOSFETs show their drain current.** The reading used to be the gate's voltage and current, which is always
  about 0 A, so a MOSFET switching a motor appeared to pass nothing. It now shows the voltage across the MOSFET
  (drain to source) and the current through it (the drain current).
- **NPN and PNP transistors** likewise show the voltage from collector to emitter and the collector current,
  instead of the base's.
- New test covering all of the above.

## 1.5.2 — US symbols, PWM looks steady even when the simulation can't keep up, and fast switching runs faster
- **New address: https://wirely-app.github.io/** (code: github.com/wirely-app/wirely-app.github.io). The old
  address forwards there, keeping shared links working and bringing along unsaved work the browser kept.
- **US symbols:** View → US symbols draws parts the American way: zigzag resistors (and variable resistors,
  potentiometers, thermistors and LDRs), an S-shaped fuse, a curved − plate on electrolytic capacitors and a
  filament in bulbs. Only the look changes; it's remembered next time.
- The resistor's description no longer mentions a "realistic view" that doesn't exist.
- **The website switches to a new version straight away** (or asks if there's unsaved work) instead of only on the
  next visit.
- **LEDs on PWM no longer blink when a busy circuit runs slower than real time:** the eye's averaging now covers
  the right stretch of simulated time for the speed you've chosen, not for how fast the computer keeps up. At a
  slow-motion speed you still see them flick on and off.
- **Faster simulation of fast switching** (555s, PWM, the buck converter): after a sudden change the simulator gets
  back up to speed sooner, and takes bigger steps when little is changing. The *PWM dimmer* runs about 40% faster
  and the *555 doorbell* nearly twice as fast, with the same accuracy (555 frequencies unchanged).

## 1.5.1 — PWM dims LEDs and bulbs
- **LEDs, bulbs and displays look as bright as your eye would see them:** their light is averaged over each
  moment on screen, so PWM (switching fully on and off faster than you can see) makes them look steadily dimmer,
  as in real life, instead of flickering at random. Slow the simulation down and you can watch them flick on and off.
  This works for RGB LEDs (PWM one colour to change the mix) and multiplexed 7-segment displays too.
- New example: *PWM dimmer (555)* — turn the knob to dim an LED and a bulb.
- The website shows its version number next to the logo.
- **Much less CPU while running:** the dotted grid is kept ready-drawn instead of being drawn dot by dot every
  frame, parts and wires are only redrawn when they change, a frame where nothing looks any different isn't drawn
  at all, and the current-flow dots and graph do less work. E.g. the Night light went from about 60% of a CPU core
  to under 10% on the desktop. It looks exactly the same. The browser version gains too.

## 1.5.0 — new parts, a unit box for values, movable readings and many fixes
- **A unit box next to values:** in a part's properties, resistance has Ω / kΩ / MΩ beside the number, capacitance
  pF / nF / µF / mF / F, inductance µH / mH / H and frequency Hz / kHz / MHz. Typing the whole value (4k7, 100n)
  still works — it's tidied into the number and its size.
- **Crystal clock:** an exact square-wave clock for logic (set its frequency).
- **Stepper motor** (48 or 200 steps a turn): its shaft turns one step each time the coils change — drive it with an
  L293D. You can see the shaft turn.
- **Rotary switch** (1 pole, 4 ways: click to turn it) and a **12-key keypad** (rows × columns, like a door-lock
  keypad: hold down a key).
- **JK flip-flop** (4027) and **Schmitt NAND gate** (4093).
- New examples: *Stepper motor (crystal clock + L293D)*, *Keypad (which key is pressed)*, *Binary counter (JK flip-flops)*,
  *Schmitt NAND flasher (4093)* and *Rotary switch (pick an LED)*.
- **Logic at switch-on:** an input that's simply high from the start no longer counts as a clock edge, so counters
  and flip-flops start from 0.
- **Drag a reading** (pinned, or with Readings on) to move it out of the way; a dashed line shows what it belongs to.

Bugs found by checking every example step by step and testing every part in thousands of random circuits:
- **Wire currents next to 0 V symbols** (hover, Readings, flow dots) could be wrong — e.g. 7.3 mA instead of
  14.8 mA in the Night light, or in the shift register example. Part readings and voltages were always right.
- **Readings at the moment something switches:** regulators, 555s, logic chips, relays and motors showed the
  current for the state they were switching *to* for one step (a 7805 flashed 137 A at switch-on). The 555 also
  left out the current into its CTRL pin.
- **Chips and displays show their power** in Readings (they showed 0 W).
- **Mis-wired parts no longer freeze the simulation:** a voltage regulator with its input and output swapped (or
  wired any other wrong way), a TL431 upside down or with REF on the supply, an op-amp whose output is held
  outside its supply, and a burnt-out thyristor.
- **Voltage regulators** leak back from OUT to IN when wired the wrong way round, like real ones.
- **Op-amps** are destroyed by a reversed supply, or by their output being forced well outside their supply.
- **Thyristors** now switch relay coils (and other coils) on: they used to let go while the coil's current was
  still building up, even with the gate driven.
- **Thyristors:** too much gate current (gate wired straight to the supply) burns them out, with a message saying
  to add a gate resistor.
- **Labels:** part names no longer sit on top of pins when chips and regulators are turned round, the bridge
  rectifier's label sits clear of its pins, the RGB LED's name no longer has its light arrows through it, and the
  pin names of a chip turned on its side run along their pins instead of overlapping.

## 1.4.1 — RGB LED fix, brighter LEDs
- **RGB LEDs:** green is now the same kind of chip as blue (about 3.1 V, like real RGB LEDs), so green and blue
  on one resistor share the current and mix. (Red, at about 2 V, still takes nearly all the current if it shares
  a resistor with them — as in a real one; give each colour its own resistor to mix any colours.)
- **LEDs look brighter when they're on:** a stronger colour and a bigger, brighter glow.

## 1.4.0 — Readings, and 16 new parts
- **Readings:** a new toolbar button shows the voltage and current on every wire, and the voltage, current and
  power of every part, while the circuit runs. Click any wire or part while it runs to pin just its reading.
  **Simulate → Copy readings** copies every part's readings as a table to paste into a spreadsheet.
- **Bi-colour LEDs** (2-leg and 3-leg) and an **RGB LED** that mixes its colours.
- **Bridge rectifier**, and a **transformer** (set its turns ratio; warns if you give it DC).
- **Thyristor (SCR):** C106D, 2N5060, TIC106D and BT151 — latches on from a gate pulse and stays on until the
  current drops below its holding current.
- **Voltage regulators:** 7805, 7809, 7812, LM1117-3.3 and the adjustable LM317, with dropout, current limit and
  thermal shutdown (fit a heatsink in its properties).
- **Comparators:** LM393 and LM311 (open-collector outputs).
- **L293D motor driver:** four half-H drivers with built-in spike diodes — drive a motor both ways from logic
  pins, or set its speed with PWM on the enable pin. It shuts down if it gets too hot.
- **4026** decade counter with 7-segment outputs, and the **4060** counter with its own oscillator.
- **DPDT switch**, **DPDT relay** (two changeover contacts), **Hall effect sensor** (click to bring the
  magnet near) and a **solenoid** that clicks.
- New examples: *Thyristor alarm (latching)*, *5 V power supply (7805)*, *RGB colour mixer*,
  *Counter (555 + 4026)*, *Reversing a motor (DPDT)*, *Motor driver (L293D)* and *Relay reversing a motor
  (DPDT)*.
- Voltage regulators now have a proper dropout (about 1.2 V at light load, 2 V at 1 A for a 78xx), and no
  longer get stuck when a battery sags under load.
- The website counts visits with GoatCounter (no cookies, no personal data).

## 1.3.0 — parts requested by users, and Wirely in your web browser
- **Wirely Web:** the whole app runs in a web browser, so it works on **Chromebooks** and school computers with
  nothing to install — at https://wirely-app.github.io/. It's the desktop app's own Python code
  (the sheet, the symbols and the simulator) running in the browser with Pyodide, so it looks and behaves the same.
- In the browser: open and save `.wirely` files (they work in both versions), all the examples, the graph,
  sound, PNG pictures, the parts list, **links that carry a circuit** (for Google Classroom / Teams), works
  **offline** after the first visit, installs as an app, and touch-screen and touchpad gestures.
- On the graph, a curved trace no longer hides the grid lines and the other traces under it.
- **Shift registers:** 74HC164 (serial in, parallel out), 74HC595 (with output latch and output enable),
  74HC165 (parallel in, serial out) and 74HC597 (with input latch). They warn if run above their 6 V limit.
- **4051 analogue switch** (CD4051B and 74HC4051), with each type's datasheet on-resistance at its supply voltage.
- **TL431 / TLV431 adjustable shunt references:** Vout = Vref × (1 + R1/R2), with their current and voltage limits.
- **Solid-state relay (TLP3122A):** photo-MOSFET output that switches AC or DC, turning on over about a millisecond.
- **2N7002** MOSFET.
- **Every part type is explained:** choose a type in a part's properties and a line underneath says what it's for.
- New examples: *TL431 adjustable reference* and *Shift register (74HC595)*.
- Chip labels sit above the chip instead of over its pins.

## 1.2.0 — real filament lamps
- **Filament lamps behave like real ones:** the filament's resistance rises as it heats up, so the current–voltage
  graph curves (I ∝ V^0.6, as measured on real lamps — the GCSE/A-level required practical), a cold lamp takes a
  surge of about 11× its running current at switch-on, and it takes a moment to brighten and to fade.
- **Resistors heat up over about a second** before burning out, so a brief surge (like a lamp's switch-on) is fine
  but a lasting overload still burns them out.

## 1.1.0 — more accurate MOSFETs and op-amps
- **MOSFETs fitted to their datasheets:** threshold voltage and on-resistance at the datasheet's gate voltages,
  mobility falling at high gate voltage, the body diode, internal gate resistance, and voltage-dependent gate and
  drain capacitances. Switching now takes real time and shows the Miller plateau; gate charge matches the
  datasheets (AO3400 6.1 nC vs 6 nC, FQP27P06 32.3 nC vs 33 nC) and switching delays match ngspice.
- **Op-amps fitted to their datasheets:** open-loop gain, input bias current and resistance, supply current,
  output swing that depends on the load, separate source/sink limits, and the LM358 swinging to 0 V but not to
  its top rail. Output current is drawn through the supply pins, and too much supply voltage destroys the chip.
- Diodes ride out short current surges (as real ones do) instead of popping on a nanosecond spike.
- **MOSFETs break down above their voltage rating** (avalanche, at about 15 % over): a short spike is absorbed up to
  the part's avalanche energy rating (power MOSFETs survive a relay coil's spike; a 2N7000 doesn't), but a supply
  above the rating destroys it, with a message saying why.
- **Motors burn out** on far more than their rated voltage (a 9 V motor on 150 V spins much too fast and overheats).
- The simulator is about twice as fast on every circuit (and much faster with MOSFETs).
- The installer clears out the old version's library files when updating.
- Linux: prefers X11/XWayland and falls back to Wayland; the automatic build now tests both.

## 1.0.0 — first official release
Everything below, together: the circuit editor (r1), live simulation (r2), chips, logic and the graph (r3),
sound, relays, motors and sensors (r4), and the Wirely name, icons and downloads (r5).

- New part: **optoisolator** (optocoupler) — PC817, 4N25, 4N35, TLP521 and 6N139 (Darlington), with an
  example circuit. Its two sides are truly separate circuits, each with its own supply.
- Fixed: a circuit joined to another only through a relay's contacts or an optoisolator now gets its own 0 V
  reference, so its own supply can be anything (before, a separate DC power supply there could fail to solve).
- The graph's Auto time setting now follows the fastest repeating signal on any probe (before, it only
  looked at probe A — so a buck converter, where A is smooth DC, showed a 5-second sweep of a 1 kHz signal).

## r5 — Wirely (became 1.0.0)
- **New name: Wirely** (was Sparkbench). Circuits are now `.wirely` files; old `.spark` files still open.
- **New logo** (a W drawn as a wire, with current flowing along it) and a **file icon** for `.wirely` circuits.
- **Splash screen** with the version and revision while Wirely starts.
- **Downloads built automatically on GitHub**: Windows installer (with `.wirely` file association), Mac `.dmg`
  (with document icon) and Linux AppImage (plus a script to add it to the app menu and associate `.wirely`).
  Every push runs the tests.
- Double-clicking a `.wirely` file in Finder opens it on the Mac; Wirely's own icon on the Windows taskbar.
- **Signal generator duty cycle** (PWM) for square waves.
- New example: **buck converter** (12 V → about 6 V). Its output voltage, ripple and inductor current are
  tested against the textbook formulas and against ngspice (within 0.5 %).

## r4 — sound, relays, motors and sensors
- **Sound:** buzzers buzz, loudspeakers play the simulated signal at its real pitch, motors hum, relays click.
  Sound button to switch it off. Wirely checks the computer's sound safely first, so a broken sound setup
  can never crash it.
- **Relay** (coil + changeover contacts, pull-in 75 %, drop-out 30 %) and **inductor**. Switching a coil with
  no flyback diode makes a real voltage spike that destroys the transistor — with a message explaining the fix.
- **Motors** now have back-EMF: big starting current, then less; a *Load* setting slows them and makes them
  take more current; hover to see their speed in rpm.
- New sensors: **reed switch** (click to bring the magnet near), **tilt switch**, **moisture sensor** (slider),
  **phototransistor** (light slider).
- Many more types: MOSFETs BS170, IRLZ44N (logic level), IRF530, IRF3205, AO3400, IRF9530, FQP27P06,
  IRLML6402; transistors BC547, BC337, 2N2222, TIP120, BC557, BC327, 2N2907, TIP125; diodes 1N4007, 1N5408,
  1N5819 (Schottky); op-amp TL071.
- **Hover readings:** while running, hover over a wire for its voltage and current (with direction).
- **Text notes** for worksheets, **right-click menus**, **autosave** every minute with recovery after a crash.
- Fixed: a MOSFET with an unconnected gate turned itself on; LED glow now centred on the LED.
- Five new examples: relay switching a lamp, motor and load, 555 doorbell, burglar alarm, rain alarm.

## r3 — chips, logic and the graph
- **Graph (oscilloscope):** put graph probes A–D on wires and press Play. Automatic or fixed time and volts
  per square, live readings with frequency, hover to read values, save the graph as a picture.
- **Logic probe:** shows H / L / ? on whatever it touches.
- New parts: **555 timer**, **op-amp** (741, LM358, rail-to-rail), **NOT / AND / OR / NAND / NOR / XOR /
  Schmitt NOT gates**, **D-type flip-flop**, **4017 decade counter**, **4511 decoder**, **7-segment display**,
  **N- and P-channel MOSFETs** (2N7000, IRF540, BS250, IRF9540), **signal generator** (square / sine / triangle).
- The solver lands exactly on switching moments, so 555 timing matches the textbook formulas (within 1 %).
- Logic chips and op-amps with unconnected supply pins are powered from the circuit's supply automatically.
- Seven new examples: 555 LED flasher, LED chaser (555 + 4017), op-amp dark sensor, logic gates, MOSFET motor
  switch, RC filter on the graph, binary to 7-segment.
- Sliders find a clear spot next to their part.

## r2 — live simulation
- **Play / Pause / Stop** (F5 / F6 / Shift+F5) and a speed control (10× faster down to 1/1000 speed).
- Wirely's own circuit solver: Newton–Raphson for diodes, LEDs and transistors; capacitors over time with
  automatic step control. Checked against hand-worked answers and ngspice in the tests.
- LEDs glow in their colour, lamps light up, motors spin, buzzers show sound waves, meters show a reading.
- Wires coloured by voltage (with a colour key) and animated current flow — both can be switched off.
- Click switches and changeover switches, hold push switches, drag sliders for LDRs (light level),
  thermistors (temperature) and variable resistors while it runs. Double-click a part to change its value
  live.
- Parts that are overloaded show it: LEDs, diodes, transistors and electrolytics pop, lamps and fuses blow,
  resistors burn out — with a message saying what happened and how to fix it. Short-circuited batteries are
  pointed out. Stop mends everything.
- Hover over a wire or part while running to read voltage, current and power.
- Two new examples: *Capacitor charging* and *Buzzer and motor*.
- Fixed: "Diodes & LEDs" lost its "&" on Windows; greyed-out buttons now look greyed out.

## r1 — circuit editor (first release)
- Parts gallery with 29 parts in 9 groups, UK/IEC-style symbols, search box.
- Place parts by clicking or dragging; rotate (R / Shift+R), flip (F), move, delete.
- Wires: drag from pin to pin, or click corners; wires stay square, pick the corner that doesn't run
  through a part, follow parts when you move or rotate them; branch off a wire (W) with a junction dot;
  drag a wire sideways or move its loose end.
- Double-click a part to change its values — type them the usual way (10k, 4k7, 100n, 4.7µ).
- Undo / redo for everything, copy / cut / paste / duplicate.
- Save and open circuits (.wirely files), recent files, four example circuits.
- Export the diagram as PNG, SVG or PDF (always black on white), copy it as a picture, bill of materials.
- Light and dark themes, dot grid, smooth zoom-to-fit.
