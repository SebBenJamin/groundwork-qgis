# Adding data and placing it on a profile

This guide shows how to bring a model into the Geophysics Workbench from an ordinary text file, and how the plugin decides where along the line it sits.

**Geophysics Workbench → Add Data…** is the one dialog for every file. Formats the plugin knows (R2/ResIPy, ZondRes2D, VTK, BERT/pyGIMLi data) are recognised as before. For any other text table you say what the columns are. The menu entry is available as soon as a workbench project is open; no profile has to be open.

---

## 1. What the dialog asks

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
  - **Local height**: heights against an arbitrary zero. The section is drawn as a *local section*, see part 5.
- **Value**: **Resistivity** (Ω·m) or **Other** (type a name and a unit). Tick **Values are log10** when the column holds log10 of the values.

First guesses come from the column names (a unit in brackets is ignored, so `Rho [ohm.m]` is found) and from the numbers (a constant column is never a position). Text columns, such as remarks, are shown and marked "not used".

### Preview

The first rows with each column's role. Below the scrolling part of the dialog, right above **Add**, a fixed block always shows the result of the check: a summary line, the fit report (part 3), a note about electrodes (part 4) and warnings. For a long file the summary is made from the first 1000 rows, and says so; it also lists skipped rows (with the first line number). The whole file is read when you press **Add**. If something fails, nothing is saved. Once the data are saved, a problem refreshing the view afterwards only shows a warning on the message bar ("Saved, but the view could not be refreshed: …"): the data are in the project, so do not add the file again.

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

---

## 2. Step by step

### (a) A text table in distance and depth, on a drawn line

1. Draw or select the line in QGIS, or have the profile already (**New Profile…**).
2. **Add Data…** and choose the file. Check **File Format**.
3. Under **What the Columns Are** choose Position: **Distance along the line**, Vertical: **Depth below surface**, Value: **Resistivity**, and check the columns the dialog guessed.
4. Under **Where the Line Runs** choose the profile (or the selected line, or start and end points). Say where distance 0 is.
5. Read the preview, then press **Add**.

With no surveyed positions the model sits rigidly on the line: file distance 0 at the point you chose, one metre per metre. Without any heights the section is a local section (part 5).

### (b) A file with map coordinates

1. **Add Data…**, choose the file, set Position to **Map coordinates**, and pick the easting and northing columns and their coordinate system.
2. Vertical is usually **Elevation**.
3. Under **Where the Line Runs** choose **the file's own coordinates**, or an existing profile.
4. **Add**.

Each point is projected onto the line. Points past the ends of the line (a model's padding) are placed along the line's first or last segment extended: before the start they get a negative distance, after the end a distance beyond the line's length. The preview says how many lie beyond the ends. A profile made from the file's own coordinates follows the cells' map positions: the positions are ordered along the line and simplified to its bends. A model that covers an area instead of following a line is refused. Lines you draw or import are used as drawn; GPS tracks are not smoothed. The preview map shows the line before you save.

### (c) Adding surveyed positions later

1. Open the profile in the section panel and choose **Profile Properties…**.
2. Under **Set surveyed positions** choose a positions file or a point layer, and the station set they replace (or a new set).
3. Choose **Keep the line** (the points are projected onto it; points more than 5 m off are listed first) or **Move the line to the points**. Moving asks first and names what moves.
4. **OK**. Everything is saved together, or not at all.

When the line moves, field notes and the current interpretation follow by map position, frozen interpretation versions keep their stored positions, and the models keep their place on the map. What lies past the ends of the old line (interpretation drawn over a model's padding, a note range) keeps its distance beyond the ends of the new one.

**Profile Properties…** also holds the **name**, the **station spacing** (empty clears it) and **Reference Height…**. It replaces Rename Profile…. Under the spacing it shows the fit report (part 3) for the spacing and positions as you edit them, before anything is saved.

---

## 3. Known points and the fit report

A **known point** is a surveyed position whose distance in the model file is known. A station gets its distance from the first of these that has one:

1. a distance column (stored with the station);
2. the electrode list of a readings file (e.g. a BERT `.data` file): station *n* is electrode *n*;
3. a **station spacing** you typed in Profile Properties: station number × spacing;
4. a spacing guessed from the model (part 4), used only when it fits.

With two or more known points the model sits at the real positions and is stretched evenly in between; outside them it continues one metre per metre.

The **fit report** says how far the file's distances and the surveyed positions disagree, for example:

> 5 known points, largest shift 1.6 m at station 16

A shift larger than half the gap between known points is shown in the warning colour and followed by *Check the station spacing or the station numbers.*: the file and the survey probably do not belong together, or the spacing is wrong. Add Data shows the report in its result block, Profile Properties under the station spacing.

- A typed spacing is stored with the profile. A guessed one never is.
- A guess that does not fit is not used. The profile then says *Known points not used: the station spacing guessed from the model does not fit them; type the station spacing in Profile Properties*.
- Stations numbered out of order along the line are named the same way.
- Stations that an older version invented from a spacing on a drawn line (no heights, exactly on the line, evenly spaced) are never known points. They stay as they are.

---

## 4. Electrodes you did not import

When a profile has no stored stations, the section still shows where the electrodes are, from the best source there is:

| Kind | Where it comes from |
|---|---|
| **imported** | stored stations (a positions file, a point layer) |
| **from the readings file** | the electrode list of the measured data |
| **from spacing** | the station spacing you typed |
| **guessed** | the model's top edge, only for models given as rows or columns of cells |

A triangulated mesh, such as the pyGIMLi VTK results, gives no guess: its surface nodes are three to four times denser than the electrodes and reach past the line ends. A profile with only such a model and no positions says *No electrode positions: import them or type the spacing in Profile Properties*.

Derived electrodes are **never stored**. They show

- on the map as the temporary layer **electrodes (derived)**, in the Geophysics Workbench group. Style it like any layer; your style is kept with the QGIS project. If you remove it, it comes back the next time the project is opened;
- in the section as dashed ticks.

A line under the section says which kind is shown, any placement note, and for a local section *Local section: no heights yet, values are depth below the surface*.

Field notes by electrode number work on derived electrodes too; their label says "(guessed)" or "(from spacing)".

A guess is a guess. In the small demo models the cells are half an electrode spacing wide, so the guessed spacing comes out as half the real one (see the 0.9.0 release notes). Type the spacing when you know it.

---

## 5. Local sections and the reference height

A profile with no station heights, no DEM and no model with real elevations is drawn **local**: the ground is flat at 0, or at the top of a Local height model. The Topography list shows **Local**.

To give it real heights, choose **Reference Height…** (next to the Topography list, and in Profile Properties…): type one height at one position, a distance or an electrode, and the whole section moves to real elevations; the view zooms to the whole section at its new height. **Ctrl+Z** undoes it; **Remove** takes it away. If the workbench file cannot be written at that moment (read-only, open in another program), a line under the section says so and nothing changes.

- Interpretation drawn on a local section moves with the reference height. When real heights arrive later (a positions file with elevations, a DEM), it is moved once onto the real ground, keeping its depth below the ground. Export does this first if needed.
- While a profile is local there are no DEM line and no boreholes (drawing, hover, snapping, picking on the map, plate legends), no ties with other profiles, and no interpretation export for it; a message says why.
- The section panel's own axis cannot be relabelled, so depths show there as negative numbers. Plates show them as positive depths.

A profile whose stations have no heights but whose models carry real elevations (such as the pyGIMLi VTK results) gets a ground line from the first model's top. A depth model on a profile without any heights is drawn as a local section, not refused.

---

## 6. Known limits

- GPS tracks and other lines are used as drawn, with no smoothing.
- Readings (a, b, m, n with apparent resistivity) from free text files are not supported yet.
- A 3D model only two cells wide is not refused as "an area" and may give a zig-zag line; the map preview shows it before you save.
- **Add Data…** has no **Reverse the line**; **New Profile…** has.
