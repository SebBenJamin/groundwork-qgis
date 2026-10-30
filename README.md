# Geophysics Workbench

A QGIS 4.2+ plugin for loading, displaying and interpreting georeferenced geophysical
profiles and sections (e.g. ERT).

**Status:** 0.1.1, a patch of the first test release (milestone M1). See the latest
[release note](docs/releases/0.1.1.md) (first release: [0.1.0](docs/releases/0.1.0.md)).

## Install

Requires QGIS 4.2 or newer.

1. **Plugins → Manage and Install Plugins… → Install from ZIP** (German QGIS:
   **Erweiterungen → Erweiterungen verwalten und installieren… → Aus ZIP installieren**).
2. Choose `geophysics_workbench-0.1.1.zip` and click **Install Plugin**.
3. A **Geophysics Workbench** menu appears in the menu bar.

## Open the demo

Unzip `geophysics_workbench-demo-0.1.1.zip` into any folder and open `demo_project.qgz`
in it (**Project → Open…**). Then **Geophysics Workbench → Pick profile on map** and click
the P1 line to show its section.

## What 0.1.0 (M1) does

- Profiles from an electrode table, a selected line feature or start/end points.
- ERT model sections (R2/ResIPy `f001_res.dat`, ZondRes2D XYZ, legacy VTK) drawn in a
  section panel under the map, following the topography; depth models are hung from the
  electrode elevations.
- Map and section linked by a cursor in both directions; per-model visibility, opacity and
  colour scale; vertical exaggeration.
- Profiles, stations and the model list are stored in a GeoPackage next to the QGIS project.

Not yet: projecting context data onto sections and interpretation (M2/M3).

## Development install

```powershell
scripts/dev_install.ps1
```

Creates a directory junction from the QGIS 4 default profile's plugin folder to
`geophysics_workbench/`. Requires QGIS 4.2.3 in `C:\Program Files\QGIS 4.2.3`.

## Release build

```powershell
& "C:\Program Files\QGIS 4.2.3\bin\python-qgis.bat" scripts/render_demo_section.py   # docs/releases/<version>-P1/P2.png
& "C:\Program Files\QGIS 4.2.3\bin\python-qgis.bat" scripts/package.py               # dist/*.zip
```

## Running tests

```powershell
scripts/test.ps1            # whole suite
scripts/test.ps1 tests/test_package.py -q
```

Tests run in QGIS's own Python (offscreen). pytest is not bundled with QGIS; install it once with
`$env:PYTHONNOUSERSITE=1; & "C:\Program Files\QGIS 4.2.3\bin\python-qgis.bat" -m pip install --target .testlibs pytest`.

## License

GPL-2.0-or-later. See `LICENSE`.
