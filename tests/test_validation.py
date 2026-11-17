"""Regular-expression and field-parsing tests, including near misses."""

import pytest

from busbidder.exceptions import InvalidIdentifierError, InvalidRecordError
from busbidder.validation import (is_valid_booking_reference, parse_bool, parse_offer_id,
                                  parse_optional_float, parse_timestamp)


def test_valid_offer_id_returns_named_parts():
    parts = parse_offer_id("SOL-MAL-20260712-01")
    assert parts == {"company": "SOL", "destination": "MAL", "date": "20260712", "sequence": "01"}


@pytest.mark.parametrize("value", [
    "SOL_MAL_2026",            # wrong separators
    "SOL-MAL-20260712-1",      # sequence too short
    "SO-MAL-20260712-01",      # company too short
    "sol-mal-20260712-01",     # lower case (normalised earlier by the loader)
    "SOL-MAL-20260712-01X",    # trailing character, fullmatch needed
    "",
])
def test_invalid_offer_ids(value):
    with pytest.raises(InvalidIdentifierError):
        parse_offer_id(value)


@pytest.mark.parametrize("value, valid", [
    ("BB-2026-AB12CD", True),
    ("BB-2026-ab12cd", False),
    ("BB-26-AB12CD", False),
    ("BB-2026-AB12C", False),
    ("XBB-2026-AB12CD", False),
])
def test_booking_reference_format(value, valid):
    assert is_valid_booking_reference(value) is valid


def test_timestamp_shape_and_meaning_are_both_checked():
    assert parse_timestamp("2026-07-12 08:30", "departure").hour == 8
    with pytest.raises(InvalidRecordError, match="format"):
        parse_timestamp("12/07/2026 08:30", "departure")
    with pytest.raises(InvalidRecordError, match="real calendar"):
        parse_timestamp("2026-02-30 08:30", "departure")  # right shape, impossible date


@pytest.mark.parametrize("text, expected", [("yes", True), ("NO", False), ("Y", True), ("false", False)])
def test_parse_bool_accepts_common_words(text, expected):
    assert parse_bool(text, "changeable") is expected


def test_parse_bool_rejects_ambiguous_value():
    with pytest.raises(InvalidRecordError):
        parse_bool("maybe", "changeable")


def test_optional_float_handles_missing_value():
    assert parse_optional_float("", "co2_kg") is None
    assert parse_optional_float("6.4", "co2_kg") == 6.4
