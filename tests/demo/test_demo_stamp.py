"""The shipped demos' plates carry the stamp (read only: the committed folders are never
written)."""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
DEMOS = (("demo", "demo_project.qgz"), ("demo_guelpe", "guelpe_project.qgz"),
         ("demo_erfurt", "erfurt_project.qgz"))


@pytest.mark.parametrize("folder,project", DEMOS)
def test_demo_plates_have_the_stamp(qgis_app, folder, project):
    from qgis.core import QgsProject
    prj = QgsProject()
    assert prj.read(str(REPO / folder / project))
    layouts = prj.layoutManager().printLayouts()
    for layout in layouts:
        assert layout.itemById("wb_stamp_area") is not None, layout.name()
        assert layout.itemById("wb_stamp_plate") is not None, layout.name()
        assert layout.itemById("wb_title_frame") is None, layout.name()
    prj.clear()
