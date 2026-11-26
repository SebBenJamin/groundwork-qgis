# Borehole tables

What borehole data Groundwork needs, and how to get it from the layouts clients deliver.

Templates with a small made-up example, to download:

- [`boreholes_template.xlsx`](../templates/boreholes_template.xlsx), with the sheets `collars`, `layers` and `curves`;
- the same three tables as CSV files: [`boreholes_collars.csv`](../templates/boreholes_collars.csv),
  [`boreholes_layers.csv`](../templates/boreholes_layers.csv) and
  [`boreholes_curves.csv`](../templates/boreholes_curves.csv).

You can fill them in yourself, or send them to a client. How to load them into QGIS and connect them is in [Boreholes and logs](../howto/boreholes.md).

## What the plugin needs

Three tables, linked by a **borehole ID**. Column names are free: you pick them in Context Layers….

### Collars: one point per borehole (required)

| Column (template name) | Required? | Content |
|---|---|---|
| `id` | yes | Borehole name or number, e.g. `BH1`. |
| `x`, `y` | yes | Coordinates, used to make the points (see [step 3](../howto/boreholes.md#into-qgis-step-by-step)). |
| `elevation` | recommended | Ground height at the borehole, in metres, in the same height system as your sections. |
| `total_depth` | optional | Final depth in metres. A borehole without layers is drawn as an empty column down to this depth. |

### Layers: one row per layer (optional)

| Column | Required? | Content |
|---|---|---|
| `id` | yes | The borehole's ID, as in the collars. |
| `top`, `bottom` | yes | Depth of the layer's top and bottom in **metres below the ground at the borehole**, positive downwards (0 = ground). |
| `lithology` (or any text) | recommended | Shown as layer text, and what you usually style by. |
| further columns | optional | Anything else, e.g. a code, a description or a stratigraphic unit. You can style by any of them. |

### Curves: one row per depth (optional)

| Column | Required? | Content |
|---|---|---|
| `id` | yes | The borehole's ID. |
| `depth` | yes | Metres below the ground, positive downwards. |
| one column per curve | yes | e.g. `gamma_api`, `resistivity_ohmm`. Empty cells are gaps: the line breaks there. |

Logs in **LAS files** need no curves table of your own: **Import LAS…** in Context Layers
makes one (see [Logs from LAS files](../howto/boreholes.md#logs-from-las-files)).

### Rules the plugin follows

- **IDs are compared as text, without leading or trailing spaces.** `7` (a number) in the collars matches `" 7 "` (text) in the layers.
  - Spelling still matters: `BH 1` and `BH1` are different boreholes.
- **Depths, never elevations, in the layers and curves.** The plugin hangs them from the borehole's top. If your layer table has elevations (m a.s.l.), convert them first: depth = ground elevation − layer elevation.
- **If top > bottom in a row, the two are swapped.** Rows with an empty top or bottom are left out.
- **Where a borehole's top comes from:**
  1. the `elevation` column;
  2. if that is empty, the DEM chosen in Context Layers…;
  3. if there is no DEM either, the section's surface line.

  The readout says which one was used.

- **Height check:** when the elevation column and the DEM differ by more than the tolerance in Context Layers…, the borehole gets a **red triangle**, and hovering shows both numbers. Nothing is corrected for you.
- **Which boreholes appear on a section:** collar points within the **buffer** (Context Layers…, distance from the profile line) are projected onto it.
- **Coordinates:** the collar points can be in any coordinate system QGIS knows. They are transformed to the project's system.

## Client layouts and how to get the three tables

Client exports differ every time. These are the layouts we see, and what to do with each.

**A. Separate sheets or files for collars and layers** (the easiest case).

- Use the collars sheet for the points ([step 3](../howto/boreholes.md#into-qgis-step-by-step)), and the layers sheet as the layer table directly.
- If the layers are in several files, see C.

**B. Everything on one sheet**, with the borehole's name and coordinates repeated on every layer row.

- The sheet *is* the layer table: use it as it is.
- For the collars:
  1. Make points from the same sheet ([step 3](../howto/boreholes.md#into-qgis-step-by-step)).
  2. Run **Processing Toolbox → Vector general → Delete duplicates by attribute** with the field `id`. This keeps one point per borehole.

**C. One file or sheet per borehole.**

- Copy the rows into one sheet, with an `id` column filled in on every row. This is the simplest way, in Excel.
- Or, in QGIS: open all of them and run **Processing Toolbox → Vector general → Merge vector layers**. This also works for tables without coordinates.

**Elevations instead of depths in the layer table:** add a depth column in Excel (`= ground elevation − layer elevation`) before you start.

**GeODin PDFs** are drawings, not data. They can't be read in yet. If you only have the PDF, type the layers into the template.
