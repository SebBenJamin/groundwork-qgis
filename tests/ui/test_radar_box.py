"""The Radargram group of Add Data (and, with its vertical rows only, of Dataset Info): the
radar velocity as velocity or dielectric constant, time zero, where time zero lies and how the
traces are placed. Driven programmatically (offscreen)."""
import pytest

from groundwork_geophysics.readers.radar_info import RadarInfo

NS = 1e-9


def info(**kw) -> RadarInfo:
    values = dict(n_traces=19310, n_samples=1024, step=565 * NS / 1024, window=565 * NS,
                  first=0.0, time_zero=None, velocity=None, dielectric=None, antenna="270MHz",
                  frequency_mhz=270.0, trace_step=0.02, start=0.0, length=386.18)
    values.update(kw)
    return RadarInfo(**values)


@pytest.fixture
def box(qgis_app):
    from groundwork_geophysics.ui.radar_box import RadarBox
    made = RadarBox()
    yield made
    made.deleteLater()


def _type(edit, text):
    edit.setText(text)
    edit.editingFinished.emit()


def test_the_facts_line_says_what_the_file_holds(box):
    from groundwork_geophysics.core.numbers import fmt_count, fmt_trim
    box.set_info(info())
    assert box.title() == "Radargram"
    assert box.facts_label.text() == (
        f"{fmt_count(19310)} traces × {fmt_count(1024)} samples · 565 ns · 270MHz · "
        f"{fmt_trim(386.18, 2)} m from the distance wheel")


def test_the_velocity_fields_fill_each_other_with_a_decimal_comma(box):
    from groundwork_geophysics.core.numbers import fmt_trim
    box.set_info(info())
    _type(box.velocity_edit, "0,1")
    assert box.dielectric_edit.text() == fmt_trim(8.98755, 2)
    assert box.options()["velocity"] == pytest.approx(1.0e8)
    _type(box.dielectric_edit, "4")
    assert box.velocity_edit.text() == fmt_trim(0.299792458 / 2, 4)
    assert box.options()["velocity"] == pytest.approx(0.299792458e9 / 2)
    _type(box.dielectric_edit, "6,25")
    assert box.options()["velocity"] == pytest.approx(0.299792458e9 / 2.5)


def test_a_dielectric_from_the_header_is_shown_with_its_note(box):
    box.set_info(info(dielectric=18.0, velocity=0.299792458e9 / 18 ** 0.5))
    assert box.dielectric_edit.text() == "18"
    assert box.velocity_note.text() == ("from the file's header (an instrument setting; "
                                        "check it)")
    assert box.velocity_note.isVisibleTo(box)
    assert box.options()["velocity"] == pytest.approx(0.299792458e9 / 18 ** 0.5)
    _type(box.velocity_edit, "0,1")
    assert box.velocity_note.text() == "" and not box.velocity_note.isVisibleTo(box)


def test_without_a_stated_dielectric_the_velocity_is_empty_and_needed(box):
    box.set_info(info())
    assert box.velocity_edit.text() == "" and box.dielectric_edit.text() == ""
    assert "Enter the velocity or the dielectric constant." in box.problems()
    assert "velocity" not in box.options()


@pytest.mark.parametrize("field, text, problem", [
    ("dielectric_edit", "0,5", "The dielectric constant must be 1 or greater."),
    ("velocity_edit", "0,4", "The velocity must be greater than 0 and not above the speed of "
                             "light (0.2998 m/ns)."),
    ("velocity_edit", "0", "The velocity must be greater than 0 and not above the speed of "
                           "light (0.2998 m/ns).")])
def test_an_impossible_velocity_is_a_problem(box, field, text, problem):
    box.set_info(info())
    _type(getattr(box, field), text)
    assert problem in box.problems() and "velocity" not in box.options()


def test_time_zero_comes_from_the_file_or_the_first_arrival(box):
    box.set_info(info(time_zero=9.77 * NS))
    assert box.time_zero_edit.text() == "9.77"
    assert box.time_zero_note.text() == "from the file"
    box.set_estimate(30 * NS)                           # the file's own wins
    assert box.options()["time_zero"] == pytest.approx(9.77 * NS)
    box.set_info(info(), "other.dzt")
    assert box.time_zero_edit.text() == ""
    box.set_estimate(55.18 * NS)
    assert box.time_zero_edit.text() == "55.18"
    assert box.time_zero_note.text() == ("estimated from the first arrival (first break "
                                         "of the direct wave)")
    assert box.options()["time_zero"] == pytest.approx(55.18 * NS)
    _type(box.time_zero_edit, "50")
    assert box.time_zero_note.text() == "" and box.options()["time_zero"] == pytest.approx(50 * NS)
    box.set_estimate(40 * NS)                           # never over the user's number
    assert box.options()["time_zero"] == pytest.approx(50 * NS)


def test_time_zero_beyond_the_record_is_a_problem(box):
    box.set_info(info())
    _type(box.velocity_edit, "0,1")
    _type(box.time_zero_edit, "600")
    assert "Time zero lies beyond the end of the record." in box.problems()
    _type(box.time_zero_edit, "")
    assert "Enter time zero in ns." in box.problems()


def test_a_fixed_height_needs_a_height(box):
    box.set_info(info())
    assert [box.zero_combo.itemText(i) for i in range(box.zero_combo.count())] == [
        "On the ground line", "At a fixed height"]
    box.set_zero("datum")
    assert "Enter the height of time zero." in box.problems()
    _type(box.datum_edit, "372,5")
    o = box.options()
    assert (o["zero"], o["datum"]) == ("datum", 372.5)


def test_a_file_without_a_distance_wheel_starts_with_a_trace_spacing(box):
    box.set_info(info(trace_step=None, length=None))
    assert box.by_spacing.isChecked() and not box.by_file.isEnabled()
    assert box.position_note.text() == "This file was recorded without a distance wheel."
    assert box.position_note.isVisibleTo(box)
    assert "Enter the trace spacing in metres." in box.problems()
    _type(box.spacing_edit, "0,05")
    assert box.options()["position"] == "spacing" and box.options()["spacing"] == 0.05
    box.set_info(info(), "wheel.dzt")
    assert box.by_file.isEnabled() and box.position_note.text() == ""


def test_the_options_round_trip(box, qgis_app):
    from groundwork_geophysics.ui.radar_box import RadarBox
    box.set_info(info())
    stored = {"position": "spacing", "spacing": 0.05, "velocity": 1.0e8,
              "time_zero": 55.18 * NS, "zero": "datum", "datum": 372.5}
    box.set_options(stored)
    o = box.options()
    assert set(o) == set(stored)
    for key, value in stored.items():
        assert o[key] == (pytest.approx(value) if isinstance(value, float) else value), key
    again = RadarBox()
    again.set_info(info())
    again.set_options(box.options())
    assert again.options() == box.options()
    again.deleteLater()


def test_the_line_length_offers_to_fit_the_file(box):
    box.set_info(info(length=386.2))
    assert not box.fit_check.isVisibleTo(box)
    box.set_line_length(386.2, 381.0)               # a new line: from 0 to its end
    assert (box.from_edit.text(), box.to_edit.text()) == ("0", "381")
    # the difference as a share of the file's length: the stretch the tick gives it
    assert box.length_label.text() == ("The file is 386.2 m long, the stretch from From to To "
                                       "381 m (1.3 % shorter).")
    assert box.fit_check.isVisibleTo(box) and not box.fit_check.isChecked()
    assert box.fit_check.text() == "Fit the file between these two points"
    assert "fit_length" not in box.options()
    box.fit_check.setChecked(True)
    assert box.options()["fit_length"] is True
    box.set_line_length(100.0, 104.567)
    assert box.length_label.text() == ("The file is 100 m long, the stretch from From to To "
                                       "104.57 m (4.6 % longer).")
    box.set_line_length(None, None)
    assert not box.fit_check.isVisibleTo(box) and "fit_length" not in box.options()
    assert not box.from_edit.isVisibleTo(box)


def test_from_and_to_start_where_the_placement_puts_the_file(box):
    box.set_info(info(length=124.0))
    box.set_span(124.0, 25.5, 149.5)
    assert box.from_edit.isVisibleTo(box) and box.to_edit.isVisibleTo(box)
    assert (box.from_edit.text(), box.to_edit.text()) == ("25.5", "149.5")
    assert box.length_label.text() == ("The file and the stretch from From to To are both "
                                       "124 m long.")
    assert box.fit_check.isVisibleTo(box)
    assert "span" not in box.options()              # untouched: the placement decides
    _type(box.to_edit, "136,8")
    assert box.options()["span"] == pytest.approx((25.5, 136.8))
    assert box.length_label.text() == ("The file is 124 m long, the stretch from From to To "
                                       "111.3 m (10.2 % shorter).")
    box.set_span(124.0, 30.0, 154.0)                # the placement moved: typed numbers stay
    assert box.options()["span"] == pytest.approx((25.5, 136.8))
    _type(box.from_edit, "abc")
    assert "Enter From and To in metres along the profile." in box.problems()


def test_from_and_to_are_forgotten_for_another_file(box):
    box.set_info(info(length=124.0), "a.dzt")
    box.set_span(124.0, 0.0, 124.0)
    _type(box.to_edit, "130")
    box.set_info(info(length=124.0), "b.dzt")
    box.set_span(124.0, 0.0, 124.0)
    assert box.to_edit.text() == "124" and "span" not in box.options()


def test_vertical_only_hides_the_placement(qgis_app):
    from groundwork_geophysics.ui.radar_box import RadarBox
    box = RadarBox(vertical_only=True)
    box.set_info(info())
    box.set_options({"velocity": 1.0e8, "time_zero": 50 * NS})
    o = box.options()
    assert "position" not in o and o["zero"] == "ground"
    for w in (box.by_file, box.by_spacing, box.by_table, box.spacing_edit, box.fit_check):
        assert not w.isVisibleTo(box)
    assert box.problems() == []
    box.deleteLater()


def test_the_box_tells_its_edits(box):
    box.set_info(info())
    seen = []
    box.changed.connect(lambda: seen.append(1))
    box.set_options({"velocity": 1.0e8})
    assert seen == []                                   # silent
    _type(box.velocity_edit, "0,12")
    assert seen


def test_the_ground_under_a_new_radargram_is_smoothed_over_2_m(box):
    box.set_info(info())
    assert box.smoothing_edit.isVisibleTo(box) and box.smoothing_edit.text() == "2"
    assert box.options()["ground_smoothing"] == 2.0
    label = box._rows["smoothing"][0]
    assert label.text() == "Smooth the ground over (m)"
    _type(box.smoothing_edit, "0")
    assert box.options()["ground_smoothing"] == 0.0
    box.set_options({"ground_smoothing": 3.5})
    assert box.smoothing_edit.text() == "3.5"
    _type(box.smoothing_edit, "-1")
    assert "The smoothing length must be 0 m or more." in box.problems()
    box.set_zero("datum")
    assert not box.smoothing_edit.isVisibleTo(box) and "ground_smoothing" not in box.options()


def test_the_time_zero_tooltip_says_what_is_not_drawn(box):
    assert box.time_zero_edit.toolTip() == ("Samples before time zero are above the ground and "
                                            "are not drawn.")
