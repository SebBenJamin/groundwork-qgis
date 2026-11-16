"""Render the demo sections for the release screenshot check.

Opens demo/demo_project.qgz offscreen, starts the plugin with a minimal fake QGIS
interface, opens each profile in the section panel and saves the panel as a PNG:

    python-qgis.bat scripts/render_demo_section.py [version] [out_dir]

writes <out_dir>/<version>-P1.png, -P2.png, -ties.png and -dialog.png (the open Context
layers dialog) (version defaults to
metadata.txt, out_dir to docs/releases). P1 is the R2 elevation model, P2 the Zond depth
model (checks depth conversion against the topography). P2 is zoomed to its upper part
from the powerline crossing on, at a higher vertical exaggeration, with Topography on DEM:
the surface follows the 2 m road embankment near s = 250, while the stations stay at
their measured heights (red) on a thin line of their own. The ties panel is shown with
the P1 x P3 row selected. The demo is copied to a temporary folder first, so switching
the topography never writes to the committed demo/demo_groundwork.gpkg.
"""
import os
import shutil
import sys
import tempfile
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

#: profile name -> (vertical exaggeration, zoom, topography); zoom (s0, s1, z_top) or
#: None = whole section
PROFILES = {"P1": (2.0, None, "stations"), "P2": (4.0, (125.0, 360.0, 77.0), "dem")}
SIZE = (1400, 560)
TIES_SIZE = (900, 720)
TIES_ROW = "P1 × P3"
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


def zoom_to(dock, ve: float, s0: float, s1: float, z_top: float) -> None:
    """Show chainage s0 .. s1 at exaggeration ``ve``, the top of the view at ``z_top``,
    as a user zoom (the dock stops re-fitting the whole section)."""
    dock.fit.user_navigated()
    area = dock.canvas.plotArea()
    epp = (s1 - s0) / area.width() / ve              # elevation per pixel
    dock.canvas.setVisiblePlotRange(s0, s1, z_top - epp * area.height(), z_top)


def version() -> str:
    cp = ConfigParser()
    cp.read(REPO / "groundwork_geophysics" / "metadata.txt", encoding="utf-8")
    return cp["general"]["version"]


def render(out_dir: Path, ver: str, demo: Path) -> list[Path]:
    from groundwork_geophysics.plugin import WorkbenchPlugin

    project = QgsProject.instance()
    if not project.read(str(demo / "demo_project.qgz")):
        raise RuntimeError(f"could not read {demo / 'demo_project.qgz'}")
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
        for name, (ve, zoom, topography) in PROFILES.items():
            dock.ve_spin.setValue(ve)
            plugin.provider.set_topography_source(by_name[name], topography)
            dock.open_profile(by_name[name])
            wait_idle(app, dock)
            if zoom is not None:
                zoom_to(dock, ve, *zoom)
                wait_idle(app, dock)
            errors = dock.errors.text()
            if errors:
                raise RuntimeError(f"{name}: layer errors: {errors}")
            out = out_dir / f"{ver}-{name}.png"
            if not dock.grab().save(str(out)):
                raise RuntimeError(f"could not write {out}")
            written.append(out)
            print(f"wrote {out}")
        written.append(render_ties(plugin, app, out_dir / f"{ver}-ties.png"))
        written.append(render_dialog(plugin, app, out_dir / f"{ver}-dialog.png"))
    finally:
        plugin.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        project.clear()
        iface.mainWindow().close()
    return written


def render_ties(plugin, app, out: Path) -> Path:
    """The Profile ties panel, floating, with the ``TIES_ROW`` row selected."""
    plugin.show_ties_panel()
    panel = plugin.ties_panel
    panel.setFloating(True)
    panel.resize(*TIES_SIZE)
    table = panel.table
    rows = [r for r in range(table.rowCount()) if table.item(r, 0).text() == TIES_ROW]
    if not rows:
        raise RuntimeError(f"the ties panel has no {TIES_ROW} row")
    table.selectRow(rows[0])
    for _ in range(5):                               # let the plot and layout settle
        app.processEvents()
        time.sleep(0.05)
    panel.plot.draw()
    app.processEvents()
    if not panel.grab().save(str(out)):
        raise RuntimeError(f"could not write {out}")
    print(f"wrote {out}")
    return out


def render_dialog(plugin, app, out: Path) -> Path:
    """The non-modal Context layers dialog, left open as a user would, grabbed to a PNG."""
    plugin.edit_context()
    dialog = plugin._context_dialog
    if dialog is None:
        raise RuntimeError("the Context layers dialog did not open")
    for _ in range(5):
        app.processEvents()
        time.sleep(0.05)
    if not dialog.grab().save(str(out)):
        raise RuntimeError(f"could not write {out}")
    print(f"wrote {out}")
    return out


def main() -> int:
    ver = sys.argv[1] if len(sys.argv) > 1 else version()
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else REPO / "docs" / "releases"
    out_dir.mkdir(parents=True, exist_ok=True)
    app = QgsApplication([], True)
    app.initQgis()
    app.setFont(QFont(UI_FONT, 9))   # offscreen Qt otherwise picks an odd fallback font
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            demo = Path(tmp) / "demo"
            shutil.copytree(REPO / "demo", demo)
            render(out_dir, ver, demo)
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)    # QGIS/Qt teardown at interpreter exit can crash; keep the exit code
