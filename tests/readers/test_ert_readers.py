from pathlib import Path
import numpy as np, pytest
from geophysics_workbench import readers
F = Path("tests/fixtures/ert")


def test_detect_picks_specific_reader():
    assert readers.detect(F / "f001_res.dat")[0] == "r2_res_dat"
    assert readers.detect(F / "zond_model.dat")[0] == "zondres_xyz"
    assert readers.detect(F / "f001_res.vtk")[0] == "vtk_legacy"


def test_detect_never_raises_on_garbage(tmp_path):
    p = tmp_path / "junk.dat"
    p.write_bytes(bytes(range(256)) * 40)
    assert readers.detect(p) == []
    assert readers.detect(tmp_path / "missing.dat") == []


def test_zond_reads_resistivity_not_log():
    r = readers.read(F / "zond_model.dat")
    assert r.mesh.values.min() > 1 and r.z_kind == "unknown"
    assert r.provenance["has_world_xy"] is True and r.provenance["reader"] == "zondres_xyz"
    assert r.provenance["source_name"] == "zond_model.dat"


def test_zond_depth_header_sets_z_kind():
    r = readers.read(F / "zond_model_depth.dat")
    assert r.z_kind == "depth" and r.provenance["has_world_xy"] is False


def test_r2_res_is_elevation_with_iteration():
    r = readers.read(F / "f001_res.dat")
    assert r.z_kind == "elevation" and r.provenance["file_index"] == 1
    assert r.mesh.bounds()[2] < 0


def test_vtk_keeps_original_cells():
    r = readers.read(F / "f001_res.vtk")
    assert r.mesh.cells.shape[0] == 8          # fixture: 4 quads + 4 triangles
    assert "array_names" in r.provenance


def test_vtk_array_choice_and_axes():
    r = readers.read(F / "f001_res.vtk")
    assert r.provenance["array"].startswith("Resistivity") and r.provenance["axes"] == (0, 2)
    assert r.mesh.values.tolist() == [50, 80, 120, 200, 300, 400, 500, 600]
    assert (r.mesh.cells[:4, 3] >= 0).all() and (r.mesh.cells[4:, 3] == -1).all()
    s = readers.read(F / "f001_res.vtk", array="Sensitivity(log10)")
    assert s.mesh.values[1] == pytest.approx(-0.3) and s.mesh.quantity == "Sensitivity(log10)"
    with pytest.raises(ValueError, match="not found"):
        readers.read(F / "f001_res.vtk", array="nope")


def test_vtk_unsupported_cell_type_message(tmp_path):
    bad = (F / "f001_res.vtk").read_text().replace("CELL_TYPES 8\n9", "CELL_TYPES 8\n10", 1)
    p = tmp_path / "bad.vtk"; p.write_text(bad)
    with pytest.raises(ValueError, match="cell type 10"):
        readers.read(p)


def test_vtk_resipy_single_line_layout(tmp_path):
    """ResIPy writes all cell types and all values on one line."""
    src = (F / "f001_res.vtk").read_text().split("\n")
    out, i = [], 0
    while i < len(src):
        out.append(src[i])
        if src[i].startswith(("CELL_TYPES", "LOOKUP_TABLE")):
            j = i + 1
            vals = []
            while j < len(src) and src[j] and not src[j][0].isalpha():
                vals.append(src[j]); j += 1
            out.append(" ".join(vals)); i = j; continue
        i += 1
    p = tmp_path / "one.vtk"; p.write_text("\n".join(out))
    a, b = readers.read(p), readers.read(F / "f001_res.vtk")
    assert np.array_equal(a.mesh.cells, b.mesh.cells) and np.array_equal(a.mesh.values, b.mesh.values)


@pytest.mark.parametrize("content", ["not numbers\n", "", "1 2\n3 4\n"])
def test_garbage_files_raise_value_error(tmp_path, content):
    for name, reader in (("g.dat", "zondres_xyz"), ("f002_res.dat", "r2_res_dat"), ("g.vtk", "vtk_legacy")):
        p = tmp_path / name; p.write_text(content)
        with pytest.raises(ValueError):
            readers.read(p, reader)


def test_unknown_format_and_reader(tmp_path):
    p = tmp_path / "x.bin"; p.write_bytes(b"\x00\x01")
    with pytest.raises(ValueError, match="could not recognise"):
        readers.read(p)
    with pytest.raises(ValueError, match="Unknown reader"):
        readers.get("nope")


def test_r2_fill_values_are_masked(tmp_path):
    lines = (F / "f001_res.dat").read_text().splitlines()
    lines[0] = "\t-9.99900e+03\t-9.99900e+03\t-9.99900e+03\t-9.99900e+03"
    lines[1] = lines[1].replace(lines[1].split()[2], "-9.99900e+03")
    p = tmp_path / "f002_res.dat"; p.write_text("\n".join(lines) + "\n")
    r = readers.read(p)
    assert r.provenance["n_masked"] == 2 and (r.mesh.values > 0).all()
    assert readers.read(F / "f001_res.dat").provenance["n_masked"] == 0


def test_r2_all_fill_raises(tmp_path):
    p = tmp_path / "f003_res.dat"
    p.write_text("".join(f"\t{i}.0\t-{i}.0\t-9999.0\t-9999.0\n" for i in range(5)))
    with pytest.raises(ValueError, match="fill values"):
        readers.read(p)


def test_nonpositive_resistivity_message(tmp_path):
    p = tmp_path / "f004_res.dat"
    p.write_text("".join(f"\t{i}.0\t-{j}.0\t{0 if i == 0 else 5}.0\t0.0\n" for i in range(3) for j in range(1, 3)))
    with pytest.raises(ValueError, match=r"f004_res\.dat: 2 resistivity value"):
        readers.read(p)


def test_vtk_fill_values_become_nan(tmp_path):
    txt = (F / "f001_res.vtk").read_text().replace("\n80.00\n", "\n-9999\n", 1)
    p = tmp_path / "fill.vtk"; p.write_text(txt)
    r = readers.read(p)
    assert r.provenance["n_masked"] == 1 and np.isnan(r.mesh.values[1])
    assert r.mesh.cells.shape[0] == 8 and np.isfinite(np.delete(r.mesh.values, 1)).all()


def test_zond_nan_token_is_masked(tmp_path):
    lines = (F / "zond_model.dat").read_text().splitlines()
    cols = lines[2].split("\t"); cols[3] = "nan"; lines[2] = "\t".join(cols)
    p = tmp_path / "nan.dat"; p.write_text("\n".join(lines) + "\n")
    r = readers.read(p)
    assert r.provenance["n_masked"] == 1 and (r.mesh.values > 0).all()
