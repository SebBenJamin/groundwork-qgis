# Field notes

What the field crew saw along the line, kept with the profile.


Field notes are what the crew experienced along the line: "electrodes 23–28 disabled (farmer)", "fence at 140 m", "wet ground". They are stored with the profile in the Groundwork GeoPackage. Your own QGIS layers are never changed.

**Adding a note on the section**

1. In the section panel, choose the **Note** tool.
2. Click once for a note at one place, or drag along the profile for a stretch (e.g. 115–140 m).
3. Type the text. Pick a category if you like, e.g. "access" or "equipment". Untick **Shown** to keep the note but hide it from the section and the plates.

**The Field notes list** is in the section's Interpretation menu, under **Field Notes…**. There you can:

- see every note of the profile, in chainage order;
- edit, hide or delete notes;
- add a note by electrode numbers, e.g. from 23 to 28. The plugin works out the chainage from the station set.

**Show Field Notes**, in the same menu, switches all notes off or on in the panel.

On the section, a note at one place shows as an orange mark down to the ground; a stretch as a bar in its own lane just above the ground (overlapping stretches get separate lanes). Each has a label with the first line of its text. The full text is shown when you hover or click. A stretch that runs past the ends of the profile is cut to the profile, and the note says so.

**On the map**, the layers "Field notes" and "Field notes (stretches)" in the Groundwork group show the notes. They are read-only and are updated when you change a note. They are added to the project as soon as it has notes.

**Styling notes**: the section takes each note's colour from these layers, a stretch's line width from "Field notes (stretches)". Restyle them in Layer Properties like any layer; a categorized style on `category` colours each note by its category. The section follows at once.

Photos are not stored. Look at them, then write what matters into a note.
