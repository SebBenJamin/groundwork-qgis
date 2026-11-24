"""Which profile a data file belongs to, guessed from its name (Add Data with several files)."""
import pytest

from groundwork_geophysics.core.file_profiles import guess_profile

JWD = [("p1a", "Line 1A"), ("p1b", "Line 1B"), ("p2", "Line 2"), ("p2b", "Line 2B"),
       ("p3", "Line 3"), ("p8", "Line 8"), ("p10", "Line 10")]


@pytest.mark.parametrize("stem, expected", [
    ("JWD_L8_DD_ERTmodel", "p8"),                    # initial + number
    ("JWD_L2B_DD_ERTmodel", "p2b"),                  # a letter after the number
    ("JWD_L2_DD_ERTmodel", "p2"),                    # not Line 2B
    ("jwd_line_10_model", "p10"),                    # the word + number
    ("Line3", "p3"),
    ("JWD_L1A_DD_ERTmodel", "p1a"),
    ("JWD_2018_L3_DD", "p3"),                        # a year does not count as a number
    ("JWD_L5_DD_ERTmodel", None),                    # no Line 5
    ("JWD_2018_SP_Data", None),
])
def test_line_numbers_in_file_names(stem, expected):
    assert guess_profile(stem, JWD) == expected


def test_whole_profile_name_in_the_file_name():
    profiles = [("e1", "ERT01"), ("e2", "ERT02"), ("t3", "Transect 3")]
    assert guess_profile("ERT02_model_robust", profiles) == "e2"
    assert guess_profile("ert2_model", profiles) == "e2"           # leading zero dropped
    assert guess_profile("T3_bert_result", profiles) == "t3"
    assert guess_profile("transect_3", profiles) == "t3"


def test_two_profiles_matching_equally_give_no_guess():
    profiles = [("a", "Line 3"), ("b", "Lane 3")]                     # both "L3"
    assert guess_profile("JWD_L3_DD", profiles) is None


def test_profile_names_without_a_number_match_whole():
    profiles = [("n", "North"), ("s", "South dyke")]
    assert guess_profile("south_dyke_model", profiles) == "s"
    assert guess_profile("north", profiles) == "n"
    assert guess_profile("northern_part", profiles) is None
