# Runs pytest inside QGIS 4.2.3's Python. Extra args are passed through.
# pytest is not bundled with QGIS; install it locally with:
#   $env:PYTHONNOUSERSITE=1; python-qgis.bat -m pip install --target .testlibs pytest
$ErrorActionPreference = "Stop"
$env:QT_QPA_PLATFORM = "offscreen"
$env:PYTHONNOUSERSITE = "1"
$repo = Split-Path -Parent $PSScriptRoot
$env:GW_TESTLIBS = Join-Path $repo ".testlibs"
$runner = "import os, sys; sys.path.insert(0, os.environ['GW_TESTLIBS']); import pytest; sys.exit(pytest.main(sys.argv[1:]))"
Push-Location $repo
try {
    & "C:\Program Files\QGIS 4.2.3\bin\python-qgis.bat" -c $runner @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
