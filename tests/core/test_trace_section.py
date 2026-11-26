"""Trace sections: depths from a velocity, placing, readout, display gain and the picture."""
import numpy as np
import pytest

from groundwork_geophysics.core.trace_section import (
    DisplayGain, TraceSection, Velocity, agc, color_limits, depth_at, display_values, ground_time,
    muted_mask, place, reduce_image, sample_depths)


def _section(a, **kw):
    a = np.asarray(a, np.float32)
    return TraceSection(a, np.arange(a.shape[0]) * 2.0, kw.get("first", 0.0),
                        kw.get("step", 0.001), kw.get("domain", "time"))


V = Velocity          # V(2000.0) is one velocity


def test_depths_are_half_the_two_way_time_times_velocity():
    s = _section(np.zeros((3, 5)), first=0.006, step=0.0001)
    assert sample_depths(s, V(1500.0))[:2] == pytest.approx([4.5, 4.575])


def test_depth_section_needs_no_velocity():
    s = _section(np.zeros((3, 5)), first=10.0, step=2.0, domain="depth")
    assert list(sample_depths(s, None)) == [10.0, 12.0, 14.0, 16.0, 18.0]


@pytest.mark.parametrize("v", [None, V(), V(0.0), V(-5.0), V(float("nan"))])
def test_time_section_without_a_velocity_says_so(v):
    with pytest.raises(ValueError, match="velocity"):
        sample_depths(_section(np.zeros((3, 5))), v)


def test_average_velocity_function():
    s = _section(np.zeros((1, 3)), first=0.0, step=1.0)             # t = 0, 1, 2 s
    v = V(table=((0.0, 2000.0), (2.0, 4000.0)), kind="average")      # v(1 s) = 3000
    assert list(sample_depths(s, v)) == pytest.approx([0.0, 1500.0, 4000.0])


def test_interval_velocity_function():
    s = _section(np.zeros((1, 4)), first=0.0, step=1.0)             # t = 0..3 s
    v = V(table=((0.0, 2000.0), (2.0, 4000.0)), kind="interval")
    assert list(sample_depths(s, v)) == pytest.approx([0.0, 1000.0, 2000.0, 4000.0])


def test_a_function_whose_depths_turn_back_is_refused():
    s = _section(np.zeros((1, 3)), first=1.0, step=1.0)
    with pytest.raises(ValueError, match="do not increase"):
        sample_depths(s, V(table=((1.0, 4000.0), (2.0, 1000.0)), kind="average"))


@pytest.mark.parametrize("table", [((1.0, 2000.0), (1.0, 3000.0)), ((0.0, 2000.0), (1.0, 0.0))])
def test_a_table_with_times_that_do_not_increase_or_a_zero_velocity_is_refused(table):
    with pytest.raises(ValueError, match="velocity"):
        sample_depths(_section(np.zeros((1, 3))), V(table=table))


def test_velocity_from_options_and_its_text():
    assert Velocity.from_options({"velocity": 1500.0}).text() == "v = 1500 m/s"
    v = Velocity.from_options({"velocity_table": [[0, 1800], [2, 3400]], "velocity_kind": "interval"})
    assert v.kind == "interval" and v.text() == "a velocity function (1800–3400 m/s)"
    assert Velocity.from_options({}) == Velocity()


def test_display_values_without_gain_is_the_same_array():
    s = _section(np.ones((2, 5)))
    assert display_values(s, DisplayGain()) is s.amplitudes


def test_time_power_trace_balance_and_polarity():
    s = _section([[1.0, 1, 1], [4, 4, 4]], first=1.0, step=1.0)          # t = 1, 2, 3 s
    assert list(display_values(s, DisplayGain(time_power=2.0))[0]) == [1.0, 4.0, 9.0]
    b = display_values(s, DisplayGain(balance_traces=True))
    assert np.allclose(b[0], b[1])
    assert list(display_values(s, DisplayGain(reverse_polarity=True))[0]) == [-1.0, -1.0, -1.0]
    assert s.amplitudes[1, 0] == 4.0                                      # the data are untouched


def test_display_gain_round_trips_and_reports_activity():
    g = DisplayGain(agc_window=0.25, time_power=1.5, balance_traces=True, reverse_polarity=True)
    assert g.active() and DisplayGain.from_dict(g.to_dict()) == g
    assert DisplayGain.from_dict(None) == DisplayGain() and not DisplayGain().active()
    assert DisplayGain.from_dict({"reverse_polarity": True}) == DisplayGain(reverse_polarity=True)


def test_agc_in_display_values_uses_the_window_in_seconds():
    a = np.outer(np.ones(2), np.sin(np.arange(400)) * np.exp(-np.arange(400) / 50)).astype(np.float32)
    s = TraceSection(a, np.array([0.0, 1.0]), 0.0, 0.001, "time")
    g = display_values(s, DisplayGain(agc_window=0.041))
    assert g.dtype == np.float32 and np.allclose(g, agc(a, 41))


def test_agc_balances_a_fading_trace_and_leaves_the_data():
    a = np.outer(np.ones(2), np.sin(np.arange(400)) * np.exp(-np.arange(400) / 50)).astype(np.float32)
    g = agc(a, 41)
    assert g is not a and g.dtype == np.float32 and a[0, 399] != g[0, 399]
    early, late = np.abs(g[0, 20:60]).max(), np.abs(g[0, 340:380]).max()
    assert 0.5 < late / early < 2.0
    assert not np.isnan(agc(np.zeros((2, 50), np.float32), 11)).any()


def test_place_hangs_from_a_datum_and_reports_bounds():
    p = place(_section(np.zeros((3, 5)), step=0.002), 500.0, V(2000.0))
    assert p.bounds() == pytest.approx((0.0, 4.0, 500.0 - 4 * 2.0, 500.0))


def test_place_orders_traces_that_run_backwards():
    a = np.array([[1.0, 1], [2, 2], [3, 3]], np.float32)
    s = TraceSection(a, np.array([4.0, 2.0, 0.0]), 0.0, 0.001, "time")
    p = place(s, 0.0, V(2000.0))
    assert list(p.section.x) == [0.0, 2.0, 4.0] and p.section.amplitudes[0, 0] == 3.0


def test_place_orders_mixed_traces_with_their_numbers_and_datum():
    a = np.array([[1.0], [2], [3]], np.float32)
    s = TraceSection(a, np.array([2.0, 0.0, 4.0]), 0.0, 0.001, "time", numbers=np.array([10, 11, 12]))
    p = place(s, np.array([5.0, 6.0, 7.0]), V(2000.0))
    assert list(p.section.amplitudes[:, 0]) == [2.0, 1.0, 3.0]
    assert list(p.section.numbers) == [11, 10, 12] and list(p.z_top) == [6.0, 5.0, 7.0]


def test_hit_gives_amplitude_time_and_depth():
    a = np.arange(15, dtype=np.float32).reshape(3, 5)
    p = place(_section(a, step=0.002), 100.0, V(2000.0))
    h = p.hit(2.1, 100.0 - 4.1)          # trace 1, sample 2 (depth 4 m)
    assert (h["trace"], h["sample"], h["amplitude"]) == (1, 2, 7.0)
    assert h["time"] == pytest.approx(0.004) and h["depth"] == pytest.approx(4.0)
    assert p.hit(50.0, 99.0) is None and p.hit(2.0, 120.0) is None


def test_hit_below_the_last_sample_is_outside_and_depth_sections_have_no_time():
    s = TraceSection(np.ones((2, 3), np.float32), np.array([0.0, 2.0]), 0.0, 1.0, "depth",
                     numbers=np.array([101, 102]))
    p = place(s, 10.0, None)
    h = p.hit(1.9, 10.0 - 2.4)
    assert h["time"] is None and h["number"] == 102 and h["sample"] == 2
    assert p.hit(1.9, 10.0 - 2.6) is None


def test_clip_and_limits_for_signed_and_positive_data():
    assert color_limits(_section([[-4.0, 1], [2, 3]]), 100.0) == (-4.0, 4.0)
    assert color_limits(_section([[0.0, 1], [2, 3]]), 100.0) == (0.0, 3.0)


def test_limits_of_a_plain_array():
    assert color_limits(np.array([[-2.0, 1.0]]), 100.0) == (-2.0, 2.0)


@pytest.mark.parametrize("a", [np.zeros((4, 6)), np.full((4, 6), np.nan), np.full((4, 6), 7.0)])
def test_limits_never_collapse(a):                       # Review Focus 2
    lo, hi = color_limits(_section(a), 98.0)
    assert np.isfinite([lo, hi]).all() and hi > lo


def test_reduce_keeps_the_strongest_sample_with_its_sign():
    a = np.zeros((8, 8), np.float32); a[3, 5] = -9.0; a[4, 5] = 2.0
    img, _ = reduce_image(place(_section(a), 0.0, V(2000.0)), max_width=4, max_height=4)
    assert img.shape == (4, 4) and np.nanmin(img) == -9.0


def test_reduce_without_reduction_is_the_section_itself():
    a = np.arange(12, dtype=np.float32).reshape(3, 4)          # 3 traces 2 m apart, 1 m samples
    img, ext = reduce_image(place(_section(a), 50.0, V(2000.0)))
    assert ext == pytest.approx((-1.0, 5.0, 50.0 - 3.5, 50.5))
    assert img.shape == (4, 3) and (img == a.T).all()


def test_reduce_shifts_columns_where_the_datum_varies():
    a = np.ones((2, 2), np.float32)
    a[1] = 2.0
    s = TraceSection(a, np.array([0.0, 2.0]), 0.0, 1.0, "depth")
    img, ext = reduce_image(place(s, np.array([10.0, 11.0]), None))
    assert ext == pytest.approx((-1.0, 3.0, 10.0 - 1.5, 11.5))
    assert img.shape == (3, 2)
    assert np.isnan(img[0, 0]) and list(img[1:, 0]) == [1.0, 1.0]
    assert list(img[:2, 1]) == [2.0, 2.0] and np.isnan(img[2, 1])


def test_reduce_puts_a_velocity_function_on_an_even_depth_grid():
    # interval velocities: 2000 m/s down to 2 s, 4000 below; samples at 0..3 s
    a = np.array([[1.0, 2.0, 3.0, 4.0]], np.float32)
    p = place(TraceSection(a, np.array([0.0]), 0.0, 1.0, "time"), 0.0,
              V(table=((0.0, 2000.0), (2.0, 4000.0)), kind="interval"))
    assert list(p.depths) == [0.0, 1000.0, 2000.0, 4000.0]
    img, ext = reduce_image(p)
    # sample edges -500, 500, 1500, 3000, 5000 m: 5500 m in rows of at most 1000 m -> six rows
    assert ext == pytest.approx((-0.5, 0.5, -5000.0, 500.0))
    assert img.shape == (6, 1) and list(img[:, 0]) == [1.0, 2.0, 3.0, 3.0, 4.0, 4.0]


def _reference_image(p, w, h, mute=None):
    """Cell by cell: the strongest of the trace and sample centres in it, else the nearest;
    samples ``mute`` marks are left out (NaN when nothing else is in the cell)."""
    sec, (s0, s1, z0, z1) = p.section, reduce_image(p, w, h)[1]
    xe = np.r_[sec.x[0] - 0.5 * (sec.x[1] - sec.x[0]), 0.5 * (sec.x[1:] + sec.x[:-1]),
               sec.x[-1] + 0.5 * (sec.x[-1] - sec.x[-2])]
    de = np.r_[p.depths[0] - 0.5 * (p.depths[1] - p.depths[0]), 0.5 * (p.depths[1:] + p.depths[:-1]),
               p.depths[-1] + 0.5 * (p.depths[-1] - p.depths[-2])]
    ds, dz = (s1 - s0) / w, (z1 - z0) / h
    img = np.full((h, w), np.nan)
    for j in range(w):
        lo, hi = s0 + j * ds, s0 + (j + 1) * ds
        tr = [i for i in range(sec.n_traces) if lo <= sec.x[i] < hi or (j == w - 1 and sec.x[i] == hi)]
        if not tr:
            tr = [int(np.searchsorted(xe, lo + 0.5 * ds, "right") - 1)]
        for r in range(h):
            top, bottom = z1 - r * dz, z1 - (r + 1) * dz
            best = np.nan
            for i in tr:
                el = p.z_top[i] - p.depths
                ks = [k for k in range(sec.n_samples) if bottom < el[k] <= top]
                if not ks:
                    d = p.z_top[i] - (top - 0.5 * dz)
                    k = int(np.searchsorted(de, d, "right") - 1)
                    ks = [k] if 0 <= k < sec.n_samples else []
                for k in ks:
                    if mute is not None and mute[i, k]:
                        continue
                    v = float(sec.amplitudes[i, k])
                    if np.isnan(best) or abs(v) > abs(best):
                        best = v
            img[r, j] = best
    return img


@pytest.mark.parametrize("muted", [False, True])
@pytest.mark.parametrize("z_top", [20.0, "varying"])
@pytest.mark.parametrize("w, h", [(5, 4), (40, 30)])
def test_reduce_matches_the_rule_cell_by_cell(z_top, w, h, muted):
    rng = np.random.default_rng(1)
    a = rng.standard_normal((13, 11)).astype(np.float32)
    mute = rng.random(a.shape) < 0.4 if muted else None
    if muted:
        mute[2] = True                                   # one trace muted all through
    z = 20.0 + 3.0 * np.arange(13) % 7 if z_top == "varying" else z_top
    p = place(_section(a), z, V(2000.0))
    img, _ = reduce_image(p, w, h, mute=mute)
    assert np.allclose(img, _reference_image(p, *img.shape[::-1], mute=mute), equal_nan=True)
    if muted:
        assert not np.allclose(img, reduce_image(p, w, h)[0], equal_nan=True)   # it matters


def test_ground_time_and_depth_at():
    assert list(ground_time(700.0, np.array([700.0, 600.0, 720.0]), 2000.0)) == \
        pytest.approx([0.0, 0.1, -0.02])
    s = _section(np.zeros((1, 3)), first=0.0, step=1.0)
    assert list(depth_at(s, V(2000.0), np.array([0.5, 3.0]))) == [500.0, 3000.0]


def test_depth_at_one_velocity_holds_above_time_zero_too():
    s = _section(np.zeros((1, 3)), first=0.1, step=0.1)
    assert depth_at(s, V(3000.0), np.array([-0.02, 0.0, 0.5])) == pytest.approx([-30.0, 0.0, 750.0])


def test_depth_at_follows_a_velocity_function_and_its_end_slopes():
    s = _section(np.zeros((1, 4)), first=0.0, step=1.0)             # t = 0..3 s
    v = V(table=((0.0, 2000.0), (2.0, 4000.0)), kind="interval")     # depths 0, 1000, 2000, 4000
    assert depth_at(s, v, np.array([1.5, 2.5, 4.0, -1.0])) == pytest.approx(
        [1500.0, 3000.0, 6000.0, -1000.0])
    one = _section(np.zeros((1, 1)), first=1.0, step=0.5)
    assert depth_at(one, v, np.array([1.0, 2.0])) == pytest.approx([1000.0, 2000.0])


def test_depth_at_refuses_a_depth_section():
    with pytest.raises(ValueError):
        depth_at(_section(np.zeros((1, 3)), domain="depth", step=1.0), None, np.array([0.0]))


def test_muted_mask_marks_edges_not_the_inside():
    a = np.array([[0, 0, 5, 0, 7, 0], [0, 0, 0, 0, 0, 0], [1, 0, 0, 2, 3, 4]], np.float32)
    m = muted_mask(a)
    assert m.tolist() == [[True, True, False, False, False, True], [True] * 6, [False] * 6]
    assert m.dtype == bool and muted_mask(a.astype(np.int16)).tolist() == m.tolist()


def test_live_from_mutes_the_samples_above_it():
    a = np.arange(1, 13, dtype=np.float32).reshape(3, 4)            # no zeros at all
    m = muted_mask(a, np.array([0, 2, 1]))
    assert [list(np.flatnonzero(row)) for row in m] == [[], [0, 1], [0]]
    a[2, 3] = 0.0                                                    # with an end run too
    assert muted_mask(a, np.array([0, 2, 1]))[2].tolist() == [True, False, False, True]


def test_place_carries_live_from_in_the_trace_order():
    s = TraceSection(np.ones((3, 4), np.float32), np.array([4.0, 2.0, 0.0]), 0.0, 0.001, "time")
    p = place(s, 0.0, V(2000.0), live_from=np.array([0, 1, 3]))
    assert list(p.live_from) == [3, 1, 0]
    assert place(s, 0.0, V(2000.0)).live_from is None
    with pytest.raises(ValueError):
        place(s, 0.0, V(2000.0), live_from=np.array([0, 1]))


def test_reduce_leaves_fully_muted_cells_empty():
    a = np.zeros((4, 8), np.float32); a[:, 4:] = 1.0
    p = place(_section(a), 0.0, V(2000.0))
    img, _ = reduce_image(p, mute=muted_mask(a))
    assert np.isnan(img[:4]).all() and np.isfinite(img[4:]).all()


def test_a_cell_with_muted_and_live_samples_keeps_the_live_one():
    a = np.zeros((2, 8), np.float32); a[:, 3:] = 0.5; a[:, 7] = -0.25
    p = place(_section(a), 0.0, V(2000.0))
    img, _ = reduce_image(p, max_width=1, max_height=2, mute=muted_mask(a))
    assert img[:, 0].tolist() == [0.5, 0.5]              # the top row: three muted, one live


def test_show_muted_round_trips_and_needs_no_gained_copy():
    g = DisplayGain(show_muted=True)
    assert not g.active() and DisplayGain.from_dict(g.to_dict()) == g
    assert DisplayGain.from_dict({"agc_window": 0.2}).show_muted is False
    s = _section(np.ones((2, 5)))
    assert display_values(s, g) is s.amplitudes


def test_with_x_and_place_share_the_samples():            # Review Focus 5
    s = _section(np.zeros((4, 6)))
    assert s.with_x(lambda x: x + 10).amplitudes is s.amplitudes
    assert place(s, 0.0, V(1500.0)).section.amplitudes is s.amplitudes


def test_integer_samples_keep_their_type():
    s = TraceSection(np.ones((2, 3), np.int16), np.array([0.0, 1.0]), 0.0, 0.001, "time")
    assert s.amplitudes.dtype == np.int16 and s.clip(100.0) == 1.0


def test_large_sections_are_sampled_for_clip_and_sign():
    a = np.ones((2000, 500), np.float32)
    a[::7, ::3] = -1.0
    s = TraceSection(a, np.arange(2000.0), 0.0, 0.001, "time")
    assert s.signed() and s.clip(50.0) == 1.0


# -- AGC and trace balance keep dead and muted parts quiet ---------------------------------
def _half_dead(rng_seed=3):
    """Two traces: a signal in the first half, exact zeros plus leftovers of 1e-6 of the
    signal's size in the second half."""
    rng = np.random.default_rng(rng_seed)
    n = 400
    sig = np.sin(np.arange(n) / 2.0)
    a = np.outer(np.ones(2), sig)
    a[:, n // 2:] = 0.0
    a[:, n // 2::7] = 1e-6 * rng.standard_normal(a[:, n // 2::7].shape)
    return a.astype(np.float32)


def test_agc_keeps_a_muted_part_quiet():
    a = _half_dead()
    g = agc(a, 21)
    level = np.abs(g[:, 20:180]).max()
    assert level > 0.5
    assert np.abs(g[:, 230:]).max() < 0.01 * level


def test_agc_floor_zero_is_the_plain_division():
    a = _half_dead()
    assert np.abs(agc(a, 21, floor=0.0)[:, 230:]).max() > 0.1


def test_agc_of_dead_data_is_zero():
    g = agc(np.zeros((3, 60), np.float32), 11)
    assert not np.isnan(g).any() and not g.any()
    assert not np.isnan(display_values(_section(np.zeros((3, 60), np.float32)),
                                       DisplayGain(agc_window=0.01, balance_traces=True))).any()


def test_trace_balance_keeps_a_dead_trace_dead():
    a = np.outer(np.ones(3), np.sin(np.arange(100) / 2.0)).astype(np.float32)
    a[1] = 1e-6 * np.sin(np.arange(100) / 2.0)        # a dead trace with leftovers
    a[2] = 0.0                                         # an exactly zero one
    g = display_values(_section(a), DisplayGain(balance_traces=True))
    assert np.abs(g[0]).max() > 0.5
    assert np.abs(g[1]).max() < 0.01 * np.abs(g[0]).max() and not g[2].any()


def test_gain_with_time_never_lifts_a_dead_trace():
    a = np.outer(np.ones(2), np.sin(np.arange(100) / 2.0)).astype(np.float32)
    a[1] = 1e-6 * a[0]
    g = display_values(_section(a, step=0.01), DisplayGain(time_power=2.0))
    assert np.abs(g[1]).max() <= 1e-5 * np.abs(g[0]).max()
