import re
import shutil
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
DEMOS = [("demo", "demo_project.qgz", "demo_groundwork.gpkg", "demo_workbench.gpkg"),
         ("demo_guelpe", "guelpe_project.qgz", "guelpe_groundwork.gpkg", "guelpe_workbench.gpkg"),
         ("demo_erfurt", "erfurt_project.qgz", "erfurt_groundwork.gpkg", "erfurt_workbench.gpkg"),
         ("demo_calhoun", "calhoun_project.qgz", "calhoun_groundwork.gpkg",
          "calhoun_workbench.gpkg"),
         ("demo_vaud", "vaud_project.qgz", "vaud_groundwork.gpkg", "vaud_workbench.gpkg")]


def _qgs_text(qgz):
    with zipfile.ZipFile(qgz) as z:
        name = next(n for n in z.namelist() if n.endswith(".qgs"))
        return z.read(name).decode("utf-8")


@pytest.mark.parametrize("folder,project,store,old", DEMOS)
def test_store_file_has_the_new_name(folder, project, store, old):
    assert (REPO / folder / store).is_file()
    assert not (REPO / folder / old).exists()


@pytest.mark.parametrize("folder,project,store,old", DEMOS)
def test_project_text_uses_the_new_names(folder, project, store, old):
    text = _qgs_text(REPO / folder / project)
    assert "_workbench.gpkg" not in text
    assert "Geophysics Workbench" not in text
    assert re.search(r'<layer-tree-group[^>]*name="Groundwork"', text)
    assert "geophysics_workbench" in text            # hidden properties scope stays


@pytest.mark.parametrize("folder,project,store,old", DEMOS)
def test_project_finds_the_renamed_store(qgis_app, tmp_path, folder, project, store, old):
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.project_actions import attach_store
    copy = tmp_path / folder
    shutil.copytree(REPO / folder, copy)
    prj = QgsProject()
    assert prj.read(str(copy / project))
    st = attach_store(prj)
    assert st.path.resolve() == (copy / store).resolve()
