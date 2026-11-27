# Sources and licences

This demo uses only open data. Files marked *derived* were made from the source.

## Seismic reflection (swisstopo, free use with source)
- **Stacks** (`data/VD-P760057_stack.sgy`, `data/VD-P760068_stack.sgy`): lines VD-P760057 and
  VD-P760068 from the dataset "2D and 3D reflection seismic in Switzerland",
  https://opendata.swiss/en/dataset/2d-und-3d-reflexionsseismik-in-der-schweiz
  Source: Federal Office of Topography swisstopo. The files are swisstopo's `*_stk-p.sgy`
  stacks, unchanged and renamed.
- The datum of 500 m and the average velocities come from the original section sheet of
  VD-P760057 (CGG, 1976), a scan that swisstopo ships with the line. The sheet also names a
  replacement velocity of 4000 m/s, which processing used to bring the data to the datum.
  VD-P760068 has no such sheet; it is from the same 1976 survey, and the demo applies the
  same values to it as an assumption.
- The sheet gives five velocity columns for different stretches of the line. The demo
  uses one function for the whole line: at each time the median of the five columns. The
  columns differ by up to 12.5 % in the first 0.4 s and by less than 5 % below 1 s.
- The top of each section is at 500 m, so where the ground is higher the uppermost part
  of the ground is not in the data. Where the ground lies below 500 m (the east end of
  VD-P760068), the section starts above the ground line: that strip is the processing's
  fill between ground and datum, not earth.

## Elevation (swisstopo, free use with source)
- `context/dem_swissalti3d_10m.tif` (*derived*: resampled to 10 m and cut to 500 m each side
  of the lines): swissALTI3D, 2 m tiles. Source: Federal Office of Topography swisstopo.

## OpenStreetMap (ODbL)
- The background map: © OpenStreetMap contributors, ODbL,
  https://www.openstreetmap.org/copyright
