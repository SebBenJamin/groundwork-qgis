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
    from geophysics_workbench.core.plates import PlateSpec
    from geophysics_workbench.plates.build import create_or_update_plate
    from geophysics_workbench.plates.export import export_plates
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
