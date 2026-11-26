"""Each main dialog has QGIS's standard Help button, opening its page on the site."""
import pytest


@pytest.fixture
def env(qgis_app, fake_iface, store_with_model, monkeypatch):
    from qgis.core import QgsProject
    from qgis.PyQt.QtGui import QDesktopServices

    from groundwork_geophysics.core.context import ContextItems
    from groundwork_geophysics.plates.items import register_items, set_context_provider
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.ui.project_actions import use_store
    st, p, _ = store_with_model
    prj = QgsProject.instance()
    prj.clear()
    use_store(st, prj)
    prov = SectionDataProvider(st)
    prov.context_source = lambda profile: ContextItems()
    register_items()
    set_context_provider(prov)
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url.toString()) or True))
    yield fake_iface, st, p, prov, prj, opened
    from groundwork_geophysics.plates.sources import detach_frame_items, unregister_frame_sources
    detach_frame_items(prj)
    unregister_frame_sources()
    set_context_provider(None)
    prj.removeAllMapLayers()
    prj.clear()


def _add_data(iface, st, p, prov, prj):
    from groundwork_geophysics.ui.add_data_dialog import AddDataDialog
    return AddDataDialog(iface, st, p.id)


def _new_profile(iface, st, p, prov, prj):
    from groundwork_geophysics.ui.new_profile_dialog import NewProfileDialog
    return NewProfileDialog(iface, st, prj, prov)


def _profile_properties(iface, st, p, prov, prj):
    from groundwork_geophysics.ui.profile_properties_dialog import ProfilePropertiesDialog
    return ProfilePropertiesDialog(iface, st, p.id, prov)


def _context(iface, st, p, prov, prj):
    from groundwork_geophysics.ui.context_dialog import ContextDialog
    return ContextDialog(iface, prj)


def _plates(iface, st, p, prov, prj):
    from groundwork_geophysics.ui.plates_dialog import PlatesDialog
    return PlatesDialog(prj, st, prov)


def _plate_details(iface, st, p, prov, prj):
    from groundwork_geophysics.ui.plates_dialog import PlateDetailsDialog
    return PlateDetailsDialog(prj)


def _view3d(iface, st, p, prov, prj):
    from groundwork_geophysics.ui.view3d_dialog import View3dDialog
    from groundwork_geophysics.ui.view3d_layers import Choice
    return View3dDialog(st, Choice())


@pytest.mark.parametrize("make,key", [(_add_data, "add_data"), (_new_profile, "new_profile"),
                                      (_profile_properties, "profile_properties"),
                                      (_context, "context_layers"), (_plates, "plates"),
                                      (_plate_details, "plate_details"),
                                      (_view3d, "view3d")])
def test_dialog_help_buttons(env, make, key):
    from qgis.PyQt.QtWidgets import QDialogButtonBox

    from groundwork_geophysics.ui.help import help_url
    iface, st, p, prov, prj, opened = env
    dlg = make(iface, st, p, prov, prj)
    try:
        helps = [box.button(QDialogButtonBox.StandardButton.Help)
                 for box in dlg.findChildren(QDialogButtonBox)]
        helps = [b for b in helps if b is not None]
        assert len(helps) == 1, key
        helps[0].click()
        assert opened == [help_url(key)]
    finally:
        dlg.close()
        dlg.deleteLater()


def test_add_data_help_opens_the_reflection_page_for_a_segy_file(env):
    from qgis.PyQt.QtWidgets import QDialogButtonBox

    from groundwork_geophysics.ui.help import help_url
    iface, st, p, prov, prj, opened = env
    dlg = _add_data(iface, st, p, prov, prj)
    try:
        dlg.file_edit.setText("line.sgy")           # a SEG-Y file chosen
        dlg.format_combo.setCurrentIndex(dlg.format_combo.findData("segy"))
        (box,) = [b for b in dlg.findChildren(QDialogButtonBox)
                  if b.button(QDialogButtonBox.StandardButton.Help) is not None]
        box.button(QDialogButtonBox.StandardButton.Help).click()
        assert opened == [help_url("add_segy")]
    finally:
        dlg.close()
        dlg.deleteLater()
