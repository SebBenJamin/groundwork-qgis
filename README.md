# Geophysics Workbench

A QGIS plugin that brings geophysical profiles and sections into their map context: ERT
models and measured data as sections under the map, boreholes, geology and crossing profiles
on the section, your interpretation as QGIS layers, and report plates in the QGIS layout.

**Version 0.9.1. Experimental.** Shared privately for testing; please do not pass it on.
What changed: [0.9.1 release note](docs/releases/0.9.1.md), earlier notes in
[docs/releases](docs/releases/).

## What it does

- **Profiles** from an electrode table, a line on the map or start and end points
  (**New Profile…**; name, spacing and positions later in **Profile Properties…**).
- **Add Data…**: any text table (distance or map coordinates, elevation, depth or local height)
  can be added as a model by saying what its columns are; the plugin places it on the surveyed
  electrodes when it knows them, and shows a fit report. See
  [adding data](docs/user/import.md).
- **Sections** in a panel under the map, linked to it by a cursor both ways:
  - ERT models from R2/ResIPy, ZondRes2D, pyGIMLi/BERT and VTK, plus measured data and misfit;
  - drawn as cells, a smooth field or contours (automatic, or major and minor levels you type),
    with QGIS colour ramps, a coverage fade and automatic vertical exaggeration.
- **Context on the section**: crossing lines, points, boreholes as lithology columns with log
  curves, one or several surface strips (geology maps stacked above the ground, each with a
  title), a DEM line, and ties to crossing profiles showing their model.
- **Borehole viewer**: a profile's boreholes side by side; leave a borehole out of one section.
- **Interpretation**: lines, polygons and points drawn per profile with type, name, confidence
  and note; undo and redo; frozen versions; QGIS layers in 2D and 3D; DXF and CSV export.
- **Field notes** along a profile, styled like any QGIS layer.
- **Plates**: A4 and A3 report layouts with stacked sections, colour bars, legends, a mini-map
  and a title block; your text edits survive updates; vector PDF export.

Your work is kept in one GeoPackage next to the QGIS project (`<project>_workbench.gpkg`).
Model files are read where they lie and never changed.

## Install

Requires **QGIS 4.2** or newer.

1. Get `geophysics_workbench-0.9.1.zip` (from the person who shared this with you, or build
   it, see *For developers*).
2. In QGIS: **Plugins → Manage and Install Plugins… → Install from ZIP** (German QGIS:
   **Erweiterungen → Erweiterungen verwalten und installieren… → Aus ZIP installieren**).
3. Choose the zip and click **Install Plugin**. A **Geophysics Workbench** menu appears.

## Try it with the demos

| Folder | Data | Open |
|---|---|---|
| `demo_guelpe/` | Real: ERT, sediment cores and state survey data from Lake Gülpe (Havel, Brandenburg) | `guelpe_project.qgz` |
| `demo_erfurt/` | Real: seven ERT lines and 56 cores from Erfurt (Thuringia) | `erfurt_project.qgz` |
| `demo/` | Synthetic: three ERT formats, made-up boreholes and geology | `demo_project.qgz` |

The background maps and the Gülpe state layers are loaded from the internet. Choose
**Geophysics Workbench → Show Section Panel**, pick a profile, then try **Display…**, the
borehole viewer and **Plates…**. The user guides explain more:
[adding data and placement](docs/user/import.md),
[boreholes and logs](docs/user/boreholes.md),
[field notes, dataset info and plates](docs/user/plates.md).

Opening a demo writes to its workbench file; keep a copy of the folder if you want to start
over.

## Feedback

Please report problems and wishes as GitHub issues: what you did, what you expected, what
happened, and a screenshot if it helps.

## For developers

- **Tests** run in QGIS's own Python, offscreen: `scripts/test.ps1` (whole suite) or
  `scripts/test.ps1 tests/test_package.py -q`. pytest is not bundled with QGIS; install it
  once into `.testlibs`:
  `$env:PYTHONNOUSERSITE=1; & "<QGIS folder>\bin\python-qgis.bat" -m pip install --target .testlibs pytest`.
- **Release zips** (`dist/`): `& "<QGIS folder>\bin\python-qgis.bat" scripts/package.py`.
- **Working copy in QGIS**: `scripts/dev_install.ps1` links `geophysics_workbench/` into the
  plugin folder of your QGIS 4 default profile.
- The scripts expect QGIS 4.2.3 in its default install folder (`C:\Program Files\QGIS 4.2.3`).

## Data sources and licences

The plugin's code is licensed under **GPL-2.0-or-later** (see `LICENSE`). The demo data is
open data from the sources below; each demo folder also has an `ATTRIBUTION.md` with the
details.

**Gülpe demo** (`demo_guelpe/`)
- ERT: Pohle, M.; Birnstengel, S.; Werban, U. (2025): 2D-ERT data measured in June 2023 and
  June 2024 in the Lower Havel Inner Delta near Lake Gülpe, Brandenburg (Germany). PANGAEA,
  https://doi.org/10.1594/PANGAEA.983478. CC BY 4.0.
- Cores: Köhler, A.; Kaniecki, M.; Schneider, B.; Zielhofer, C. (2025): Field based and
  laboratory data of sediment cores from the Lower Havel Inner Delta near Lake Gülpe. PANGAEA,
  https://doi.org/10.1594/PANGAEA.983887. CC BY 4.0.
- Both belong to: Köhler, A. et al. (2025): Geophysical, Sedimentological and Geochemical Data
  from the Lower Havel Inner Delta (Gülpe Island), Brandenburg (Germany). PANGAEA,
  https://doi.org/10.1594/PANGAEA.983208; data paper: Data in Brief 112372,
  https://doi.org/10.1016/j.dib.2025.112372.
- Boreholes (Bohrpunktkarte) and geology (Geologische Karte 1 : 25 000, and the GÜK300
  switched off on the map; both drawn as strips on the section), live WFS: © LBGR,
  dl-de/by-2-0.
- DGM1 terrain model (tiles merged and cropped) and DOP20 aerial images (live WMS):
  © GeoBasis-DE/LGB, dl-de/by-2-0.
- Waterways: © OpenStreetMap contributors, ODbL.

**Erfurt demo** (`demo_erfurt/`)
- ERT: Silbermann, M.; Pohle, M.; Jung, P.; Werban, U. (2025): 2D-ERT data for localizing a
  Black Death mass grave in Erfurt, Thuringia (Germany). PANGAEA,
  https://doi.org/10.1594/PANGAEA.974818. CC BY 4.0.
- Cores: Hein, M. et al. (2026): What the landscape can tell: An integrative stratigraphic
  prospection approach to localize a Black Death mass grave in Erfurt/Central Germany.
  PLoS ONE 21(1): e0337410, https://doi.org/10.1371/journal.pone.0337410, Supporting
  Information S1 File, Suppl. Table 3. CC BY 4.0.

**Synthetic demo** (`demo/`)
- Power line and pylons: © OpenStreetMap contributors, ODbL. Everything else (boreholes,
  geology, terrain, ERT models) is made up for the demo and does not describe the real ground.

**All demos:** background map © OpenStreetMap contributors, ODbL,
https://www.openstreetmap.org/copyright.

Licences: CC BY 4.0, https://creativecommons.org/licenses/by/4.0/ ·
Datenlizenz Deutschland Namensnennung 2.0 (dl-de/by-2-0), https://www.govdata.de/dl-de/by-2-0 ·
ODbL, https://opendatacommons.org/licenses/odbl/
