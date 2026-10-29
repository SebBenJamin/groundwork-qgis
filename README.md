# Geophysics Workbench

A QGIS 4.2+ plugin for loading, displaying and interpreting georeferenced geophysical
profiles and sections (e.g. ERT).

**Status:** pre-0.1, in development.

## Development install

```powershell
scripts/dev_install.ps1
```

Creates a directory junction from the QGIS 4 default profile's plugin folder to
`geophysics_workbench/`. Requires QGIS 4.2.3 in `C:\Program Files\QGIS 4.2.3`.

## Running tests

```powershell
scripts/test.ps1            # whole suite
scripts/test.ps1 tests/test_package.py -q
```

Tests run in QGIS's own Python (offscreen). pytest is not bundled with QGIS; install it once with
`$env:PYTHONNOUSERSITE=1; & "C:\Program Files\QGIS 4.2.3\bin\python-qgis.bat" -m pip install --target .testlibs pytest`.

## License

GPL-2.0-or-later. See `LICENSE`.
