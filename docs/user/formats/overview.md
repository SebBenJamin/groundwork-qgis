# Methods and formats

Which methods Groundwork works with, which files it reads, and what it writes.

## Methods

| Method | What you can bring in | Shown as |
|---|---|---|
| **ERT** (resistivity) | inversion models; measured readings; the misfit of an inversion | resistivity section (Ω·m); readings and misfit as pseudosections |
| **Seismic refraction** | velocity models, from any program that writes one of the formats below | Vp section (m/s), with its ray coverage if the file has one |
| **Seismic reflection** | processed sections (stack, migrated or depth section) as SEG-Y | the section in depth, in grey or any colour ramp |
| any other method | a model or grid as a text table | a section of the value you name, with its unit |

Ground-penetrating radar in its own formats is planned; radar exported as SEG-Y loads now.

Everything is 2D: one section along one profile line. 3D models and 3D electrode layouts are refused with a message.

## Files you add with Add Data

**Groundwork → Add Data…** recognises these formats by their content (some also by their name). A file that fits none of them can still be read as a [text table](#any-text-table).

| Format | Typical file | Method | What it brings in |
|---|---|---|---|
| [R2 / ResIPy model](#r2-resipy-model) | `f001_res.dat` | ERT | model |
| [VTK (legacy, ASCII)](#vtk-legacy-ascii) | `*.vtk` from ResIPy, pyGIMLi, BERT, Refrapy | ERT or seismic refraction | model, with coverage or sensitivity |
| [ZondRes2D XYZ](#zondres2d-xyz) | model exported as XYZ text | ERT | model |
| [Refrapy velocity model](#refrapy-velocity-model) | `<line>_xzv.txt` | seismic refraction | model, with ray coverage and geophone positions |
| [pyGIMLi / BERT data](#pygimli-bert-data) | `*.data`, `*.ohm`, `*.dat` | ERT | measured readings; with a response file, the misfit |
| [R2 / ResIPy misfit](#r2-resipy-misfit) | `f001_err.dat` | ERT | misfit, observed and calculated readings |
| [SEG-Y](#seg-y) | `*.sgy`, `*.segy` | seismic reflection | processed section, with the trace positions when the file has them |
| [Any text table](#any-text-table) | `*.csv`, `*.txt`, `*.xyz`, … | any | model, with the columns you assign |

The **Method** row in Add Data is preselected from the file (a velocity file proposes Seismic refraction, a SEG-Y file Seismic reflection); measured readings and misfits are always ERT. How the file is placed on its profile line is in [Add data](../howto/add-data.md#where-the-line-runs).

### R2 / ResIPy model

- One row per cell centre: `x  z  resistivity  log10(resistivity)`, no header, z as elevation.
- Recognised by the name `f001_res.dat` (any three digits) or, when renamed, by four columns where the fourth is the log10 of the third. The digits are kept as the iteration.
- The five-column 3D result (`x y z ρ log ρ`) is refused.

### VTK (legacy, ASCII)

- `# vtk DataFile` header, `ASCII`, `DATASET UNSTRUCTURED_GRID`, with triangle and quad cells: the mesh is drawn as it is, cell by cell.
- The value: an array named *velocity* is a refraction model; otherwise the linear *resistivity* array (not its log10); otherwise the first array.
- Coverage: a *coverage* or *sensitivity* array (BERT, ResIPy) is used to fade the unresolved parts; for a velocity model, the ray coverage.
- Not read: binary VTK, the VTK 5.1 layout (OFFSETS / CONNECTIVITY), other cell types, VTU/XML files.

### ZondRes2D XYZ

- Header like `#X  Z  log_Rho  Rho  X,m  Y,m`: distance, Z, log10 resistivity, resistivity; further map columns are ignored.
- Recognised by content: the third column is the log10 of the fourth (R2 files have it the other way round).
- Z counts as depth when the header says *depth*. Otherwise choose its meaning under **Z means** in Add Data.

### Refrapy velocity model

- Refrainv's **Save results**: the header `x z velocity converage standardized coverage sc_v` (Refrapy's own spelling) and one row per cell centre.
- Velocity in m/s and the ray coverage come in; the lowest coverage Refrainv counts as resolved becomes the default fade threshold.
- `<line>_topography.txt` next to the file gives the shot and geophone positions. Without it the stations are unknown, and the check result says so.

### pyGIMLi / BERT data

- The unified data format: the electrode count and positions (`# x z`), then the readings (`# a b m n rhoa err …`), optionally topography.
- The measured value is `rhoa`, else `r` × `k`, else `u` / `i` × `k`. Units in the column names (`err/%`, `u/mV`, `i/mA`) are applied.
- With a **Response file** (one calculated value per reading, e.g. `response.vector`), the misfit comes in too. Add Data looks for one next to the data file.
- Remote electrodes (far off the line) count as poles. A 3D electrode layout is refused.

### R2 / ResIPy misfit

- R2's error file: a header, then per reading the four electrode numbers, the normalised misfit, observed and calculated apparent resistivity, the weights and a flag.
- The electrodes are numbers only: put ResIPy's `electrodes.dat` next to the file.
- When `R2.out` lies next to it, its final RMS must agree with the misfit read.

### SEG-Y

- A processed 2D section: one trace per CDP (or shot) position, in two-way time or in depth.
  Read with the free library segyio, which Groundwork installs when you ask
  ([segyio](../howto/reflection-sections.md#segyio)).
- Byte order and sample format are found by segyio: standard big-endian files and
  little-endian files both open.
- Trace positions from the CDP, source or receiver fields of the trace headers (with their
  scalar and unit), from a coordinate file (trace or CDP number, easting, northing), or from a
  trace spacing you type.
- A velocity is taken from the text header only when a line names a sound velocity in m/s;
  otherwise you type it.
- Not read: 3D volumes, Seismic Unix `.su` files, navigation files in fixed formats (UKOOA,
  SPS). Unstacked gathers get a warning.

How a section is added, hung in depth and drawn is in
[Reflection sections](../howto/reflection-sections.md).

### Any text table

Any table of numbers, read with the columns you assign in Add Data:

- **Position**: distance along the line, or map coordinates (easting and northing in any coordinate system);
- **Vertical**: elevation, depth below the surface, or local height;
- **Value**: resistivity, P-wave velocity, or any other quantity with its unit; optionally as log10;
- **Coverage** (optional).

Delimiter, header lines, column names and decimal comma are detected or set by you. The details are in [Add data](../howto/add-data.md#file-format-text-tables-only).

## Data you bring in as QGIS layers

Everything around the sections comes from ordinary QGIS layers, in any format QGIS opens (GeoPackage, shapefile, CSV, Excel, WMS/WFS, GeoTIFF, …). You choose them in **Context Layers…**; they are only read, never changed.

| Data | Layer | Where it is described |
|---|---|---|
| Boreholes: collars, layers, curves | a point layer and two tables, linked by an ID | [Borehole tables](borehole-tables.md), [Boreholes and logs](../howto/boreholes.md) |
| Geology and other map units | polygon layers, drawn as bands over the section | [Context Layers…](../howto/boreholes.md#context-layers-field-by-field), **Band and DEM** tab |
| Terrain | a raster layer (DEM) | [Reference height](../howto/reference-height.md) |
| Crossing lines | line layers, marked where they cross the profile | **Lines** tab |
| Points near the line | point layers | **Points** tab |
| Surveyed station positions | a text table or a point layer | [Placement on the electrodes](../howto/placement.md) |

Borehole curves come as a table of depth and values; LAS well-log files are not read.

## What Groundwork writes

| What | Format | Where |
|---|---|---|
| Profiles, datasets, interpretation, field notes | GeoPackage | `<project>_groundwork.gpkg` next to the QGIS project |
| Report plates | vector PDF, one per plate or one combined | a folder you choose ([Report plates](../howto/plates.md)) |
| Interpretation in 3D | GeoPackage or DXF | **Interpretation → Export…** in the section panel |
| Curtains for the 3D view | LAS point clouds and pictures | the folder `<project>_groundwork_3d` ([The 3D view](../howto/3d-view.md)) |
| Borehole styles | QGIS style file (`.qml`) | [Styling](../howto/boreholes.md#styling) |
| Plate templates | QGIS layout template (`.qpt`) | [Plate templates](plate-templates.md) |

Your own files and layers are never changed.
