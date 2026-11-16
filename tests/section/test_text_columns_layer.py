"""A free-text dataset whose file lost a column shows as a layer error, not a traceback."""
import shutil
from pathlib import Path

import numpy as np

from groundwork_geophysics.core.model import Dataset, file_fingerprint
from groundwork_geophysics.core.roles import ModelColumns
from groundwork_geophysics.readers.texttable import TableOptions
from groundwork_geophysics.section.data import SectionDataProvider

WILD = Path(__file__).resolve().parent.parent / "fixtures" / "wild"


def test_reread_with_missing_column_is_a_layer_error(store_with_model, tmp_path):
    st, p, _ = store_with_model
    [station_set] = st.station_sets(p.id)
    src = tmp_path / "x_zero_depth_rho.txt"
    shutil.copy(WILD / "x_zero_depth_rho.txt", src)
    mt, sha = file_fingerprint(src)
    st.save_dataset(Dataset(
        "d2", p.id, station_set.id, "ert_model", str(src), mt, sha, "text_columns",
        {"table": TableOptions(header=False).to_dict(),
         "columns": ModelColumns(distance=0, vertical=2, vertical_kind="depth",
                                 value=3).to_dict(),
         "z_kind": "depth"}, {}, name="P1 text"))
    provider = SectionDataProvider(st)
    assert {la.dataset.id: la.error for la in provider.layers(p.id)} == {"d1": None, "d2": None}

    np.savetxt(src, np.loadtxt(WILD / "x_zero_depth_rho.txt")[:, :3], fmt="%.6g")
    layers = {la.dataset.id: la for la in provider.layers(p.id)}
    assert layers["d2"].mesh is None and "column 4" in layers["d2"].error
    assert layers["d1"].mesh is not None and layers["d1"].error is None
