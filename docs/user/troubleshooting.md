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

## Reflection sections

### Reading SEG-Y needs the library segyio

Groundwork reads SEG-Y with segyio, a small free library that QGIS does not include. In
**Add Data…**, choose the SEG-Y file and press **Install segyio**: it is installed into a
Groundwork folder in your QGIS profile, and nothing else is changed. When the install fails,
the message shows two commands to run by hand. With internet, run the first. Without
internet: download the segyio file for your system from
<https://pypi.org/project/segyio/#files> on another computer, then run the second, with the
path of the downloaded file in place of `<path to the downloaded file>`. Then restart QGIS.
See [segyio](howto/reflection-sections.md#segyio). Everything else in Groundwork works
without it.

### The section sits at the wrong depth

| What you see | Usual cause | Fix |
|---|---|---|
| Reflectors too shallow or too deep against boreholes | The velocity does not fit. One velocity for a deep section is increasingly wrong with depth | Type the velocity, or a velocity function, from the processing report in [Dataset info](howto/dataset-info.md) |
| The whole section too high or too low | Time zero is at the wrong height | **Time zero is** and **Height of time zero** in Dataset info: the datum from the processing report. With velocities from the processing sheet, choose **At a fixed height**, not **corrected to the ground** |
| The depths are far off, by a factor | The sample step is wrong (files in depth, radar exported as SEG-Y) | Correct **Sample step** in Dataset info |
| "Enter the velocity in m/s." | A time section has no velocity, and Groundwork assumes none | Type it in Add Data or Dataset info |

Drawings stay at their heights when the section moves; Groundwork asks first.

### The section has a flat top and does not follow the ground

This is how processed land sections are delivered: every trace was moved to a flat datum, and
the ground shows only as the blank zone above the first data. When your velocities come from
the processing sheet, they count from that datum: keep **At a fixed height**, the flat top is
right. When your velocity is the velocity of the ground below the surface (typically one
velocity for a shallow line), choose **At a fixed height, corrected to the ground** in Dataset
info and type the replacement velocity from the processing sheet; the profile needs heights
(stations with heights, or a DEM). The first data
of a stack still lie some tens of metres below the ground line, because processing muted the
first arrivals. On a line several kilometres deep, zoom in to see the ground at all
([A flat top, and where the ground is](howto/reflection-sections.md#a-flat-top-and-where-the-ground-is)).

### Nothing is drawn above the ground

Samples that are exactly zero at the top of a trace (the muted zone) are left transparent, and
so is everything above the ground line in a section corrected to the ground. To see them, tick
**Paint muted zones** in the section's **Display…**.

## Radargrams

| What you see | Usual cause | Fix |
|---|---|---|
| "Enter the velocity or the dielectric constant." | The file states no velocity, and Groundwork assumes none | Type one in Add Data; see [where a value comes from](howto/gpr.md#velocity-and-dielectric-constant) |
| Reflectors far too shallow or too deep against a borehole | The velocity does not fit. A GSSI header's dielectric constant is an instrument setting, not a measurement | Change the velocity in [Dataset info](howto/dataset-info.md): every depth moves by the same factor |
| The whole radargram a little too high or too low | Time zero is off | **Time zero (ns)** in Dataset info: later lifts the picture, earlier lowers it |
| Flat bands parallel to the ground all along the line | The antenna's ringing | Tick **Remove background** in **Display…**; a moving window of 10 m is the start for a new radargram |
| A long flat layer fades | The background removal over 10 m takes away what runs flat much longer than that | **Remove background** → **Whole line**, or untick it ([why](howto/gpr.md#why-the-background-is-removed-over-10-m)) |
| The radargram is longer or shorter than the line | The wheel measures along the ground; the line is straight between its ends | Usually right as it is. Fit it with **From** and **To** only when both points are better than the wheel ([fitting](howto/gpr.md#fitting-a-file-between-two-points)) |
| Vertical seams in the radargram | Steps of the elevation model under it | **Smooth the ground over (m)** in Dataset info, for example 2 m |
| "…holds 2 channels; Groundwork reads single-channel files." | A GSSI file of a multi-channel system | Not read yet. One channel exported as SEG-Y from the radar software loads as a reflection section |
| "…the header file … is missing beside it." | A pulseEKKO `.DT1` without its `.HD`, or the other way round | Put both files with the same name in one folder |

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
| Point-cloud curtains look black from a distance | The cloud shows only some of its points; eye-dome lighting darkens each lone point | Layer properties → **3D View** → **Maximum screen space error** 0.1 px (the plugin sets this for its own clouds) |

## Large models

| What you see | Usual cause | Fix |
|---|---|---|
| "Reading Line 7 (2 of 4)…" for a while when a profile first opens | The models are read for the first time; large files on a slow drive (a USB stick) take longest | Wait, or cancel in QGIS's status bar; next time they come from the `_cache` folder at once. Read over-fine exports as [coarser cells](howto/add-data.md) when adding them |
| The geology strip comes a moment after the section | It comes from a web layer and is fetched in the background the first time | Nothing to do: it is remembered per profile afterwards |
| A change on a web service does not show in the strip | The strip is remembered per profile | Right-click the **Profile** list → **Refresh Web Layers** |
| The smooth field looks linear though another interpolation is chosen | The method could not be used for this model (for example, not enough memory) | **View → Panels → Log Messages**, tab **Groundwork**, says why; try **Inverse distance**, or a coarser grid cell |

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
