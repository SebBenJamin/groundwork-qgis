"""Reflection sections drawn in the section: picture levels made from the samples, the display
options (gain, polarity, clip) on a copy only, and the levels remembered on disk."""
from dataclasses import replace

import numpy as np
import pytest

from groundwork_geophysics.core.colors import ColorScale
from groundwork_geophysics.core.trace_section import DisplayGain, color_limits, display_values
from groundwork_geophysics.section import display_render
from groundwork_geophysics.section.data import identify_layers, trace_limits
from groundwork_geophysics.section.display_render import build_drawing


@pytest.fixture(autouse=True)
def _fresh_cache():
    display_render.clear_cache()
    yield
    display_render.clear_cache()


@pytest.fixture(scope="module")
def big_trace_layer(make_trace_layer):
    """20,000 traces x 6,000 samples (int8, so the test stays light): noise of -1, 0 and 1 and
    one strong reflector of 100 at sample 3,000, under a typed scale of -50 .. 50."""
    rng = np.random.default_rng(5)
    a = rng.integers(-1, 2, size=(20_000, 6_000), dtype=np.int8)
    a[:, 3000] = 100
    layer = make_trace_layer(a, x=np.arange(20_000) * 1.0, clip_percent=None,
                             scale=ColorScale("gray", -50.0, 50.0, False))
    yield layer
    display_render.clear_cache()


@pytest.fixture
def dead_trace_layer(make_trace_layer):
    return make_trace_layer(np.zeros((11, 50), np.float32))


def _pixels(image) -> np.ndarray:
    """(h, w) uint32 ARGB of a QImage."""
    from qgis.PyQt.QtGui import QImage
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    raw = np.frombuffer(image.constBits().asstring(image.sizeInBytes()), np.uint32)
    return raw.reshape(image.height(), image.bytesPerLine() // 4)[:, :image.width()].copy()


def test_a_trace_layer_becomes_picture_levels(qgis_app, trace_layer):
    d = build_drawing(trace_layer, None)
    assert d.field is None and not d.groups and len(d.levels) == 3
    img, rect = d.levels[0]
    assert (img.width(), img.height()) == (11, 50)
    assert (rect.left(), rect.right()) == pytest.approx((-5.0, 105.0))    # half a spacing each side
    assert (rect.top(), rect.bottom()) == pytest.approx((500.0 - 49.5, 500.5))
    assert d.clip is None                       # nothing above the ground is cut off


def test_levels_are_premultiplied_and_own_their_bytes(qgis_app, trace_layer):
    from qgis.PyQt.QtGui import QImage
    d = build_drawing(trace_layer, None)
    for img, _rect in d.levels:
        assert img.format() == QImage.Format.Format_ARGB32_Premultiplied
    widths = [img.width() for img, _r in d.levels]
    assert widths == sorted(widths, reverse=True) and min(widths) >= 1
    img = d.levels[0][0]
    before = _pixels(img)
    import gc
    gc.collect()
    assert (_pixels(img) == before).all()


def test_the_picture_is_upright(qgis_app, make_trace_layer):
    # strong at the first sample (the top), weak below: the top row of the drawn picture is the
    # end colour of the scale; image row 0 is the lowest z (as for the smooth field)
    a = np.zeros((11, 50), np.float32)
    a[:, 0] = 10.0
    a[:, 1:] = -10.0
    layer = make_trace_layer(a, clip_percent=None, scale=ColorScale("gray", -10.0, 10.0, False))
    img, _rect = build_drawing(layer, None).levels[0]
    px = _pixels(img)
    assert (px[-1] == 0xFFFFFFFF).all()                        # z max: white (+10)
    assert (px[0] == 0xFF000000).all()                         # z min: black (-10)


def test_a_long_line_is_capped(qgis_app, big_trace_layer):                 # Review Focus 5
    img, _ = build_drawing(big_trace_layer, None).levels[0]
    assert img.width() <= 4096 and img.height() <= 4096


def test_a_strong_reflector_survives_the_coarsest_level(qgis_app, big_trace_layer):
    # one sample row set to 100, the rest noise of +-1: the coarsest image still has a row
    # whose colour is the scale's end colour all along
    d = build_drawing(big_trace_layer, None)
    img, _rect = d.levels[-1]
    assert img.width() < d.levels[0][0].width()
    end = big_trace_layer.style.scale.rgba([50.0])[0]
    white = (255 << 24) | (int(end[0]) << 16) | (int(end[1]) << 8) | int(end[2])
    px = _pixels(img)
    assert ((px == white).all(axis=1)).sum() >= 1
    assert not (px == white).all()


def test_dead_data_draws_blank_without_raising(qgis_app, dead_trace_layer):   # Review Focus 2
    d = build_drawing(dead_trace_layer, None)
    assert d.levels
    assert trace_limits(dead_trace_layer, dead_trace_layer.style) == (0.0, 1.0)


def _paint(layers, size=(200, 100)):
    """``layers``' drawings painted through ``paint_layers``: s -50 .. 150 m and z 510 .. 440
    m fill the image, on red."""
    from qgis.core import QgsRenderContext
    from qgis.PyQt.QtGui import QColor, QImage, QPainter, QTransform

    from groundwork_geophysics.section.profile_source import paint_layers
    img = QImage(*size, QImage.Format.Format_ARGB32)
    img.fill(QColor(255, 0, 0))
    painter = QPainter(img)
    try:
        sx, sz = size[0] / 200.0, size[1] / 70.0
        wt = QTransform(sx, 0.0, 0.0, -sz, 50.0 * sx, 510.0 * sz)
        paint_layers(painter, [build_drawing(la, None) for la in layers], wt,
                     QgsRenderContext.fromQPainter(painter))
    finally:
        painter.end()
    return _pixels(img)


RED = 0xFFFF0000


def test_paint_layers_draws_the_section(qgis_app, trace_layer):
    px = _paint([trace_layer])
    # s -5 .. 105 m is x 45 .. 155; z 500.5 .. 450.5 is y 13.6 .. 84.3
    assert (px[20:80, 50:150] != RED).all()
    assert (px[:, :44] == RED).all() and (px[:, 157:] == RED).all()
    assert (px[:12] == RED).all() and (px[86:] == RED).all()


def test_the_profile_generator_draws_a_trace_layer(qgis_app, trace_layer):
    from qgis.core import QgsProfileRenderContext, QgsRenderContext
    from qgis.PyQt.QtGui import QColor, QImage, QPainter, QTransform

    from groundwork_geophysics.section.data import SectionSnapshot
    from groundwork_geophysics.section.profile_source import WorkbenchProfileGenerator

    class Owner:
        last_results = None

    gen = WorkbenchProfileGenerator(SectionSnapshot("p1", [trace_layer], None, []), Owner())
    assert gen.generateProfile()
    results = gen.takeResults()
    assert results._layers[0].levels
    img = QImage(200, 100, QImage.Format.Format_ARGB32)
    img.fill(QColor(255, 0, 0))
    painter = QPainter(img)
    try:
        ctx = QgsProfileRenderContext(QgsRenderContext.fromQPainter(painter))
        ctx.setWorldTransform(QTransform(1.0, 0.0, 0.0, -100 / 70.0, 50.0, 510.0 * 100 / 70.0))
        results.renderResults(ctx)
    finally:
        painter.end()
    px = _pixels(img)
    assert (px[20:80, 50:150] != RED).all() and (px[:, :44] == RED).all()


def test_the_3d_section_picture_draws_a_trace_layer(qgis_app, trace_layer):
    from qgis.PyQt.QtGui import QColor

    from groundwork_geophysics.section.picture import section_pictures
    (pic,) = section_pictures([trace_layer], None, base=QColor(255, 0, 0))
    px = _pixels(pic.image)
    h, w = px.shape
    assert (px[h // 4:3 * h // 4, w // 4:3 * w // 4] != RED).all()


def test_opacity_is_drawn(qgis_app, trace_layer):
    faint = replace(trace_layer, style=replace(trace_layer.style, opacity=0.0))
    assert (_paint([faint]) == RED).all()


def test_the_painter_takes_the_coarsest_level_still_fine_enough():
    from qgis.PyQt.QtCore import QRectF
    from qgis.PyQt.QtGui import QImage, QTransform
    rect = QRectF(0.0, 0.0, 1000.0, 100.0)
    levels = [(QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied), rect)
              for w, h in ((4000, 400), (2000, 200), (1000, 100))]
    pick = display_render.level_for
    assert pick(levels, QTransform(0.5, 0, 0, -0.5, 0, 0)) == 2       # 500 px wide on screen
    assert pick(levels, QTransform(1.0, 0, 0, -1.0, 0, 0)) == 2       # exactly 1 px each
    assert pick(levels, QTransform(1.5, 0, 0, -1.5, 0, 0)) == 1
    assert pick(levels, QTransform(3.0, 0, 0, -3.0, 0, 0)) == 0
    assert pick(levels, QTransform(30.0, 0, 0, -30.0, 0, 0)) == 0     # zoomed in: the finest
    assert pick(levels, QTransform(0.5, 0, 0, -3.0, 0, 0)) == 0       # z decides: the finer


# -- display options -----------------------------------------------------------------------
OPTIONS = [DisplayGain(agc_window=0.01), DisplayGain(time_power=2.0),
           DisplayGain(balance_traces=True), DisplayGain(reverse_polarity=True)]


@pytest.mark.parametrize("gain", OPTIONS, ids=["agc", "power", "balance", "polarity"])
def test_each_option_changes_the_picture_but_not_the_data(qgis_app, make_trace_layer, gain):
    a = trace_amplitudes_scaled()
    layer = make_trace_layer(a)
    kept = layer.traces.section.amplitudes.copy()
    hit = identify_layers([layer], 20.0, 490.0)
    plain = _pixels(build_drawing(layer, None).levels[0][0])
    shown = replace(layer, style=replace(layer.style, gain=gain))
    gained = _pixels(build_drawing(shown, None).levels[0][0])
    assert (gained != plain).any()
    assert np.array_equal(shown.traces.section.amplitudes, kept)
    assert shown.traces.section.amplitudes is layer.traces.section.amplitudes
    assert identify_layers([shown], 20.0, 490.0) == hit


def trace_amplitudes_scaled():
    """Signed traces that differ in strength and fade with time (every option shows)."""
    t = np.arange(50, dtype=np.float32)
    a = np.sin(t / 3.0)[None, :] * np.exp(-t / 15.0)[None, :]
    return (a * np.linspace(1.0, 5.0, 11, dtype=np.float32)[:, None]).astype(np.float32)


def test_without_an_option_nothing_is_copied(qgis_app, trace_layer):
    sec = trace_layer.traces.section
    assert display_values(sec, DisplayGain()) is sec.amplitudes
    build_drawing(trace_layer, None)
    assert display_render.shown_values(trace_layer) is not None
    entry = display_render._trace_entry(trace_layer)
    assert entry.shown is None                   # the drawing used the file's own array


def test_one_gained_copy_per_layer(qgis_app, trace_layer):
    for window in (0.005, 0.01, 0.02):
        build_drawing(replace(trace_layer, style=replace(trace_layer.style,
                                                         gain=DisplayGain(agc_window=window))),
                      None)
    assert len([k for k in display_render._traces if k[0] == trace_layer.dataset.id]) == 1


def test_swap_polarity_mirrors_the_colours(qgis_app, make_trace_layer):
    a = np.where(np.arange(11)[:, None] % 2 == 0, 1.0, -1.0).astype(np.float32) * np.ones((1, 50))
    layer = make_trace_layer(a.astype(np.float32))
    plain = _pixels(build_drawing(layer, None).levels[0][0])
    swapped = replace(layer, style=replace(layer.style, gain=DisplayGain(reverse_polarity=True)))
    mirrored = _pixels(build_drawing(swapped, None).levels[0][0])
    assert (plain[:, 0] != plain[:, 1]).all()
    assert (mirrored[:, 0] == plain[:, 1]).all() and (mirrored[:, 1] == plain[:, 0]).all()


def test_the_limits_follow_the_gain(qgis_app, make_trace_layer):
    layer = make_trace_layer(trace_amplitudes_scaled())
    gain = DisplayGain(time_power=2.0)
    style = replace(layer.style, gain=gain, clip_percent=90.0)
    shown = display_values(layer.traces.section, gain)
    assert trace_limits(layer, style) == pytest.approx(color_limits(shown, 90.0))
    assert trace_limits(layer, style, values=shown) == pytest.approx(color_limits(shown, 90.0))
    typed = replace(style, clip_percent=None, scale=ColorScale("gray", -3.0, 3.0, False))
    assert trace_limits(layer, typed) == (-3.0, 3.0)


def test_the_drawing_uses_the_clipped_limits(qgis_app, make_trace_layer):
    # the scale stored says -100 .. 100, the clip says otherwise: the clip wins while it is on
    layer = make_trace_layer(clip_percent=50.0, scale=ColorScale("gray", -100.0, 100.0, False))
    clipped = _pixels(build_drawing(layer, None).levels[0][0])
    typed = replace(layer, style=replace(layer.style, clip_percent=None))
    wide = _pixels(build_drawing(typed, None).levels[0][0])
    assert (clipped != wide).any()
    # with typed limits nearly everything is mid grey (the first sample of trace 1 is an
    # exact zero at the top, a muted sample: transparent)
    grey = ((wide >> 8) & 0xFF)[(wide >> 24) == 255]
    assert grey.min() > 110 and grey.max() < 145


# -- muted zones ---------------------------------------------------------------------------
def _muted_top(make_trace_layer, **style):
    """Traces of 1 and -1 whose first 20 samples (20 m below the datum of 500 m) are zero."""
    a = np.where(np.arange(50)[None, :] % 2 == 0, 1.0, -1.0) * np.ones((11, 1))
    a[:, :20] = 0.0
    return make_trace_layer(a.astype(np.float32), **style)


def test_a_muted_top_is_left_transparent(qgis_app, make_trace_layer):
    px = _paint([_muted_top(make_trace_layer)])
    # z 500 .. 481 m is y 14 .. 41 (100 px for 70 m): red shows through; below it the picture
    assert (px[16:40, 50:150] == RED).all()
    assert (px[45:80, 50:150] != RED).all()


def test_show_muted_paints_the_muted_top(qgis_app, make_trace_layer):
    layer = _muted_top(make_trace_layer, gain=DisplayGain(show_muted=True))
    px = _paint([layer])
    assert (px[16:80, 50:150] != RED).all()
    assert display_render._trace_entry(layer).shown is None       # no gained copy for it


def test_the_mute_is_a_bool_mask_kept_once_per_layer(qgis_app, make_trace_layer, monkeypatch):
    from groundwork_geophysics.core import trace_section
    calls = {"n": 0}
    real = trace_section.muted_mask

    def counted(a):
        calls["n"] += 1
        return real(a)
    monkeypatch.setattr(display_render, "muted_mask", counted)
    layer = _muted_top(make_trace_layer)
    build_drawing(layer, None)
    entry = display_render._trace_entry(layer)
    assert entry.mute.dtype == bool and entry.mute.shape == (11, 50)
    for gain in (DisplayGain(agc_window=0.01), DisplayGain(time_power=2.0)):
        build_drawing(replace(layer, style=replace(layer.style, gain=gain)), None)
    assert calls["n"] == 1


def test_the_limits_do_not_follow_the_mute(qgis_app, make_trace_layer):
    layer = _muted_top(make_trace_layer, clip_percent=50.0)
    shown = replace(layer, style=replace(layer.style, gain=DisplayGain(show_muted=True)))
    build_drawing(layer, None)
    hidden = display_render.shown_values(layer)
    build_drawing(shown, None)
    assert hidden is not None
    assert np.array_equal(hidden, display_render.shown_values(shown))
    assert trace_limits(layer, layer.style, values=hidden) == color_limits(layer.traces.section, 50.0)


def test_show_muted_writes_a_new_level_file(qgis_app, cached_layer, tmp_path):
    build_drawing(cached_layer, None)
    (old,) = _level_files(tmp_path)
    shown = replace(cached_layer, style=replace(cached_layer.style,
                                                gain=DisplayGain(show_muted=True)))
    build_drawing(shown, None)
    (new,) = _level_files(tmp_path)
    assert new != old


# -- the levels on disk --------------------------------------------------------------------
@pytest.fixture
def cached_layer(make_trace_layer, tmp_path, monkeypatch):
    monkeypatch.setattr(display_render, "LEVEL_CACHE_MIN_SECONDS", 0.0)
    return make_trace_layer(trace_amplitudes_scaled(), level_cache=(tmp_path, "read-key"))


@pytest.fixture
def reduce_calls(monkeypatch):
    count = {"n": 0}
    real = display_render.reduce_image

    def counted(*args, **kwargs):
        count["n"] += 1
        return real(*args, **kwargs)
    monkeypatch.setattr(display_render, "reduce_image", counted)
    return count


def _level_files(folder, did="s1"):
    return sorted(folder.glob(f"{did}.*.levels.npz"))


def test_the_levels_are_read_back_from_disk(qgis_app, cached_layer, tmp_path, reduce_calls):
    first = [_pixels(img) for img, _r in build_drawing(cached_layer, None).levels]
    assert reduce_calls["n"] == 3 and len(_level_files(tmp_path)) == 1
    display_render.clear_cache()
    again = build_drawing(cached_layer, None)
    assert reduce_calls["n"] == 3                                   # none: read from the file
    assert all((a == _pixels(img)).all() for a, (img, _r) in zip(first, again.levels))
    assert [r for _i, r in again.levels] == [r for _i, r in build_drawing(cached_layer,
                                                                          None).levels]


def test_a_new_look_colours_the_kept_grids(qgis_app, cached_layer, reduce_calls):
    build_drawing(cached_layer, None)
    for style in (replace(cached_layer.style, scale=ColorScale("viridis", -1.0, 1.0, False)),
                  replace(cached_layer.style, clip_percent=50.0),
                  replace(cached_layer.style, opacity=0.3)):
        build_drawing(replace(cached_layer, style=style), None)
    assert reduce_calls["n"] == 3


def test_a_changed_gain_writes_a_new_file(qgis_app, cached_layer, tmp_path):
    build_drawing(cached_layer, None)
    (old,) = _level_files(tmp_path)
    gained = replace(cached_layer, style=replace(cached_layer.style,
                                                 gain=DisplayGain(balance_traces=True)))
    build_drawing(gained, None)
    (new,) = _level_files(tmp_path)
    assert new != old and not old.exists()


def test_a_corrupt_file_is_ignored(qgis_app, cached_layer, tmp_path, reduce_calls):
    build_drawing(cached_layer, None)
    (path,) = _level_files(tmp_path)
    path.write_bytes(b"not a level file")
    display_render.clear_cache()
    d = build_drawing(cached_layer, None)
    assert len(d.levels) == 3 and reduce_calls["n"] == 6


def test_an_unwritable_folder_is_ignored(qgis_app, make_trace_layer, tmp_path, monkeypatch):
    monkeypatch.setattr(display_render, "LEVEL_CACHE_MIN_SECONDS", 0.0)
    blocker = tmp_path / "file"
    blocker.write_text("x")
    layer = make_trace_layer(level_cache=(blocker / "inside", "k"))
    assert len(build_drawing(layer, None).levels) == 3


def test_a_quick_section_is_not_worth_a_file(qgis_app, make_trace_layer, tmp_path):
    layer = make_trace_layer(level_cache=(tmp_path, "read-key"))
    build_drawing(layer, None)                  # far below LEVEL_CACHE_MIN_SECONDS
    assert not _level_files(tmp_path)


def test_a_new_placement_is_a_new_file(qgis_app, make_trace_layer, tmp_path, monkeypatch):
    monkeypatch.setattr(display_render, "LEVEL_CACHE_MIN_SECONDS", 0.0)
    build_drawing(make_trace_layer(level_cache=(tmp_path, "k")), None)
    (old,) = _level_files(tmp_path)
    build_drawing(make_trace_layer(z_top=300.0, level_cache=(tmp_path, "k")), None)
    (new,) = _level_files(tmp_path)
    assert new != old


def test_the_reader_cache_keeps_its_own_files(qgis_app, cached_layer, tmp_path):
    # the remembered reads are "<id>-<key>.npz": forgetting them leaves the levels alone
    from groundwork_geophysics.section.data import _forget_others
    build_drawing(cached_layer, None)
    kept = tmp_path / "s1-abc.npz"
    kept.write_bytes(b"")
    _forget_others(kept, "s1")
    assert len(_level_files(tmp_path)) == 1
