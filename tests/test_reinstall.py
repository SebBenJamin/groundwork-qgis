"""Installing a new zip while QGIS runs: QGIS re-imports the package but may keep the old
submodules in sys.modules; the new plugin.py then met an old plates.items without
items_registered (initGui failed). classFactory drops the leftovers first.

Run in a separate QGIS Python process: swapping the package's modules inside the test
session would leave the other tests with mixed module versions."""
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SCRIPT = textwrap.dedent(r'''
    import os, sys, types
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    sys.path.insert(0, sys.argv[1])
    from qgis.core import QgsApplication
    from qgis.gui import QgsMapCanvas, QgsMessageBar
    from qgis.PyQt.QtWidgets import QMainWindow
    app = QgsApplication([], True)
    app.initQgis()

    class Iface:
        def __init__(self):
            self.w = QMainWindow(); self.c = QgsMapCanvas(self.w); self.b = QgsMessageBar(self.w)
        def mainWindow(self): return self.w
        def mapCanvas(self): return self.c
        def messageBar(self): return self.b
        def activeLayer(self): return None
        def addDockWidget(self, area, dock): self.w.addDockWidget(area, dock)
        def removeDockWidget(self, dock): self.w.removeDockWidget(dock)

    import geophysics_workbench
    import geophysics_workbench.plates.items                 # the "old version" loaded
    sys.modules["geophysics_workbench.plates.items"] = types.ModuleType(
        "geophysics_workbench.plates.items")                 # without items_registered
    # what QGIS does on install: drops the package and plugin.py, imports the package again
    del sys.modules["geophysics_workbench"]
    sys.modules.pop("geophysics_workbench.plugin", None)
    import importlib
    fresh = importlib.import_module("geophysics_workbench")
    plugin = fresh.classFactory(Iface())
    plugin.initGui()                                         # raised AttributeError
    ok = hasattr(sys.modules["geophysics_workbench.plates.items"], "items_registered")
    plugin.unload()
    print("OK" if ok else "STALE")
    sys.stdout.flush()
    os._exit(0)
''')


def test_class_factory_drops_stale_submodules(tmp_path):
    script = tmp_path / "reinstall.py"
    script.write_text(SCRIPT, encoding="utf-8")
    done = subprocess.run([sys.executable, str(script), str(REPO)], capture_output=True,
                          text=True, timeout=180)
    assert done.stdout.strip().endswith("OK"), done.stdout + done.stderr
