# Troubleshooting

What to do when something doesn't look right.

## When boreholes don't show

| What you see | Usual cause | Fix |
|---|---|---|
| No boreholes on the section | Points are farther from the line than the **buffer** | Raise the buffer in Context Layers… |
| No boreholes on the section | Wrong coordinate system when you made the points | Make the points again with the right CRS ([step 3](howto/boreholes.md#into-qgis-step-by-step)) |
| A column but no layers in it | The layer table's IDs don't match the collars (spelling, `BH 1` vs `BH1`) | Compare the ID columns in both attribute tables |
| Some layers are missing | Empty top or bottom, or a decimal comma in a CSV | Fill in the cells; use the decimal-comma option ([step 3](howto/boreholes.md#into-qgis-step-by-step)) |
| Boreholes far too high or low | Layer table holds elevations, not depths; or the elevation column uses another height system | Convert to depths; check the heights against the DEM (the red triangle shows large differences) |
| Red triangle at the top | Elevation column and DEM disagree by more than the tolerance | Check which one is right; hover the top to see both numbers |
| "No height" in the viewer | No elevation, no DEM, no surface line at that point | Fill in the elevation, or choose a DEM in Context Layers… |
| No curves in the viewer | No curve table set up, or its IDs don't match | Context Layers… → Add Curve Table; compare IDs |

## Known limits of Add Data

- GPS tracks and other lines are used as drawn, with no smoothing.
- Readings (a, b, m, n with apparent resistivity) from free text files are not supported yet.
- A 3D model only two cells wide is not refused as "an area" and may give a zig-zag line; the map preview shows it before you save.
- **Add Data…** has no **Reverse the line**; **New Profile…** has.
