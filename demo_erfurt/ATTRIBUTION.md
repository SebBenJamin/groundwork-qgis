# Sources and licences

This demo uses only open data. Files marked *derived* were converted from the source
without changing its values.

## Research data (CC BY 4.0, https://creativecommons.org/licenses/by/4.0/)
- **ERT**: Silbermann, M.; Pohle, M.; Jung, P.; Werban, U. (2025): 2D-ERT data for localizing
  a Black Death mass grave in Erfurt, Thuringia (Germany). PANGAEA,
  https://doi.org/10.1594/PANGAEA.974818.
  - `data/ert/ERT*/dcinv.result.vtk`: the authors' BERT 2.2.9 inversion results, unchanged;
  - `data/ert/ERT*/ERT*_measured.data`: the authors' BERT input data, unchanged;
  - `data/stations/*.csv`: their electrode positions (*derived*: reformatted).
  - Electrode positions: total station for ERT02-ERT07, differential GPS for ERT11 and ERT12
    (UTM zone 32N, as stated in the authors' explanation files).
- **Cores**: Hein, M. et al. (2026): What the landscape can tell: An integrative stratigraphic
  prospection approach to localize a Black Death mass grave in Erfurt/Central Germany.
  PLoS ONE 21(1): e0337410, https://doi.org/10.1371/journal.pone.0337410, Supporting
  Information S1 File, Suppl. Table 3. `context/cores.gpkg` (*derived*: depths converted from
  cm to m; stratigraphic units and properties in the authors' words). Cores EN-RK 40 and 46
  are listed there without coordinates and are left out. The cores have no published surface
  heights: on the sections they hang from the ERT topography.
- **Core colours** (`context/core_logs_style.qml`): chosen for this demo after the authors'
  unit descriptions; restyle them in Borehole style….

## OpenStreetMap (ODbL)
- The background map: © OpenStreetMap contributors, ODbL, https://www.openstreetmap.org/copyright
