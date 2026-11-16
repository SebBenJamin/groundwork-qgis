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
MARK_COLOR = "#009485"      # the site's teal (mkdocs.yml: primary)
DIALOG_WIDTH = 760
TABLE_SOURCE = "data/ert/P1/f001_res.dat"       # distance, elevation, resistivity, log10
TABLE = "data/ert/P1/P1_table.csv"
TABLE_HEADER = "Distance [m],Elevation [m],Rho [ohm.m]"
PROFILE = "P1"


def marker_tops(dialog, targets) -> list[int]:
    """The top of each named widget in the dialog's coordinates, in the order given."""
    from qgis.PyQt.QtCore import QPoint
    from qgis.PyQt.QtWidgets import QWidget
    tops = []
    for name in targets:
        widget = dialog.findChild(QWidget, name)
        if widget is None:
            raise RuntimeError(f"the dialog has no part named {name!r}")
        if not widget.isVisibleTo(dialog):
            raise RuntimeError(f"the part {name!r} is hidden: it cannot be marked")
        tops.append(widget.mapTo(dialog, QPoint(0, 0)).y())
    return tops


def annotate(image, tops: list[int]):
    """``image`` with a gutter on its left carrying the markers 1, 2, … at ``tops``."""
    from qgis.PyQt.QtCore import QRectF, Qt
    from qgis.PyQt.QtGui import QColor, QFont, QImage, QPainter
    out = QImage(image.width() + GUTTER, image.height(), QImage.Format.Format_ARGB32)
    out.fill(image.pixelColor(0, 0))
    painter = QPainter(out)
    try:
        painter.drawImage(GUTTER, 0, image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(painter.font())
        font.setBold(True)
        font.setPixelSize(MARK_D * 3 // 5)
        painter.setFont(font)
        last = None
        for number, top in enumerate(tops, 1):
            if last is not None:                    # never one marker on another
                top = max(top, last + MARK_D + MARK_GAP)
            last = top
            circle = QRectF((GUTTER - MARK_D) / 2, top, MARK_D, MARK_D)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(MARK_COLOR))
            painter.drawEllipse(circle)
            painter.setPen(QColor("white"))
            painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, str(number))
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
        for row in range(model.rowCount()):
            for column in range(model.columnCount()):
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


@dataclass(frozen=True)
class Picture:
    name: str                       # file stem under out_dir
    setup: Callable                 # (plugin, demo) -> the dialog, shown and in its state
    targets: tuple[str, ...]        # object names of the parts, in marker order


PICTURES = (
    Picture("add-data", add_data_dialog,
            ("table_options", "columns_group", "placement", "preview_group", "status_block")),
)


def full_height(dialog, app) -> None:
    """Make the dialog as tall as its scrolling part needs: nothing is cut off."""
    from qgis.PyQt.QtWidgets import QScrollArea
    app.processEvents()
    scroll = dialog.findChild(QScrollArea)
    extra = 0
    if scroll is not None and scroll.widget() is not None:
        extra = scroll.widget().sizeHint().height() - scroll.viewport().height()
    dialog.resize(DIALOG_WIDTH, dialog.height() + max(extra, 0))
    for _ in range(5):                          # the layout settles over a few rounds
        app.processEvents()
    if scroll is not None and scroll.verticalScrollBar().maximum() > 0:
        extra = scroll.verticalScrollBar().maximum()
        dialog.resize(DIALOG_WIDTH, dialog.height() + extra)
        for _ in range(5):
            app.processEvents()
        if scroll.verticalScrollBar().maximum() > 0:
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
                full_height(dialog, app)
                tops = marker_tops(dialog, picture.targets)
                check_no_private_path(dialog, private)
                image = annotate(dialog.grab().toImage(), tops)
                written.append(save(image, out_dir / f"{picture.name}.png"))
                print(f"  {image.width()} x {image.height()} px, markers at {tops}")
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
        app.processEvents()
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
