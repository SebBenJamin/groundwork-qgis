"""Add ERT model previews what will be drawn for the chosen "Z means" (0.1.1)."""
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parent.parent.parent / "demo" / "data" / "ert" / "P2"
FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "ert"


def _close(dialog, qgis_app):
    dialog.close()
    dialog.deleteLater()
    qgis_app.processEvents()


def test_preview_rereads_with_the_chosen_z(qgis_app, fake_iface, store_with_model, tmp_path,
                                           monkeypatch):
    from qgis.PyQt.QtWidgets import QMessageBox

    from geophysics_workbench.ui.add_model_dialog import AddModelDialog

    # the 355 m model overhangs this 50 m profile: answer the question with Yes
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))

    st, p, _ = store_with_model
    lines = (DEMO / "P2_model.dat").read_text().splitlines()
    lines[0] = "#X\tZ\tlog_Rho\tRho"
    src = tmp_path / "P2_z.dat"
    src.write_text("\n".join(lines) + "\n")
    dlg = AddModelDialog(fake_iface, st, p.id)
    try:
        dlg.set_file(src)
        assert dlg.z_combo.currentData() is None
        assert dlg._result.mesh.bounds()[2] == pytest.approx(-0.0125)
        dlg.z_combo.setCurrentIndex(dlg.z_combo.findData("depth"))
        assert dlg._result.mesh.bounds()[2] == 0.0
        assert "z 0.0 –" in dlg.preview.text() and "(depth)" in dlg.preview.text()
        dlg.z_combo.setCurrentIndex(dlg.z_combo.findData("elevation"))
        assert dlg._result.mesh.bounds()[2] == pytest.approx(-0.0125)
        dlg.z_combo.setCurrentIndex(dlg.z_combo.findData("depth"))
        dlg.accept()
        d = st.datasets(p.id)[-1]
        assert d.reader_options["z_kind"] == "depth" and d.provenance["reconstruction"] == "rows"
    finally:
        _close(dlg, qgis_app)


def test_describe_counts_blank_cells(tmp_path):
    from geophysics_workbench import readers
    from geophysics_workbench.ui.add_model_dialog import describe

    lines = (FIXTURES / "f001_res.dat").read_text().splitlines()
    lines[3] = lines[3].replace(lines[3].split()[2], "-9.99900e+03")
    p = tmp_path / "f002_res.dat"
    p.write_text("\n".join(lines) + "\n")
    text = describe(readers.read(p), "elevation")
    assert text.endswith(" · 1 cell without a value (shown blank)")
    lines[5] = lines[5].replace(lines[5].split()[2], "nan")
    p.write_text("\n".join(lines) + "\n")
    assert describe(readers.read(p), "elevation").endswith(
        " · 2 cells without a value (shown blank)")
