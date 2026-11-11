"""Export of interpretation features' 3D pieces to GeoPackage or DXF."""
import numpy as np
import pytest
from osgeo import ogr

from geophysics_workbench.core.interpretation import (InterpFeature, InterpPiece, new_id,
                                                      normalise)


@pytest.fixture
def two(tmp_path):
    from geophysics_workbench.core.model import profile_from_stations
    from geophysics_workbench.store.gpkg_store import ProjectStore
    st = ProjectStore.create(tmp_path / "wb.gpkg", "EPSG:25832")
    p, s = profile_from_stations("bent", "EPSG:25832",
                                 np.array([[0, 0, 100], [50, 0, 100], [50, 50, 100.0]]))
    st.save_profile(p)
    st.save_station_set(s)
    st.ensure_interpretation()
    v = st.current_version().id
    a = InterpFeature(new_id(), v, type="anomaly", name="A")
    b = InterpFeature(new_id(), v, type="clay", name="B")
    st.save_feature(a)
    st.save_feature(b)
    st.save_piece(normalise(InterpPiece(new_id(), v, a.id, p.id, "polygon",
                                        [(40, 100), (60, 100), (60, 95), (40, 95)])))
    st.save_piece(InterpPiece(new_id(), v, b.id, p.id, "line", [(5, 99), (20, 97)]))
    return st, v, a, b


def test_export_gpkg_one_feature(two, tmp_path):
    from geophysics_workbench.ui.interp_export import export_pieces
    st, v, a, _b = two
    out = tmp_path / "a.gpkg"
    assert export_pieces(st, v, {a.id}, str(out)) == 1
    ds = ogr.Open(str(out))
    assert [ds.GetLayer(i).GetName() for i in range(ds.GetLayerCount())] == ["polygons_3d"]
    feat = ds.GetLayer(0).GetNextFeature()
    assert feat["name"] == "A" and feat["type"] == "anomaly"
    ring = feat.GetGeometryRef().GetGeometryRef(0)
    assert feat.GetGeometryRef().Is3D()
    assert (50.0, 0.0) in {tuple(round(c, 6) for c in pt[:2]) for pt in ring.GetPoints()}
    assert ds.GetLayer(0).GetSpatialRef().GetAuthorityCode(None) == "25832"


def test_export_dxf_keeps_z_for_mixed_kinds(two, tmp_path):
    from geophysics_workbench.ui.interp_export import export_pieces
    st, v, *_ = two
    out = tmp_path / "all.dxf"
    assert export_pieces(st, v, None, str(out)) == 2
    ds = ogr.Open(str(out))
    feats = list(ds.GetLayer(0))
    assert len(feats) == 2
    assert all(f.GetGeometryRef().Is3D() for f in feats)
    assert {f.GetField("Layer") for f in feats} == {"A - anomaly", "B - clay"}
    zs = {round(pt[2], 6) for f in feats for pt in f.GetGeometryRef().GetPoints()}
    assert {95.0, 100.0, 99.0, 97.0} <= zs


def test_export_overwrites_and_rejects_bad_extension(two, tmp_path):
    from geophysics_workbench.ui.interp_export import export_pieces
    st, v, *_ = two
    out = tmp_path / "x.gpkg"
    export_pieces(st, v, None, str(out))
    assert export_pieces(st, v, None, str(out)) == 2
    with pytest.raises(ValueError):
        export_pieces(st, v, None, str(tmp_path / "x.shp"))


def test_dxf_layer_names_are_safe():
    from geophysics_workbench.ui.interp_export import dxf_layer_name
    assert dxf_layer_name(InterpFeature("f", "v", name="C2", type="Ton/Schluff: nass")) ==         "C2 - Ton_Schluff_ nass"
    assert dxf_layer_name(InterpFeature("f", "v", type="Lösslehm")) == "Loesslehm"
    assert dxf_layer_name(InterpFeature("f", "v", type="Kies (é)")) == "Kies (_)"
    assert dxf_layer_name(None) == "unnamed"


def test_export_refuses_the_workbench_geopackage(two):
    from geophysics_workbench.ui.interp_export import export_pieces
    st, v, *_ = two
    with pytest.raises(ValueError):
        export_pieces(st, v, None, str(st.path))
    assert st.pieces(v)                                     # store untouched
