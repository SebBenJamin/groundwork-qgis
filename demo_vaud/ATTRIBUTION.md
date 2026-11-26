# Sources and licences

This demo uses only open data. Files marked *derived* were made from the source.

## Seismic reflection (swisstopo, free use with source)
- **Stacks** (`data/VD-P760057_stack.sgy`, `data/VD-P760068_stack.sgy`): lines VD-P760057 and
  VD-P760068 from the dataset "2D and 3D reflection seismic in Switzerland",
  https://opendata.swiss/en/dataset/2d-und-3d-reflexionsseismik-in-der-schweiz
  Source: Federal Office of Topography swisstopo. The files are swisstopo's `*_stk-p.sgy`
  stacks, unchanged and renamed.
- Both sections are hung in two-way time with time zero at 500 m, the lines' seismic
  reference datum in swisstopo's catalogue. The velocity of 3000 m/s used for the depth
  display is an assumption of the demo, not a value from swisstopo.

## Elevation (swisstopo, free use with source)
- `context/dem_swissalti3d_10m.tif` (*derived*: resampled to 10 m and cut to 500 m each side
  of the lines): swissALTI3D, 2 m tiles. Source: Federal Office of Topography swisstopo.

## OpenStreetMap (ODbL)
- The background map: © OpenStreetMap contributors, ODbL,
  https://www.openstreetmap.org/copyright
