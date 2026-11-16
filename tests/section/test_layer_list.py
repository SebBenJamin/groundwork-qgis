"""Layer list sizing: the controls of every row stay fully visible."""


def test_layer_rows_fit_without_horizontal_scrolling(qgis_app, store_with_model):
    from dataclasses import replace

    from qgis.PyQt.QtGui import QFont
    from qgis.PyQt.QtWidgets import QScrollArea

    from groundwork_geophysics.core.colors import ColorScale
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.layer_list import LayerList

    st, p, _ = store_with_model
    prov = SectionDataProvider(st)
    ds_id = st.datasets(p.id)[0].id
    prov.set_style(ds_id, replace(prov.style(ds_id),
                                  scale=ColorScale("Spectral_r", 15.1, 501.0, True)))
    ll = LayerList()
    ll.setFont(QFont("Segoe UI", 9))                 # the QGIS UI font on Windows
    try:
        layers = prov.layers(p.id)
        layers[0].dataset = replace(layers[0].dataset, name="P2 P2_model_it2.dat")
        ll.set_layers(prov, layers)
        ll.resize(ll.minimumWidth(), 200)
        ll.show()
        qgis_app.processEvents()
        [row] = ll._rows.values()
        scroll = ll.findChild(QScrollArea)
        assert not scroll.horizontalScrollBar().isVisible()
        for widget in (row.scale_button, row.opacity):
            assert widget.visibleRegion().boundingRect() == widget.rect(), widget
        assert row.scale_button.width() >= row.scale_button.sizeHint().width()
    finally:
        ll.close()
        ll.deleteLater()
        qgis_app.processEvents()


def test_layer_list_widens_in_its_splitter_for_full_names(qgis_app, store_with_model):
    from dataclasses import replace

    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtGui import QFont
    from qgis.PyQt.QtWidgets import QSplitter, QWidget

    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.layer_list import LayerList

    st, p, _ = store_with_model
    prov = SectionDataProvider(st)
    splitter = QSplitter(Qt.Orientation.Horizontal)
    splitter.setFont(QFont("Segoe UI", 9))
    splitter.addWidget(QWidget())
    ll = LayerList()
    splitter.addWidget(ll)
    splitter.setStretchFactor(0, 1)
    splitter.resize(1400, 300)
    splitter.show()                                  # sizes fixed while the list is empty
    qgis_app.processEvents()
    try:
        layers = prov.layers(p.id)
        layers[0].dataset = replace(layers[0].dataset, name="P2 P2_model_it2.dat")
        ll.set_layers(prov, layers)
        qgis_app.processEvents()
        [row] = ll._rows.values()
        from groundwork_geophysics.section.layer_list import MAX_HINT_WIDTH, MIN_NAME_WIDTH
        # usability round 1: the list stays at most 300 px wide; a longer name is cut and the
        # tooltip has it all
        assert splitter.sizes()[1] <= MAX_HINT_WIDTH
        assert row.check.width() >= MIN_NAME_WIDTH
        assert "P2 P2_model_it2.dat" in row.check.toolTip()
        assert splitter.sizes()[0] > 800                         # the section keeps the rest
    finally:
        splitter.close()
        splitter.deleteLater()
        qgis_app.processEvents()
