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
        # the name gets the room first: the summary may be cut, never below its least
        # (its colour swatch stays)
        assert row.scale_button.width() >= row.scale_button.minimumSizeHint().width()
    finally:
        ll.close()
        ll.deleteLater()
        qgis_app.processEvents()


def test_cut_layer_name_keeps_its_start_and_its_end(qgis_app):
    """Names on one line often share their start ("Line 3 model", "Line 3 misfit"): a cut
    name keeps both ends, so the rows stay told apart."""
    from groundwork_geophysics.section.layer_list import _ElidedCheck
    check = _ElidedCheck("Transect 3 resistivity model (robust inversion)")
    check.resize(150, 20)
    check.show()
    qgis_app.processEvents()
    try:
        shown = check.text()
        assert "…" in shown
        assert shown.startswith("Tran") and shown.endswith("ion)")
    finally:
        check.close()
        check.deleteLater()


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


def _list_in_splitter(qgis_app, store_with_model):
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
    splitter.setCollapsible(0, False)
    splitter.resize(1400, 300)
    splitter.show()
    qgis_app.processEvents()
    ll.set_layers(prov, prov.layers(p.id))
    qgis_app.processEvents()
    return splitter, ll, prov, p


def _rebuild(qgis_app, ll, prov, p):
    """A rebuild of the rows (as after adding a layer or switching profile)."""
    ll.set_layers(prov, [])
    qgis_app.processEvents()
    ll.set_layers(prov, prov.layers(p.id))
    qgis_app.processEvents()


def test_collapsed_layer_list_stays_collapsed_on_rebuild(qgis_app, store_with_model):
    splitter, ll, prov, p = _list_in_splitter(qgis_app, store_with_model)
    try:
        assert splitter.sizes()[1] > 0
        splitter.setSizes([1400, 0])                 # dragged all the way to the right
        ll.sized_by_user = True                      # what the panel sets on splitterMoved
        qgis_app.processEvents()
        _rebuild(qgis_app, ll, prov, p)
        assert splitter.sizes()[1] == 0
    finally:
        splitter.close()
        splitter.deleteLater()
        qgis_app.processEvents()


def test_narrowed_layer_list_keeps_its_width_on_rebuild(qgis_app, store_with_model):
    splitter, ll, prov, p = _list_in_splitter(qgis_app, store_with_model)
    try:
        total = sum(splitter.sizes())
        narrow = ll.minimumWidth()
        splitter.setSizes([total - narrow, narrow])
        ll.sized_by_user = True
        qgis_app.processEvents()
        before = splitter.sizes()[1]
        _rebuild(qgis_app, ll, prov, p)
        assert splitter.sizes()[1] == before
    finally:
        splitter.close()
        splitter.deleteLater()
        qgis_app.processEvents()


def test_untouched_layer_list_still_grows_to_fit(qgis_app, store_with_model):
    splitter, ll, prov, p = _list_in_splitter(qgis_app, store_with_model)
    try:
        total = sum(splitter.sizes())
        splitter.setSizes([total - ll.minimumWidth(), ll.minimumWidth()])   # not by the user
        qgis_app.processEvents()
        _rebuild(qgis_app, ll, prov, p)
        assert splitter.sizes()[1] >= ll.sizeHint().width()
    finally:
        splitter.close()
        splitter.deleteLater()
        qgis_app.processEvents()


def _radar_row(qgis_app, store_with_model, width):
    """A layer list ``width`` wide with one radargram-like row: an antenna in the name and
    the longest look summary."""
    from dataclasses import replace

    from qgis.PyQt.QtGui import QFont

    from groundwork_geophysics.core.colors import ColorScale
    from groundwork_geophysics.core.trace_section import DisplayGain
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.layer_list import LayerList

    st, p, _ = store_with_model
    prov = SectionDataProvider(st)
    ds_id = st.datasets(p.id)[0].id
    prov.set_style(ds_id, replace(
        prov.style(ds_id), scale=ColorScale("gray", -1.0, 1.0, False), clip_percent=98.0,
        max_depth=8.0, gain=DisplayGain(agc_window=20e-9, band_low=50e6, band_high=200e6,
                                        background="all")))
    layers = prov.layers(p.id)
    layers[0].dataset = replace(layers[0].dataset, name="GPR11 270 MHz, E to W")
    layers[0].traces = object()                  # drawn as a trace section: the look summary
    ll = LayerList()
    ll.setFont(QFont("Segoe UI", 9))
    ll.set_layers(prov, layers)
    ll.resize(width, 200)
    ll.show()
    for _ in range(2):                           # the row shares its room, then lays out
        qgis_app.processEvents()
    [row] = ll._rows.values()
    return ll, row


def test_the_name_keeps_its_room_beside_a_long_look_summary(qgis_app, store_with_model):
    from groundwork_geophysics.section.layer_list import MAX_HINT_WIDTH
    ll, row = _radar_row(qgis_app, store_with_model, MAX_HINT_WIDTH)
    try:
        full = row.scale_button.full_text()
        assert full == "clip 98 % · band-pass · background · AGC · to 8 m"
        assert row.check.text() == "GPR11 270 MHz, E to W"          # the name in full
        shown = row.scale_button.text()
        assert shown != full and shown.endswith("…") and full.startswith(shown[:-1])
        assert full in row.scale_button.toolTip()                    # the whole look
        assert row.scale_button.width() >= row.scale_button.minimumSizeHint().width()
    finally:
        ll.close()
        ll.deleteLater()
        qgis_app.processEvents()


def test_a_wide_list_shows_name_and_summary_in_full(qgis_app, store_with_model):
    ll, row = _radar_row(qgis_app, store_with_model, 700)
    try:
        assert row.check.text() == "GPR11 270 MHz, E to W"
        assert row.scale_button.text() == row.scale_button.full_text()
        assert row.scale_button.full_text() not in row.scale_button.toolTip()
    finally:
        ll.close()
        ll.deleteLater()
        qgis_app.processEvents()


def test_a_narrow_list_cuts_the_name_in_the_middle_last(qgis_app, store_with_model):
    ll, row = _radar_row(qgis_app, store_with_model, 100)     # held at its least width
    try:
        assert row.scale_button.width() == row.scale_button.minimumSizeHint().width()
        name = row.check.text()
        assert "…" in name and name.startswith("GPR") and name.endswith("W")
        assert "GPR11 270 MHz, E to W" in row.check.toolTip()
        for widget in (row.scale_button, row.opacity):
            assert widget.visibleRegion().boundingRect() == widget.rect(), widget
    finally:
        ll.close()
        ll.deleteLater()
        qgis_app.processEvents()
