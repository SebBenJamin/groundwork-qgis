"""The FGDC lithology patterns ship with the plugin and appear in QGIS's SVG pickers."""
import csv


def test_register_adds_once_and_unregister_removes_only_ours(qgis_app):
    from qgis.core import QgsApplication, QgsSettings

    from geophysics_workbench.patterns import PATTERN_DIR, register_svg_path, unregister_svg_path
    settings_before = QgsSettings().value("svg/searchPathsForSVG", [])
    before = list(QgsApplication.svgPaths())
    register_svg_path()
    register_svg_path()
    after = list(QgsApplication.svgPaths())
    ours = [p for p in after if p.rstrip("/\\") == str(PATTERN_DIR).replace("\\", "/")
            or p.rstrip("/\\") == str(PATTERN_DIR)]
    assert len(ours) == 1
    unregister_svg_path()
    assert list(QgsApplication.svgPaths()) == before
    assert QgsSettings().value("svg/searchPathsForSVG", []) == settings_before   # untouched


def test_every_index_row_has_a_file_and_parses_as_svg(qgis_app):
    from qgis.PyQt.QtSvg import QSvgRenderer

    from geophysics_workbench.patterns import PATTERN_DIR
    rows = list(csv.DictReader(open(PATTERN_DIR / "fgdc" / "index.csv", encoding="utf8")))
    assert len(rows) >= 100 and any(r["code"] == "607" for r in rows)
    for r in rows:
        path = PATTERN_DIR / "fgdc" / r["file"]
        assert path.is_file() and r["name"], r
        assert QSvgRenderer(str(path)).isValid(), r


def test_attribution_names_source_and_licence():
    from geophysics_workbench.patterns import PATTERN_DIR
    text = (PATTERN_DIR / "fgdc" / "ATTRIBUTION.md").read_text(encoding="utf8")
    assert "davenquinn/geologic-patterns" in text and "CC0" in text
    assert "FGDC-STD-013-2006" in text and "7fdb820b" in text


def test_zip_contains_patterns_and_attribution():
    from scripts.package import PLUGIN, files_under
    rel = {p.relative_to(PLUGIN).as_posix() for p in files_under(PLUGIN)}
    assert "patterns/fgdc/607.svg" in rel and "patterns/fgdc/ATTRIBUTION.md" in rel
