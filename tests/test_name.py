"""The plugin says Groundwork wherever a user reads it."""
from configparser import ConfigParser
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "groundwork_geophysics"


def test_no_old_name_in_plugin():
    offenders = []
    for path in PACKAGE.rglob("*"):
        if not path.is_file() or path.suffix in (".pyc", ".svg", ".png", ".gpkg"):
            continue
        if path.name == "ids.py" and path.parent == PACKAGE:
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            # the 0.10.0 changelog line names the old plugin once, on purpose
            if "Geophysics Workbench" in line and "(was Geophysics Workbench)" not in line:
                offenders.append(path.relative_to(REPO).as_posix())
                break
    assert offenders == []


def test_menu_and_titles(fake_iface):
    from groundwork_geophysics import classFactory

    p = classFactory(fake_iface)
    p.initGui()
    try:
        assert p.menu.title() == "Groundwork"
        texts = [a.text() for a in p.menu.actions()]
        assert "New Groundwork Project…" in texts
        assert "Open Groundwork Project…" in texts
        assert not any("orkbench" in t for t in texts)
    finally:
        p.unload()


def test_metadata_name():
    cp = ConfigParser()
    cp.read(PACKAGE / "metadata.txt", encoding="utf-8")
    assert cp["general"]["name"] == "Groundwork"


def test_layout_item_names(qgis_app):
    from qgis.core import QgsApplication

    from groundwork_geophysics.plates import items

    items.register_items()
    reg = QgsApplication.layoutItemRegistry()
    names = {reg.itemMetadata(t).visibleName()
             for t in (items.COLOUR_BAR_TYPE, items.BOREHOLE_LEGEND_TYPE)}
    assert names == {"Colour bar (Groundwork)", "Borehole legend (Groundwork)"}


def test_docs_use_new_name():
    files = [REPO / "README.md", *sorted((REPO / "docs" / "user").glob("*.md"))]
    offenders = []
    for path in files:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "Geophysics Workbench" in line and "ormerly" not in line:
                offenders.append(f"{path.name}:{n}")
    assert not offenders, offenders
