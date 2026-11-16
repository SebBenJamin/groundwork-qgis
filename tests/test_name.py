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
        if "Geophysics Workbench" in path.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(path.relative_to(REPO).as_posix())
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
