"""Calhoun refraction demo data (scripts/calhoun_data.py): pure functions, synthetic inputs;
the check against the real cache is skipped without it."""
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
CACHE = REPO / ".cache" / "calhoun"


def _pieces_file(tmp_path) -> Path:
    """Two pieces as in allBR.txt: E N depth br_lin br_quad dist br_mean br_std."""
    rows = []
    for k, (x0, y0) in enumerate(((0.0, 0.0), (1000.0, 0.0))):
        for i in range(5):
            d = 5.0 + 10.0 * i
            surface = 150.0 + 0.5 * i + 3 * k
            rows.append([x0 + d, y0, 10.0, surface - 10.0, surface - 10.0, d, surface - 10.0, 0.1])
    p = tmp_path / "allBR.txt"
    np.savetxt(p, rows, fmt="%.4f")
    return p


def test_read_pieces_splits_on_distance_reset(tmp_path):
    import calhoun_data
    pieces = calhoun_data.read_pieces(_pieces_file(tmp_path))
    assert len(pieces) == 2 and all(len(p) == 5 for p in pieces)
    assert pieces[1][0, 0] == pytest.approx(1005.0)


def test_match_piece_finds_shifted_copy(tmp_path):
    import calhoun_data
    pieces = calhoun_data.read_pieces(_pieces_file(tmp_path))
    surface = pieces[1][:, 6] + pieces[1][:, 2]
    x_h = np.arange(0.0, 70.0, 1.0)
    z = np.interp(x_h - 7.0, pieces[1][:, 5], surface)      # the line starts 7 m earlier
    line = calhoun_data.LineData(np.zeros((0, 3)), x_h, z, x_h.copy())
    k, offset, rms = calhoun_data.match_piece(line, pieces)
    assert k == 1 and offset == pytest.approx(7.0) and rms < 0.01


def test_stations_follow_the_piece():
    import calhoun_data
    piece = np.array([[0.0, 0.0, 0, 0, 0, 0.0, 0, 0], [10.0, 0.0, 0, 0, 0, 10.0, 0, 0]])
    picks = np.array([[0.0, 5.0, 0.01], [0.0, 15.0, 0.02], [15.0, 5.0, 0.01]])
    x = np.array([0.0, 5.0, 10.0, 15.0])
    line = calhoun_data.LineData(picks, x, np.full(4, 100.0), x.copy())
    xyz, numbers, inline = calhoun_data.stations_xy(line, piece, 0.0)
    assert numbers.tolist() == [1, 2]                       # the geophones at 5 and 15 m
    assert xyz[:, :2] == pytest.approx(np.array([[5.0, 0.0], [15.0, 0.0]]))
    assert inline == pytest.approx([5.0, 15.0]) and xyz[:, 2] == pytest.approx([100.0, 100.0])


def test_read_line_drops_zero_offset_and_bad_times(tmp_path):
    import calhoun_data
    picks = tmp_path / "p.txt"
    picks.write_text("0 0 0\n0 1 0.004\n0 2 -1\n1 0 0.004\n")
    elev = tmp_path / "e.txt"
    elev.write_text("0.00 100.0 0.00\n0.99 100.1 1.00\n1.98 100.2 2.00\n")
    line = calhoun_data.read_line(picks, elev)
    assert line.picks.tolist() == [[0.0, 1.0, 0.004], [1.0, 0.0, 0.004]]
    assert line.x_h.tolist() == [0.0, 0.99, 1.98] and line.x_nom.tolist() == [0.0, 1.0, 2.0]


def test_write_sgt_header_and_indices(tmp_path):
    import calhoun_data
    x = np.array([0.0, 1.0, 2.0])
    line = calhoun_data.LineData(np.array([[0.0, 1.0, 0.004], [0.0, 2.0, 0.008]]),
                                 x * 0.99, np.array([100.0, 100.1, 100.2]), x)
    out = tmp_path / "L.sgt"
    calhoun_data.write_sgt(out, line)
    lines = out.read_text().splitlines()
    assert lines[0].split()[0] == "3" and lines[1] == "#x y"
    assert lines[2].split() == ["0.00", "100.00"] and lines[3].split()[0] == "0.99"
    assert lines[5].split()[0] == "2" and lines[5].endswith("# measurements")
    assert lines[6] == "#s g t"
    assert lines[7].split()[:2] == ["1", "2"] and lines[8].split()[:2] == ["1", "3"]


def test_the_dem_moves_a_line_its_map_points_place_wrongly():
    """The authors' map points of a line can sit metres off along it while its elevations are
    LiDAR at the true places: the DEM finds the offset that puts them back."""
    import calhoun_data
    piece = np.array([[e, 0.0, 0, 0, 0, e, 0, 0] for e in np.arange(0.0, 400.0, 10.0)])

    def dem_at(e, n):                               # hills along the east axis
        return 150.0 + 5.0 * np.sin(np.asarray(e, float) / 30.0)
    x_h = np.arange(0.0, 300.0, 1.0)
    line = calhoun_data.LineData(np.zeros((0, 3)), x_h, dem_at(x_h + 23.0, 0.0), x_h.copy())
    offset, rms = calhoun_data.refine_offset(line, piece, 0.0, dem_at)
    assert offset == pytest.approx(-23.0) and rms < 0.05
    xyz, _n, _i = calhoun_data.stations_xy(
        calhoun_data.LineData(np.array([[0.0, 100.0, 0.1]]), x_h, line.z, x_h), piece, offset)
    assert xyz[0, 0] == pytest.approx(123.0)        # geophone at 100 m stands at E 123


@pytest.mark.skipif(not (CACHE / "dem_3dep.tif").exists(), reason="no Calhoun cache")
def test_cached_lines_fit_the_dem_after_refining():
    """Line 6's map points in allBR.txt sit ~23 m off along it; the others within 3 m."""
    import calhoun_data
    from osgeo import gdal
    ds = gdal.Open(str(CACHE / "dem_3dep.tif"))
    dem_at = calhoun_data.raster_sampler(ds.GetGeoTransform(),
                                         ds.GetRasterBand(1).ReadAsArray().astype(float))
    pieces = calhoun_data.read_pieces(CACHE / "allBR.txt")
    shifts = {}
    for name in calhoun_data.LINES:
        line = calhoun_data.read_line(*calhoun_data.line_files(CACHE, name))
        k, off, _rms = calhoun_data.match_piece(line, pieces)
        refined, rms = calhoun_data.refine_offset(line, pieces[k], off, dem_at)
        assert rms <= calhoun_data.MAX_DEM_RMS, (name, rms)
        shifts[name] = refined - off
    assert shifts["L6"] == pytest.approx(-23.0, abs=1.5)
    assert all(abs(v) <= 3.0 for k, v in shifts.items() if k != "L6"), shifts


@pytest.mark.skipif(not (CACHE / "allBR.txt").exists(), reason="no Calhoun cache")
def test_cached_matches():
    import calhoun_data
    pieces = calhoun_data.read_pieces(CACHE / "allBR.txt")
    for name, (piece, _offset) in calhoun_data.EXPECTED.items():
        line = calhoun_data.read_line(*calhoun_data.line_files(CACHE, name))
        k, _off, rms = calhoun_data.match_piece(line, pieces)
        assert k == piece and rms <= calhoun_data.MAX_RMS, (name, k, rms)


def test_write_sgt_merges_points_that_coincide(tmp_path):
    """A shot beyond the elevation file's end lands on the last geophone (as the authors'
    script snaps it): one sensor, and the pick from that shot to that geophone is dropped."""
    import calhoun_data
    x = np.array([0.0, 1.0, 2.0])
    picks = np.array([[0.0, 2.0, 0.008], [3.0, 2.0, 0.004], [3.0, 0.0, 0.010]])
    line = calhoun_data.LineData(picks, x, np.array([100.0, 100.1, 100.2]), x)
    out = tmp_path / "L.sgt"
    n = calhoun_data.write_sgt(out, line)
    lines = out.read_text().splitlines()
    assert lines[0].split()[0] == "2"                       # 0 and 2 (3 is clamped onto 2)
    assert n == 2 and lines[-2:] == ["1 2 0.008000", "2 1 0.010000"]


def test_thinned_keeps_every_nth_geophone_and_all_shots():
    import calhoun_data
    picks = np.array([[0.0, 1.0, 0.004], [0.0, 2.0, 0.006], [5.0, 4.0, 0.003],
                      [5.0, 3.0, 0.005]])
    x = np.arange(0.0, 6.0)
    line = calhoun_data.LineData(picks, x, np.full(6, 100.0), x)
    thin = calhoun_data.thinned(line, 2)
    assert thin.picks[:, 1].tolist() == [2.0, 4.0] and set(thin.picks[:, 0]) == {0.0, 5.0}
    assert calhoun_data.thinned(line, 1).picks.shape == picks.shape


def test_stations_merge_geophones_beyond_the_elevation_file():
    import calhoun_data
    piece = np.array([[0.0, 0.0, 0, 0, 0, 0.0, 0, 0], [10.0, 0.0, 0, 0, 0, 10.0, 0, 0]])
    picks = np.array([[0.0, 1.0, 0.01], [0.0, 2.0, 0.02], [0.0, 3.0, 0.03]])
    x = np.array([0.0, 1.0, 2.0])                  # the file ends at 2 m: 3 m lands on it
    line = calhoun_data.LineData(picks, x, np.full(3, 100.0), x)
    _xyz, numbers, inline = calhoun_data.stations_xy(line, piece, 0.0)
    assert numbers.tolist() == [1, 2] and inline == pytest.approx([1.0, 2.0])
