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


def test_install_failure_also_says_how_to_install_without_internet(tmp_path, monkeypatch):
    monkeypatch.setattr(libs, "_profile_dir", lambda: tmp_path)
    ok, message = libs.install("segyio", run=lambda args: (1, "no network"))
    assert not ok
    assert message == (
        "Installing segyio failed:\nno network\n\n"
        f"With internet, you can also install it by hand with:\n{libs.manual_command('segyio')}"
        "\n\nWithout internet: download the segyio file for your system from "
        "https://pypi.org/project/segyio/#files on another computer, then run:\n"
        f"{libs.offline_command('segyio')}\n\nThen restart QGIS.")


def test_the_offline_command_installs_from_the_downloaded_file(tmp_path, monkeypatch):
    monkeypatch.setattr(libs, "_profile_dir", lambda: tmp_path)
    command = libs.offline_command("segyio")
    assert "--target" in command and "--no-deps" in command
    assert command.endswith('"<path to the downloaded file>"')
    assert not command.endswith("segyio")
    online = libs.manual_command("segyio")
    assert command == online[:-len("segyio")] + '"<path to the downloaded file>"'


def test_missing_library_is_a_value_error_naming_it():
    exc = libs.MissingLibrary("segyio")
    assert isinstance(exc, ValueError) and exc.name == "segyio" and "segyio" in str(exc)


def test_available_is_false_for_a_name_nobody_has():
    assert libs.available("no_such_library_xyz") is False


def test_a_pip_that_hangs_is_stopped_and_counts_as_failed(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setattr(libs, "_profile_dir", lambda: tmp_path)
    seen = {}

    def hanging(*args, **kwargs):
        seen["timeout"] = kwargs.get("timeout")
        raise subprocess.TimeoutExpired(args[0], kwargs.get("timeout"))
    monkeypatch.setattr(subprocess, "run", hanging)
    ok, message = libs.install("segyio")
    assert seen["timeout"] == 300 and not ok
    assert "did not finish within 300 seconds" in message
    assert libs.manual_command("segyio") in message
