"""Shared fixtures and small factories for building test objects."""

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from busbidder.models import Company, Destination, DepartureWindow, FareConditions, Offer, TravelRequest

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

COMPANY = Company("SOL", "SolRuta", "Low-cost daytime services")
DESTINATION = Destination("MAL", "Malaga", 530, True)

DEFAULT_WEIGHTS = {"price": 0.4, "duration": 0.25, "departure_time": 0.15, "flexibility": 0.2}


def make_offer(offer_id="SOL-MAL-20260712-01", departure="2026-07-12 09:00", minutes=420, price=40.0,
               transfers=0, luggage_kg=20, changeable=True, refundable=False, change_fee=0.0,
               seats=10, rating=4.0, co2_kg=15.0, company=COMPANY, destination=DESTINATION):
    start = datetime.strptime(departure, "%Y-%m-%d %H:%M")
    return Offer(offer_id, company, destination, start, start + timedelta(minutes=minutes), price,
                 transfers, luggage_kg, FareConditions(changeable, refundable, change_fee), seats, rating, co2_kg)


def make_request(weights=None, preferred="morning", **constraints):
    return TravelRequest(
        name="test", label="Test traveller", destination="MAL",
        date_from=date(2026, 7, 12), date_to=date(2026, 7, 14),
        weights=weights or dict(DEFAULT_WEIGHTS),
        preferred_departure=DepartureWindow.parse(preferred),
        **constraints,
    )


@pytest.fixture
def data_dir():
    return DATA_DIR
