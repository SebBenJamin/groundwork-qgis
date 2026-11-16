# Add data

This page shows how to bring a model into Groundwork from an ordinary text file, and what the Add Data dialog asks.

**Groundwork → Add Data…** is the one dialog for every file. Formats the plugin knows (R2/ResIPy, ZondRes2D, VTK, BERT/pyGIMLi data) are recognised as before. For any other text table you say what the columns are. The menu entry is available as soon as a Groundwork project is open; no profile has to be open.

## What the dialog asks

Choose the file; the dialog fills in what it can guess and shows a preview. You check three things.

### File Format (text tables only)

- **Delimiter**: Detect, Comma, Semicolon, Tab or Space.
- **Skip lines** (lines before the table), and **First row holds column names**.
- **Decimal comma** (off while Detect is chosen; Detect decides).

### What the Columns Are

- **Position**: a **distance along the line**, or **map coordinates** (easting and northing, with their coordinate system; a file that looks like degrees preselects EPSG:4326).
- **Vertical**, which has three meanings:
  - **Elevation**: heights above sea level;
  - **Depth below surface**: the depths must be all positive or all negative (the size is used); a column with both signs is refused with a message;
  - **Local height**: heights against an arbitrary zero. The section is drawn as a *local section*, see [Reference height](reference-height.md).
- **Value**: **Resistivity** (Ω·m) or **Other** (type a name and a unit). Tick **Values are log10** when the column holds log10 of the values.

First guesses come from the column names (a unit in brackets is ignored, so `Rho [ohm.m]` is found) and from the numbers (a constant column is never a position). Text columns, such as remarks, are shown and marked "not used".

### Preview

The first rows with each column's role. Below the scrolling part of the dialog, right above **Add**, a fixed block always shows the result of the check: a summary line, the fit report (see [Placement](placement.md#known-points-and-the-fit-report)), a note about electrodes (see [Placement](placement.md#electrodes-you-did-not-import)) and warnings. For a long file the summary is made from the first 1000 rows, and says so; it also lists skipped rows (with the first line number). The whole file is read when you press **Add**. If something fails, nothing is saved. Once the data are saved, a problem refreshing the view afterwards only shows a warning on the message bar ("Saved, but the view could not be refreshed: …"): the data are in the project, so do not add the file again.

The dialog remembers the last table settings and column roles and offers them again for a file with the same columns.

### Where the Line Runs

Which profile the file belongs to, or where a new one is:

- an existing profile (preselected when a profile is open; the group is then collapsed and **Other…** opens it);
- a selected line feature on the map;
- start and end points (use **Pick on Map**);
- a positions file or a point layer;
- the file's own coordinates (map coordinates only).

**Distance 0 is at** the start of the line, the end of the line, or station 1 (when the profile has stations), plus an offset you can type. A **Station set** row appears when the profile has several sets, and a **Method** row when the import creates stations.

The new line and its points are drawn on the map while the dialog is open.

## Step by step

### (a) A text table in distance and depth, on a drawn line

1. Draw or select the line in QGIS, or have the profile already (**New Profile…**).
2. **Add Data…** and choose the file. Check **File Format**.
3. Under **What the Columns Are** choose Position: **Distance along the line**, Vertical: **Depth below surface**, Value: **Resistivity**, and check the columns the dialog guessed.
4. Under **Where the Line Runs** choose the profile (or the selected line, or start and end points). Say where distance 0 is.
5. Read the preview, then press **Add**.

With no surveyed positions the model sits rigidly on the line: file distance 0 at the point you chose, one metre per metre. Without any heights the section is a local section (see [Reference height](reference-height.md)).

### (b) A file with map coordinates

1. **Add Data…**, choose the file, set Position to **Map coordinates**, and pick the easting and northing columns and their coordinate system.
2. Vertical is usually **Elevation**.
3. Under **Where the Line Runs** choose **the file's own coordinates**, or an existing profile.
4. **Add**.

Each point is projected onto the line. Points past the ends of the line (a model's padding) are placed along the line's first or last segment extended: before the start they get a negative distance, after the end a distance beyond the line's length. The preview says how many lie beyond the ends. A profile made from the file's own coordinates follows the cells' map positions: the positions are ordered along the line and simplified to its bends. A model that covers an area instead of following a line is refused. Lines you draw or import are used as drawn; GPS tracks are not smoothed. The preview map shows the line before you save.

To add surveyed positions afterwards, see [Placement on the electrodes](placement.md#adding-surveyed-positions-later).
