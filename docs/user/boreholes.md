# Borehole data in the Groundwork

This guide shows how to get borehole data, as clients usually deliver it, onto your sections and into the borehole viewer.

The plugin reads boreholes from ordinary QGIS layers. You set those up once per project in **Context Layers…**. There is no import dialog yet: you bring the data in with QGIS's own tools, as shown below.

Templates and a small made-up example are in [`templates/`](templates/):
- `boreholes_template.xlsx`, with the sheets `collars`, `layers` and `curves`;
- the same three tables as CSV files.

You can fill them in yourself, or send them to a client.

---

## 1. What the plugin needs

Three tables, linked by a **borehole ID**. Column names are free: you pick them in Context Layers….

### Collars: one point per borehole (required)

| Column (template name) | Required? | Content |
|---|---|---|
| `id` | yes | Borehole name or number, e.g. `BH1`. |
| `x`, `y` | yes | Coordinates, used to make the points (see step 3). |
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

---

## 2. Client layouts and how to get the three tables

Client exports differ every time. These are the layouts we see, and what to do with each.

**A. Separate sheets or files for collars and layers** (the easiest case).
- Use the collars sheet for the points (step 3), and the layers sheet as the layer table directly.
- If the layers are in several files, see C.

**B. Everything on one sheet**, with the borehole's name and coordinates repeated on every layer row.
- The sheet *is* the layer table: use it as it is.
- For the collars:
  1. Make points from the same sheet (step 3).
  2. Run **Processing Toolbox → Vector general → Delete duplicates by attribute** with the field `id`. This keeps one point per borehole.

**C. One file or sheet per borehole.**
- Copy the rows into one sheet, with an `id` column filled in on every row. This is the simplest way, in Excel.
- Or, in QGIS: open all of them and run **Processing Toolbox → Vector general → Merge vector layers**. This also works for tables without coordinates.

**Elevations instead of depths in the layer table:** add a depth column in Excel (`= ground elevation − layer elevation`) before you start.

**GeODin PDFs** are drawings, not data. They can't be read in yet. If you only have the PDF, type the layers into the template.

---

## 3. Into QGIS, step by step

1. **Open the Excel file:** Layer → Add Layer → Add Vector Layer…, then choose the `.xlsx` file.
   - QGIS asks which sheets to add: add each one you need.
   - The first row is used as column names.
   - Columns that contain only whole numbers come in as integers, and that's fine.
2. **Check the columns:** right-click the layer → Open Attribute Table.
   - Numbers should be right-aligned.
   - Numbers that show as text usually mean a cell in that column holds text: a unit, a dash or a note.
3. **Make the collar points:** Processing Toolbox → search "points layer from table" (**Create points layer from table**).
   - Input: the collars sheet.
   - X field: `x`, Y field: `y`.
   - Target CRS: the coordinate system of those coordinates.
   - Save to a file, e.g. `collars.gpkg` (recommended), so the points stay when the Excel file changes.
4. **Optional: save the tables as GeoPackage too.** Right-click → Export → Save Features As…, then GeoPackage. Recommended if the Excel file is still being edited, or if it comes from a network drive.

**CSV instead of Excel:** use Layer → Add Layer → **Add Delimited Text Layer…**.
- Set the delimiter, and tick **Decimal separator is comma** for German CSV files (`0,4`). A decimal comma that QGIS doesn't know about makes the plugin skip that row.
- Choose "No geometry" for the layer and curve tables. For collars, it can make the points straight away from the X and Y columns.

---

## 4. Context Layers…: field by field

**Groundwork** menu → **Context Layers…** → **Boreholes**. Each borehole entry is one set of collars with its tables. Use **Add** for a second set, e.g. state boreholes next to your own.

| Field in the dialog | What to choose |
|---|---|
| Borehole layer | your collar points |
| Borehole id field | `id` |
| Ground elevation field | `elevation` (or None: then the DEM or the surface line gives the height) |
| Total depth field | `total_depth` (optional) |
| Interval table | your layer table |
| Intervals: borehole id / top / bottom field | `id`, `top`, `bottom` |
| Intervals: text field | `lithology` |
| Add Curve Table | the curve table, its id and depth fields; tick each curve and give its unit |

Press **Apply** or **OK**. The section redraws with the boreholes as columns.

**How they look is set in the borehole viewer**, and the section follows:
- **Layer text** and the ticked **Curves** in the viewer's side panel are drawn on the section too.
- So are the **column width** and **opacity** under "On the section".
- These settings apply to **every** borehole entry at once (e.g. your cores and the state boreholes).

---

## 5. Styling

- **Borehole Style…**, in Context Layers… or in the borehole viewer, opens QGIS's own style editor.
  - **Categorized** on `lithology`, then **Classify**, gives one class per value.
  - **Patterns…** (button in the same window) gives every class a colour and an FGDC lithology pattern in one table.
    - Type in a pattern box to search, e.g. "sand" or "607".
    - OK hands the result to QGIS's editor as ordinary symbols: a colour fill with the pattern on top.
  - You can also set any class by hand: double-click it, then pick a colour or an **SVG fill**.
    - The FGDC patterns are listed among the SVG fills, named by code and name, e.g. "607 Massive sand or sandstone".
    - Codes 601–686 are sediments, 701–733 metamorphic and igneous rocks.
  - **Export… / Import…** save the style as a `.qml` file for the next project.
  - **Ready-made styles:** Import… opens in the plugin's own styles folder.
    - `din_codes.qml`: German short codes G, S, fS, U, T, H, Mu, A …
    - `iso_14688.qml`: EN ISO 14688-1 symbols Gr, Sa, Si, Cl, Or …

    Both are Categorized on a column `lithology`; switch to your column after importing. Their colours and patterns are the plugin's choice, not a standard's drawing rules.
  - **A class only applies to values that are exactly that code** ("fS, ms, u'" is not "fS"). To style by the main component, add a column in QGIS's field calculator with `trim(regexp_substr("lithology", '^[^,;]+'))` and style by that column.
- **Curve style…** in the viewer sets each curve's colour, line, fill, and linear or log scale with min/max.
- **Leaving a borehole out of one section**: right-click its column in the section → **Hide in Section**. It leaves that profile's section and plates only; the map, other profiles and your layer are not changed. The borehole viewer still shows it, faded and marked "hidden in section". There, click a column to select it (Ctrl+click for several) and right-click → **Hide in Section** or **Show in Section**. **Show › Hidden boreholes** switches the hidden ones off in the viewer. A borehole whose id field is empty cannot be hidden on its own.
- Without a saved style, each layer text gets its own neutral colour. The plugin never guesses a colour from the words.

---

## 6. When something doesn't show

| What you see | Usual cause | Fix |
|---|---|---|
| No boreholes on the section | Points are farther from the line than the **buffer** | Raise the buffer in Context Layers… |
| No boreholes on the section | Wrong coordinate system when you made the points | Make the points again with the right CRS (step 3) |
| A column but no layers in it | The layer table's IDs don't match the collars (spelling, `BH 1` vs `BH1`) | Compare the ID columns in both attribute tables |
| Some layers are missing | Empty top or bottom, or a decimal comma in a CSV | Fill in the cells; use the decimal-comma option (step 3) |
| Boreholes far too high or low | Layer table holds elevations, not depths; or the elevation column uses another height system | Convert to depths; check the heights against the DEM (the red triangle shows large differences) |
| Red triangle at the top | Elevation column and DEM disagree by more than the tolerance | Check which one is right; hover the top to see both numbers |
| "No height" in the viewer | No elevation, no DEM, no surface line at that point | Fill in the elevation, or choose a DEM in Context Layers… |
| No curves in the viewer | No curve table set up, or its IDs don't match | Context Layers… → Add Curve Table; compare IDs |

---

*These steps are checked by the plugin's tests on the templates* (`tests/docs/test_borehole_guide.py`).
