import json

from geophysics_workbench.core.context_settings import (BandSetting, BoreholeSetting,
                                                        ContextSettings, LineLayerSetting,
                                                        PointLayerSetting)


def test_settings_json_roundtrip():
    s = ContextSettings(
        line_layers=[LineLayerSetting("l1", "name", "#ff0000", True, True), LineLayerSetting("l2")],
        point_layers=[PointLayerSetting("p1", "label")],
        borehole=BoreholeSetting("b", "bid", "elev", "log", "lid", "top", "bot", "lith"),
        band=BandSetting("g", "unit"), dem_layer_id="dem",
        buffer=40.0, near_miss=12.5, dem_tolerance=2.5)
    text = s.to_json()
    assert json.loads(text)["version"] == 2
    assert ContextSettings.from_json(text) == s


def test_settings_from_bad_json_gives_defaults():
    for text in ("", "{", '{"buffer": "x"}', "[]", "null"):
        got = ContextSettings.from_json(text)
        assert got.buffer == 25.0 and got.line_layers == [] and got.borehole is None
    got = ContextSettings.from_json('{"line_layers": 3, "borehole": 5, "extra": 1, "near_miss": 7}')
    assert got.line_layers == [] and got.borehole is None and got.near_miss == 7.0


def test_distances_beyond_the_dialog_range_fall_back():
    got = ContextSettings.from_json('{"buffer": 1e9, "near_miss": Infinity, "dem_tolerance": 999999}')
    assert got.buffer == 25.0 and got.near_miss == 10.0 and got.dem_tolerance == 999999.0


def test_line_setting_v2_round_trip():
    import json
    s = ContextSettings(line_layers=[LineLayerSetting("a", "name", "#12ab34", True, False),
                                     LineLayerSetting("b")])
    text = s.to_json()
    assert json.loads(text)["version"] == 2
    assert ContextSettings.from_json(text) == s


def test_v1_line_entries_load_ticked():
    want = [LineLayerSetting("a", "voltage", "", False, True)]
    old = {"line_layers": [{"layer_id": "a", "label_field": "voltage", "powerline": True}]}
    assert ContextSettings.from_json(json.dumps({"version": 1, **old})).line_layers == want
    assert ContextSettings.from_json(json.dumps(old)).line_layers == want


def test_bad_line_fields_fall_back():
    def load(**kw):
        d = {"version": 2, "line_layers": [{"layer_id": "a", **kw}]}
        return ContextSettings.from_json(json.dumps(d)).line_layers[0]
    for bad in ("red", "#12345", 5):
        assert load(colour=bad).colour == ""
    assert load(checked="yes").checked is None
    assert load(checked=None).checked is None
    assert load(selected_only="1").selected_only is False
    assert load(checked=False).checked is False
