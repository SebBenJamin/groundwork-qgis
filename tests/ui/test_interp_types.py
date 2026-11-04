"""The Types dialog: rename or merge an interpretation type everywhere at once."""


def test_types_dialog_lists_and_renames(qgis_app):
    from geophysics_workbench.ui.interp_types import TypesDialog

    counts = {"clay": 2, "anomaly": 1}
    calls = []

    def rename(old, new):
        calls.append((old, new))
        counts[new] = counts.pop(old)
        return 2

    dlg = TypesDialog(None, lambda: dict(counts), rename)
    assert sorted(dlg.table.item(r, 0).text() for r in range(dlg.table.rowCount())) == [
        "anomaly", "clay"]
    dlg.ask_text = lambda old: "clay lens"
    dlg.table.selectRow(dlg.row_of("clay"))
    dlg.rename_selected()
    assert calls == [("clay", "clay lens")]
    assert dlg.row_of("clay lens") >= 0 and dlg.row_of("clay") == -1


def test_cancelled_rename_does_nothing(qgis_app):
    from geophysics_workbench.ui.interp_types import TypesDialog

    calls = []
    dlg = TypesDialog(None, lambda: {"clay": 1}, lambda o, n: calls.append(1) or 0)
    dlg.ask_text = lambda old: None
    dlg.table.selectRow(0)
    dlg.rename_selected()
    assert calls == []
