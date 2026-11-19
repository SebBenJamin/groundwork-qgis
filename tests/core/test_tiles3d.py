"""Section pictures as 3D Tiles: the binary glTF of a textured strip, the tileset placing it on
the earth, and the strip's columns from a picture's painted texels."""
import json
import struct

import numpy as np
import pytest

from groundwork_geophysics.core.chainage import Chainage

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 20      # contents do not matter to the container


def _chunks(data: bytes):
    magic, version, total = struct.unpack_from("<III", data, 0)
    jlen, jtype = struct.unpack_from("<II", data, 12)
    doc = json.loads(data[20:20 + jlen])
    blen, btype = struct.unpack_from("<II", data, 20 + jlen)
    return magic, version, total, jtype, doc, blen, btype


def _piece(n_cols=3):
    pos = np.array([[i, 0.0, z] for i in range(n_cols) for z in (0.0, 1.0)], np.float32)
    uv = np.array([[i / (n_cols - 1), v] for i in range(n_cols) for v in (1.0, 0.0)], np.float32)
    tris = np.array([t for i in range(n_cols - 1)
                     for t in ((2 * i, 2 * i + 2, 2 * i + 3), (2 * i, 2 * i + 3, 2 * i + 1))])
    return pos, uv, tris, PNG


def test_the_glb_is_a_valid_container_with_a_texture_per_piece():
    from groundwork_geophysics.core.tiles3d import glb
    data = glb([_piece(3), _piece(4)])
    magic, version, total, jtype, doc, blen, btype = _chunks(data)
    assert (magic, version, total) == (0x46546C67, 2, len(data))
    assert (jtype, btype) == (0x4E4F534A, 0x004E4942)
    assert len(doc["meshes"][0]["primitives"]) == 2 and len(doc["images"]) == 2
    assert doc["buffers"][0]["byteLength"] == blen
    for view in doc["bufferViews"]:
        assert view["byteOffset"] + view["byteLength"] <= blen
    pos = doc["accessors"][doc["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
    assert pos["count"] == 6 and pos["max"] == [2.0, 0.0, 1.0]


def test_every_triangle_is_also_there_reversed_so_both_sides_show():
    from groundwork_geophysics.core.tiles3d import glb
    _p, _uv, tris, _png = _piece(3)
    doc = _chunks(glb([_piece(3)]))[4]
    indices = doc["accessors"][doc["meshes"][0]["primitives"][0]["indices"]]
    assert indices["count"] == 2 * tris.size
    material = doc["materials"][0]
    assert material["doubleSided"] and material["alphaMode"] == "BLEND"


def test_the_east_north_up_frame_is_orthonormal_and_up_points_away_from_the_centre():
    from groundwork_geophysics.core.tiles3d import enu_axes
    origin = np.array([3_900_000.0, 760_000.0, 4_950_000.0])        # central Germany
    e, n, u = enu_axes(origin)
    for a, b in ((e, n), (n, u), (e, u)):
        assert abs(float(a @ b)) < 1e-12
    assert all(abs(np.linalg.norm(v) - 1) < 1e-12 for v in (e, n, u))
    assert float(u @ origin / np.linalg.norm(origin)) > 0.99
    assert n[2] > 0                                                  # north is up the globe


def test_the_tileset_places_the_glb_with_its_frame():
    from groundwork_geophysics.core.tiles3d import tileset
    e, n, u, o = (np.array(v, float) for v in ((1, 0, 0), (0, 1, 0), (0, 0, 1), (5, 6, 7)))
    ts = tileset("m.glb", e, n, u, o, np.array([1.0, 2.0, 3.0]), np.array([4.0, 5.0, 6.0]))
    root = ts["root"]
    assert ts["asset"]["version"] == "1.1" and root["content"]["uri"] == "m.glb"
    assert root["transform"][12:15] == [5.0, 6.0, 7.0] and root["transform"][15] == 1.0
    assert root["boundingVolume"]["box"] == [1, 2, 3, 4, 0, 0, 0, 5, 0, 0, 0, 6]


def test_the_strip_covers_the_painted_texels_column_by_column():
    from groundwork_geophysics.core.view3d import picture_strip
    alpha = np.zeros((100, 200), np.uint8)
    alpha[20:61, :] = 255                       # painted between rows 20 and 60
    alpha[0:40, 150:] = 255                     # higher on the right
    sz, tris = picture_strip(alpha, 0.0, 20.0, 40.0, 50.0, [], step=0.5)
    assert len(tris) == 2 * (len(sz) // 2 - 1)
    left = sz[(sz[:, 0] < 5.0)]
    assert left[:, 1].max() == pytest.approx(50.0 - 19 / 100 * 10, abs=0.2)   # top, one row up
    assert left[:, 1].min() == pytest.approx(50.0 - 62 / 100 * 10, abs=0.2)
    right = sz[sz[:, 0] > 17.0]
    assert right[:, 1].max() == pytest.approx(50.0, abs=0.2)
    assert (sz[:, 2] >= 0).all() and (sz[:, 2] <= 1).all()                     # u
    assert sz[:, 3] == pytest.approx((50.0 - sz[:, 1]) / 10.0)                 # v from the top


def test_the_strip_has_a_column_at_each_bend_and_at_most_the_column_limit():
    from groundwork_geophysics.core.view3d import picture_strip
    alpha = np.full((10, 100), 255, np.uint8)
    sz, _ = picture_strip(alpha, 0.0, 1000.0, 0.0, 10.0, [123.4], step=0.5, max_columns=50)
    s = np.unique(sz[:, 0])
    assert 123.4 in s and len(s) <= 51


def test_bends_are_the_real_corners_not_electrode_jitter():
    from groundwork_geophysics.core.view3d import bend_chainages
    corner = Chainage(np.array([[0.0, 0.0], [30.0, 0.0], [30.0, 30.0]]))
    assert bend_chainages(corner) == pytest.approx([30.0])
    x = np.linspace(0, 50, 101)
    jitter = Chainage(np.column_stack([x, 0.02 * np.sin(x * 7)]))
    assert bend_chainages(jitter) == []
