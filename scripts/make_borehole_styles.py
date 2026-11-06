"""The shipped borehole styles (geophysics_workbench/styles/boreholes/*.qml).

Categorized on a column "lithology" (switch the column in QGIS's editor after importing):
- din_codes.qml: German short codes as commonly used in layer descriptions;
- iso_14688.qml: EN ISO 14688-1 soil symbols.
Colours and FGDC patterns are the plugin's own choice, NOT DIN 4023 or any other standard's
drawing rules. Patterns are referenced by name relative to the plugin's pattern folder, so
the styles work on every machine with the plugin loaded.

Run with QGIS's Python:  python-qgis.bat scripts/make_borehole_styles.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# (code, label, rgb, FGDC code or None)
GRAVEL, SAND_F, SAND_M, SAND_C = (230, 170, 90), (250, 236, 165), (242, 218, 120), (226, 192, 85)
DIN = [
    ("G", "Kies (gravel)", GRAVEL, "601"),
    ("fG", "Feinkies (fine gravel)", (238, 190, 120), "601"),
    ("mG", "Mittelkies (medium gravel)", GRAVEL, "601"),
    ("gG", "Grobkies (coarse gravel)", (215, 145, 70), "602"),
    ("S", "Sand", SAND_M, "607"),
    ("fS", "Feinsand (fine sand)", SAND_F, "607"),
    ("mS", "Mittelsand (medium sand)", SAND_M, "607"),
    ("gS", "Grobsand (coarse sand)", SAND_C, "607"),
    ("U", "Schluff (silt)", (205, 195, 150), "616"),
    ("T", "Ton (clay)", (150, 162, 192), "620"),
    ("X", "Steine (cobbles)", (200, 140, 80), "602"),
    ("Y", "Blöcke (boulders)", (170, 110, 70), "602"),
    ("H", "Torf (peat)", (110, 80, 50), "657"),
    ("F", "Mudde (organic mud)", (120, 110, 80), "624"),
    ("Mu", "Mutterboden (topsoil)", (140, 110, 70), None),
    ("A", "Auffüllung (fill)", (185, 185, 185), "605"),
    ("Mg", "Geschiebemergel (boulder marl)", (165, 155, 125), "681"),
    ("Lg", "Geschiebelehm (boulder loam)", (180, 150, 110), "682"),
]
ISO = [
    ("Bo", "Boulders", (170, 110, 70), "602"),
    ("Co", "Cobbles", (200, 140, 80), "602"),
    ("Gr", "Gravel", GRAVEL, "601"),
    ("CGr", "Coarse gravel", (215, 145, 70), "602"),
    ("MGr", "Medium gravel", GRAVEL, "601"),
    ("FGr", "Fine gravel", (238, 190, 120), "601"),
    ("Sa", "Sand", SAND_M, "607"),
    ("CSa", "Coarse sand", SAND_C, "607"),
    ("MSa", "Medium sand", SAND_M, "607"),
    ("FSa", "Fine sand", SAND_F, "607"),
    ("Si", "Silt", (205, 195, 150), "616"),
    ("Cl", "Clay", (150, 162, 192), "620"),
    ("Or", "Organic soil", (110, 80, 50), "657"),
    ("Mg", "Made ground", (185, 185, 185), "605"),
]
FIELD = "lithology"

# the Gülpe demo cores (Köhler et al. 2025): values are "main class · texture code" (KA5),
# e.g. "sand · Ss (mS)"; classified by the main class, the text before "·"
GUELPE_EXPRESSION = """trim(regexp_substr("lithology", '^[^·]+'))"""
GUELPE = [
    ("sand", "sand (S…)", SAND_M, "607"),
    ("loam", "loam (L…, Sl…)", (196, 160, 110), "619"),
    ("clay", "clay (T…)", (150, 162, 192), "620"),
    ("peat", "peat", (110, 80, 50), "657"),
    ("Oh", "Oh – organic horizon", (85, 65, 45), "624"),
]
GUELPE_OUT = ROOT / "demo_guelpe" / "context" / "core_logs_style.qml"


def write(out: Path) -> list[Path]:
    from qgis.core import (QgsCategorizedSymbolRenderer, QgsMapLayer, QgsRendererCategory,
                           QgsVectorLayer)
    from qgis.PyQt.QtGui import QColor

    from geophysics_workbench.patterns import catalogue, register_svg_path, unregister_svg_path
    from geophysics_workbench.ui.pattern_table import pattern_symbol
    by_code = {p.code: p for p in catalogue()}
    out.mkdir(parents=True, exist_ok=True)
    register_svg_path()                    # so QGIS stores pattern names, not full paths
    written = []
    try:
        for path, attr, classes in ((out / "din_codes.qml", FIELD, DIN),
                                    (out / "iso_14688.qml", FIELD, ISO),
                                    (GUELPE_OUT, GUELPE_EXPRESSION, GUELPE)):
            layer = QgsVectorLayer(f"Polygon?field={FIELD}:string", "style", "memory")
            layer.setRenderer(QgsCategorizedSymbolRenderer(attr, [
                QgsRendererCategory(code, pattern_symbol(QColor(*rgb),
                                                         by_code.get(fgdc) if fgdc else None),
                                    f"{code} – {label}")
                for code, label, rgb, fgdc in classes]))
            msg, ok = layer.saveNamedStyle(str(path), QgsMapLayer.StyleCategory.Symbology)
            if not ok:
                raise RuntimeError(f"cannot write {path}: {msg}")
            written.append(path)
    finally:
        unregister_svg_path()
    return written


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from qgis.core import QgsApplication
    app = QgsApplication([], False)
    app.initQgis()
    for path in write(ROOT / "geophysics_workbench" / "styles" / "boreholes"):
        print(f"wrote {path.relative_to(ROOT)}")
    os._exit(0)


if __name__ == "__main__":
    sys.exit(main())
