"""Usability round 1, Task 13 (D5): error messages in plain words, naming the file and
ending with what to do next."""
from pathlib import Path

import pytest

INTERNAL = ("max_edge", "z_kind", "reader=", "Traceback")
NEXT = ("Check", "Choose", "Open", "Remove", "Pick", "Select")


def _ok(text: str, name: str):
    assert name in text, text
    assert not any(word in text for word in INTERNAL), text
    last = text.rstrip(".").split(". ")[-1]
    assert last.startswith(NEXT), text


def test_triangulation_error_in_plain_words():
    from geophysics_workbench.readers.errors import plain_error
    exc = ValueError("All triangles were filtered out; increase max_edge or check the points")
    _ok(plain_error(exc, Path("D:/data/model.xyz")), "model.xyz")


def test_unknown_format(tmp_path):
    from geophysics_workbench import readers
    from geophysics_workbench.readers.errors import plain_error
    junk = tmp_path / "notes.txt"
    junk.write_text("hello\nworld\n")
    with pytest.raises(ValueError) as info:
        readers.read(junk)
    _ok(plain_error(info.value, junk), "notes.txt")


def test_missing_file(tmp_path):
    from geophysics_workbench.readers.errors import plain_error
    gone = tmp_path / "gone.vtk"
    exc = FileNotFoundError(2, "No such file or directory", str(gone))
    text = plain_error(exc, gone)
    _ok(text, "gone.vtk")
    assert "not found" in text


def test_z_meaning_error():
    from geophysics_workbench.readers.errors import plain_error
    exc = ValueError("z_kind must be one of ('elevation', 'depth', 'unknown'), got 'x'")
    _ok(plain_error(exc, Path("m.dat")), "m.dat")


def test_layer_error_on_the_panel_is_plain(qgis_app, store_with_model, tmp_path):
    """A model whose file broke shows a plain message in the layer row."""
    from geophysics_workbench.section.data import SectionDataProvider
    st, p, _ = store_with_model
    d = st.datasets(p.id)[0]
    path = Path(st.path).parent / d.source_path
    path.write_text("not a model\n")
    [layer] = [la for la in SectionDataProvider(st).layers(p.id) if la.dataset.id == d.id]
    assert layer.error is not None
    _ok(layer.error, path.name)


def test_add_model_preview_of_a_station_file(qgis_app, fake_iface, store_with_model, tmp_path):
    """Usability review 2: a German electrode CSV chosen in Add ERT Model… showed a raw
    Python error ("unsupported operand type(s) for +: 'int' and 'NoneType')."""
    from geophysics_workbench.ui.add_model_dialog import AddModelDialog
    st, p, _ = store_with_model
    csv = tmp_path / "P9_Elektroden.csv"
    csv.write_text("Nr;Rechtswert;Hochwert;Höhe\n1;437681,98;5850793,00;59,06\n"
                   "2;437686,95;5850793,52;59,14\n3;437691,93;5850794,03;59,21\n",
                   encoding="utf-8")
    dlg = AddModelDialog(fake_iface, st, p.id)
    dlg.set_file(str(csv))
    qgis_app.processEvents()
    shown = dlg.preview.text() + " " + dlg.warning.text()
    assert "NoneType" not in shown and "unsupported operand" not in shown, shown
