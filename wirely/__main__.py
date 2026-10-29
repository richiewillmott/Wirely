"""Run with:  python -m wirely [circuit.wirely]

Extra options (used for testing):
    --snapshot out.png   open, take a picture of the window, and quit
    --theme dark|light   start in this theme
    --self-test out.txt  check everything loads, write OK / FAILED, and quit
"""
import os
import sys


def _deps_ok():
    import importlib.util
    return all(importlib.util.find_spec(m) is not None for m in ("PySide6", "numpy"))


def _self_test(out_path):
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from PySide6 import QtSvg  # noqa: F401
        app = QApplication.instance() or QApplication([])
        from wirely.model.circuit import Circuit
        from wirely.ui.scene import CircuitScene
        from wirely.ui import export as EX
        c = Circuit()
        c.add("battery")
        c.add("resistor", 100, 0)
        img = EX.render_image(CircuitScene(c), 1.0)
        from wirely.sim.engine import Simulator
        d = Circuit()
        b = d.add("dc_supply", 0, 0, props={"voltage": 10})
        r = d.add("resistor", 0, 100, props={"resistance": 1000})
        d.add_wire([b.pin_positions()["+"], (-30, 100)])
        d.add_wire([b.pin_positions()["-"], (30, 100)])
        s = Simulator(d)
        s.run_until(0.01)
        ok_sim = abs(abs(s.device(r.id).i_pins[0]) - 0.01) < 1e-4
        msg = "OK" if img.width() > 10 and len(c.nets()) >= 2 and ok_sim else "FAILED: wrong result"
        del app
    except Exception as e:  # noqa: BLE001
        import traceback
        msg = "FAILED: " + "".join(traceback.format_exception(e))
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(msg)
    return 0 if msg == "OK" else 1


class _FileOpener:
    """Opens circuits that macOS hands over when you double-click a .wirely file in Finder."""

    def __init__(self, app):
        from PySide6.QtCore import QEvent, QObject
        outer = self
        self.pending, self.window = [], None

        class _Filter(QObject):
            def eventFilter(self, obj, ev):
                if ev.type() == QEvent.FileOpen and ev.file():
                    if outer.window is not None:
                        outer.window._open_checked(ev.file())
                    else:
                        outer.pending.append(ev.file())
                    return True
                return False
        self._filter = _Filter(app)
        app.installEventFilter(self._filter)

    def attach(self, window):
        self.window = window
        for p in self.pending:
            window.open_file(p)
        self.pending = []


def main():
    args = sys.argv[1:]
    if "--audio-probe" in args:          # used by the sound check in built apps (see ui/sound.py)
        from wirely.ui.sound import PROBE_CODE
        exec(compile(PROBE_CODE, "audio-probe", "exec"), {})
        return
    if "--self-test" in args:
        i = args.index("--self-test")
        sys.exit(_self_test(args[i + 1] if i + 1 < len(args) else "selftest.txt"))
    if not _deps_ok() and os.environ.get("WIRELY_BOOTSTRAPPED") != "1":
        from wirely.bootstrap import launch
        launch(args)
        return
    snapshot = theme = None
    files = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--snapshot" and i + 1 < len(args):
            snapshot = args[i + 1]
            i += 2
            continue
        if a == "--theme" and i + 1 < len(args):
            theme = args[i + 1]
            i += 2
            continue
        if not a.startswith("--"):
            files.append(a)
        i += 1

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    if sys.platform == "win32":     # show Wirely's own icon on the taskbar (not Python's)
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Wirely.Wirely")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(sys.argv[:1])
    opener = _FileOpener(app)
    app.setApplicationName("Wirely")
    app.setOrganizationName("Wirely")
    from wirely.ui import lang
    lang.apply(lang.saved())            # the language chosen last time, before anything is shown
    splash = None if snapshot else __import__("wirely.ui.splash", fromlist=["show_splash"]).show_splash()

    from wirely.i18n import tr

    def step(text, frac):
        if splash is not None:
            splash.step(tr(text), frac)
    step("Loading the parts library…", 0.2)
    from wirely.model import parts  # noqa: F401
    step("Loading the circuit solver…", 0.4)
    from wirely.sim import engine  # noqa: F401
    step("Building the window…", 0.65)
    from wirely.ui.mainwindow import MainWindow
    from wirely.ui import icons
    app.setWindowIcon(icons.app_icon())
    if theme:
        from PySide6.QtCore import QSettings
        QSettings("Wirely", "Wirely").setValue("theme", theme)
    w = MainWindow()
    if theme:
        w.set_theme(theme)
    step("Opening…", 0.9)
    w.show()
    if splash is not None:
        splash.finish(w)
    opener.attach(w)
    if files:
        w.open_file(os.path.abspath(files[0]))
    elif not snapshot:
        QTimer.singleShot(300, w.offer_recovery)
    if snapshot:
        def snap():
            w.grab().save(snapshot)
            print(f"[Wirely] snapshot saved: {snapshot} (display: {app.platformName()})", flush=True)
            w.undo.setClean()
            app.quit()
        QTimer.singleShot(1500, snap)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
