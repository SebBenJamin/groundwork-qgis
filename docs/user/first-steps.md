# First steps with the Gülpe demo

A walk through Groundwork in about fifteen minutes, on real data: four resistivity transects
with sediment cores at Lake Gülpe (Havel, Brandenburg), the state's boreholes and geology
maps, a 1 m terrain model and aerial images.

You need Groundwork installed (see [Get started](../index.md#get-started)) and an internet
connection for the aerial images and the geology maps.

## 1. Open the demo

1. Download `groundwork_geophysics-demo-guelpe-<version>.zip` from the
   [latest release](https://github.com/SebBenJamin/groundwork-qgis/releases/latest) and unzip
   it into a folder of its own.
2. In QGIS, open `guelpe_project.qgz`. The map shows the four transects over the aerial image,
   with the cores and the state boreholes.

Opening the demo writes to its Groundwork file. Keep a copy of the zip to start over.

## 2. Open a section

1. **Groundwork → Show Section Panel**. The panel opens under the map.
2. Choose **Transect 3** in the **Profile** list, or click the button next to it and click the
   transect on the map.

The section shows the resistivity model at its real height, the ground line, the cores as
columns and two geology strips above the ground (GÜK 300 over GK 25).

Move the mouse over the section: the line below reads out the distance, height, depth and
resistivity, and a marker follows on the map. See [The section panel](howto/section-panel.md).

## 3. Change how the model looks

1. Click the colour button of the model in the **Layers** list on the right. **Display…**
   opens.
2. Set **Draw as** to **Smooth field + contours**.
3. Tick **Fade where coverage is low** and move the threshold: the part of the model the data
   hardly see fades out.
4. **OK**.

## 4. Look at a core

Click a core column in the section. The [borehole viewer](howto/boreholes.md) opens with all
cores of the transect side by side, the one you clicked framed.

## 5. Draw an interpretation

1. In the row above the section, choose **Polygon**.
2. Click around the high-resistivity body between about 117 and 142 m (red); right-click to
   close it.
3. In the form, type the type *resistive body* and the name *A*. **OK**.
4. Look at the map: the group **Interpretation** now holds the polygon in 3D, and its footprint
   along the transect is labelled *A*.

More in [Interpretation](howto/interpretation.md): editing, versions, export.

## 6. Make a report plate

1. **Groundwork → Plates…** → **Add**. The plate starts with the section as the panel shows it.
2. **Create / Update Plates**, then open the plate from QGIS's **Layout Manager**: section,
   colour bar, borehole and interpretation legends, mini-map and title block.
3. **Export Plates…** writes it as a PDF.

See [Report plates](howto/plates.md).

## 7. Look at it in 3D

1. Click the **3D** button next to the **Profile** list → **Look at Profile in 3D**.
2. A 3D map view opens with the model standing as a curtain under the transect, the cores as
   columns and your polygon at its depth.

See [The 3D view](howto/3d-view.md).

## Next: your own data

1. **Groundwork → New Groundwork Project…** in your own QGIS project (see
   [Projects and profiles](howto/projects-and-profiles.md)).
2. **Groundwork → Add Data…** for your model files (see [Add data](howto/add-data.md) and
   [Methods and formats](formats/overview.md)).
3. **Groundwork → Context Layers…** for your boreholes, geology and elevation model (see
   [Boreholes and logs](howto/boreholes.md) and
   [Geology, crossing lines and ties](howto/context.md)).
