# Sources and licences

This demo uses only open data. Files marked *derived* were converted from the source
without changing its values.

## Research data (CC BY 4.0)
- **ERT**: Pohle, M.; Birnstengel, S.; Werban, U. (2025): 2D-ERT data measured in June 2023 and
  June 2024 in the Lower Havel Inner Delta near Lake Gülpe, Brandenburg (Germany). PANGAEA,
  https://doi.org/10.1594/PANGAEA.983478. `data/ert/T*/dcinv.result.vtk` are the authors' BERT
  inversion results, unchanged; `data/stations/*.csv` are their DGPS electrode positions
  (*derived*: reformatted). **Transect 4, corrected:** its DGPS file lists the positions (E, N)
  from the north-east end, while its heights, the field notes (standing water at 30–60 m and
  144–190 m) and the authors' sketch put electrode 1 in the south-west. The demo turns the
  positions round and keeps the heights in order; so read, the heights agree with the DGM1
  (0.09 m spread instead of 0.45 m), as on the other transects.
- **Cores**: Köhler, A.; Kaniecki, M.; Schneider, B.; Zielhofer, C. (2025): Field based and
  laboratory data of sediment cores from the Lower Havel Inner Delta near Lake Gülpe. PANGAEA,
  https://doi.org/10.1594/PANGAEA.983887. `context/cores.gpkg` (*derived*: layer label =
  grain-size class and texture code; core-loss rows marked "offset" left out). Its table
  `core_lab` holds the lab values of the 62 core samples (C, N, S and grain-size fractions)
  unchanged, each at the middle of its sample (to the centimetre) with the sample's top and
  bottom; `sand`, `silt` and `clay` are the sums of their fractions (*derived*). Sulfur given
  as "<0.0020" (below detection, five RK15 samples) is left empty.
- Both are part of: Köhler, A. et al. (2025): Geophysical, Sedimentological and Geochemical Data
  from the Lower Havel Inner Delta (Gülpe Island), Brandenburg (Germany). PANGAEA,
  https://doi.org/10.1594/PANGAEA.983208; data paper: Data in Brief 112372,
  https://doi.org/10.1016/j.dib.2025.112372.
- Licence: https://creativecommons.org/licenses/by/4.0/

## State data (Datenlizenz Deutschland Namensnennung 2.0, https://www.govdata.de/dl-de/by-2-0)
- **Boreholes** `context/state_boreholes.gpkg` (*derived*: the Bohrpunktkarte WFS, layers
  bpk_m_sch and bpk_o_sch, within 1.5 km of the transects, saved unchanged):
  © LBGR, dl-de/by-2-0
- **Geology** GK 25, Geologische Karte 1 : 25 000 (live WFS), and GÜK300 (live, switched
  off on the map; both drawn as strips on the section): © LBGR, dl-de/by-2-0
- **DGM1** `context/dgm1.tif` (*derived*: tiles merged and cropped): © GeoBasis-DE/LGB, dl-de/by-2-0
- **Aerial images** DOP20 (live WMS): © GeoBasis-DE/LGB, dl-de/by-2-0

## OpenStreetMap (ODbL)
- `context/waterways.geojson` (*derived*: reprojected) and the background map:
  © OpenStreetMap contributors, ODbL, https://www.openstreetmap.org/copyright
