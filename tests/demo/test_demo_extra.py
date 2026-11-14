"""Demo projects carry no personal data: save user blanked, own-folder paths relative."""
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import demo_extra  # noqa: E402


def _qgz(path: Path, qgs: str) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("p.qgs", qgs)
        zf.writestr("p_styles.db", b"\x00styles")
    return path


def _qgs(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        return zf.read("p.qgs").decode()


def test_save_user_blanked_and_own_folder_made_relative(tmp_path):
    folder = tmp_path / "demo"
    folder.mkdir()
    own = str(folder.resolve())
    qgs = (f'<qgis saveUser="someone" saveUserFull="Some One">'
           f'<LayerStyle source="{own}\\store.gpkg|layername=profiles"/>'
           f'<LayerStyle source="{own.replace(chr(92), "/")}/store.gpkg|layername=stations"/>'
           f'<layer source="./data/a.csv"/>'
           f'<layer source="https://tile.openstreetmap.org/x"/></qgis>')
    path = _qgz(folder / "p.qgz", qgs)
    demo_extra.strip_save_user(path)
    out = _qgs(path)
    assert 'saveUser=""' in out and 'saveUserFull=""' in out
    assert "./store.gpkg|layername=profiles" in out
    assert "./store.gpkg|layername=stations" in out
    assert own not in out and own.replace("\\", "/") not in out
    assert "./data/a.csv" in out and "https://tile.openstreetmap.org/x" in out
    with zipfile.ZipFile(path) as zf:
        assert zf.read("p_styles.db") == b"\x00styles"


def test_paths_outside_the_folder_are_left_alone(tmp_path):
    folder = tmp_path / "demo"
    folder.mkdir()
    other = str((tmp_path / "elsewhere").resolve())
    path = _qgz(folder / "p.qgz", f'<qgis><layer source="{other}\\x.tif"/></qgis>')
    demo_extra.strip_save_user(path)
    assert f"{other}\\x.tif" in _qgs(path)
