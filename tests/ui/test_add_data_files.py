"""Add Data with several files: the first file's settings for all, each file on the profile its
name points to (changeable), map files without one on a profile of their own."""
from pathlib import Path

import numpy as np
import pytest

WILD = Path(__file__).resolve().parent.parent / "fixtures" / "wild"


@pytest.fixture(autouse=True)
def no_remembered_import(qgis_app):
    from qgis.core import QgsSettings

    from groundwork_geophysics.ui.add_data_dialog import SETTINGS_KEY
    QgsSettings().remove(SETTINGS_KEY)
    yield
    QgsSettings().remove(SETTINGS_KEY)


@pytest.fixture
def make_dialog(qgis_app, fake_iface):
    from groundwork_geophysics.ui.add_data_dialog import AddDataDialog
    made = []

    def make(store, project):
        dlg = AddDataDialog(fake_iface, store, None, project=project)
        dlg.show()
        qgis_app.processEvents()
        made.append(dlg)
        return dlg

    yield make
    for dlg in made:
        dlg.close()
        dlg.deleteLater()
    qgis_app.processEvents()


@pytest.fixture
def answers(monkeypatch):
    """QMessageBox.question answered with ``state["button"]``; the questions are recorded."""
    from qgis.PyQt.QtWidgets import QMessageBox
    state = {"button": QMessageBox.StandardButton.Yes, "asked": []}

    def question(parent, title, text, *args, **kwargs):
        state["asked"].append(text)
        return state["button"]

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    return state


def _map_files(tmp_path, names, shift=30.0):
    """Copies of the wild map file, each moved ``shift`` m further north."""
    text = (WILD / "east_north_depth_rho.csv").read_text().splitlines()
    paths = []
    for i, name in enumerate(names):
        rows = [text[0]]
        for line in text[1:]:
            e, n, rest = line.split(",", 2)
            rows.append(f"{e},{float(n) + i * shift:.2f},{rest}")
        path = tmp_path / name
        path.write_text("\n".join(rows) + "\n")
        paths.append(str(path))
    return paths


def _line_of(path):
    rows = np.loadtxt(path, delimiter=",", skiprows=1)
    return np.array([rows[0, :2], rows[-1, :2]])


def test_several_map_files_go_to_their_profiles_or_new_ones(qgis_app, make_dialog,
                                                             project_store, tmp_path,
                                                             warnings_shown):
    from groundwork_geophysics.core.model import profile_from_polyline
    st, prj = project_store
    paths = _map_files(tmp_path, ["JWD_L8_DD.csv", "JWD_L9_DD.csv"])
    line8 = profile_from_polyline("Line 8", st.crs_authid, _line_of(paths[0]))
    st.save_profile(line8)
    dlg = make_dialog(st, prj)
    dlg.set_files(paths)
    assert dlg.files_box.isVisible() and not dlg.placement.isVisible()
    assert dlg.files_box.targets() == [(paths[0], line8.id), (paths[1], dlg.files_box.NEW)]
    assert dlg.files_box.status(0) == dlg.files_box.status(1) == "Ready"
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    names = sorted(p.name for p in st.profiles())
    assert names == ["JWD_L9_DD", "Line 8"]
    [d8] = st.datasets(line8.id)
    assert d8.name == "JWD_L8_DD" and d8.reader_options["columns"]["position"] == "map"
    [new] = [p for p in st.profiles() if p.name == "JWD_L9_DD"]
    assert len(st.datasets(new.id)) == 1 and dlg.created


def test_a_distance_file_needs_a_profile_chosen(qgis_app, make_dialog, project_store,
                                                tmp_path, answers, warnings_shown):
    from groundwork_geophysics.core.model import profile_from_polyline
    st, prj = project_store
    p = profile_from_polyline("Line 3", st.crs_authid, np.array([[0.0, 0.0], [100.0, 0.0]]))
    st.save_profile(p)
    a, b = tmp_path / "L3_model.txt", tmp_path / "other_model.txt"
    for path in (a, b):
        path.write_bytes((WILD / "dist_y_rho_junk.txt").read_bytes())
    dlg = make_dialog(st, prj)
    dlg.set_files([str(a), str(b)])
    assert dlg.files_box.targets() == [(str(a), p.id), (str(b), None)]
    assert "Choose a profile" in dlg.files_box.status(1)
    answers["button"] = answers["button"].No                 # not without the second file
    dlg.accept()
    assert dlg.result() == 0 and st.datasets(p.id) == []
    assert "1 of 2 files" in answers["asked"][0] and "other_model.txt" in answers["asked"][0]
    dlg.files_box.set_target(1, p.id)
    assert dlg.files_box.status(1) == "Ready"
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    assert sorted(d.name for d in st.datasets(p.id)) == ["L3_model", "other_model"]
    assert all(d.reader_options["table"]["skip"] == 2 for d in st.datasets(p.id))


def test_a_file_with_other_columns_is_left_out_after_asking(qgis_app, make_dialog,
                                                            project_store, tmp_path, answers,
                                                            warnings_shown):
    st, prj = project_store
    good = _map_files(tmp_path, ["A_1.csv"])[0]
    odd = tmp_path / "B_2.csv"
    odd.write_text("x,y,z,resistivity\n" + "\n".join(
        Path(good).read_text().splitlines()[1:]) + "\n")
    dlg = make_dialog(st, prj)
    dlg.set_files([good, str(odd)])
    assert "other columns" in dlg.files_box.status(1).lower()
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    assert [p.name for p in st.profiles()] == ["A_1"]
    assert "B_2.csv" in dlg.last_warning and "left out" in dlg.last_warning.lower()


def test_one_file_chosen_is_the_single_file_dialog(qgis_app, make_dialog, project_store,
                                                   tmp_path):
    st, prj = project_store
    [path] = _map_files(tmp_path, ["only.csv"])
    dlg = make_dialog(st, prj)
    dlg.set_files([path])
    assert not dlg.files_box.isVisible() and dlg.placement.isVisible()
    assert dlg.file_edit.text() == path


def test_files_without_a_cells_choice_show_no_box(qgis_app, tmp_path):
    """A row with nothing to offer (a radargram, a SEG-Y file, a fine-enough model) shows no
    check box, also after the table has laid out its cell widgets."""
    from qgis.PyQt.QtWidgets import QCheckBox

    from groundwork_geophysics.ui.add_data_files import FilesBox
    box = FilesBox()
    box.resize(700, 300)
    box.show()
    box.set_files([str(tmp_path / "a.DZT"), str(tmp_path / "b.DZT")], [("p1", "Line 1")],
                  False)
    qgis_app.processEvents()
    for row in range(2):
        box.set_cells(row, "")
    box.table.resize(690, 250)                             # lays the cell widgets out again
    box.table.viewport().update()
    qgis_app.processEvents()
    shown = [c for c in box.table.findChildren(QCheckBox) if c.isVisible()]
    assert shown == [] and box.cells_text(0) == "" and not box.cells_checked(1)
    box.set_cells(1, "0.5 × 0.2 m")                         # an offer still shows, ticked
    qgis_app.processEvents()
    assert box.cells_text(1) == "0.5 × 0.2 m" and box.cells_checked(1)
    assert [c.text() for c in box.table.findChildren(QCheckBox) if c.isVisible()] \
        == ["0.5 × 0.2 m"]
    box.close()
    box.deleteLater()


def _fine_export(path, nx=404, nz=250):
    x, z = np.meshgrid(np.arange(nx) * 0.25, np.arange(nz) * 0.1 + 0.05)
    rho = 10 ** (1 + x / 100)
    lines = [f"{a:.2f} {b:.2f} {c:.3f}" for a, b, c in zip(x.ravel(), z.ravel(), rho.ravel())]
    path.write_text("distance depth rho\n" + "\n".join(lines) + "\n")
    return str(path)


def test_over_fine_files_offer_coarser_cells_each(qgis_app, make_dialog, project_store,
                                                  tmp_path, warnings_shown):
    from groundwork_geophysics.core.model import profile_from_polyline
    st, prj = project_store
    p = profile_from_polyline("Line 1", st.crs_authid, np.array([[0.0, 0.0], [101.0, 0.0]]))
    st.save_profile(p)
    fine = _fine_export(tmp_path / "L1_fine.txt")
    small = tmp_path / "L1_small.txt"
    small.write_text("distance depth rho\n" + "\n".join(
        Path(fine).read_text().splitlines()[1:2001]) + "\n")
    dlg = make_dialog(st, prj)
    dlg.set_files([fine, str(small)])
    assert dlg.coarse_row.isHidden()                         # offered per file instead
    assert "0.5 × 0.2 m" in dlg.files_box.cells_text(0) and dlg.files_box.cells_checked(0)
    assert dlg.files_box.cells_text(1) == ""                 # not over-fine: no offer
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    by_name = {d.name: d for d in st.datasets(p.id)}
    assert by_name["L1_fine"].reader_options["block"] == [2, 2]
    assert "block" not in by_name["L1_small"].reader_options
