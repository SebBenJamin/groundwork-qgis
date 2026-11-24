# Troubleshooting

What to do when something doesn't look right.

## When the section panel is empty

| What you see | Usual cause | Fix |
|---|---|---|
| "No project open." | No Groundwork project is open in this QGIS project | **Groundwork → New Groundwork Project…** or **Open Groundwork Project…** ([Projects and profiles](howto/projects-and-profiles.md)) |
| The **Profile** list is empty | The Groundwork project has no profiles yet | **New Profile…** or **Add Data…** |
| "Profile not found in the Groundwork project" | The profile was deleted, or another Groundwork file is open | Choose another profile; check which Groundwork project the QGIS project opens |
| A profile without a model | The model's file could not be read | Its row in **Layers** says why; a moved file must go back to its folder, or be added again |

## When a model sits in the wrong place

| What you see | Usual cause | Fix |
|---|---|---|
| A profile line far away from the survey, or thousands of kilometres long | Wrong coordinate system for the easting and northing | Choose the file's own CRS under ② in **Add Data…**; degrees get EPSG:4326 |
| "The model's map coordinates do not follow a line" | The file holds an area or a 3D model | Draw the profile line, then add the file to it |
| "N rows have no map position (-9999)" | The export writes -9999 for cells past the line | Nothing to do: those rows are left out (since 0.14.2). A profile made from such a file with an older version: delete it and add the file again |
| The model sits too high or too low | Depth read as elevation, or the other way round | **Vertical** in **Add Data…**: **Depth below surface** or **Elevation** |
| The model is shifted along the line | Distance 0 of the file is not the start of the line | Set where distance 0 lies under ③ in **Add Data…**, or add the surveyed positions ([Placement](howto/placement.md)) |
| The model is drawn in depth with no terrain | The profile has no heights: a local section | See below |

## Local sections (no heights)

A profile without any heights (no station heights, no DEM, a depth model) is drawn as a local
section, in depth below its surface. Until it has a [reference height](howto/reference-height.md),
it has no DEM line, no boreholes, no ties with other profiles, no interpretation export and no
3D view. **Reference Height…** next to **Topography** lifts it to real heights with one height
at one place.

## When boreholes don't show

| What you see | Usual cause | Fix |
|---|---|---|
| No boreholes on the section | Points are farther from the line than the **Search distance from the line** | Raise it in **Context Layers…** |
| No boreholes on the section | Wrong coordinate system when you made the points | Make the points again with the right CRS ([step 3](howto/boreholes.md#into-qgis-step-by-step)) |
| No boreholes on the section | Hidden in this section | Right-click the section → **Show Hidden Boreholes** |
| A column but no layers in it | The layer table's IDs don't match the collars (spelling, `BH 1` vs `BH1`) | Compare the ID columns in both attribute tables |
| Some layers are missing | Empty top or bottom, or a decimal comma in a CSV | Fill in the cells; use the decimal-comma option ([step 3](howto/boreholes.md#into-qgis-step-by-step)) |
| Boreholes far too high or low | Layer table holds elevations, not depths; or the elevation column uses another height system | Convert to depths; check the heights against the DEM (the red triangle shows large differences) |
| Red triangle at the top | Elevation column and DEM disagree by more than the tolerance | Check which one is right; hover the top to see both numbers |
| "No height" in the viewer | No elevation, no DEM, no surface line at that point | Fill in the elevation, or choose a DEM in **Context Layers…** |
| No curves in the viewer | No curve table set up, or its IDs don't match | **Context Layers… → Add Curve Table**; compare IDs |

## In the 3D view

| What you see | Usual cause | Fix |
|---|---|---|
| Nothing of Groundwork in 3D | Nothing is shown until you ask | **Groundwork → Show in 3D…**, tick, **Apply** |
| A profile is greyed out in **Show in 3D…** | A local section | Give it a [reference height](howto/reference-height.md) |
| A curtain hides under the terrain | The terrain is on and the model lies below it | Switch the terrain off, or **Cut 3D View Along Profile** with the section panel's **3D** button |
| The 3D view turns white or hangs | A large web layer (WFS) loads for the 3D view | Switch such layers off while you use the 3D view, or save a local copy (right-click → **Export → Save Features As…**) |

## Demos

| What you see | Usual cause | Fix |
|---|---|---|
| No aerial image or background map | No internet connection | The demos load them from the web; the sections work without |
| Gülpe: no geology map and no geology strips on the section | The state's geology web services (WFS) are down or slow | Try later; the model, cores and state boreholes still show |
| A demo looks different from the pictures | It was changed while you tried it | Unzip the demo again into a new folder |

## Known limits of Add Data

- GPS tracks and other lines are used as drawn, with no smoothing.
- Readings (a, b, m, n with apparent resistivity) from free text files are not supported yet.
- A 3D model only two cells wide is not refused as "an area" and may give a zig-zag line; the map preview shows it before you save.
- **Add Data…** has no **Reverse the line**; **New Profile…** has.
