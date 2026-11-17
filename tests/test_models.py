"""Descriptor, model and departure-window tests (normal, invalid and boundary cases)."""

import pytest

from busbidder.exceptions import (ConfigurationError, FieldTypeError, FieldValueError,
                                  SeatsUnavailableError)
from busbidder.models import DepartureWindow, FareConditions, TravelRequest

from conftest import make_offer, make_request


# ------------------------------------------------------------- descriptors
@pytest.mark.parametrize("rating", [1.0, 5.0, 3])
def test_rating_boundaries_are_accepted(rating):
    assert make_offer(rating=rating).rating == rating


@pytest.mark.parametrize("rating", [0.9, 5.1, 7.5])
def test_rating_outside_scale_is_rejected(rating):
    with pytest.raises(FieldValueError) as info:
        make_offer(rating=rating)
    assert info.value.field == "rating"


def test_negative_price_is_rejected():
    with pytest.raises(FieldValueError):
        make_offer(price=-1)


def test_zero_seats_is_valid_but_negative_is_not():
    assert make_offer(seats=0).is_sold_out
    with pytest.raises(FieldValueError):
        make_offer(seats=-1)


@pytest.mark.parametrize("value", ["40", True, None])
def test_wrong_type_for_price_is_rejected(value):
    with pytest.raises((FieldTypeError, FieldValueError)):
        make_offer(price=value)


def test_transfers_must_be_int():
    with pytest.raises(FieldTypeError):
        make_offer(transfers=1.5)


def test_validation_also_applies_after_creation():
    offer = make_offer()
    with pytest.raises(FieldValueError):
        offer.price = -5
    assert offer.price == 40.0  # the old value is kept


def test_optional_co2_accepts_none():
    assert make_offer(co2_kg=None).co2_kg is None


# ------------------------------------------------------------------- offers
def test_arrival_before_departure_is_rejected():
    with pytest.raises(FieldValueError):
        make_offer(minutes=-30)


def test_duration_and_overnight_offer():
    offer = make_offer(departure="2026-07-12 23:30", minutes=500)
    assert offer.duration_min == 500
    assert offer.travel_date.isoformat() == "2026-07-12"


def test_reserve_and_release_seats():
    offer = make_offer(seats=2)
    offer.reserve(2)
    assert offer.available_seats == 0
    with pytest.raises(SeatsUnavailableError):
        offer.reserve(1)
    offer.release(1)
    assert offer.available_seats == 1


# ------------------------------------------------------------ fare conditions
def test_change_fee_on_non_changeable_fare_is_inconsistent():
    with pytest.raises(FieldValueError):
        FareConditions(changeable=False, refundable=False, change_fee=10)


@pytest.mark.parametrize("fare, code", [
    (FareConditions(False, False), "-"),
    (FareConditions(True, False, 0), "C"),
    (FareConditions(True, False, 5), "C*"),
    (FareConditions(True, True, 0), "R+C"),
])
def test_fare_short_codes(fare, code):
    assert fare.short_code() == code


# ---------------------------------------------------------- departure window
def test_named_window_contains_and_distance():
    morning = DepartureWindow.parse("morning")  # 06:00-12:00
    assert morning.minutes_outside(9 * 60) == 0
    assert morning.minutes_outside(6 * 60) == 0          # start is inclusive
    assert morning.minutes_outside(12 * 60) == 0          # boundary: zero distance to the end edge
    assert morning.minutes_outside(12 * 60 + 1) == 1
    assert morning.minutes_outside(14 * 60) == 120


def test_window_wrapping_past_midnight():
    night = DepartureWindow.parse("night")  # 21:00-05:00
    assert night.minutes_outside(23 * 60) == 0
    assert night.minutes_outside(2 * 60) == 0
    assert night.minutes_outside(19 * 60) == 120


def test_custom_window_and_no_preference():
    assert DepartureWindow.parse("07:00-10:00").minutes_outside(11 * 60) == 60
    assert DepartureWindow.parse("any") is None


@pytest.mark.parametrize("text", ["breakfast", "25:00-26:00", "08:00-08:00", "7-10"])
def test_invalid_window_is_rejected(text):
    with pytest.raises(ConfigurationError):
        DepartureWindow.parse(text)


# ------------------------------------------------------------ travel request
def test_request_rejects_reversed_dates():
    with pytest.raises(ConfigurationError):
        TravelRequest.from_profile("x", {"weights": {}}, {"destination": "MAL",
                                                          "date_from": "2026-07-14", "date_to": "2026-07-12"})


def test_request_rejects_unknown_constraint_names():
    profile = {"weights": {}, "constraints": {"max_budjet": 50}}
    with pytest.raises(ConfigurationError, match="max_budjet"):
        TravelRequest.from_profile("x", profile, {"destination": "MAL",
                                                  "date_from": "2026-07-12", "date_to": "2026-07-14"})


def test_request_lists_hard_constraints():
    text = make_request(max_budget=50, require_changeable=True).hard_constraints_text()
    assert "price at most EUR 50.00" in text
    assert "ticket must be changeable" in text
