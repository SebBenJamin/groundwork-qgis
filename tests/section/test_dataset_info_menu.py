"""The layer row menu offers Dataset info…."""


def test_layer_menu_has_dataset_info(qgis_app, store_with_model, make_dock):
    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.open_profile(p.id)
    ds_id = st.datasets(p.id)[0].id
    texts = [a.text() for a in dock.layer_list.row_menu(ds_id).actions()]
    assert "Dataset info…" in texts
