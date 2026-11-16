"""Export the project's plates as vector PDFs: one file per plate, or one combined file."""
from __future__ import annotations

import re
from pathlib import Path

from qgis.core import QgsLayoutExporter, QgsLayoutRenderContext
from qgis.PyQt.QtCore import QMarginsF, QSizeF
from qgis.PyQt.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter

from ..ids import NAME
from .build import find_plate_layout
from .sources import read_plates

COMBINED_NAME = "Plates.pdf"
DPI = 300


def pdf_name(plate) -> str:
    """``Plate_<number>_<title>.pdf`` with anything but letters, digits, - and _ replaced."""
    stem = re.sub(r"[^\w\-]+", "_", f"Plate_{plate.number}_{plate.title}").strip("_")
    return f"{stem or 'Plate'}.pdf"


def _settings() -> QgsLayoutExporter.PdfExportSettings:
    settings = QgsLayoutExporter.PdfExportSettings()
    settings.forceVectorOutput = True
    settings.rasterizeWholeImage = False
    settings.dpi = DPI
    return settings


def _layouts(project) -> list:
    out = []
    for plate in read_plates(project):
        layout = find_plate_layout(project, plate)
        if layout is not None:
            out.append((plate, layout))
    return out


def export_plates(project, folder: Path, combined: bool = False) -> list[Path]:
    """Write the plates' layouts (as they are now; create/update them first) into
    ``folder``. Returns the files written; raises ``OSError`` when one cannot be written."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    plates = _layouts(project)
    if combined:
        path = folder / COMBINED_NAME
        _combined(plates, path)
        return [path]
    out = []
    for plate, layout in plates:
        path = folder / pdf_name(plate)
        result = QgsLayoutExporter(layout).exportToPdf(str(path), _settings())
        if result != QgsLayoutExporter.ExportResult.Success:
            raise OSError(f"could not write {path} (QGIS export result {result})")
        out.append(path)
    return out


def _combined(plates, path: Path) -> None:
    """All pages of all plates into one PDF, drawn as vectors (each page its own size)."""
    writer = QPdfWriter(str(path))
    writer.setResolution(DPI)
    writer.setCreator(NAME)
    painter = None
    try:
        for plate, layout in plates:
            context = layout.renderContext()
            old_flags, old_dpi = context.flags(), context.dpi()
            context.setFlag(QgsLayoutRenderContext.Flag.FlagForceVectorOutput, True)
            context.setDpi(DPI)
            exporter = QgsLayoutExporter(layout)
            try:
                for i in range(layout.pageCollection().pageCount()):
                    w, h = _mm(layout, layout.pageCollection().page(i))
                    writer.setPageLayout(QPageLayout(QPageSize(QSizeF(w, h),
                                                               QPageSize.Unit.Millimeter),
                                                     QPageLayout.Orientation.Portrait,
                                                     QMarginsF(0, 0, 0, 0)))
                    if painter is None:
                        painter = QPainter(writer)
                        if not painter.isActive():      # e.g. open (locked) in a PDF viewer
                            painter = None
                            raise OSError(f"could not write {path} (is it open elsewhere?)")
                    else:
                        writer.newPage()
                    exporter.renderPage(painter, i)
            finally:
                context.setFlags(old_flags)
                context.setDpi(old_dpi)
    finally:
        if painter is not None:
            painter.end()
    if not path.exists():
        raise OSError(f"could not write {path}")


def _mm(layout, page) -> tuple[float, float]:
    from qgis.core import QgsUnitTypes
    size = layout.renderContext().measurementConverter().convert(
        page.sizeWithUnits(), QgsUnitTypes.LayoutMillimeters)
    return size.width(), size.height()
