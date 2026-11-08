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
    assert "patterns/fgdc/607 Massive sand or sandstone.svg" in rel
    assert "patterns/fgdc/ATTRIBUTION.md" in rel


def test_files_are_named_by_code_and_name():
    """QGIS's SVG picker shows file names: "607 Massive sand or sandstone.svg", not 607.svg;
    characters Windows does not allow in file names are left out."""
    from geophysics_workbench.patterns import PATTERN_DIR
    rows = list(csv.DictReader(open(PATTERN_DIR / "fgdc" / "index.csv", encoding="utf8")))
    for r in rows:
        assert r["file"].startswith(r["code"] + " ") and r["file"].endswith(".svg"), r
        assert not any(c in r["file"] for c in r'<>:"/\|?*'), r
    assert {r["code"]: r["file"] for r in rows}["607"] == "607 Massive sand or sandstone.svg"


def test_catalogue_lists_every_pattern(qgis_app):
    from geophysics_workbench.patterns import catalogue
    items = catalogue()
    assert len(items) == 116
    sand = next(i for i in items if i.code == "607")
    assert sand.name == "Massive sand or sandstone" and sand.path.is_file()
    assert sand.label == "607 – Massive sand or sandstone"



def test_unregister_keeps_paths_added_by_others_meanwhile(qgis_app):
    """Minor 9: another plugin's default SVG path, added after ours, survives our unload."""
    from qgis.core import QgsApplication

    from geophysics_workbench.patterns import _defaults, register_svg_path, unregister_svg_path
    register_svg_path()
    QgsApplication.setDefaultSvgPaths(_defaults() + ["C:/other_plugin/svg"])
    unregister_svg_path()
    paths = [p.replace("\\", "/") for p in QgsApplication.svgPaths()]
    assert "C:/other_plugin/svg" in paths
    assert not any(p.rstrip("/").endswith("geophysics_workbench/patterns") for p in paths)
    QgsApplication.setDefaultSvgPaths([p for p in _defaults() if "other_plugin" not in p])
