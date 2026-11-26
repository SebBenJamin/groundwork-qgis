"""Optional libraries (segyio) installed on request into a folder of the QGIS profile."""
import sys

import pytest

from groundwork_geophysics import libs


@pytest.fixture(autouse=True)
def _keep_sys_path(monkeypatch):
    # install() puts the folder on sys.path; give each test its own copy so nothing leaks
    monkeypatch.setattr(sys, "path", list(sys.path))


def test_libs_dir_is_per_python_version(tmp_path, monkeypatch):
    monkeypatch.setattr(libs, "_profile_dir", lambda: tmp_path)
    v = f"py{sys.version_info.major}{sys.version_info.minor}"
    assert libs.libs_dir() == tmp_path / "python" / "groundwork_libs" / v


def test_install_runs_pip_into_the_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(libs, "_profile_dir", lambda: tmp_path)
    calls = []
    ok, message = libs.install("segyio", run=lambda args: calls.append(args) or (0, ""))
    assert ok and "--no-deps" in calls[0] and "--only-binary=:all:" in calls[0]
    assert str(libs.libs_dir()) in calls[0] and calls[0][-1] == "segyio"
    assert str(libs.libs_dir()) in sys.path


def test_install_failure_gives_the_manual_command(tmp_path, monkeypatch):
    monkeypatch.setattr(libs, "_profile_dir", lambda: tmp_path)
    ok, message = libs.install("segyio", run=lambda args: (1, "no network"))
    assert not ok and "no network" in message and libs.manual_command("segyio") in message


def test_missing_library_is_a_value_error_naming_it():
    exc = libs.MissingLibrary("segyio")
    assert isinstance(exc, ValueError) and exc.name == "segyio" and "segyio" in str(exc)


def test_available_is_false_for_a_name_nobody_has():
    assert libs.available("no_such_library_xyz") is False
