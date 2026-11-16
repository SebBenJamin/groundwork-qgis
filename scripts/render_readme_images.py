"""Render the README pictures from the Gülpe demo.

    python-qgis.bat scripts/render_readme_images.py [out_dir] [profile]

Opens a temporary copy of demo_guelpe/ offscreen (the committed demo is never written), starts
the plugin with a minimal QGIS window (map canvas above, section panel docked below) and
writes to ``out_dir`` (default docs/images):

- ``overview.jpg``: the window: map around the profile, its section below;
- ``section.png``: the section panel alone, zoomed to the first cores;
- ``plate.jpg``: the demo's report plate exported from its layout.

The live layers (aerial images, OpenStreetMap, state geology and boreholes) need the internet;
without it they are missing from the pictures.
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from qgis.core import QgsApplication, QgsProject, QgsRectangle  # noqa: E402
from qgis.PyQt.QtCore import QEventLoop, Qt, QTimer  # noqa: E402
from qgis.PyQt.QtGui import QFont  # noqa: E402

from render_demo_section import UI_FONT, FakeIface, wait_idle, zoom_to  # noqa: E402

PROFILE = "Transect 3"
WINDOW = (1500, 980)
SECTION_HEIGHT = 430
SECTION_ALONE = (1500, 520)
SECTION_ZOOM = (4.0, -2.0, 105.0, 28.6)    # exaggeration, from s, to s, top of the view
PLATE_DPI = 110
MAP_MARGIN = 0.25           # of the profile's extent, on each side
NETWORK_WAIT_S = 25.0
AERIAL = "Aerial images"
HIDE = "misfit"       # live tiles keep arriving after the first render


def spin(app, seconds: float) -> None:
    loop, deadline = QEventLoop(), time.perf_counter() + seconds
    timer = QTimer()
    timer.timeout.connect(lambda: time.perf_counter() > deadline and loop.quit())
    timer.start(50)
    loop.exec()
    timer.stop()
    app.processEvents()


def wait_canvas(app, canvas, seconds: float = NETWORK_WAIT_S) -> None:
    """Refresh until the map has drawn, then once more after the live tiles had time."""
    canvas.refreshAllLayers()
    spin(app, seconds)
    canvas.refresh()
    deadline = time.perf_counter() + 60
    spin(app, 1.0)
    while canvas.isDrawing() and time.perf_counter() < deadline:
        spin(app, 0.5)


def profile_extent(profile) -> QgsRectangle:
    xy = profile.xy
    x0, y0 = xy.min(axis=0)
    x1, y1 = xy.max(axis=0)
    pad = max(x1 - x0, y1 - y0) * MAP_MARGIN
    return QgsRectangle(x0 - pad, y0 - pad, x1 + pad, y1 + pad)


def save(widget_or_image, out: Path, quality: int = -1) -> Path:
    image = widget_or_image.grab() if hasattr(widget_or_image, "grab") else widget_or_image
    if not image.save(str(out), None, quality):
        raise RuntimeError(f"could not write {out}")
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
    return out


def render(demo: Path, out_dir: Path, profile_name: str) -> None:
    from qgis.core import QgsLayoutExporter
    from qgis.gui import QgsLayerTreeMapCanvasBridge

    from geophysics_workbench.plugin import WorkbenchPlugin

    app = QgsApplication.instance()
    iface = FakeIface()
    plugin = WorkbenchPlugin(iface)
    plugin.initGui()                         # item types first, or QGIS drops plate items
    project = QgsProject.instance()
    try:
        if not project.read(str(demo / "guelpe_project.qgz")):
            raise RuntimeError("could not read the Gülpe project")
        if plugin.store is None:
            raise RuntimeError("the demo project has no workbench store")
        root = project.layerTreeRoot()
        for layer in project.mapLayers().values():          # aerial images instead of OSM
            if layer.name().startswith(AERIAL):
                root.findLayer(layer.id()).setItemVisibilityChecked(True)
        window, canvas = iface.mainWindow(), iface.mapCanvas()
        bridge = QgsLayerTreeMapCanvasBridge(project.layerTreeRoot(), canvas)  # noqa: F841
        canvas.setDestinationCrs(project.crs())
        window.resize(*WINDOW)
        dock = plugin.dock
        plugin.show_section_panel()
        window.resizeDocks([dock], [SECTION_HEIGHT], Qt.Orientation.Vertical)
        by_name = {p.name: p for p in plugin.store.profiles()}
        if profile_name not in by_name:
            raise RuntimeError(f"no profile {profile_name!r}; have {sorted(by_name)}")
        profile = by_name[profile_name]
        dock.open_profile(profile.id)
        wait_idle(app, dock)
        canvas.setExtent(profile_extent(profile))
        wait_canvas(app, canvas)
        plugin.provider.notify_changed()     # the live strip layers have their features now
        wait_idle(app, dock)
        for row in dock.layer_list._rows.values():     # the model alone, without the misfit
            if HIDE in row.check.full_text().lower():
                row.check.setChecked(False)
        wait_idle(app, dock)
        errors = dock.errors.text()
        if errors:
            print(f"note: section layer errors: {errors}")
        save(window, out_dir / "overview.jpg", 88)

        dock.setFloating(True)
        dock.resize(*SECTION_ALONE)
        app.processEvents()
        wait_idle(app, dock)
        dock.ve_spin.setValue(SECTION_ZOOM[0])
        wait_idle(app, dock)
        zoom_to(dock, *SECTION_ZOOM)
        wait_idle(app, dock)
        save(dock, out_dir / "section.png")

        layouts = project.layoutManager().printLayouts()
        if not layouts:
            raise RuntimeError("the demo project has no plate layout")
        exporter = QgsLayoutExporter(layouts[0])
        settings = QgsLayoutExporter.ImageExportSettings()
        settings.dpi = PLATE_DPI
        out = out_dir / "plate.png"
        result = exporter.exportToImage(str(out), settings)
        if result != QgsLayoutExporter.ExportResult.Success:
            raise RuntimeError(f"plate export failed: {exporter.errorMessage()}")
        from qgis.PyQt.QtGui import QImage
        save(QImage(str(out)), out_dir / "plate.jpg", 88)
        out.unlink()
    finally:
        # no plugin.unload() / project.clear(): with live web requests still open they can
        # hang; the process ends with os._exit right after this
        project.setDirty(False)


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "docs" / "images"
    profile = sys.argv[2] if len(sys.argv) > 2 else PROFILE
    out_dir.mkdir(parents=True, exist_ok=True)
    app = QgsApplication([], True)
    app.initQgis()
    app.setFont(QFont(UI_FONT, 9))
    app.messageLog().messageReceived.connect(
        lambda msg, tag, level: print(f"log [{tag}] {msg}") if "Workbench" in tag or
        "WFS" in tag else None)
    tmp = Path(tempfile.mkdtemp(prefix="wb_readme_"))
    try:
        demo = tmp / "demo_guelpe"
        shutil.copytree(REPO / "demo_guelpe", demo,
                        ignore=shutil.ignore_patterns("*.gpkg-wal", "*.gpkg-shm"))
        render(demo, out_dir, profile)
        return 0
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)
