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
    assert str(libs.libs_dir()) in calls[0] and calls[0][-1] == "segyio>=1.9,<2"
    assert str(libs.libs_dir()) in sys.path


def test_an_install_from_a_worker_thread_leaves_sys_path_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(libs, "_profile_dir", lambda: tmp_path)
    ok, _message = libs.install("segyio", run=lambda args: (0, ""), put_on_path=False)
    assert ok and str(libs.libs_dir()) not in sys.path


def test_the_installed_version_is_read_from_the_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(libs, "_profile_dir", lambda: tmp_path)

    def fake_pip(args):
        info = libs.libs_dir() / "segyio-1.9.15.dist-info"
        info.mkdir(parents=True)
        (info / "METADATA").write_text("Metadata-Version: 2.1\nName: segyio\nVersion: 1.9.15\n")
        return 0, ""
    ok, message = libs.install("segyio", run=fake_pip, put_on_path=False)
    assert ok and message == "segyio 1.9.15 is installed."


def _fake_python(tmp_path, monkeypatch, name, executable_name, prefix_names):
    """``sys.executable`` named ``executable_name`` and files ``prefix_names`` in a fake
    ``sys.exec_prefix`` (paths relative to it)."""
    prefix = tmp_path / "prefix"
    for n in prefix_names:
        (prefix / n).parent.mkdir(parents=True, exist_ok=True)
        (prefix / n).write_text("")
    exe = tmp_path / "app" / executable_name
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("")
    monkeypatch.setattr(libs, "_on_windows", lambda: name == "nt")
    monkeypatch.setattr(sys, "executable", str(exe))
    monkeypatch.setattr(sys, "exec_prefix", str(prefix))
    return prefix, exe


def test_on_windows_the_python_beside_qgis_runs_pip(tmp_path, monkeypatch):
    prefix, _exe = _fake_python(tmp_path, monkeypatch, "nt", "qgis-bin.exe", ["python.exe"])
    assert libs._python() == str(prefix / "python.exe")


def test_elsewhere_a_qgis_program_is_never_taken_for_python(tmp_path, monkeypatch):
    v = f"{sys.version_info.major}.{sys.version_info.minor}"
    prefix, _exe = _fake_python(tmp_path, monkeypatch, "posix", "QGIS", [f"bin/python{v}"])
    assert libs._python() == str(prefix / "bin" / f"python{v}")
    prefix, _exe = _fake_python(tmp_path / "b", monkeypatch, "posix", "qgis", ["bin/python3"])
    assert libs._python() == str(prefix / "bin" / "python3")


def test_elsewhere_a_python_executable_is_used_as_it_is(tmp_path, monkeypatch):
    _prefix, exe = _fake_python(tmp_path, monkeypatch, "posix", "python3.12", [])
    assert libs._python() == str(exe)


def test_without_any_python_the_install_says_it_is_not_possible_here(tmp_path, monkeypatch):
    _fake_python(tmp_path, monkeypatch, "posix", "qgis", [])
    monkeypatch.setattr(libs, "_profile_dir", lambda: tmp_path)
    monkeypatch.setattr(libs.subprocess, "run", lambda *a, **k: pytest.fail("ran"))
    ok, message = libs.install("segyio")
    assert not ok and message.startswith("segyio cannot be installed from here")


def test_pip_runs_in_the_libraries_folder_without_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(libs, "_profile_dir", lambda: tmp_path)
    libs.libs_dir().mkdir(parents=True)
    seen = {}

    class Done:
        returncode, stdout, stderr = 0, "", ""

    def run(cmd, **kwargs):
        seen["cmd"], seen["kwargs"] = cmd, kwargs
        return Done()
    monkeypatch.setattr(libs.subprocess, "run", run)
    assert libs._run(["--version"]) == (0, "")
    cmd = seen["cmd"]
    assert cmd[0] == libs._python()
    assert cmd[1:4] == ["-P", "-m", "pip"] and cmd[-1] == "--version"
    assert seen["kwargs"]["cwd"] == str(libs.libs_dir())
    assert "env" not in seen["kwargs"]                  # QGIS's own environment is kept
    assert '"segyio>=1.9,<2"' in libs.manual_command("segyio")


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
    assert command == online[:-len('"segyio>=1.9,<2"')] + '"<path to the downloaded file>"'


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


def test_the_install_task_changes_sys_path_only_when_finished(qgis_app, monkeypatch):
    from groundwork_geophysics.ui import lib_install
    seen = []
    monkeypatch.setattr(libs, "install", lambda name, run=None, put_on_path=True:
                        seen.append(put_on_path) or (True, "segyio is installed."))
    monkeypatch.setattr(libs, "ensure_on_path", lambda: seen.append("on path"))
    task = lib_install.InstallTask("segyio")
    assert task.run() and seen == [False]               # the worker thread's part
    task.finished(True)                                  # on the main thread
    assert seen == [False, "on path"]
