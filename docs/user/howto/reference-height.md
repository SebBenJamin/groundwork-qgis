# Reference height and local sections

What a local section is, and how to give it real heights.

## Local sections and the reference height

A profile with no station heights, no DEM and no model with real elevations is drawn **local**: the ground is flat at 0, or at the top of a Local height model. The Topography list shows **Local**.

To give it real heights, choose **Reference Height…** (next to the Topography list, and in Profile Properties…): type one height at one position, a distance or an electrode, and the whole section moves to real elevations; the view zooms to the whole section at its new height. **Ctrl+Z** undoes it; **Remove** takes it away. If the Groundwork file cannot be written at that moment (read-only, open in another program), a line under the section says so and nothing changes.

- Interpretation drawn on a local section moves with the reference height. When real heights arrive later (a positions file with elevations, a DEM), it is moved once onto the real ground, keeping its depth below the ground. Export does this first if needed.
- While a profile is local there are no DEM line and no boreholes (drawing, hover, snapping, picking on the map, plate legends), no ties with other profiles, and no interpretation export for it; a message says why.
- The section panel's own axis cannot be relabelled, so depths show there as negative numbers. Plates show them as positive depths.

A profile whose stations have no heights but whose models carry real elevations (such as the pyGIMLi VTK results) gets a ground line from the first model's top. A depth model on a profile without any heights is drawn as a local section, not refused.
