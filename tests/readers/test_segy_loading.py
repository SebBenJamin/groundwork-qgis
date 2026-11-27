"""How a segyio that is missing, cannot be loaded, or cannot open a file is told apart (none of
these tests needs segyio itself)."""
import sys
import types

import pytest

from groundwork_geophysics import libs
from groundwork_geophysics.readers import segy


class _Failing:
    """A finder that makes ``import segyio`` raise ``exc``."""

    def __init__(self, exc):
        self.exc = exc

    def find_spec(self, name, path=None, target=None):
        if name == "segyio":
            raise self.exc
        return None


@pytest.fixture
def segyio_import(monkeypatch):
    def make(exc):
        monkeypatch.delitem(sys.modules, "segyio", raising=False)
        monkeypatch.setattr(sys, "meta_path", [_Failing(exc), *sys.meta_path])
    return make


def test_a_segyio_that_is_not_there_is_missing(segyio_import):
    segyio_import(ModuleNotFoundError("No module named 'segyio'", name="segyio"))
    with pytest.raises(libs.MissingLibrary):
        segy._segyio()


@pytest.mark.parametrize("exc", [
    ImportError("DLL load failed while importing _segyio"),
    ModuleNotFoundError("No module named 'numpy.core._multiarray_umath'",
                        name="numpy.core._multiarray_umath"),
    OSError("the file is cut short"),
])
def test_a_segyio_that_cannot_be_loaded_says_so_without_an_install_offer(segyio_import, exc):
    segyio_import(exc)
    with pytest.raises(ValueError) as caught:
        segy._segyio()
    assert not isinstance(caught.value, libs.MissingLibrary)
    text = str(caught.value)
    assert text.startswith("Reading SEG-Y needs the library segyio, which is installed but "
                           "cannot be loaded (")
    assert str(exc) in text and "Restart QGIS" in text


def _segyio_raising(exc):
    def open_(*_args, **_kwargs):
        raise exc
    return types.SimpleNamespace(open=open_)


def test_a_file_that_is_there_but_cannot_be_opened_is_not_called_missing(tmp_path):
    path = tmp_path / "line.sgy"
    path.write_bytes(b"\0" * 4000)
    with pytest.raises(OSError) as caught:
        segy._open(_segyio_raising(FileNotFoundError(2, "No such file or directory")), path)
    assert not isinstance(caught.value, FileNotFoundError)
    assert "although it is there" in str(caught.value) and "Copy the file" in str(caught.value)


def test_a_file_that_is_gone_stays_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        segy._open(_segyio_raising(FileNotFoundError(2, "No such file or directory")),
                   tmp_path / "gone.sgy")
