"""Render the demo sections for the release screenshot check.

Opens demo/demo_project.qgz offscreen, starts the plugin with a minimal fake QGIS
interface, opens each profile in the section panel and saves the panel as a PNG:

    python-qgis.bat scripts/render_demo_section.py [version]

writes docs/releases/<version>-P1.png and -P2.png (version defaults to metadata.txt).
P1 is the R2 elevation model, P2 the Zond depth model (checks depth conversion against
the topography).
"""
import os
import sys
import time
from configparser import ConfigParser
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from qgis.core import QgsApplication, QgsProject  # noqa: E402
from qgis.PyQt.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer  # noqa: E402
from qgis.PyQt.QtGui import QFont  # noqa: E402

PROFILES = ("P1", "P2")
SIZE = (1400, 560)
UI_FONT = "Segoe UI"            # what QGIS uses on Windows


class FakeIface:
    """Just enough of QgisInterface for WorkbenchPlugin."""

    def __init__(self):
        from qgis.gui import QgsMapCanvas, QgsMessageBar
        from qgis.PyQt.QtWidgets import QMainWindow

        self._window = QMainWindow()
        self._window.resize(1400, 900)
        self._canvas = QgsMapCanvas(self._window)
        self._window.setCentralWidget(self._canvas)
        self._bar = QgsMessageBar(self._window)
        self._active_layer = None
        self._window.show()

    def mainWindow(self):
        return self._window

    def mapCanvas(self):
        return self._canvas

    def messageBar(self):
        return self._bar

    def activeLayer(self):
        return self._active_layer

    def setActiveLayer(self, layer):
        self._active_layer = layer

    def addDockWidget(self, area, dock):
        self._window.addDockWidget(area, dock)

    def removeDockWidget(self, dock):
        self._window.removeDockWidget(dock)


def wait_idle(app, dock, timeout_s=60.0, quiet_s=0.5):
    """Spin the event loop until the section canvas has had no job for ``quiet_s``."""
    state = {"since": None}
    loop, timer = QEventLoop(), QTimer()
    deadline = time.perf_counter() + timeout_s

    def check():
        now = time.perf_counter()
        state["since"] = None if dock.is_busy() else (state["since"] or now)
        if (state["since"] and now - state["since"] > quiet_s) or now > deadline:
            loop.quit()

    timer.timeout.connect(check)
    timer.start(10)
    loop.exec()
    timer.stop()
    app.processEvents()
    if time.perf_counter() > deadline:
        raise RuntimeError("section generation did not finish")


def version() -> str:
    cp = ConfigParser()
    cp.read(REPO / "geophysics_workbench" / "metadata.txt", encoding="utf-8")
    return cp["general"]["version"]


def render(out_dir: Path, ver: str) -> list[Path]:
    from geophysics_workbench.plugin import WorkbenchPlugin

    project = QgsProject.instance()
    if not project.read(str(REPO / "demo" / "demo_project.qgz")):
        raise RuntimeError("could not read demo/demo_project.qgz")
    iface = FakeIface()
    plugin = WorkbenchPlugin(iface)
    plugin.initGui()                                 # attaches the demo's workbench store
    if plugin.store is None:
        raise RuntimeError("the demo project has no workbench store")
    written = []
    try:
        dock = plugin.dock
        plugin.show_section_panel()
        dock.setFloating(True)
        dock.resize(*SIZE)
        app = QgsApplication.instance()
        app.processEvents()
        by_name = {p.name: p.id for p in plugin.store.profiles()}
        for name in PROFILES:
            dock.open_profile(by_name[name])
            wait_idle(app, dock)
            errors = dock.errors.text()
            if errors:
                raise RuntimeError(f"{name}: layer errors: {errors}")
            out = out_dir / f"{ver}-{name}.png"
            if not dock.grab().save(str(out)):
                raise RuntimeError(f"could not write {out}")
            written.append(out)
            print(f"wrote {out.relative_to(REPO)}")
    finally:
        plugin.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        project.clear()
        iface.mainWindow().close()
    return written


def main() -> int:
    ver = sys.argv[1] if len(sys.argv) > 1 else version()
    out_dir = REPO / "docs" / "releases"
    out_dir.mkdir(parents=True, exist_ok=True)
    app = QgsApplication([], True)
    app.initQgis()
    app.setFont(QFont(UI_FONT, 9))   # offscreen Qt otherwise picks an odd fallback font
    try:
        render(out_dir, ver)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)    # QGIS/Qt teardown at interpreter exit can crash; keep the exit code
