# Runs pytest inside QGIS 4.2.3's Python. Extra args are passed through.
# pytest is not bundled with QGIS; install it locally with:
#   $env:PYTHONNOUSERSITE=1; python-qgis.bat -m pip install --target .testlibs pytest
# The SEG-Y tests need the optional library segyio (--no-deps: QGIS's own NumPy is used):
#   $env:PYTHONNOUSERSITE=1; python-qgis.bat -m pip install --target .testlibs --no-deps segyio
$ErrorActionPreference = "Stop"
$env:QT_QPA_PLATFORM = "offscreen"
$env:PYTHONNOUSERSITE = "1"
$repo = Split-Path -Parent $PSScriptRoot
$env:GW_TESTLIBS = Join-Path $repo ".testlibs"
# os._exit: QGIS/Qt teardown at interpreter shutdown crashes (access violation 0xC0000005) even when
# all tests pass, which would mask pytest's exit code. Flush, then exit with pytest's code directly.
$runner = "import os, sys; sys.path.insert(0, os.environ['GW_TESTLIBS']); import pytest; rc = int(pytest.main(sys.argv[1:])); sys.stdout.flush(); sys.stderr.flush(); os._exit(rc)"
Push-Location $repo
try {
    & "C:\Program Files\QGIS 4.2.3\bin\python-qgis.bat" -c $runner @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
