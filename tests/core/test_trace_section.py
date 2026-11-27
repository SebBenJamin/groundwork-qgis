"""Trace sections: depths from a velocity, placing, readout, display gain and the picture."""
import numpy as np
import pytest

from groundwork_geophysics.core.trace_section import (
    DisplayGain, TraceSection, Velocity, agc, color_limits, depth_at, dielectric_from_velocity,
    display_values, first_arrival, ground_time, muted_mask, place, reduce_image, sample_depths,
    velocity_from_dielectric)


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


def test_a_constant_rms_function_is_the_one_velocity():
    s = _section(np.zeros((1, 5)), first=0.0, step=0.5)             # t = 0..2 s
    rms = V(table=((0.5, 2500.0), (1.0, 2500.0), (2.0, 2500.0)), kind="rms")
    assert list(sample_depths(s, rms)) == pytest.approx(list(sample_depths(s, V(2500.0))))


def test_rms_velocities_become_interval_velocities_by_dix():
    # interval 2 is sqrt((10e6 * 2 - 2000**2 * 1) / 1) = 4000 m/s
    s = _section(np.zeros((1, 4)), first=0.0, step=1.0)             # t = 0..3 s
    rms = V(table=((1.0, 2000.0), (2.0, 10e6 ** 0.5)), kind="rms")
    assert list(sample_depths(s, rms)) == pytest.approx([0.0, 1000.0, 3000.0, 5000.0])
    assert depth_at(s, rms, np.array([0.5, 1.5])) == pytest.approx([500.0, 2000.0])


def test_rms_velocities_without_a_real_interval_velocity_are_refused():
    s = _section(np.zeros((1, 3)), first=0.0, step=1.0)
    with pytest.raises(ValueError, match="^The RMS velocities give no real interval velocity "
                                         "between 1000 ms and 2000 ms.$"):
        sample_depths(s, V(table=((1.0, 3000.0), (2.0, 2000.0)), kind="rms"))


def test_rms_is_kept_and_an_unknown_kind_reads_as_average():
    assert Velocity.from_options({"velocity_table": [[0, 1800], [2, 3400]],
                                  "velocity_kind": "rms"}).kind == "rms"
    assert Velocity.from_options({"velocity_table": [[0, 1800], [2, 3400]],
                                  "velocity_kind": "stacking"}).kind == "average"


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


def test_dielectric_and_velocity_convert_both_ways():
    assert velocity_from_dielectric(9.0) == pytest.approx(0.299792458e9 / 3)
    assert dielectric_from_velocity(1.0e8) == pytest.approx(8.98755, rel=1e-4)
    for bad in (0.5, float("nan")):
        with pytest.raises(ValueError, match="dielectric"):
            velocity_from_dielectric(bad)
    for bad in (0.0, 4.0e8):
        with pytest.raises(ValueError, match="speed of light"):
            dielectric_from_velocity(bad)


def test_time_zero_puts_that_sample_on_the_ground():
    s = _section(np.zeros((2, 10)), first=0.0, step=1e-9)          # 10 samples of 1 ns
    p = place(s, 100.0, V(1.0e8), time_zero=3e-9)
    assert p.depths[3] == pytest.approx(0.0) and p.depths[5] == pytest.approx(0.10)
    assert list(p.live_from) == [3, 3]
    h = p.hit(0.0, 100.0 - 0.10)
    assert h["sample"] == 5 and h["time"] == pytest.approx(5e-9) and h["depth"] == pytest.approx(0.10)


def test_time_zero_beyond_the_record_and_on_a_depth_section_are_refused():
    s = _section(np.zeros((2, 10)), step=1e-9)
    with pytest.raises(ValueError, match="beyond the end"):
        place(s, 0.0, V(1e8), time_zero=1e-6)
    d = _section(np.zeros((2, 10)), step=1.0, domain="depth")
    with pytest.raises(ValueError):
        place(d, 0.0, None, time_zero=1.0)


def test_time_zero_keeps_a_given_live_from_where_it_is_later_and_shifts_depth_at():
    s = _section(np.zeros((3, 10)), step=1e-9)
    p = place(s, 0.0, V(1.0e8), np.array([1, 5, 3]), time_zero=3e-9)
    assert list(p.live_from) == [3, 5, 3]
    assert p.bounds()[3] == 0.0                       # the top is the ground (time zero)
    assert depth_at(s, V(1.0e8), np.array([5e-9]), time_zero=3e-9)[0] == pytest.approx(0.10)
    assert sample_depths(s, V(1.0e8), 3e-9)[0] == pytest.approx(-0.15)
    assert place(s, 0.0, V(1.0e8), time_zero=0.0).live_from is None


def test_first_arrival_finds_the_direct_wave():
    a = np.zeros((50, 200), np.float32)
    a[:, 40:44] = [300, -500, 400, -100]
    a += np.random.default_rng(0).normal(0, 1, a.shape).astype(np.float32)
    s = _section(a, step=1e-9)
    assert first_arrival(s) == pytest.approx(40e-9, abs=2e-9)
    assert first_arrival(_section(np.zeros((3, 10)), first=0.002)) == 0.002   # nothing qualifies


def test_dewow_removes_a_slow_drift_and_keeps_a_wavelet():
    t = np.arange(400)
    drift = 50 * np.exp(-t / 150.0)
    wave = np.zeros(400)
    wave[200:204] = [5, -9, 6, -2]
    s = _section(np.tile(drift + wave, (3, 1)), step=1e-9)
    d = display_values(s, DisplayGain(dewow_window=20e-9))
    assert abs(d[0, 100]) < 2.0 and abs(d[0, 201]) > 5.0 and d.dtype == np.float32
    assert s.amplitudes[0, 100] == pytest.approx(drift[100])           # the data are untouched


def test_background_removal_takes_out_what_every_trace_shares():
    a = np.zeros((40, 50), np.float32)
    a[:, 10] = 7.0
    a[20, 30] = 4.0                                    # a band and one reflector
    d = display_values(_section(a), DisplayGain(background="all"))
    assert abs(d[5, 10]) < 0.2 and d[20, 30] > 3.5
    w = display_values(_section(a), DisplayGain(background="window", background_traces=11))
    assert abs(w[5, 10]) < 0.2 and w[20, 30] > 3.0


def test_background_window_matches_a_plain_moving_mean_across_blocks(monkeypatch):
    import groundwork_geophysics.core.trace_section as ts
    monkeypatch.setattr(ts, "_BLOCK", 7 * 5)           # blocks of 5 traces, fewer than the window
    a = np.random.default_rng(1).normal(0, 1, (23, 7)).astype(np.float32)
    a[4, 2] = np.nan
    got = display_values(_section(a), DisplayGain(background="window", background_traces=10))
    want = np.empty_like(a, dtype=np.float64)
    for i in range(23):                               # 10 is read as 11: five traces each side
        want[i] = a[i] - np.nanmean(a[max(0, i - 5):i + 6].astype(np.float64), axis=0)
    assert np.isnan(got[4, 2]) and np.allclose(got[~np.isnan(a)], want[~np.isnan(a)], atol=1e-5)


def _two_tones(n_traces=3, n=1024, step=0.25e-9):
    """Traces of a 20 MHz and a 100 MHz sine of amplitude 1 each, with a constant offset."""
    t = np.arange(n) * step
    slow, fast = np.sin(2 * np.pi * 20e6 * t), np.sin(2 * np.pi * 100e6 * t)
    a = np.tile(slow + fast + 3.0, (n_traces, 1))
    return _section(a, step=step), slow, fast


def test_band_pass_keeps_the_band_and_takes_out_what_lies_below_it():
    s, slow, fast = _two_tones()
    d = display_values(s, DisplayGain(band_low=50e6, band_high=200e6))
    mid = slice(200, -200)                              # away from the ends of the trace
    rest = d[0, mid] - fast[mid]
    assert np.abs(rest).max() < 0.05                    # the 100 MHz part within 5 %
    # what is left of the 20 MHz part: its share in the output, by projection on it
    share = abs(np.dot(d[0, mid], slow[mid]) / np.dot(slow[mid], slow[mid]))
    assert share < 0.02 and d.dtype == np.float32
    assert s.amplitudes[0, 0] == pytest.approx(3.0)                 # the data are untouched


def test_band_pass_off_leaves_the_values_as_they_are():
    s, _slow, _fast = _two_tones()
    assert display_values(s, DisplayGain()) is s.amplitudes
    assert display_values(s, DisplayGain(band_low=0.0, band_high=None)) is s.amplitudes
    assert not DisplayGain(band_low=0.0, band_high=0.0).active()
    assert DisplayGain(band_low=50e6, band_high=200e6).active()


def test_band_pass_in_blocks_equals_the_whole_at_once(monkeypatch):
    import groundwork_geophysics.core.trace_section as ts
    a = np.random.default_rng(3).normal(0, 1, (23, 300)).astype(np.float32)
    a[5, 40] = np.nan
    g = DisplayGain(band_low=50e6, band_high=200e6)
    whole = display_values(_section(a, step=0.25e-9), g)
    monkeypatch.setattr(ts, "_BLOCK", 300 * 4)          # blocks of a few traces
    blocks = display_values(_section(a, step=0.25e-9), g)
    assert np.isnan(blocks[5, 40]) and np.isnan(whole[5, 40])
    ok = ~np.isnan(a)
    assert np.allclose(blocks[ok], whole[ok], atol=1e-6)


def test_band_pass_corners_that_cannot_be_used_do_no_harm():
    s, _slow, fast = _two_tones()                       # Nyquist 2 GHz
    plain = s.amplitudes
    # low at or above high, or low at or above Nyquist: the option is ignored
    for low, high in ((200e6, 50e6), (100e6, 100e6), (3e9, None), (float("nan"), None)):
        d = display_values(s, DisplayGain(band_low=low, band_high=high))
        assert np.allclose(d, plain, atol=1e-5), (low, high)
    # a high corner above Nyquist: only the low corner works (a high-pass)
    d = display_values(s, DisplayGain(band_low=50e6, band_high=5e9))
    assert np.abs(d[0, 200:-200] - fast[200:-200]).max() < 0.05
    # one corner alone: a high-pass or a low-pass
    lp = display_values(s, DisplayGain(band_high=40e6))
    assert np.abs(lp[0, 200:-200] - 3.0 - _slow[200:-200]).max() < 0.05


def test_band_pass_is_ignored_on_a_depth_section():
    a = np.random.default_rng(4).normal(0, 1, (3, 64)).astype(np.float32)
    s = _section(a, step=0.05, domain="depth")
    d = display_values(s, DisplayGain(band_low=1.0, band_high=4.0))
    assert np.allclose(d, a)


def test_band_pass_comes_through_the_dict_and_old_dicts_have_none():
    g = DisplayGain(band_low=50e6, band_high=200e6, agc_window=5e-8, background="all")
    assert DisplayGain.from_dict(g.to_dict()) == g
    old = DisplayGain.from_dict({"agc_window": 5e-8, "dewow_window": 2e-8})
    assert old.band_low is None and old.band_high is None
    assert "band_low" not in DisplayGain(agc_window=0.2).to_dict()        # stored as before
    assert DisplayGain.from_dict({"band_low": "x", "band_high": 2e8}).band_low is None


def test_a_section_shown_down_to_a_depth_keeps_only_the_samples_above_it():
    from groundwork_geophysics.core.trace_section import shown_down_to
    s = _section(np.arange(30.0).reshape(3, 10), step=1e-9)
    p = place(s, 100.0, V(1.0e8), time_zero=2e-9)          # depths (k - 2) * 0.05 m
    q = shown_down_to(p, 0.2)
    assert q.section.n_samples == 7 and q.depths[-1] == pytest.approx(0.2)
    assert np.shares_memory(q.section.amplitudes, p.section.amplitudes)      # no copy
    assert q.bounds()[2] == pytest.approx(99.8) and q.bounds()[3] == p.bounds()[3]
    assert q.hit(2.0, 99.75) is None and q.hit(2.0, 99.85) is not None
    assert q.time_zero == p.time_zero and list(q.live_from) == list(p.live_from)
    for limit in (None, 0.0, -1.0, float("nan"), "x", 0.4, 5.0):     # off, or below the record
        assert shown_down_to(p, limit) is p, limit
    assert shown_down_to(p, 0.001).section.n_samples == 3           # the top sample stays


def test_filters_survive_the_dict_round_trip_and_old_dicts_load():
    g = DisplayGain(dewow_window=20e-9, background="window", background_traces=11)
    assert DisplayGain.from_dict(g.to_dict()) == g and g.active()
    assert DisplayGain.from_dict({"agc_window": 0.2}).background == ""
    assert DisplayGain(background="all").active() and DisplayGain(dewow_window=1e-8).active()
    assert DisplayGain().to_dict() == DisplayGain.from_dict({}).to_dict()
    assert "background" not in DisplayGain(agc_window=0.2).to_dict()      # stored as before


# -- leading samples that are not data (GSSI's scan counter and marks), time zero ------------
def _counter_section(n=30, ns=60, step=1e-9):
    """A quiet section with a direct wave at sample 20 and two huge leading samples."""
    a = np.zeros((n, ns), np.float32)
    a[:, 20:23] = [300.0, -500.0, 200.0]
    a += np.random.default_rng(2).normal(0, 1, a.shape).astype(np.float32)
    a[:, 0] = -32768.0 + np.arange(n)
    a[:, 1] = -7168.0
    return _section(a, step=step)


def test_first_arrival_skips_the_leading_samples_that_are_not_data():
    s = _counter_section()
    assert first_arrival(s) == pytest.approx(0.0)                 # the counter wins
    assert first_arrival(s, skip=2) == pytest.approx(20e-9, abs=1e-9)


def test_colour_limits_skip_the_leading_samples():
    s = _counter_section()
    lo, hi = color_limits(s, 100.0, skip=2)
    assert hi == pytest.approx(500.0, rel=0.05) and lo == -hi
    assert color_limits(s, 100.0)[1] > 30000                      # without the skip
    assert color_limits(s.amplitudes, 100.0, skip=2) == (lo, hi)   # an array as well


def test_display_filters_leave_the_leading_samples_out():
    s = _counter_section()
    g = DisplayGain(dewow_window=5e-9, balance_traces=True)
    d = display_values(s, g, skip=2)
    assert np.isnan(d[:, :2]).all() and np.isfinite(d[:, 2:]).all()
    plain = display_values(replace_amplitudes(s, s.amplitudes[:, 2:]), g)
    assert np.allclose(d[:, 2:], plain, atol=1e-4)
    assert s.amplitudes[0, 0] == -32768.0                          # the file's samples stay


def replace_amplitudes(s, a):
    from dataclasses import replace
    return replace(s, amplitudes=np.ascontiguousarray(a))


def test_gain_with_time_counts_from_time_zero():
    s = _section(np.ones((2, 6)), step=1.0)
    assert list(display_values(s, DisplayGain(time_power=1.0))[0]) == [0, 1, 2, 3, 4, 5]
    got = display_values(s, DisplayGain(time_power=1.0), time_zero=2.0)
    assert list(got[0]) == [0, 0, 0, 1, 2, 3]
    agc_only = DisplayGain(agc_window=2.0)                        # unaffected by time zero
    assert np.array_equal(display_values(s, agc_only, time_zero=2.0), display_values(s, agc_only))


def test_place_keeps_time_zero_and_the_data_start():
    s = _section(np.ones((3, 10)), step=1e-9)
    p = place(s, 100.0, Velocity(1e8), time_zero=4e-9, data_start=2)
    assert list(p.live_from) == [4, 4, 4] and p.time_zero == 4e-9 and p.data_start == 2
    q = place(s, 100.0, Velocity(1e8), data_start=2)
    assert list(q.live_from) == [2, 2, 2] and q.time_zero == 0.0
    assert place(s, 100.0, Velocity(1e8)).data_start == 0


def test_no_hit_before_time_zero():
    s = _section(np.arange(30, dtype=float).reshape(3, 10), step=1e-9)
    p = place(s, 100.0, Velocity(1e8), time_zero=4e-9)            # 0.05 m per sample
    assert p.hit(2.0, 100.0)["sample"] == 4
    assert p.hit(2.0, 100.0 - 0.1)["sample"] == 6
    assert p.hit(2.0, 100.0 + 0.01) is None


def test_the_ground_is_smoothed_with_a_centred_window_shrinking_at_the_ends():
    from groundwork_geophysics.core.trace_section import smoothed_ground
    x = np.arange(0.0, 4.001, 0.02)
    teeth = 500.0 + 0.5 * np.abs(((x + 0.5) % 1.0) - 0.5) * 2      # a 1 m saw tooth
    z = smoothed_ground(x, teeth, 2.0)
    middle = (x >= 1.0) & (x <= 3.0)
    assert np.ptp(teeth[middle]) == pytest.approx(0.5)
    assert np.ptp(z[middle]) < 0.02 and z[middle].mean() == pytest.approx(500.25, abs=0.01)
    assert z[0] == pytest.approx(teeth[0]) and z[-1] == pytest.approx(teeth[-1])  # no window
    assert z[5] == pytest.approx(teeth[:11].mean())                 # 0.1 m each side
    assert np.array_equal(smoothed_ground(x, teeth, 0.0), teeth)
    assert np.array_equal(smoothed_ground(x[::-1], teeth[::-1], 2.0), z[::-1])
    flat = smoothed_ground(x, np.full(x.size, 7.0), 2.0)
    assert np.allclose(flat, 7.0)


def test_a_window_in_metres_is_an_odd_number_of_traces():
    from groundwork_geophysics.core.trace_section import trace_spacing, window_traces
    assert window_traces(10.0, 0.02) == 501 and window_traces(10.0, 0.1) == 101
    assert window_traces(1.0, 1.0) == 3                             # at least three
    a = np.zeros((4, 3), np.float32)
    assert trace_spacing(TraceSection(a, np.array([0.0, 0.02, 0.04, 0.06]), 0.0, 1.0,
                                      "time")) == pytest.approx(0.02)
    assert trace_spacing(TraceSection(a, np.array([3.0, 2.0, 1.0, 0.0]), 0.0, 1.0,
                                      "time")) == pytest.approx(1.0)
    assert trace_spacing(TraceSection(a, np.zeros(4), 0.0, 1.0, "time")) is None
