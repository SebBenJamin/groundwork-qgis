"""Removing a dataset from a profile via the layer list's context menu."""
import pytest


@pytest.fixture
def answer(monkeypatch):
    """Answer QMessageBox.question with the button in ``answer["button"]``; records texts."""
    from qgis.PyQt.QtWidgets import QMessageBox

    state = {"button": QMessageBox.StandardButton.Yes, "asked": []}

    def question(parent, title, text, *args, **kwargs):
        state["asked"].append(text)
        return state["button"]

    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    return state


def test_remove_from_profile_updates_store_list_and_provider(qgis_app, store_with_model,
                                                             make_dock, answer):
    from qgis.PyQt.QtWidgets import QMessageBox

    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.open_profile(p.id)
    [ds_id] = dock.layer_list.dataset_ids()
    menu = dock.layer_list.row_menu(ds_id)
    [action] = menu.actions()
    assert action.text() == "Remove from profile…"

    answer["button"] = QMessageBox.StandardButton.No           # cancelled: nothing changes
    action.trigger()
    qgis_app.processEvents()
    assert "P1 model" in answer["asked"][-1]
    assert len(st.datasets(p.id)) == 1 and dock.layer_list.dataset_ids() == [ds_id]

    answer["button"] = QMessageBox.StandardButton.Yes
    action.trigger()
    qgis_app.processEvents()
    assert st.datasets(p.id) == []
    assert dock.provider.layers(p.id) == [] and ds_id not in dock.provider._styles
    assert dock.layer_list.dataset_ids() == []
    assert dock.current_profile_id() == p.id                 # the profile stays open
    menu.deleteLater()
