import json

from geophysics_workbench.core.context_settings import (BandSetting, BoreholeSetting,
                                                        ContextSettings, LineLayerSetting,
                                                        PointLayerSetting)


def test_settings_json_roundtrip():
    s = ContextSettings(
        line_layers=[LineLayerSetting("l1", "name", True), LineLayerSetting("l2")],
        point_layers=[PointLayerSetting("p1", "label")],
        borehole=BoreholeSetting("b", "bid", "elev", "log", "lid", "top", "bot", "lith"),
        band=BandSetting("g", "unit"), dem_layer_id="dem",
        buffer=40.0, near_miss=12.5, dem_tolerance=2.5)
    text = s.to_json()
    assert json.loads(text)["version"] == 1
    assert ContextSettings.from_json(text) == s


def test_settings_from_bad_json_gives_defaults():
    for text in ("", "{", '{"buffer": "x"}', "[]", "null"):
        got = ContextSettings.from_json(text)
        assert got.buffer == 25.0 and got.line_layers == [] and got.borehole is None
    got = ContextSettings.from_json('{"line_layers": 3, "borehole": 5, "extra": 1, "near_miss": 7}')
    assert got.line_layers == [] and got.borehole is None and got.near_miss == 7.0
