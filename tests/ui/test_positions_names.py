"""Point names read from a positions file's text column or a point layer's text field: the
raw names, before any number is read from them."""
from pathlib import Path

import numpy as np

WILD = Path(__file__).resolve().parent.parent / "fixtures" / "wild"
NAMES = ["Base", "GCP3", "ERT03_01", "ERT03_02", "ERT03_03", "ERT03_04", "ERT03_04", "ERT03_05"]


def test_table_gives_raw_names(qgis_app):
    from qgis.core import QgsProject

    from groundwork_geophysics.core.roles import guess_position_columns
    from groundwork_geophysics.readers.texttable import guess_options, read_table
    from groundwork_geophysics.ui.positions_source import positions_from_table

    path = WILD / "positions_names.csv"
    table = read_table(path, guess_options(path))
    positions, skipped = positions_from_table(table, guess_position_columns(table),
                                              "EPSG:25832", QgsProject())
    assert skipped == 1 and positions.numbers is None
    assert positions.names == NAMES
    np.testing.assert_allclose(positions.xyz[6], [500006.1, 5600000.1, 57.3])


def _layer(field_type, values):
    from qgis.core import QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsVectorLayer

    layer = QgsVectorLayer("Point?crs=EPSG:25832", "gps", "memory")
    layer.dataProvider().addAttributes([QgsField("pt", field_type)])
    layer.updateFields()
    feats = []
    for i, v in enumerate(values):
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(1000.0 + 10 * i, 2000.0)))
        f.setAttributes([v])
        feats.append(f)
    layer.dataProvider().addFeatures(feats)
    return layer


def test_layer_gives_raw_names(qgis_app):
    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QMetaType

    from groundwork_geophysics.ui.positions_source import positions_from_layer

    layer = _layer(QMetaType.Type.QString, ["E1", None, "E2"])
    p = positions_from_layer(layer, "pt", None, None, False, "EPSG:25832", QgsProject())
    assert p.names == ["E1", "", "E2"] and p.numbers is None
    layer = _layer(QMetaType.Type.Int, [3, 1, 2])
    p = positions_from_layer(layer, "pt", None, None, False, "EPSG:25832", QgsProject())
    assert p.names is None and p.numbers.tolist() == [3, 1, 2]
