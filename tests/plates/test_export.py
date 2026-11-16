"""Export plates: one vector PDF per plate (optionally one combined PDF)."""
import re
import zlib

import pytest

from tests.plates.test_build import _plate, env  # noqa: F401  (fixture)


def pdf_content(path):
    """(path operators, image widths) of a PDF, its streams inflated."""
    data = path.read_bytes()
    ops, widths = 0, [int(w) for w in re.findall(rb"/Subtype\s*/Image.*?/Width\s+(\d+)", data,
                                                  re.S)]
    for raw in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        try:
            text = zlib.decompress(raw)
        except zlib.error:
            text = raw
        ops += len(re.findall(rb"\s(?:m|l|c|re)\s", text))
    return ops, widths


def test_export_writes_one_pdf_per_plate_with_vector_content(env, tmp_path):
    from groundwork_geophysics.core.plates import PlateSpec
    from groundwork_geophysics.plates.build import create_or_update_plate
    from groundwork_geophysics.plates.export import export_plates
    st, p, prov, prj = env
    a = _plate(st, p)
    b = PlateSpec("pl9", "4b", "Line: A/B?", "A4_portrait", _plate(st, p).frames)
    b.frames[0].frame_id = "g0"
    create_or_update_plate(prj, st, prov, a)
    create_or_update_plate(prj, st, prov, b)
    paths = export_plates(prj, tmp_path, combined=False)
    assert sorted(x.name for x in paths) == ["Plate_3_Transect.pdf", "Plate_4b_Line_A_B.pdf"]
    ops, widths = pdf_content(paths[0])
    assert ops > 100                                          # sections drawn as paths
    assert all(w < 2000 for w in widths)                      # no full-page raster
    combined = export_plates(prj, tmp_path, combined=True)
    assert [x.name for x in combined] == ["Plates.pdf"]
    assert combined[0].read_bytes().count(b"/Type /Page\n") + \
        combined[0].read_bytes().count(b"/Type /Page ") + \
        combined[0].read_bytes().count(b"/Type/Page") >= 2


def test_combined_pdf_that_cannot_be_written_raises(env, tmp_path):
    """Review I5: a combined PDF that cannot be opened (e.g. locked by a viewer) must not be
    reported as exported."""
    from groundwork_geophysics.plates.build import create_or_update_plate
    from groundwork_geophysics.plates.export import export_plates
    st, p, prov, prj = env
    create_or_update_plate(prj, st, prov, _plate(st, p))
    (tmp_path / "Plates.pdf").mkdir()                      # cannot be opened as a file
    with pytest.raises(OSError):
        export_plates(prj, tmp_path, combined=True)


def test_a_failing_update_leaves_other_plates_attached(env, monkeypatch):
    from groundwork_geophysics.core.plates import PlateSpec
    from groundwork_geophysics.plates import build
    st, p, prov, prj = env
    first = build.create_or_update_plate(prj, st, prov, _plate(st, p))
    second = PlateSpec("pl2", "5", "Other", "A4_landscape", _plate(st, p).frames)
    second.frames[0].frame_id = "g9"

    def boom(*_a, **_k):
        raise RuntimeError("broken")
    monkeypatch.setattr(build, "field_notes_text", boom)
    with pytest.raises(RuntimeError):
        build.create_or_update_plate(prj, st, prov, second)
    assert [s.profileSourceId() for s in first.itemById("wb_frame_1").sources()] == [
        "geophysics_workbench:frame:f0"]


def test_export_dialog_does_not_export_after_a_failed_update(env, tmp_path, monkeypatch):
    from qgis.PyQt.QtWidgets import QFileDialog

    from groundwork_geophysics.plates.sources import write_plates
    from groundwork_geophysics.ui import plates_dialog
    st, p, prov, prj = env
    write_plates(prj, [_plate(st, p)])
    dlg = plates_dialog.PlatesDialog(prj, st, prov)

    def boom(*_a, **_k):
        raise RuntimeError("broken")
    monkeypatch.setattr(plates_dialog, "create_or_update_plate", boom)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        staticmethod(lambda *a, **k: str(tmp_path)))
    dlg.export_dialog()
    assert "Failed" in dlg.message.text() and "broken" in dlg.message.text()
    assert list(tmp_path.glob("*.pdf")) == []
