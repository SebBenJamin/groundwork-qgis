# Report plates, field notes and Dataset info

This guide shows how to turn sections into report plates (PDF), how to record what the field crew saw, and how to note where a dataset comes from.

---

## 1. Field notes

Field notes are what the crew experienced along the line: "electrodes 23–28 disabled (farmer)", "fence at 140 m", "wet ground". They are stored with the profile in the workbench GeoPackage. Your own QGIS layers are never changed.

**Adding a note on the section**
1. In the section panel, choose the **Note** tool.
2. Click once for a note at one place, or drag along the profile for a stretch (e.g. 115–140 m).
3. Type the text. Pick a category if you like, e.g. "access" or "equipment". Untick **Shown** to keep the note but hide it from the section and the plates.

**The Field notes list** is in the section's Interpretation menu, under **Field Notes…**. There you can:
- see every note of the profile, in chainage order;
- edit, hide or delete notes;
- add a note by electrode numbers, e.g. from 23 to 28. The plugin works out the chainage from the station set.

**Show Field Notes**, in the same menu, switches all notes off or on in the panel.

On the section, a note shows as an orange mark (a stretch as a bar) with the first line of its text. The full text is shown when you hover or click. A stretch that runs past the ends of the profile is cut to the profile, and the note says so.

**On the map**, the layers "Field notes" and "Field notes (stretches)" in the Geophysics Workbench group show the notes. They are read-only and are updated when you change a note.

Photos are not stored. Look at them, then write what matters into a note.

---

## 2. Dataset info

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

The dialog also shows what the readers found in the files, e.g. the RMS of a misfit. Plates use these fields for each section's **provenance line**, e.g.:

> Transect 3 · ERT model: BERT inversion (Pohle et al. 2025) · dipole-dipole, 1 m spacing · RMS 8.0 %

Only what is known is shown. An empty field is left out; nothing is guessed.

---

## 3. Making plates

Open **Geophysics Workbench → Plates…**.

1. **Add** a plate. It starts with one frame showing the profile and look of the section panel.
2. Set its **number**, **title** and **template**: A4 or A3, portrait or landscape. You can also choose **Own template…** (see section 5).
3. **Section frames** are stacked top to bottom. Each row is a profile with its own look. To show the ERT model and the seismics of the same line, add two rows with the same profile.
   - **Take from Section Panel** copies the panel's profile and look into the selected frame. The look covers which models are shown, their colour scale, display mode and opacity, the interpretation version, and whether boreholes, field notes and context are shown. Restyling the panel later does not change the plate.
   - **From / To** limit the chainage range. Leave them empty for the full data range.
   - **Scale / VE** fix the scale (e.g. 2500 for 1:2500) or the vertical exaggeration. Leave them empty to fit the page.
4. **Plate Details…** sets project, client, job number, date, author and revision. They are entered once per project and shown on every plate.
5. **Create / Update Plates** makes the layouts. They are ordinary QGIS print layouts, named e.g. "Plate 1 – Transect 3", and you open them from QGIS's Layout Manager.
6. **Export Plates…** updates every plate and writes one vector PDF per plate (`Plate_1_Transect_3.pdf`) into a folder you choose. Tick **One combined PDF** to get all pages in one file instead.

### Fit to page

- The **horizontal scale** is the largest standard scale (1:100, 1:200, 1:250, 1:500, 1:1000, 1:2000, 1:2500, 1:5000, 1:10000, 1:20000, 1:25000, 1:50000) at which the frame's range fits its width.
- The **VE** is the largest standard value (1, 1.5, 2, 2.5, 3, 4, 5, 10, 20) at which the depth range fits the frame's height.
- **Frames of the same profile** share scale, range and VE, so features line up vertically.
- The provenance line under each frame states the scale and the VE ("1:2500 · VE 2×"), plus the start and end coordinates of the profile.

### What updating keeps

Running **Create / Update Plates** or **Export Plates…** again refreshes only the plugin's own content:
- the sections;
- the colour bars;
- the contents of the legends;
- the field-notes list;
- the title fields;
- the provenance lines.

Anything you moved, resized, restyled or added in the layout designer stays as it is. One exception: when a plate gets more or fewer frames, the frames and their colour bars are laid out in the section area again.

Deleting a plate in the dialog keeps its layout. Delete the layout in the Layout Manager if you no longer need it.

If a plate's profile was removed from the workbench, its frame says "Profile not found". The plate can still be exported.

---

## 4. What is on a plate

- **Section frames**: QGIS's own elevation-profile layout items, drawing the same section as the panel, with distance and elevation axes in metres.
- **Colour bars**: one per model shown, using the frame's colour scale. Select a colour bar in the layout designer to tune it. In its panel you set:
  - ticks: `auto`, a step such as `step:25`, or a list such as `list:1,10,100,1000`;
  - title and unit;
  - QGIS's own colour-ramp legend settings: orientation, which end the minimum is at, number format, prefix/suffix and fonts.
- **Interpretation legend**: a normal QGIS legend of the interpretation layers. It lists only the entities on this plate's profiles, with their QGIS styles.
- **Borehole legend**: the classes of each borehole style that occur on the plate (colour, pattern, label), plus the log curves shown (name, unit, line). Select it to change its font.
- **Field-notes list**: the shown notes of the plate's profiles, in chainage order.
- **Mini-map**: the plate's profiles are highlighted, with a dot at the start and an arrow at the end; other profiles are faint. It has a north arrow (grid north), a bar scale and the coordinate system. It shows the project's visible map layers.
- **Title block**: project, client, job number, plate number and title, date, author and revision.

---

## 5. Own templates

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
| `wb_title_plate` | label | "Plate <number> – <title>" |
| `wb_title_project` | label | `[% @wb_project %]` |
| `wb_title_client` | label | `[% @wb_client %]` |
| `wb_title_job` | label | `[% @wb_job %]` |
| `wb_title_date` | label | `[% @wb_date %]` |
| `wb_title_author` | label | `[% @wb_author %]` |
| `wb_title_revision` | label | `[% @wb_revision %]` |
| `wb_crs` | label | "Coordinate system: <code> <name>" |

The plugin makes these items itself; don't put them in templates:
- `wb_frame_<n>`: the sections;
- `wb_colourbar_<n>_<k>`: the colour bars;
- `wb_provenance_<n>`: the provenance lines;
- `wb_placeholder_<n>`: the "profile not found" notice.

Title labels whose text already mentions their variable (e.g. "Auftraggeber: `[% @wb_client %]`") keep your wording. The project variables `wb_project`, `wb_client` and so on are ordinary QGIS project variables. You can use them in any label, also outside plates.
