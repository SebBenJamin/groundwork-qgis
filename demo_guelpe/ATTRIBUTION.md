# Sources and licences

This demo uses only open data. Files marked *derived* were converted from the source
without changing its values.

## Research data (CC BY 4.0)
- **ERT**: Pohle, M.; Birnstengel, S.; Werban, U. (2025): 2D-ERT data measured in June 2023 and
  June 2024 in the Lower Havel Inner Delta near Lake Gülpe, Brandenburg (Germany). PANGAEA,
  https://doi.org/10.1594/PANGAEA.983478. `data/ert/T*/dcinv.result.vtk` are the authors' BERT
  inversion results, unchanged; `data/stations/*.csv` are their DGPS electrode positions
  (*derived*: reformatted).
- **Cores**: Köhler, A.; Kaniecki, M.; Schneider, B.; Zielhofer, C. (2025): Field based and
  laboratory data of sediment cores from the Lower Havel Inner Delta near Lake Gülpe. PANGAEA,
  https://doi.org/10.1594/PANGAEA.983887. `context/cores.gpkg` (*derived*: layer label =
  grain-size class and texture code; core-loss rows marked "offset" left out).
- **Synthetic curves** (`context/synthetic_logs.gpkg`, layer "Synthetic curves (NOT measured)"):
  made up for the demo, **not measured**. The cores have no geophysical logs; these seeded
  random values only show how log curves look in the borehole viewer
  (scripts/make_synthetic_curves.py).
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
