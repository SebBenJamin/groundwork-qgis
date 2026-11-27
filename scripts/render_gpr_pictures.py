"""Render the pictures of the GPR how-to (docs/user/howto/gpr.md) from the Srednja Kanomlja
trial project.

    python-qgis.bat scripts/render_gpr_pictures.py [out_dir]

The data are not in the repository and must be downloaded first: Grützner, C. et al. (2020):
Geophysical survey (GPR, ERT, magnetic) on active faults in Slovenia and Italy. PANGAEA,
https://doi.org/10.1594/PANGAEA.922902, CC BY 4.0. The script reads a Groundwork project
built from the Srednja Kanomlja site of that dataset in ``.cache/kanomlja_project/project/``
(git-ignored): ``kanomlja_project.qgz`` with its store, the GSSI files under ``data/gpr/``,
two ERT models inverted with pyGIMLi from the authors' readings, and the ARSO lidar terrain
model DMR1 as the DEM. The profiles and layers it uses are named in the constants below.

The project folder is copied to a temporary folder and only the copy is opened: the trial
project is never written. Writes to ``out_dir`` (default docs/images/howto):

- ``gpr-section.jpg``: radar over resistivity on SreKan4, the top 8 m;
- ``gpr-add-data.png``: Add Data with a 270 MHz file on SreKan4, its radar parts numbered in a
  gutter as in render_doc_images.py (``ADD_DATA_PARTS``);
- ``gpr-display.png``: the radargram's Display… dialog, its filters numbered
  (``DISPLAY_PARTS``);
- ``gpr-look-before.jpg`` / ``gpr-look-after.jpg``: one radargram without and with the
  background removal of the default look;
- ``gpr-antenna-100.jpg`` / ``gpr-antenna-270.jpg``: the 100 and 270 MHz files of one line.

Data: Grützner et al. 2020, PANGAEA, CC BY 4.0. Terrain: ARSO (Slovenian Environment Agency).
"""
import os
import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / ".testlibs"))

TRIAL = REPO / ".cache" / "kanomlja_project" / "project"
PROJECT = "kanomlja_project.qgz"
PANEL = (1500, 600)
LIST_WIDTH = 560            # px: the panel's Layers list
JPEG_QUALITY = 82
#: profiles (by the start of their name) and layers (by the start of their name)
ERT_LINE = "SreKan4"
ERT = "SreKan4 resistivity"
GPR_100, GPR_270 = "GPR12 100 MHz", "GPR12 270 MHz"
LOOK_LINE, LOOK_LAYER = "GPR9", "GPR9 270 MHz"
#: the file Add Data is shown with, relative to the project folder, and the velocity typed
ADD_FILE = "data/gpr/270MHz/270_AAA_____034.DZT"
ADD_NAME = "GPR12 270 MHz, W to E"
VELOCITY = "0.15"
#: views: from s, to s, top of the view (m above sea level), depth shown (m)
SECTION_VIEW = (-5.0, 191.0, 349.0, 8.5)
ANTENNA_VIEW = (40.0, 140.0, 348.5, 12.0)
LOOK_VIEW = (-12.0, 148.0, 350.5, 8.0)
DIALOG_WIDTH = 760
DISPLAY_WIDTH = 520
#: Add Data's parts in marker order: rows of the radar box by their key, or dialog parts by
#: attribute name
ADD_DATA_PARTS = (("box", "velocity"), ("box", "time_zero"), ("box", "zero"),
                  ("box", "smoothing"), ("box", "position"), ("box", "span"),
                  ("dialog", "placement"), ("dialog", "status_block"))
DISPLAY_PARTS = ("dewow_check", "background_check", "agc_check")


def tops(dialog, widgets) -> list[int]:
    """The top of each widget in the dialog's coordinates; a hidden one stops the script."""
    from qgis.PyQt.QtCore import QPoint
    out = []
    for name, widget in widgets:
        if not widget.isVisibleTo(dialog):
            raise RuntimeError(f"the part {name!r} is hidden: it cannot be marked")
        out.append(widget.mapTo(dialog, QPoint(0, 0)).y())
    return out


def default_look(layer):
    """The look a new radargram starts with (``radar_gain``), whatever the trial stored."""
    from groundwork_geophysics.section.data import radar_gain
    section = layer.traces.section
    return radar_gain((layer.dataset.provenance or {}).get("frequency_mhz"),
                      section.n_samples * section.step)


class Views:
    """The section panel on one profile: which layers show, how, and where the view is."""

    def __init__(self, app, plugin, profile_id):
        from render_demo_section import wait_idle
        self.app, self.plugin, self.dock = app, plugin, plugin.dock
        self.profile_id = profile_id
        self.dock.open_profile(profile_id)
        wait_idle(app, self.dock, timeout_s=300)
        if self.dock.errors.text():
            raise RuntimeError(f"layer errors: {self.dock.errors.text()}")
        self.layers = {layer.dataset.name: layer for layer in plugin.provider.layers(profile_id)}
        self.styles = {name: plugin.provider.style(layer.dataset.id)
                       for name, layer in self.layers.items()}

    def layer(self, start: str):
        """The layer whose name starts with ``start``, with the style it has now."""
        found = [layer for layer in self.plugin.provider.layers(self.profile_id)
                 if layer.dataset.name.startswith(start)]
        if len(found) != 1:
            raise RuntimeError(f"no single layer named {start!r}: {list(self.layers)}")
        return found[0]

    def show(self, shown: dict) -> None:
        """Only the layers in ``shown`` (name start -> dict of style changes, "gain" as a
        DisplayGain) are visible, each with its style as opened plus these changes."""
        provider = self.plugin.provider
        for name, layer in self.layers.items():
            changes = next((c for start, c in shown.items() if name.startswith(start)), None)
            style = replace(self.styles[name], visible=changes is not None)
            if changes:
                style = replace(style, **changes)
            provider.set_style(layer.dataset.id, style)
        provider.notify_redraw()

    def save(self, out: Path, view) -> None:
        from render_demo_section import wait_idle, zoom_to
        from render_readme_images import save
        s0, s1, top, depth = view
        width = self.dock.splitter.width()      # the layer names in full, whatever the
        self.dock.splitter.setSizes([width - LIST_WIDTH, LIST_WIDTH])   # last session kept
        self.app.processEvents()
        area = self.dock.canvas.plotArea()
        ve = round((s1 - s0) / area.width() / (depth / area.height()), 2)
        self.dock.fit.user_navigated()
        self.dock.ve_spin.setValue(ve)
        wait_idle(self.app, self.dock, timeout_s=300)
        zoom_to(self.dock, ve, s0, s1, top)
        wait_idle(self.app, self.dock, timeout_s=300)
        if self.dock.errors.text():
            raise RuntimeError(f"layer errors: {self.dock.errors.text()}")
        save(self.dock, out, JPEG_QUALITY)


def add_data_picture(app, plugin, folder: Path, profile_id: str, out: Path) -> None:
    import render_doc_images as rd
    from render_readme_images import save

    from groundwork_geophysics.ui.add_data_dialog import AddDataDialog

    os.chdir(folder)                            # the File field shows a path inside the project
    dialog = AddDataDialog(plugin.iface, plugin.store, profile_id, plugin.provider)
    dialog.show()
    try:
        dialog.set_file(ADD_FILE)
        box = dialog.radar_box
        if not box.isVisible():
            raise RuntimeError(f"Add Data shows no radar box: {dialog.summary_label.text()}")
        box.velocity_edit.setText(VELOCITY)
        box.velocity_edit.editingFinished.emit()
        dialog.name_edit.setText(ADD_NAME)
        dialog._refresh()
        app.processEvents()
        if not dialog.add_button.isEnabled():
            raise RuntimeError(f"Add is not possible: {dialog.summary_label.text()}")
        rd.full_height(dialog, app, DIALOG_WIDTH)
        parts = [(key, box._rows[key][0] if where == "box" else getattr(dialog, key))
                 for where, key in ADD_DATA_PARTS]
        marks = tops(dialog, parts)
        rd.check_no_private_path(dialog, [str(folder.parent), str(Path.home())])
        save(rd.annotate(dialog.grab().toImage(), marks), out)
    finally:
        os.chdir(REPO)
        dialog.reject()
        dialog.deleteLater()


def display_picture(app, dock, layer, out: Path) -> None:
    import render_doc_images as rd
    from render_readme_images import save

    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    dialog = DisplayDialog(dock.layer_list, layer)
    dialog.show()
    try:
        rd.full_height(dialog, app, DISPLAY_WIDTH)
        marks = tops(dialog, [(n, getattr(dialog, n)) for n in DISPLAY_PARTS])
        rd.check_no_private_path(dialog, [str(Path.home())])
        save(rd.annotate(dialog.grab().toImage(), marks), out)
    finally:
        dialog.reject()


def render(folder: Path, out_dir: Path) -> None:
    from qgis.core import QgsApplication, QgsProject
    from render_demo_section import FakeIface

    from groundwork_geophysics.plugin import WorkbenchPlugin

    app = QgsApplication.instance()
    project = QgsProject.instance()
    if not project.read(str(folder / PROJECT)):
        raise RuntimeError("could not read the trial project")
    plugin = WorkbenchPlugin(FakeIface())
    plugin.initGui()
    if plugin.store is None:
        raise RuntimeError("the trial project has no Groundwork store")
    try:
        dock = plugin.dock
        plugin.show_section_panel()
        dock.setFloating(True)
        dock.resize(*PANEL)
        app.processEvents()
        profiles = {p.name: p.id for p in plugin.store.profiles()}

        def profile(start):
            return next(pid for name, pid in profiles.items() if name.startswith(start))

        line = Views(app, plugin, profile(ERT_LINE))
        g100, g270 = line.layer(GPR_100), line.layer(GPR_270)
        look_100, look_270 = default_look(g100), default_look(g270)
        line.show({ERT: {}, GPR_270: {"gain": look_270, "opacity": 0.5}})
        line.save(out_dir / "gpr-section.jpg", SECTION_VIEW)
        line.show({GPR_100: {"gain": look_100}})
        line.save(out_dir / "gpr-antenna-100.jpg", ANTENNA_VIEW)
        line.show({GPR_270: {"gain": look_270}})
        line.save(out_dir / "gpr-antenna-270.jpg", ANTENNA_VIEW)
        shown = line.layer(GPR_270)
        if shown.style.gain != look_270:
            raise RuntimeError("the Display dialog would not show the default look")
        display_picture(app, dock, shown, out_dir / "gpr-display.png")
        add_data_picture(app, plugin, folder, profile(ERT_LINE), out_dir / "gpr-add-data.png")

        look = Views(app, plugin, profile(LOOK_LINE))
        after = default_look(look.layer(LOOK_LAYER))
        look.show({LOOK_LAYER: {"gain": replace(after, background="", background_traces=0)}})
        look.save(out_dir / "gpr-look-before.jpg", LOOK_VIEW)
        look.show({LOOK_LAYER: {"gain": after}})
        look.save(out_dir / "gpr-look-after.jpg", LOOK_VIEW)
    finally:
        # no plugin.unload() / project.clear(): the live background map can hang them; the
        # process ends with os._exit right after this
        project.setDirty(False)


def main() -> int:
    from qgis.core import QgsApplication, QgsSettings
    from qgis.PyQt.QtCore import QLocale
    from qgis.PyQt.QtGui import QFont
    from render_demo_section import UI_FONT

    from groundwork_geophysics.ui.add_data_dialog import RADAR_SETTINGS_KEY

    out_dir = (Path(sys.argv[1]) if len(sys.argv) > 1
               else REPO / "docs" / "images" / "howto").resolve()
    if not (TRIAL / PROJECT).is_file():
        print(f"error: the trial project is missing: {TRIAL.relative_to(REPO) / PROJECT} "
              "(see the docstring: the data must be downloaded first)", file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    app = QgsApplication([], True)
    app.initQgis()
    app.setFont(QFont(UI_FONT, 9))
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedKingdom))
    settings = QgsSettings()
    remembered = settings.value(RADAR_SETTINGS_KEY, None)
    tmp = Path(tempfile.mkdtemp(prefix="wb_gpr_"))
    try:
        settings.remove(RADAR_SETTINGS_KEY)     # the developer's last radar settings must not show
        folder = tmp / "project"
        shutil.copytree(TRIAL, folder)
        render(folder, out_dir)
        return 0
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if remembered is not None:
            settings.setValue(RADAR_SETTINGS_KEY, remembered)
            settings.sync()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)
