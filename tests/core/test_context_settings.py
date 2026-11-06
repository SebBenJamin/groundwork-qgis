import json

from geophysics_workbench.core.context_settings import (BandSetting, BoreholeSetting,
                                                        ContextSettings, CurveField,
                                                        CurveTableSetting, LineLayerSetting,
                                                        PointLayerSetting, curve_key)


def test_settings_json_roundtrip():
    s = ContextSettings(
        line_layers=[LineLayerSetting("l1", "name", "#ff0000", True, True), LineLayerSetting("l2")],
        point_layers=[PointLayerSetting("p1", "label")],
        boreholes=[BoreholeSetting("b", "bid", "elev", "log", "lid", "top", "bot", "lith")],
        band=BandSetting("g", "unit"), dem_layer_id="dem",
        buffer=40.0, near_miss=12.5, dem_tolerance=2.5)
    text = s.to_json()
    assert json.loads(text)["version"] == 3
    assert ContextSettings.from_json(text) == s


def test_settings_from_bad_json_gives_defaults():
    for text in ("", "{", '{"buffer": "x"}', "[]", "null"):
        got = ContextSettings.from_json(text)
        assert got.buffer == 25.0 and got.line_layers == [] and got.boreholes == []
    got = ContextSettings.from_json('{"line_layers": 3, "borehole": 5, "extra": 1, "near_miss": 7}')
    assert got.line_layers == [] and got.boreholes == [] and got.near_miss == 7.0


def test_distances_beyond_the_dialog_range_fall_back():
    got = ContextSettings.from_json('{"buffer": 1e9, "near_miss": Infinity, "dem_tolerance": 999999}')
    assert got.buffer == 25.0 and got.near_miss == 10.0 and got.dem_tolerance == 999999.0


def test_line_setting_v2_round_trip():
    import json
    s = ContextSettings(line_layers=[LineLayerSetting("a", "name", "#12ab34", True, False),
                                     LineLayerSetting("b")])
    text = s.to_json()
    assert json.loads(text)["version"] == 3
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


def test_point_setting_depth_roundtrip_and_old_json():
    import json

    from geophysics_workbench.core.context_settings import ContextSettings, PointLayerSetting
    s = ContextSettings(point_layers=[PointLayerSetting("p", "name", "Teufe_in_m")])
    assert ContextSettings.from_json(s.to_json()).point_layers == s.point_layers
    old = json.dumps({"version": 2, "point_layers": [{"layer_id": "p", "label_field": "n"}]})
    assert ContextSettings.from_json(old).point_layers[0].depth_field == ""


def test_v2_single_borehole_becomes_one_entry():
    v2 = json.dumps({"version": 2, "borehole": {"layer_id": "pts", "id_field": "id",
                     "elevation_field": "z", "log_layer_id": "logs", "log_id_field": "core_id",
                     "top_field": "top", "bottom_field": "bottom", "lithology_field": "lithology"}})
    s = ContextSettings.from_json(v2)
    assert len(s.boreholes) == 1 and s.boreholes[0].log_layer_id == "logs"
    assert s.boreholes[0].column_px == 16 and s.boreholes[0].curve_tables == []


def test_v3_round_trip_with_curves_and_section_options():
    b = BoreholeSetting("pts", "id", total_depth_field="td", column_px=20, opacity=0.6,
                        layer_text=True, section_curves=["gam:gr"],
                        curve_tables=[CurveTableSetting("gam", "bh", "depth",
                                                        [CurveField("gr", "API")])])
    s = ContextSettings(boreholes=[b, BoreholeSetting("pts2", "name")])
    back = ContextSettings.from_json(s.to_json())
    assert back.boreholes == s.boreholes


def test_v3_also_writes_first_entry_as_legacy_borehole_key():
    s = ContextSettings(boreholes=[BoreholeSetting("pts", "id"), BoreholeSetting("b", "id")])
    data = json.loads(s.to_json())
    assert data["version"] == 3 and data["borehole"]["layer_id"] == "pts"
    assert json.loads(ContextSettings().to_json())["borehole"] is None


def test_bad_section_options_fall_back_to_defaults():
    data = {"version": 3, "boreholes": [{"layer_id": "p", "id_field": "id", "column_px": 500,
            "opacity": "x", "layer_text": "yes", "section_curves": ["a:b", 3],
            "curve_tables": [{"layer_id": ""}, "junk",
                             {"layer_id": "c", "id_field": "i", "depth_field": "d",
                              "curves": [{"field": "gr", "unit": "API"}, {"unit": "x"}]}]}]}
    b = ContextSettings.from_json(json.dumps(data)).boreholes[0]
    assert b.column_px == 16 and b.opacity == 1.0 and b.layer_text is False
    assert b.section_curves == ["a:b"]
    assert b.curve_tables == [CurveTableSetting("c", "i", "d", [CurveField("gr", "API")])]


def test_curve_key():
    assert curve_key("lay", "gr") == "lay:gr"
