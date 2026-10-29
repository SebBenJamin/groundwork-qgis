# 0001: Section rendering on the native elevation-profile machinery

- **Status:** Accepted
- **Date:** 2026-10-29
- **Verdict:** **GO**. Tasks 10 and 11 go ahead as written.
- **Evidence:** `spikes/section_native/spike.py` (throwaway code, never imported by the plugin)

## Question

Can `QgsElevationProfileCanvas`, fed by a plugin-registered `QgsAbstractProfileSource`, do everything the section panel needs? That means rendering 100k-cell sections fast enough, hover, identify, custom click tools and print-layout output. If it can't, Tasks 10 and 11 have to be re-planned around a vendored pyqtgraph canvas.

## Setup

- QGIS 4.2.3, Python 3.12.15, Qt 6.11.0, Windows 11, AMD Ryzen 7 5800H. `QT_QPA_PLATFORM=offscreen`, `PYTHONNOUSERSITE=1`, GUI-enabled `QgsApplication([], True)`.
- **Source:** registered with `QgsApplication.profileSourceRegistry().registerProfileSource(...)`, which returns `True`.
- **Data:** 100,000 quads (a 500 × 200 grid with interior nodes jittered ±30 % of a cell, so the quads are not rectangles) covering distance 0–500 m × elevation 50–100 m. Each quad is coloured by a synthetic log-resistivity value through a 64-bin colour ramp.
- **Profile curve:** a 2-vertex LineString in EPSG:25832, (500000, 5700000) → (500500, 5700000).
- **Canvas:** 1200 × 500 px, visible range distance −10…510, elevation 45…105.
- **Generator:** builds one world-space `QPolygonF` per quad, bucketed by colour. In `image` mode it also rasterises all quads once into a 2000 × 800 `QImage`.
- **Two render strategies:**
  - `vector`: `renderResults` sets `painter.setTransform(worldTransform, True)` and calls `drawPolygon` once per quad on every paint.
  - `image`: `renderResults` calls `drawImage(worldTransform.mapRect(dataRect), cachedImage)`.

All numbers below come from the final run (run 3). The two earlier runs were consistent with it: full refresh was 623–722 ms (vector) and 664–716 ms (image), and pans were within 3 ms of the figures below.

## Measurements

### Full refresh

Each figure is wall-clock time from `canvas.refresh()` until the end of the first `renderResults` of the new results. Three runs per mode.

| mode | run 0 | run 1 | run 2 | of which `generateProfile` | of which `renderResults` | `createProfileGenerator` |
|---|---|---|---|---|---|---|
| vector | 672.2 ms | 619.4 ms | 645.8 ms | 460–531 ms | 78–79 ms | 0.5–0.6 ms |
| image  | 762.2 ms | 787.0 ms | 755.0 ms | 716–747 ms | 0.5–0.7 ms | 0.6–0.8 ms |

### Pan redraw

Each figure is wall-clock time for `panContentsBy(±40 px, 0)` plus a synchronous `viewport().repaint()`. Five runs per mode. Panning never triggered regeneration: `generateProfile` was not called and `activeJobCount` did not change.

| mode | runs | median | max | `renderResults` per paint |
|---|---|---|---|---|
| vector | 99.9, 99.7, 98.1, 98.1, 98.6 ms | 98.6 ms | 99.9 ms | ≈ 79 ms |
| image  | 21.2, 23.7, 22.2, 21.4, 22.1 ms | 22.1 ms | 23.7 ms | ≈ 0.6–1.0 ms |

### Interaction

| check | result |
|---|---|
| `canvasPointHovered` with **no** tool installed | **0 signals**. With no tool, `QGraphicsView` accepts the move event and the canvas returns before emitting the signal. |
| `canvasPointHovered` with the built-in `QgsPlotToolPan` installed | PASS: 1 signal. Target (250, 75), received (249.83, 74.94), point not empty. |
| `canvasPointHovered` with the custom `QgsPlotTool` installed | PASS: same result as with the pan tool. |
| `results.identify(QgsProfilePoint(250.3, 75.1), QgsProfileIdentifyContext())` | PASS: returns `QgsProfileIdentifyResults(None, [{cell_i: 250, cell_j: 100, value: 2.251311…}])`, and the value equals `values[250, 100]` exactly. |
| `canvas.identify(QPointF)` (bonus check) | Also reaches our results and returns 1 result set with `layer() is None`. |
| Custom `QgsPlotTool` subclass: simulated press and release | PASS: `plotPressEvent` received. `canvasPointToPlotPoint(event.position())` gives (123.18, 59.94) for target (123, 60), which is within 1 px. |

### Print layout

The layout is a `QgsPrintLayout` with one `QgsLayoutItemElevationProfile` (277 × 180 mm), using `setSources([source])`, the same curve and `QgsLayoutExporter.exportToPdf`.

| mode | result | time | `generateProfile` / `renderResults` calls | file size |
|---|---|---|---|---|
| vector | Success | 1.52 s | 1 / 1 | 4,297,742 B (gitignored, over the 2 MB limit) |
| image  | Success | 0.76 s | 1 / 1 | 1,351,186 B (committed as `out_layout_imagecache.pdf`) |

Page 1 of both PDFs was rendered with GDAL and inspected: the quads are visible, with axes and labels. Rasterised with anti-aliasing, the vector PDF shows **hairline seams** between adjacent quads. This is the usual problem with abutting filled polygons in PDF viewers. The image-mode PDF has no seams.

## Threading behaviour

Each callback was logged with `threading.current_thread()` and with `QThread.currentThread()` compared against the GUI thread:

| callback | canvas (`QgsElevationProfileCanvas`) | layout export (`QgsLayoutExporter`) |
|---|---|---|
| `createProfileGenerator` | main GUI thread | main GUI thread |
| `generateProfile` | **worker threads**: Qt thread-pool threads that Python sees as `Dummy-1` … `Dummy-5`, a different thread per refresh | **main GUI thread** (synchronous; the export blocks until done) |
| `renderResults` | main GUI thread | main GUI thread |

What this means for Task 10:

1. **Copy generator input on the main thread.** `generateProfile` runs on an arbitrary pool thread for the canvas, so `createProfileGenerator` must copy everything the generator needs into plain data (numpy arrays, floats, strings). The spike's `.copy()` of three 501×201 / 500×200 arrays took 0.5 ms. The generator must not touch `QgsProject`, layers or any `QObject`.
2. **`generateProfile` must also work on the main thread.** Layout export calls it there synchronously. Python-implemented generators did not deadlock in either path.
3. **Pure-Python work in `generateProfile` holds the GIL** and starves Python code on the GUI thread. A 5 ms Python `QTimer` on the GUI thread saw gaps of up to 211 ms during a refresh; the per-run maximum was 56–211 ms. C++ painting and event handling continue, but Python slots stall. Task 10 should keep per-cell Python loops out of `generateProfile` where it can. The spike's loop builds 100k `QPolygonF` objects and accounts for nearly all of the ~0.5 s generation time.
4. **`renderResults` runs on the GUI thread**, so it must be fast. It gets a fresh `QgsProfileRenderContext` each time; use `context.worldTransform()` and do not cache transforms.

## Render and caching approach that passed

**Both strategies pass every timing criterion at 100k cells**, so QImage caching was not *required*. The plain per-quad `renderResults` (`vector`) passed on its own:

- `vector`: full refresh max **672 ms** (≤ 1.5 s ✔), pan max **99.9 ms** (≤ 300 ms ✔). Rendering costs about 0.8 µs per quad per paint and grows linearly with cell count, so it would reach the 300 ms pan budget at around 350k cells. Output stays crisp at any zoom. Layout PDFs are true vector, but they are large and show seams.
- `image`: full refresh max **787 ms** ✔, pan max **23.7 ms** ✔. Each paint costs the same no matter how many cells there are. The cost is that rasterising in `generateProfile` adds about 250 ms, the image pixelates if you zoom past its resolution (it would have to be re-rasterised on zoom), and layout PDFs are raster but smaller and seam-free.

Recommendation for Tasks 10 and 11: start with `vector` rendering for the canvas. It passes comfortably and is the simplest. Keep the QImage cache in reserve for sections well above about 300k cells and as the option for layout or print export, where it avoids seams. Alternatively, stroke each quad with a hairline pen of its own fill colour in the PDF.

## Other findings worth carrying forward

- **The panel must always have a plot tool installed.** With no tool, `canvasPointHovered` never fires. QGIS's own profile dock always has one (pan by default), and a custom tool works as long as it leaves move events unaccepted.
- **Copy the `canvasPointHovered(QgsPointXY, QgsProfilePoint)` arguments inside the slot.** They are const references and may not be valid after the emit. The first spike run stored the wrapper objects and read them later, and that hover check failed. Copying `distance()`/`elevation()` inside the slot fixed it.
- **`activeJobCountChanged` sometimes goes `1 → 0 → 1`** after a refresh (a deferred follow-up job) with no extra `generateProfile` call. Code that waits for completion must check for "count reached 0 and new results present", not a single transition.
- **`QgsProfileSourceRegistry.unregisterProfileSource(source)` is deprecated since QGIS 4.0.** Unregister by id: `unregisterProfileSource(source_id)`. `registerProfileSource` takes ownership.
- **`QgsLayoutItemElevationProfile.plot()` axis intervals need setting.** By default the grid lines and labels are extremely dense. Set them with `plot.xAxis()/yAxis().setGridIntervalMajor/Minor/setLabelInterval`, and set the plot ranges with `setXMinimum/…/setYMaximum`.
- **The offscreen Qt platform on Windows needs `QT_QPA_FONTDIR`** (for example `C:\Windows\Fonts`), otherwise axis labels render as boxes. This only affects tests and headless runs.
- **Hover and click resolution:** `plotPointToCanvasPoint` → `canvasPointToPlotPoint` round-trips within one pixel, about 0.2 m in distance and 0.06 m in elevation at this view.

## Verdict

**GO.** Every criterion is met:

- Full refresh ≤ 1.5 s (max 672 ms vector / 787 ms image).
- Pan ≤ 300 ms (max 99.9 ms vector / 23.7 ms image).
- Hover, identify and custom plot-tool clicks all work. For hover, a tool has to be installed, as it always is in the panel.
- The layout PDF shows the quads.
- The threading behaviour is recorded above. Generation runs on worker threads for the canvas and on the main thread for layout export. Creation and rendering are always on the main thread.
