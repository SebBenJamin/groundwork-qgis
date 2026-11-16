# Plate templates

How the plugin recognises a template's items, for plates from your own layout.


Any layout can become a template: in the layout designer, choose **Layout → Save as Template…**. In the Plates dialog, pick it with **Own template…**.

The plugin recognises a template's items by their **item ID** (in the layout designer: Item Properties → ID). Items with other IDs are left alone. All items are optional: a template without a mini-map simply gets none.

| Item ID | Item type | Filled with |
|---|---|---|
| `wb_section_area` | rectangle (not printed) | the area the plugin divides among the frames |
| `wb_minimap` | map | the extent of the plate's profiles, profiles highlighted |
| `wb_north` | picture (north arrow) | linked to the mini-map |
| `wb_map_scalebar` | scale bar | linked to the mini-map |
| `wb_legend_interp` | legend | the interpretation layers, filtered to the plate |
| `wb_legend_boreholes` | Borehole legend (plugin item) | the plate's boreholes and curves |
| `wb_field_notes` | label | the field-notes list |
| `wb_stamp_area` | rectangle | the area the plugin rules into the title block (stamp) when the plate is made |

The plugin makes these items itself; don't put them in templates:

- `wb_frame_<n>`: the sections;
- `wb_colourbar_<n>_<k>`: the colour bars;
- `wb_provenance_<n>`: the provenance lines;
- `wb_placeholder_<n>`: the "profile not found" notice;
- `wb_stamp_<cell>`, `wb_stamp_<cell>_caption`, `wb_stamp_<cell>_box`, `wb_stamp_logo`: the title block's values, captions, boxes and logo.

Templates from before 0.11 may still carry the old title items (`wb_title_plate`, `wb_title_project`, `wb_title_client`, `wb_title_job`, `wb_title_date`, `wb_title_author`, `wb_title_revision`, `wb_crs`); they are filled as before.

Old title labels whose text already mentions their variable (e.g. "Auftraggeber: `[% @wb_client %]`") keep your wording. The project variables `wb_project`, `wb_client`, `wb_checked`, `wb_logo` and so on are ordinary QGIS project variables. You can use them in any label, also outside plates.
