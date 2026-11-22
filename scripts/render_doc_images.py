"""Render the annotated dialog pictures of the documentation from the synthetic demo.

    python-qgis.bat scripts/render_doc_images.py [out_dir]

Unpacks demo/ as committed (git HEAD) into a temporary folder (the demo folder is never
written, and local edits to it never show), opens it offscreen, brings each dialog of
``PICTURES`` into the state to show, and writes ``<out_dir>/<name>.png`` (default
docs/images/howto): the dialog with a gutter on its left that carries one numbered marker
per part, level with the top of that part. The parts are found by their object names, so a
picture never disagrees with the dialog; a part that is missing or hidden stops the script.
The page's legend uses the same numbers (docs/user/howto/<name>.md).
"""
import gc
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

GUTTER = 36                 # px, left of the grab, in the dialog's window colour
MARK_D = 24                 # marker diameter
MARK_GAP = 2                # least distance between two markers
CORNER_OUT = 6              # a corner marker's centre lies this far outside its part
MARK_COLOR = "#009485"      # the site's teal (mkdocs.yml: primary)
DIALOG_WIDTH = 760
PLATES_WIDTH = 980          # the dialog's own width: all columns of the frames table show
TABLE_SOURCE = "data/ert/P1/f001_res.dat"       # distance, elevation, resistivity, log10
TABLE = "data/ert/P1/P1_table.csv"
TABLE_HEADER = "Distance [m],Elevation [m],Rho [ohm.m]"
PROFILE = "P1"
POSITIONS = "data/stations/P1_electrodes.csv"


def marker_points(dialog, targets) -> list:
    """The top-left corner of each named widget in the dialog's coordinates, in the order
    given. Of several widgets with one name (pages of a stack) the visible one counts."""
    from qgis.PyQt.QtCore import QPoint
    from qgis.PyQt.QtWidgets import QWidget
    tops = []
    for name in targets:
        found = dialog.findChildren(QWidget, name)
        if not found:
            raise RuntimeError(f"the dialog has no part named {name!r}")
        widget = next((w for w in found if w.isVisibleTo(dialog)), None)
        if widget is None:
            raise RuntimeError(f"the part {name!r} is hidden: it cannot be marked")
        tops.append(widget.mapTo(dialog, QPoint(0, 0)))
    return tops


def marker_tops(dialog, targets) -> list[int]:
    """The top of each named widget in the dialog's coordinates, in the order given."""
    return [point.y() for point in marker_points(dialog, targets)]


def _marker(painter, number: int, x: float, y: float) -> None:
    """Marker ``number`` with its top-left at (x, y)."""
    from qgis.PyQt.QtCore import QRectF, Qt
    from qgis.PyQt.QtGui import QColor
    circle = QRectF(x, y, MARK_D, MARK_D)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(MARK_COLOR))
    painter.drawEllipse(circle)
    painter.setPen(QColor("white"))
    painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, str(number))


def _marker_painter(image):
    from qgis.PyQt.QtGui import QFont, QPainter
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = QFont(painter.font())
    font.setBold(True)
    font.setPixelSize(MARK_D * 3 // 5)
    painter.setFont(font)
    return painter


def annotate_corners(image, points):
    """A copy of ``image`` with the markers 1, 2, … at ``points`` (the parts' top-left
    corners), a little outside each part so its text stays clear, and inside the picture:
    for dialogs whose parts sit side by side."""
    from qgis.PyQt.QtGui import QImage
    out = image.convertToFormat(QImage.Format.Format_ARGB32)
    painter = _marker_painter(out)
    try:
        for number, point in enumerate(points, 1):
            x = min(max(point.x() - MARK_D / 2 - CORNER_OUT, 0), out.width() - MARK_D)
            y = min(max(point.y() - MARK_D / 2 - CORNER_OUT, 0), out.height() - MARK_D)
            _marker(painter, number, x, y)
    finally:
        painter.end()
    return out


def annotate(image, tops: list[int]):
    """``image`` with a gutter on its left carrying the markers 1, 2, … at ``tops``."""
    from qgis.PyQt.QtGui import QImage
    out = QImage(image.width() + GUTTER, image.height(), QImage.Format.Format_ARGB32)
    out.fill(image.pixelColor(0, 0))
    painter = _marker_painter(out)
    try:
        painter.drawImage(GUTTER, 0, image)
        last = None
        for number, top in enumerate(tops, 1):
            if last is not None:                    # never one marker on another
                top = max(top, last + MARK_D + MARK_GAP)
            last = top
            _marker(painter, number, (GUTTER - MARK_D) / 2, top)
    finally:
        painter.end()
    return out


def _texts(dialog):
    """Every text the dialog shows: fields, labels, combo items and table cells."""
    from qgis.PyQt.QtWidgets import QAbstractItemView, QComboBox, QLabel, QLineEdit
    for kind in (QLineEdit, QLabel):
        for widget in dialog.findChildren(kind):
            if widget.isVisibleTo(dialog):
                yield widget.text()
    for combo in dialog.findChildren(QComboBox):
        if combo.isVisibleTo(dialog):
            yield from (combo.itemText(i) for i in range(combo.count()))
    for view in dialog.findChildren(QAbstractItemView):
        model = view.model()
        if model is None or not view.isVisibleTo(dialog):
            continue
        try:
            columns = model.columnCount()
        except TypeError:                       # a list model keeps it private: one column
            columns = 1
        for row in range(model.rowCount()):
            for column in range(columns):
                yield str(model.index(row, column).data() or "")


def check_no_private_path(dialog, private: list[str]) -> None:
    """Stop when a text of the dialog holds one of the ``private`` folders (the temporary
    copy, the home folder): such a picture must never be written."""
    def plain(text: str) -> str:
        return text.replace("\\", "/").lower()
    needles = [plain(p).rstrip("/") for p in private if p]
    for text in _texts(dialog):
        if any(needle in plain(text) for needle in needles):
            raise RuntimeError(f"a private path shows in the dialog: {text!r}")


def committed_demo(target: Path) -> Path:
    """Unpack demo/ as committed (git HEAD) into ``target`` and return ``target/demo``: no
    local edit of the demo (store, project, data files) can reach a picture."""
    import io
    import subprocess
    import tarfile

    from render_readme_images import GIT
    data = subprocess.run([GIT, "archive", "--format=tar", "HEAD", "demo"], cwd=REPO,
                          capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(target, filter="data")
    return target / "demo"


def write_table(demo: Path) -> Path:
    """A plain text table of the demo's P1 model (distance, elevation, resistivity), so the
    dialog shows the parts it has for a file it does not know. Returns it relative to
    ``demo``."""
    rows = [line.split()[:3] for line in
            (demo / TABLE_SOURCE).read_text(encoding="utf-8").splitlines() if line.strip()]
    (demo / TABLE).write_text("\n".join([TABLE_HEADER] + [",".join(r) for r in rows]) + "\n",
                              encoding="utf-8")
    return Path(TABLE)


def add_data_dialog(plugin, demo: Path):
    """Add Data with a text table chosen, for the existing profile P1, all parts open."""
    from groundwork_geophysics import readers
    from groundwork_geophysics.ui.add_data_dialog import AddDataDialog

    table = write_table(demo)
    os.chdir(demo)                              # the File field shows a path inside the demo
    dialog = AddDataDialog(plugin.iface, plugin.store, None, plugin.provider)
    dialog.show()
    dialog.set_file(table.as_posix())
    placement = dialog.placement
    placement.select_source("existing")
    index = placement.profile_combo.findText(PROFILE)
    if index < 0:
        raise RuntimeError(f"the demo has no profile {PROFILE!r}")
    placement.profile_combo.setCurrentIndex(index)
    if dialog.last_error:
        raise RuntimeError(f"Add Data reports: {dialog.last_error}")
    if dialog.format_combo.currentData() != readers.FALLBACK:
        raise RuntimeError("the table was not taken as a plain text table")
    return dialog


def profile_properties_dialog(plugin, demo: Path):
    """Profile Properties of P1 with Set surveyed positions on and its positions file chosen."""
    from groundwork_geophysics.ui.profile_properties_dialog import ProfilePropertiesDialog

    os.chdir(demo)
    dialog = ProfilePropertiesDialog(plugin.iface, plugin.store, _profile_id(plugin),
                                     plugin.provider, dock=plugin.dock)
    dialog.show()
    dialog.set_positions.setChecked(True)
    dialog.placement.set_positions_file(POSITIONS)
    return dialog


def context_boreholes_dialog(plugin, demo: Path):
    """Context Layers on its Boreholes tab, with the demo's borehole entry."""
    plugin.edit_context()
    dialog = plugin._context_dialog
    if dialog is None:
        raise RuntimeError("the Context layers dialog did not open")
    tabs = dialog.tabs
    index = next((i for i in range(tabs.count()) if tabs.tabText(i) == "Boreholes"), -1)
    if index < 0:
        raise RuntimeError("Context layers has no Boreholes tab")
    tabs.setCurrentIndex(index)
    return dialog


def plates_dialog(plugin, demo: Path):
    """Plates with one plate: the profile P1 as the section panel shows it."""
    from qgis.core import QgsApplication
    from render_demo_section import wait_idle

    plugin.show_section_panel()             # a new plate starts with the panel's profile
    plugin.dock.open_profile(_profile_id(plugin))
    wait_idle(QgsApplication.instance(), plugin.dock)
    plugin.show_plates()
    dialog = plugin._plates_dialog
    if dialog is None:
        raise RuntimeError("the Plates dialog did not open")
    if dialog.plate_list.count() == 0:
        dialog.add_plate()
    dialog.plate_list.setCurrentRow(0)
    if dialog.frames.rowCount() == 0:
        raise RuntimeError("the plate has no section frame")
    return dialog


NAMED_POSITIONS = "data/stations/P1_gps_names.csv"


def write_named_positions(demo: Path) -> Path:
    """The demo's P1 electrodes as a field GPS file names them (ERT01_01 …), with a base
    point, a control point and one electrode measured twice. Returns it relative to
    ``demo``."""
    rows = [line.split(",") for line in
            (demo / POSITIONS).read_text(encoding="utf-8").splitlines()[1:] if line.strip()]
    x0, y0, z0 = (float(v) for v in rows[0][1:4])
    out = ["Name,East,North,Height", f"Base,{x0 + 25:.2f},{y0 - 8:.2f},{z0:.2f}",
           f"GCP3,{x0 + 30:.2f},{y0 + 12:.2f},{z0:.2f}"]
    for n, x, y, z in rows[:24]:
        out.append(f"ERT01_{int(n):02d},{x},{y},{z}")
        if n == "7":                        # measured again a little later
            out.append(f"ERT01_07,{float(x) + 0.05:.2f},{y},{z}")
    (demo / NAMED_POSITIONS).write_text("\n".join(out) + "\n", encoding="utf-8")
    return Path(NAMED_POSITIONS)


def electrode_names_dialog(plugin, demo: Path):
    """New Profile with a positions file of point names and the Electrodes from Names list
    open."""
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.new_profile_dialog import NewProfileDialog

    path = write_named_positions(demo)
    os.chdir(demo)
    dialog = NewProfileDialog(plugin.iface, plugin.store, QgsProject.instance(),
                              plugin.provider)
    dialog.show()
    dialog.placement.set_positions_file(path.as_posix())
    if dialog.placement.name_rows() is None:
        raise RuntimeError("the names column was not taken as the Number")
    dialog.placement.names_box.setCollapsed(False)
    return dialog


def show_in_3d_dialog(plugin, demo: Path):
    """Show in 3D… with P1's model ticked as a section picture with the interpretation, and
    the Sizes open."""
    from groundwork_geophysics.ui.view3d_layers import Choice, write_choice
    from qgis.core import QgsProject

    models = [d.id for p in plugin.store.profiles() for d in plugin.store.datasets(p.id)
              if d.kind.endswith("_model")]
    if not models:
        raise RuntimeError("the demo has no model")
    pid = _profile_id(plugin)
    write_choice(QgsProject.instance(), Choice(frozenset(models), frozenset({pid}),
                                               {models[0]: "picture"}, True))
    plugin.show_in_3d()
    dialog = plugin._view3d_dialog
    if dialog is None:
        raise RuntimeError("the Show in 3D dialog did not open")
    dialog.sizes.setCollapsed(False)
    return dialog


def _profile_id(plugin) -> str:
    by_name = {p.name: p.id for p in plugin.store.profiles()}
    if PROFILE not in by_name:
        raise RuntimeError(f"the demo has no profile {PROFILE!r}")
    return by_name[PROFILE]


@dataclass(frozen=True)
class Picture:
    name: str                       # file stem under out_dir
    page: str                       # the docs page that shows it, relative to docs/
    setup: Callable                 # (plugin, demo) -> the dialog, shown and in its state
    targets: tuple[str, ...]        # object names of the parts, in marker order
    corners: bool = False           # markers on the parts (side by side), not in a gutter
    width: int = DIALOG_WIDTH


PICTURES = (
    Picture("add-data", "user/howto/add-data.md", add_data_dialog,
            ("table_options", "columns_group", "placement", "preview_group", "status_block")),
    Picture("profile-properties", "user/howto/placement.md", profile_properties_dialog,
            ("name_edit", "fit_label", "reference_button", "set_positions", "set_combo"),
            width=620),
    Picture("context-layers-boreholes", "user/howto/boreholes.md", context_boreholes_dialog,
            ("borehole_layer", "borehole_elevation", "borehole_total_depth", "interval_table",
             "interval_id", "interval_text", "borehole_style", "add_curve_table",
             "search_distance")),
    Picture("plates", "user/howto/plates.md", plates_dialog,
            ("plate_list", "plate_number", "frames", "take_from_panel", "plate_details",
             "create_plates", "export_plates"), corners=True, width=PLATES_WIDTH),
    Picture("electrode-names", "user/howto/placement.md", electrode_names_dialog,
            ("names_row", "names_box"), width=620),
    Picture("show-in-3d", "user/howto/3d-view.md", show_in_3d_dialog,
            ("view3d_tree", "select_all", "interp_check", "sizes_box", "apply_button"),
            width=560),
)


def full_height(dialog, app, width: int = DIALOG_WIDTH) -> None:
    """Make the dialog ``width`` wide and as tall as its scrolling parts need: nothing that
    shows is cut off."""
    from qgis.PyQt.QtWidgets import QScrollArea

    def scrolls():
        return [s for s in dialog.findChildren(QScrollArea)
                if s.isVisibleTo(dialog) and s.widget() is not None]

    def settle():
        for _ in range(5):                      # the layout settles over a few rounds
            app.processEvents()

    settle()
    extra = max((s.widget().sizeHint().height() - s.viewport().height() for s in scrolls()),
                default=0)
    dialog.resize(width, dialog.height() + max(extra, 0))
    settle()
    extra = max((s.verticalScrollBar().maximum() for s in scrolls()), default=0)
    if extra > 0:
        dialog.resize(width, dialog.height() + extra)
        settle()
    if any(s.verticalScrollBar().maximum() > 0 for s in scrolls()):
        raise RuntimeError("the dialog still scrolls: parts would be cut off")


def render(demo: Path, out_dir: Path, private: list[str]) -> list[Path]:
    from qgis.core import QgsApplication, QgsProject
    from qgis.PyQt.QtCore import QCoreApplication, QEvent
    from render_demo_section import FakeIface
    from render_readme_images import save

    from groundwork_geophysics.plugin import WorkbenchPlugin

    app = QgsApplication.instance()
    project = QgsProject.instance()
    if not project.read(str(demo / "demo_project.qgz")):
        raise RuntimeError("could not read the demo project")
    iface = FakeIface()
    plugin = WorkbenchPlugin(iface)
    plugin.initGui()
    if plugin.store is None:
        raise RuntimeError("the demo project has no workbench store")
    written = []
    try:
        for picture in PICTURES:
            dialog = picture.setup(plugin, demo)
            try:
                full_height(dialog, app, picture.width)
                points = marker_points(dialog, picture.targets)
                check_no_private_path(dialog, private)
                grab = dialog.grab().toImage()
                image = (annotate_corners(grab, points) if picture.corners
                         else annotate(grab, [p.y() for p in points]))
                written.append(save(image, out_dir / f"{picture.name}.png"))
                print(f"  {image.width()} x {image.height()} px, markers at "
                      f"{[(p.x(), p.y()) for p in points]}")
            finally:
                dialog.reject()
                dialog.deleteLater()
    finally:
        # let go of the demo's files, or Windows keeps the temporary folder (the synthetic
        # demo has no live web layers, so this cannot hang as it can for Gülpe)
        os.chdir(REPO)
        project.setDirty(False)
        plugin.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        project.clear()
        iface.mainWindow().close()
        for _ in range(3):                      # the dialogs and layers go only now
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
            app.processEvents()
        gc.collect()
    return written


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
    from qgis.core import QgsApplication, QgsSettings
    from qgis.PyQt.QtCore import QLocale
    from qgis.PyQt.QtGui import QFont
    from render_demo_section import UI_FONT

    from groundwork_geophysics.ui.add_data_dialog import SETTINGS_KEY

    out_dir = (Path(sys.argv[1]) if len(sys.argv) > 1
               else REPO / "docs" / "images" / "howto").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    app = QgsApplication([], True)
    app.initQgis()
    app.setFont(QFont(UI_FONT, 9))
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedKingdom))
    settings = QgsSettings()
    remembered = settings.value(SETTINGS_KEY, None)
    tmp = Path(tempfile.mkdtemp(prefix="wb_docs_"))
    try:
        settings.remove(SETTINGS_KEY)       # the developer's last table must not shape
        demo = committed_demo(tmp)          # the picture; put back below
        render(demo, out_dir, [str(tmp), str(Path.home())])
        return 0
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if remembered is not None:
            settings.setValue(SETTINGS_KEY, remembered)
            settings.sync()
        os.chdir(REPO)
        shutil.rmtree(tmp, ignore_errors=True)
        if tmp.exists():
            print(f"warning: could not remove the temporary folder {tmp}", file=sys.stderr)


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)
