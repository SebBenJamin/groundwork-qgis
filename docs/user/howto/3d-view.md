# The 3D view

How to see your models, boreholes and interpretation together in QGIS's 3D view.

## Show in 3D

**Groundwork → Show in 3D…** lists every profile with its models and its **Boreholes**. Tick what you want to see and press **OK**:

- a **model** stands as a curtain under its profile: one vertical cell per model cell, at its real elevation, coloured as in the section;
- **Boreholes** are the boreholes the profile's section shows (not the ones hidden there), as columns at their real map position, from the collar down, each interval in its colour from the section;
- ticking a profile ticks all of it;
- a profile without real heights (a local section) is greyed out: give it a reference height first, see [Reference height](reference-height.md).

Nothing is shown in 3D until you ask. Untick a model or a profile's boreholes to take them out again.

The curtains and boreholes are two layers in the Groundwork group, **Models in 3D** and **Boreholes in 3D**. They are temporary: they are not stored in the Groundwork file, and are rebuilt from your models whenever you open the project. They follow the section: change a model's colour scale or its coverage fade and its curtain follows.

## Opening a 3D map view

1. **View → 3D Map Views → New 3D Map View.**
2. In the view's settings (the wrench) → **Terrain**, switch the terrain **off** to start with. The curtains hang below the ground surface, and an opaque terrain hides them. With a DEM as terrain, lower its opacity or look from below.
3. Turn the view with the middle mouse button or Ctrl + drag; zoom with the wheel.

## Stations and the interpretation in 3D

The **stations** stand as small spheres at their surveyed height, in the outline colour of their map symbol; stations without a height are left out.


The interpretation lines, polygons and points (3D) stand at the depth you drew them: lines as tubes, polygons as flat panels, points as spheres, each entity in its colour from the 2D legend. A new entity takes its 2D colour when it is drawn; if you recolour an entity later, recolour it in **3D View** too. The 3D style is an ordinary QGIS style: change it in the layer's properties → **3D View**.

## Working with the layers

- **Identify** a cell: **value**, **coverage** and **resolved** (0 or 1).
- **Only the resolved part:** filter **Models in 3D** with `"resolved" = 1`. When the section fades low coverage, the cells below the threshold are left out of the curtain anyway.
- A borehole interval has its **top** and **bottom** depth and its **text**.
- **Qgis2threejs** reads the same layers: choose **Polygon** for the curtains and **Line** for the boreholes, with the height from the Z values.
- A very large model (hundreds of thousands of cells) makes the 3D view slow; show fewer models at once.
