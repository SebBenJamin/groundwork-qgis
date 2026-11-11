"""Interpretation drawn on the section with its layer style."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _snapshot_results(pieces, features, symbols):
    from test_context_render import _results

    res = _results(None)
    res.snapshot.interpretation = pieces
    res.snapshot.interp_features = features
    res.snapshot.interp_symbols = symbols
    return res


def _poly_symbol(rgb):
    from qgis.core import QgsFillSymbol
    return QgsFillSymbol.createSimple({"color": ",".join(map(str, rgb)) + ",255",
                                       "outline_color": "0,0,0", "outline_width": "0.3"})


def test_polygon_piece_drawn_on_section(qgis_app):
    from test_context_render import _close, _img, _x, _y

    from geophysics_workbench.core.interpretation import InterpFeature, InterpPiece, normalise

    p = normalise(InterpPiece("p1", "v", "f1", "prof", "polygon",
                              [(50, 0.5), (70, 0.5), (70, -2), (50, -2)]))
    res = _snapshot_results([p], {"f1": InterpFeature("f1", "v", name="")},
                            {"p1": _poly_symbol((0, 200, 0))})
    img = _img(res)
    assert _close(img.pixel(_x(60), _y(-1)), (0, 200, 0), tol=25)
    assert not _close(img.pixel(_x(45), _y(-1)), (0, 200, 0), tol=25)


def test_letter_label_drawn(qgis_app):
    from qgis.PyQt.QtGui import QColor
    from test_context_render import _img, _x, _y

    from geophysics_workbench.core.interpretation import InterpFeature, InterpPiece

    p = InterpPiece("p1", "v", "f1", "prof", "point", [(60, -1)])
    from qgis.core import QgsMarkerSymbol
    sym = QgsMarkerSymbol.createSimple({"name": "circle", "color": "0,0,255", "size": "0.1"})
    res = _snapshot_results([p], {"f1": InterpFeature("f1", "v", name="A")}, {"p1": sym})
    img = _img(res)
    dark = 0
    for x in range(_x(60) - 25, _x(60) + 25):
        for y in range(_y(-1) - 25, _y(-1) + 25):
            c = QColor(img.pixel(x, y))
            if c.blue() > 150 and c.red() < 90 and c.green() < 90:
                dark += 1
    assert dark > 8


def test_frozen_version_shown_when_selected(qgis_app, store_with_model):
    from geophysics_workbench.core.interpretation import InterpFeature, InterpPiece, new_id
    from geophysics_workbench.section.data import SectionDataProvider

    store = store_with_model[0]
    pid = store.profiles()[0].id
    store.ensure_interpretation()
    v = store.current_version()
    f = InterpFeature(new_id(), v.id, name="OLD")
    store.save_feature(f)
    store.save_piece(InterpPiece(new_id(), v.id, f.id, pid, "line", [(1, 0), (5, -1)]))
    frozen = store.freeze_current("R1")
    [cur_piece] = store.pieces(v.id)
    store.delete_piece(cur_piece.id)
    prov = SectionDataProvider(store)
    assert prov.snapshot(pid).interpretation == []
    prov.interp_version_id = frozen.id
    snap = prov.snapshot(pid)
    assert len(snap.interpretation) == 1
    assert snap.interp_features[snap.interpretation[0].feature_id].name == "OLD"


def test_letter_opaque_on_translucent_fill(qgis_app):
    from qgis.core import QgsFillSymbol
    from qgis.PyQt.QtGui import QColor
    from test_context_render import _img, _x, _y

    from geophysics_workbench.core.interpretation import InterpFeature, InterpPiece, normalise

    p = normalise(InterpPiece("p1", "v", "f1", "prof", "polygon",
                              [(50, 0.5), (70, 0.5), (70, -2.5), (50, -2.5)]))
    sym = QgsFillSymbol.createSimple({"color": "0,0,255,20", "outline_style": "no"})
    img = _img(_snapshot_results([p], {"f1": InterpFeature("f1", "v", name="W")}, {"p1": sym}))
    strong = sum(1 for x in range(_x(60) - 5, _x(60) + 30) for y in range(_y(-1) - 30, _y(-1) + 5)
                 if QColor(img.pixel(x, y)).blue() > 200 and QColor(img.pixel(x, y)).red() < 60)
    assert strong > 5


def test_crossing_marks_drawn_at_tie_strip(qgis_app):
    from test_context_render import _close, _img, _x, _y

    from geophysics_workbench.core.interp_cross import CrossMark
    from geophysics_workbench.core.interpretation import InterpFeature

    res = _snapshot_results([], {"f1": InterpFeature("f1", "v", name="A")},
                            {"p9": _poly_symbol((0, 200, 0))})
    res.snapshot.interp_crossings = [(60.0, [CrossMark("f1", "polygon", 0.0, -3.0, "p9")])]
    img = _img(res)
    from qgis.PyQt.QtGui import QColor

    def greenish(x, y):                  # the bar is translucent over the strip
        c = QColor(img.pixel(x, y))
        return c.green() > c.red() + 50 and c.green() > c.blue() + 50
    assert greenish(_x(60) + 3, _y(-1.5))
    assert not greenish(_x(40), _y(-1.5))


def test_snapshot_has_crossing_marks_mirrored(qgis_app, store_with_model):
    from geophysics_workbench.core.interpretation import InterpFeature, InterpPiece, new_id
    from geophysics_workbench.core.model import profile_from_stations
    from geophysics_workbench.section.data import SectionDataProvider

    store, p1, _ = store_with_model
    p2, s2 = profile_from_stations("P2", "EPSG:25832",
                                   np.array([[20, -20, 100], [20, 20, 100.0]]))
    store.save_profile(p2)
    store.save_station_set(s2)
    store.ensure_interpretation()
    v = store.current_version().id
    f = InterpFeature(new_id(), v, name="A")
    store.save_feature(f)
    store.save_piece(InterpPiece(new_id(), v, f.id, p2.id, "polygon",
                                 [(15, 100), (25, 100), (25, 95), (15, 95), (15, 100)]))
    prov = SectionDataProvider(store)
    snap = prov.snapshot(p1.id)
    assert snap.interpretation == []                 # P1 has no pieces of its own
    (s, marks), = snap.interp_crossings
    assert s == pytest.approx(20.0) and marks[0].feature_id == f.id
    assert (marks[0].z_top, marks[0].z_bottom) == pytest.approx((100.0, 95.0))
    assert marks[0].piece_id in snap.interp_symbols and f.id in snap.interp_features
    length = p1.chainage.length
    (s_rev, _m), = prov.snapshot(p1.id, reverse=True).interp_crossings
    assert s_rev == pytest.approx(length - 20.0)


def test_compare_pieces_drawn_faint(qgis_app):
    from qgis.PyQt.QtGui import QColor
    from test_context_render import _img, _x, _y

    from geophysics_workbench.core.interpretation import InterpPiece, normalise

    old = normalise(InterpPiece("old", "r1", "f1", "prof", "polygon",
                                [(50, 0.5), (70, 0.5), (70, -2), (50, -2)]))
    res = _snapshot_results([], {}, {"old": _poly_symbol((0, 0, 200))})
    res.snapshot.interp_compare = [old]
    c = QColor(_img(res).pixel(_x(60), _y(-1)))
    assert c.blue() > c.red() + 40 and c.red() > 100           # blue, but faint
