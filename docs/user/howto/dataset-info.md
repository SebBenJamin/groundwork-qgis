# Dataset info

Note where a dataset comes from: what its files do not say.


Right-click a model or data layer in the section's layer list and choose **Dataset info…**. There you can enter what the files do not say:

| Field | Example |
|---|---|
| Method | ERT |
| Array | dipole-dipole |
| Spacing | 1 m |
| Date | 2025-06-12 |
| Software | BERT inversion |
| Reference | Pohle et al. 2025 |
| Note | free text |

The dialog also shows what the readers found in the files, e.g. the RMS of a misfit. Plates use these fields for each section's **provenance line** and for the [title block](plates.md#the-title-block), e.g.:

> Transect 3 · ERT model: BERT inversion (Pohle et al. 2025) · dipole-dipole, 1 m spacing · RMS 8.0 %

Only what is known is shown. An empty field is left out; nothing is guessed.

A model read as [coarser cells](add-data.md) says so in the dialog, e.g. "averaged from
623 241 cells of 0.25 × 0.1 m to 1 × 0.5 m", and its provenance line on a plate ends with
"averaged to 1 × 0.5 m cells".
