"""The Vaud demo's helpers (scripts/vaud_data.py): which zip member, which DEM tiles, which
pixels lie in the corridor."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))


def test_the_stack_member_is_found_in_any_case():
    import vaud_data
    assert vaud_data.stack_member(["a/VD-P1-stk.TIF", "a/VD-P1_stk-p.sgy", "a/r.pdf"]) \
        == "a/VD-P1_stk-p.sgy"
    assert vaud_data.stack_member(["X_STK-P.SGY"]) == "X_STK-P.SGY"
    assert vaud_data.stack_member(["a.pdf", "b_mig-p.sgy"]) is None


def test_distance_to_lines_is_to_the_nearest_segment():
    import vaud_data
    lines = [np.array([[0.0, 0.0], [100.0, 0.0]]), np.array([[0.0, 50.0], [0.0, 80.0]])]
    d = vaud_data.distance_to_lines(np.array([50.0, 150.0, 3.0]), np.array([10.0, 0.0, 70.0]),
                                    lines)
    assert np.allclose(d, [10.0, 50.0, 3.0])


def test_tiles_near_a_line_are_the_ones_it_passes():
    import vaud_data
    line = np.array([[2_500_100.0, 1_100_500.0], [2_502_900.0, 1_100_500.0]])
    tiles = vaud_data.tiles_near([line], corridor=100.0)
    assert (2500, 1100) in tiles and (2502, 1100) in tiles
    assert all(1099 <= n <= 1101 for _e, n in tiles)
    assert (2500, 1105) not in tiles


def test_newest_tiles_take_the_newest_year_and_the_2_m_file():
    import vaud_data
    asset = "https://x/{0}/{0}_{1}_2056_5728.tif"
    items = [{"id": f"swissalti3d_{y}_2525-1161",
              "assets": {f"swissalti3d_{y}_2525-1161_{g}_2056_5728.tif":
                         {"href": asset.format(f"swissalti3d_{y}_2525-1161", g)}
                         for g in ("0.5", "2")}} for y in (2019, 2023)]
    items.append({"id": "something_else", "assets": {}})
    assert vaud_data.newest_tiles(items) == {
        (2525, 1161): asset.format("swissalti3d_2023_2525-1161", "2")}


def test_outside_corridor_masks_far_pixels():
    import vaud_data
    gt = (0.0, 10.0, 0.0, 100.0, 0.0, -10.0)            # 10 x 10 pixels, 0..100 m
    line = np.array([[0.0, 50.0], [100.0, 50.0]])
    out = vaud_data.outside_corridor(gt, (10, 10), [line], corridor=20.0)
    assert not out[3:7].any() and out[:2].all() and out[8:].all()


def test_the_velocity_function_is_the_median_of_the_sheets_columns():
    import vaud_data
    o = vaud_data.OPTIONS
    assert (o["zero"], o["datum"]) == ("datum", 500.0) and "replacement_velocity" not in o
    assert vaud_data.REPLACEMENT_VELOCITY == 4000.0      # on the sheet, not applied
    assert o["velocity_kind"] == "average" and "velocity" not in o
    times = [t for t, _v in o["velocity_table"]]
    speeds = [v for _t, v in o["velocity_table"]]
    assert times == [round(0.2 * k, 1) for k in range(1, 20)]          # 0.2 to 3.8 s
    assert all(b > a for a, b in zip(speeds, speeds[1:]))              # grows with time
    for (t, v), row in zip(o["velocity_table"], vaud_data.SHEET_AVERAGE_VELOCITIES):
        assert row[0] == round(t * 1000) and v == float(np.median(row[1:]))
