"""New-profile dialog: station-file order, coordinate checks, numbering from the end,
duplicate-geometry warning. Driven programmatically (offscreen)."""
import numpy as np
import pytest


def _close(dialog, qgis_app):
    dialog.close()
    dialog.deleteLater()
    qgis_app.processEvents()


def test_new_profile_from_unsorted_station_file(qgis_app, fake_iface, project_store,
                                                tmp_path, warnings_shown):
    """Rows recorded from the far end and out of order: the line follows the numbers."""
    from geophysics_workbench.ui.new_profile_dialog import TAB_FILE, NewProfileDialog

    st, prj = project_store
    csv = tmp_path / "unsorted.csv"
    rows = [(3, 110.0), (1, 120.0), (4, 105.0), (2, 115.0), (5, 100.0)]
    csv.write_text("number,x,y,z\n" + "".join(f"{n},{x},0,50\n" for n, x in rows),
                   encoding="utf-8")
    dlg = NewProfileDialog(fake_iface, st, project=prj)
    try:
        dlg.tabs.setCurrentIndex(TAB_FILE)
        dlg.set_station_file(csv)
        dlg.accept()
        assert dlg.result() == 1, warnings_shown
        [p] = st.profiles()
        assert p.chainage.length == pytest.approx(20)                 # straight, no zigzag
        assert np.allclose(p.xy[0], [120, 0]) and np.allclose(p.xy[-1], [100, 0])
        [s] = st.station_sets(p.id)
        assert s.numbers.tolist() == [1, 2, 3, 4, 5] and s.direction == 1
    finally:
        _close(dlg, qgis_app)
