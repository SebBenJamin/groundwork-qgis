from pathlib import Path
import numpy as np
from groundwork_geophysics import readers
D = Path("demo/data")

def test_demo_models_read_and_are_plausible():
    for f in ["ert/P1/f001_res.dat", "ert/P2/P2_model.dat", "ert/P3/f001_res.vtk"]:
        r = readers.read(D / f)
        assert 3 < r.mesh.values.min() < 30 and 200 < r.mesh.values.max() < 2000

def test_demo_powerline_is_projected():
    import json
    gj = json.loads(Path("demo/context/powerline.geojson").read_text(encoding="utf-8"))
    x, y = gj["features"][0]["geometry"]["coordinates"][0][:2]
    assert 300_000 < x < 900_000 and 5_200_000 < y < 6_100_000   # UTM 32N, Germany