"""The user's "Z means" choice, not the file header, places the rebuilt cells (0.1.1)."""
import shutil
from pathlib import Path

import numpy as np
import pytest

DEMO = Path(__file__).resolve().parent.parent.parent / "demo" / "data" / "ert" / "P2"


def _store_with(tmp_path, src, z_kind):
    from geophysics_workbench.core.model import Dataset, file_fingerprint, profile_from_stations
    from geophysics_workbench.store.gpkg_store import ProjectStore

    st = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    xyz = np.column_stack([np.arange(72) * 5.0, np.zeros(72), 50 + 0.02 * np.arange(72) * 5.0])
    p, s = profile_from_stations("P2", "EPSG:25832", xyz)
    st.save_profile(p)
    st.save_station_set(s)
    mt, sha = file_fingerprint(src)
    st.save_dataset(Dataset("d1", p.id, s.id, "ert_model", str(src), mt, sha, "zondres_xyz",
                            {"z_kind": z_kind}, {}, name="P2 model"))
    return st, p


def test_z_header_file_saved_as_depth_touches_the_surface(tmp_path):
    from geophysics_workbench.section.data import SectionDataProvider

    lines = (DEMO / "P2_model.dat").read_text().splitlines()
    lines[0] = "#X\tZ\tlog_Rho\tRho"                 # the header of the user's real files
    src = tmp_path / "P2_z.dat"
    src.write_text("\n".join(lines) + "\n")
    st, p = _store_with(tmp_path, src, "depth")
    [layer] = SectionDataProvider(st).layers(p.id)
    assert layer.error is None
    v = layer.mesh.vertices
    above = v[:, 1] - np.interp(v[:, 0], *SectionDataProvider(st).topography(p.id))
    assert above.max() == pytest.approx(0.0, abs=1e-9)          # nothing above the surface
    assert int(np.isclose(above, 0.0, atol=1e-9).sum()) == 2 * 142   # every top cell on it


def test_depth_header_file_saved_as_elevation_is_not_snapped(tmp_path):
    from geophysics_workbench.section.data import SectionDataProvider

    src = tmp_path / "P2_model.dat"
    shutil.copy(DEMO / "P2_model.dat", src)
    st, p = _store_with(tmp_path, src, "elevation")
    [layer] = SectionDataProvider(st).layers(p.id)
    _s0, _s1, zmin, zmax = layer.mesh.bounds()
    assert zmin == pytest.approx(0.25 - (0.775 - 0.25) / 2)
    assert zmax == pytest.approx(69.052 + (69.052 - 63.827) / 2)
