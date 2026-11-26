"""Optional libraries (such as segyio for SEG-Y): never bundled with the plugin, installed on
the user's request with pip into a folder of the QGIS profile, one folder per Python version,
and put on sys.path when the plugin starts."""
# How pip is run (tried on Windows with QGIS 4.2.3, Python 3.12, segyio 1.9.15, 0.3 MB wheel):
# - (a) a separate process `<exec_prefix>/python.exe -m pip install --target ...` with the
#   inherited environment works: installed in 2-3 s, and `import segyio` works afterwards in
#   the same process once the folder is on sys.path and importlib.invalidate_caches() ran.
#   Inside QGIS sys.executable is QGIS itself, not Python, hence exec_prefix on Windows.
#   The QGIS environment puts QGIS's bin folder (OpenSSL DLLs) and SSL_CERT_FILE in place,
#   which pip needs for https; a bare python.exe started from a plain shell without them
#   has been seen failing with "ssl module in Python is not available".
# - (b) in-process `pip._internal.cli.main.main(args)` also installs, but pip warns that
#   importing the package in the same process after the install is deprecated (and will
#   be enforced), and pip's internals are not an API. So (a) is used.
import importlib
import importlib.metadata
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

# arguments after `python -m pip`; {dir} and {name} are filled in by _pip_args.
# --no-deps: segyio needs NumPy, and QGIS's own NumPy must not get a second copy beside it
PIP_ARGS = ["install", "--target", "{dir}", "--only-binary=:all:", "--no-deps", "--upgrade", "{name}"]

# what each library is for, in the text the user sees when it is missing
_PURPOSE = {"segyio": "Reading SEG-Y"}


class MissingLibrary(ValueError):
    """An optional library a reader needs is not installed; the text says which one."""

    def __init__(self, name: str):
        self.name = name
        purpose = _PURPOSE.get(name, "This")
        super().__init__(f"{purpose} needs the free library {name}, which is not installed.")


def _profile_dir() -> Path:
    from qgis.core import QgsApplication
    return Path(QgsApplication.qgisSettingsDirPath())


def libs_dir() -> Path:
    """The folder optional libraries are installed into, separate per Python version
    (compiled libraries only work with the Python they were built for)."""
    v = f"py{sys.version_info.major}{sys.version_info.minor}"
    return _profile_dir() / "python" / "groundwork_libs" / v


def ensure_on_path() -> None:
    """Put the libraries folder on sys.path (once), when it exists."""
    folder = libs_dir()
    if folder.is_dir() and str(folder) not in sys.path:
        sys.path.append(str(folder))
        importlib.invalidate_caches()


def available(name: str) -> bool:
    """True when the library can be imported."""
    ensure_on_path()
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def version(name: str) -> str:
    """The installed version of the library, "" when unknown."""
    ensure_on_path()
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return ""


def _python() -> str:
    # inside QGIS sys.executable is the QGIS program; Python itself sits in exec_prefix
    if os.name == "nt":
        return str(Path(sys.exec_prefix) / "python.exe")
    return sys.executable


def _pip_args(name: str) -> list:
    return [a.format(dir=libs_dir(), name=name) for a in PIP_ARGS]


def _run(args: list) -> tuple:
    """Run `python -m pip <args>`; returns (exit code, pip's output)."""
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0  # no console window popping up
    try:
        done = subprocess.run([_python(), "-m", "pip", *args], capture_output=True, text=True,
                              creationflags=flags)
    except OSError as exc:
        return 1, str(exc)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def manual_command(name: str) -> str:
    """The command line that installs the library by hand, shown when installing fails."""
    return " ".join(f'"{a}"' if " " in a else a for a in [_python(), "-m", "pip", *_pip_args(name)])


def install(name: str, run=None) -> tuple:
    """Install the library into libs_dir() and make it importable right away.
    Returns (ok, message). `run` replaces the pip runner (tests)."""
    run = run or _run
    folder = libs_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, f"Could not create {folder}: {exc}"
    code, output = run(_pip_args(name))
    if code != 0:
        return False, (f"Installing {name} failed:\n{output.strip()}\n\n"
                       f"You can install it by hand with:\n{manual_command(name)}")
    ensure_on_path()
    importlib.invalidate_caches()
    found = version(name)
    return True, f"{name} {found} is installed." if found else f"{name} is installed."
