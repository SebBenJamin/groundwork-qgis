# The 3D view

How to see your models, boreholes and interpretation together in QGIS's 3D view.

## Show in 3D

**Groundwork → Show in 3D…** lists every profile with its models and its **Boreholes**. Tick what you want to see and press **OK**:

- a **model** stands as a curtain under its profile, at its real elevation, drawn the way its section draws it (see below);
- **Boreholes** are the boreholes the profile's section shows (not the ones hidden there), as round columns at their real map position, from the collar down, each interval in its colour from the section and about as wide as two thirds of the station spacing;
- ticking a profile ticks all of it;
- a profile without real heights (a local section) is greyed out: give it a reference height first, see [Reference height](reference-height.md).

Nothing is shown in 3D until you ask. Untick a model or a profile's boreholes to take them out again.

## A curtain looks like its section

A curtain follows the model's **display** in the section panel, and changes when you change it there:

| Section display | In 3D |
|---|---|
| **Cells** | one vertical cell per model cell, in **Models in 3D** |
| **Smooth** | a point cloud of the section's smooth field, one layer per model in the group **Smooth models in 3D** |
| **Contours** | the contour lines, at the section's levels and in its contour colour, in **Contours in 3D** |
| **Smooth + contours** | the point cloud and the contour lines |

The colour scale and the coverage fade follow too: the faded part is left out of the curtain.

**Models in 3D**, **Contours in 3D** and **Boreholes in 3D** are temporary layers: they are not stored in the Groundwork file and are rebuilt from your models when you open the project.

The **point clouds** are files: they are written to a folder next to the Groundwork file, named after it with **_3d** at the end (for `site_groundwork.gpkg`: `site_groundwork_3d`). They are made from your models whenever needed, and the plugin only ever deletes the files it wrote there. If the folder is missing when you open the project (deleted, or not copied along), QGIS asks about the unavailable layers: choose to keep them, and the curtains are written again once the project is open. The first time QGIS opens a point cloud it builds an index of it (a progress bar in the status bar), and the points show when that is done.

## Section pictures instead of layers

At the bottom of **Show in 3D…**, **Show models as** offers two looks for all ticked models:

- **Layers** (the default): cells, point clouds and contour lines as above. You can style them in QGIS and **Identify** their values.
- **Section pictures (3D Tiles)**: each model exactly as its section draws it, in whatever display it has there, contour labels included, as a picture on a curtain under its profile. The picture is opaque, on the section panel's background colour: a faded or see-through model looks as it does in the panel, not see-through in 3D. One layer per model in the group **Section pictures in 3D**. Change the model's display, colour scale or fade in the section panel and its picture is drawn again. There are no values on Identify, and the look can't be restyled in QGIS: it is the section's.

The pictures are 3D Tiles (a `.json` tileset and a `.glb` model per model) in the same folder as the point clouds. Long profiles are drawn coarser, so that a picture stays a reasonable size; still, drawing the pictures takes a few seconds (a busy cursor shows it), and every picture layer also costs the 2D map a moment when it redraws.

## Opening a 3D map view

1. **View → 3D Map Views → New 3D Map View.**
2. In the view's settings (the wrench) → **Terrain**, switch the terrain **off** to start with. The curtains hang below the ground surface, and an opaque terrain hides them. With a DEM as terrain, lower its opacity or look from below.
3. For the point clouds, switch on **eye-dome lighting** in the point cloud's **Layer Properties → 3D View**: without it, a point cloud looks flat and dark.
4. Turn the view with the middle mouse button or Ctrl + drag; zoom with the wheel.

## Stations and the interpretation in 3D

The **stations** stand as small spheres at their surveyed height, in the outline colour of their map symbol, sized to the distance between them; stations without a height are left out.

The interpretation lines, polygons and points (3D) stand at the depth you drew them: lines as lines a few pixels wide, polygons as flat panels, points as spheres, each entity in its colour from the 2D legend. A new entity takes its 2D colour when it is drawn; if you recolour an entity later, recolour it in **3D View** too. The 3D style is an ordinary QGIS style: change it in the layer's properties → **3D View**.

The interpretation lies in the same plane as its profile's curtain. So that it never flickers with the curtain or hides behind it, cells and section pictures are drawn as two faces, each standing a little behind the plane as seen from its side (5 to 50 cm, depending on the profile's length): from either side, the interpretation is in front. Point clouds are drawn as they are.

## Pointing in 3D shows the place in the section

Move the mouse over a curtain, a section picture, a borehole column or a point cloud in the 3D view (with no mouse button held): when it belongs to the profile open in the section panel, the panel's cursor moves to that place, with a small ring at its elevation and the readout (chainage, elevation, depth, value) below the section, and the marker on the 2D map moves to the same place on the profile line. Over anything else, or off the 3D view, the cursor hides. It only follows while the section panel is open with a profile in it. The section never switches profile by itself: open the profile you want to follow first.

## Working with the layers

- **Identify** a cell: **value**, **coverage** and **resolved** (0 or 1). Identify a point of a smooth curtain: its **Value** (and **Log10Value**).
- **Only the resolved part:** filter **Models in 3D** with `"resolved" = 1`. When the section fades low coverage, the cells below the threshold are left out of the curtain anyway.
- **Style a smooth curtain by value:** in the point cloud's properties → **Symbology**, choose **Attribute by Ramp** on **Log10Value** (or **Value** on a linear scale) and a colour ramp; the 3D view follows the 2D style. Your style stays when the curtain is rebuilt.
- The point size is in the point cloud's **3D View** properties.
- **Identify** a borehole interval in the 3D view: its **borehole**, **top** and **bottom** depth and its **text**.
- **Qgis2threejs** reads the same layers: choose **Polygon** for the cells, **Polygon** extruded by the **height** field for the boreholes and **Line** for the contour lines, with the height from the Z values, and the point clouds as point clouds.
- A very large model (hundreds of thousands of cells) makes the 3D view slow in **Cells**; show it **Smooth** or show fewer models at once.
