# Borehole styles shipped with Groundwork

QGIS style files (`.qml`) to load in **Borehole style… → Import…**, as a starting point for your own style.

| File | Classes |
|---|---|
| `din_codes.qml` | German short codes as commonly used in layer descriptions: G, fG, mG, gG, S, fS, mS, gS, U, T, X, Y, H, F, Mu, A, Mg, Lg |
| `iso_14688.qml` | EN ISO 14688-1 soil symbols: Bo, Co, Gr, CGr, MGr, FGr, Sa, CSa, MSa, FSa, Si, Cl, Or, Mg |

- **Both are Categorized on a column named `lithology`.** After importing, choose your own column in QGIS's editor.
- A class only applies to values that are **exactly** that code. "fS, ms, u'" is not "fS". Add a column that holds only the main component, and style by that column. For example, in QGIS's field calculator, `trim(regexp_substr("lithology", '^[^,;]+'))` keeps the text up to the first comma or semicolon.
- **The colours and FGDC patterns are the plugin's own choice.** They are **not** the colours or drawings of DIN 4023, EN ISO 14688-1 or any other standard; EN ISO 14688-1 does not define any. The codes are only the labels the classes match. Change anything in QGIS's editor or with **Patterns…**, then **Export…** your own version.
- The patterns are the FGDC lithology patterns shipped with the plugin (see `../../patterns/fgdc/ATTRIBUTION.md`). They are referenced by name, so these files work on any computer where the plugin is loaded.
