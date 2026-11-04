"""Interpretation drawn on the section with its layer style."""
import sys
from pathlib import Path

import numpy as np

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
    res = _snapshot_results([p], {"f1": InterpFeature("f1", "v", letter="")},
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
    res = _snapshot_results([p], {"f1": InterpFeature("f1", "v", letter="A")}, {"p1": sym})
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
    f = InterpFeature(new_id(), v.id, letter="OLD")
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
    assert snap.interp_features[snap.interpretation[0].feature_id].letter == "OLD"


def test_letter_opaque_on_translucent_fill(qgis_app):
    from qgis.core import QgsFillSymbol
    from qgis.PyQt.QtGui import QColor
    from test_context_render import _img, _x, _y

    from geophysics_workbench.core.interpretation import InterpFeature, InterpPiece, normalise

    p = normalise(InterpPiece("p1", "v", "f1", "prof", "polygon",
                              [(50, 0.5), (70, 0.5), (70, -2.5), (50, -2.5)]))
    sym = QgsFillSymbol.createSimple({"color": "0,0,255,20", "outline_style": "no"})
    img = _img(_snapshot_results([p], {"f1": InterpFeature("f1", "v", letter="W")}, {"p1": sym}))
    strong = sum(1 for x in range(_x(60) - 5, _x(60) + 30) for y in range(_y(-1) - 30, _y(-1) + 5)
                 if QColor(img.pixel(x, y)).blue() > 200 and QColor(img.pixel(x, y)).red() < 60)
    assert strong > 5
