import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.narration import mentioned_items, resolve_item, resolve_location, spoken_location  # noqa: E402

LOCATIONS = ["A1-B2", "A1-B3", "A2-B2"]
SHELVES = ["A1-B2", "A1-B4", "A3-B1", "A4-B1"]
ITEMS = ["IFB Microwave", "TV stand", "TV unit"]


def test_spoken_location_from_real_transcript():
    t = "these are the boxes of IFB Microwave oven on aisle one bay area two"
    assert spoken_location(t) == {0: 1, 1: 2}
    assert resolve_location(t, LOCATIONS) == "A1-B2"


def test_location_digits_and_codes():
    assert resolve_location("aisle A2 shelf B2, 24-pack cartons", LOCATIONS) == "A2-B2"
    assert resolve_location("aisle 1, bay 3", LOCATIONS) == "A1-B3"


def test_unknown_or_ambiguous_location_is_none():
    assert resolve_location("aisle nine bay nine", LOCATIONS) is None
    assert resolve_location("no location said", LOCATIONS) is None


def test_a_letter_spaced_from_its_number_still_counts():
    # Real transcripts from the 9.5-minute run: after the first few turns the model wrote "A 1 B 4".
    assert resolve_location("this is shelf A 1 B 4 with three monitors and two keyboards", SHELVES) == "A1-B4"
    assert resolve_location("this is shelf A 4 B 1 with four monitors seven keyboards two mouse", SHELVES) == "A4-B1"
    assert resolve_location("thisthis is shelf A 3 B 1 with three monitors", SHELVES) == "A3-B1"
    assert resolve_location("this is shelf A 1 B 2 1 B 2 with four monitors", SHELVES) == "A1-B2"
    # the article "a" is only a tag inside a location phrase
    assert resolve_location("shelf A1 B2 with a four seater", SHELVES) == "A1-B2"
    assert spoken_location("we have a one metre shelf") == {}


def test_item_counts_said_after_the_location_are_not_location_numbers():
    # Real transcripts from the held-out set: "four" in "four monitors" once resolved a clip to A1-B4.
    assert resolve_location("this is is shelf A1 B2 with four monitors.", SHELVES) == "A1-B2"
    assert resolve_location("this is shelf A3 B1 with three monitors.", SHELVES) == "A3-B1"
    assert spoken_location("this is shelf B1 with four monitors seven keyboards two mouses") == {1: 1}


def test_shelf_said_without_an_aisle_is_ambiguous_not_guessed():
    t = "this is shelf B1 with four monitors seven keyboards two mouses"
    assert resolve_location(t, SHELVES) is None  # A3-B1 and A4-B1 both fit
    assert resolve_location(t, ["A1-B2", "A4-B1"]) == "A4-B1"  # only one B1 on the plan


def test_single_item_resolved_with_extra_words():
    assert resolve_item("these are the boxes of IFB Microwave oven", ITEMS) == "IFB Microwave"


def test_tv_stand_does_not_match_tv_unit():
    assert resolve_item("one TV stand on the top right", ITEMS) == "TV stand"


def test_mixed_clip_has_no_single_item():
    t = "five microwave boxes IFB Microwave, one TV stand and one TV unit"
    assert set(mentioned_items(t, ITEMS)) == set(ITEMS)
    assert resolve_item(t, ITEMS) is None
