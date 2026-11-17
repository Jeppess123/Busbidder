"""Booking tests and end-to-end command-line tests."""

import json
import random
from datetime import datetime

import pytest

from busbidder.booking import BookingManager
from busbidder.cli import main
from busbidder.exceptions import (BookingError, DataFileError, SeatsUnavailableError,
                                  UnknownBookingError, UnknownOfferError)
from busbidder.models import Marketplace
from busbidder.validation import is_valid_booking_reference

from conftest import make_offer


def fixed_clock():
    return datetime(2026, 6, 1, 12, 0, 0)


def new_manager(tmp_path, seats=3, refundable=False):
    offer = make_offer(seats=seats, refundable=refundable)
    marketplace = Marketplace(offers={offer.offer_id: offer})
    return BookingManager(tmp_path / "bookings.json", marketplace, rng=random.Random(1), clock=fixed_clock), offer


def test_booking_reduces_seats_and_saves(tmp_path):
    manager, offer = new_manager(tmp_path)
    booking = manager.book(offer.offer_id, "Ana", seats=2)
    assert offer.available_seats == 1
    assert is_valid_booking_reference(booking.reference)
    saved = json.loads((tmp_path / "bookings.json").read_text(encoding="utf-8"))
    assert saved[0]["reference"] == booking.reference
    assert saved[0]["fare"] == {"changeable": True, "refundable": False, "change_fee": 0.0}


def test_seat_counts_are_consistent_after_reload(tmp_path):
    manager, offer = new_manager(tmp_path, seats=3)
    manager.book(offer.offer_id, "Ana")
    fresh_offer = make_offer(seats=3)  # same official data, reloaded from file
    BookingManager(tmp_path / "bookings.json", Marketplace(offers={fresh_offer.offer_id: fresh_offer}))
    assert fresh_offer.available_seats == 2


def test_last_seat_then_sold_out(tmp_path):
    manager, offer = new_manager(tmp_path, seats=1)
    manager.book(offer.offer_id, "Ana")
    with pytest.raises(SeatsUnavailableError):
        manager.book(offer.offer_id, "Ben")
    assert len(manager.bookings) == 1


def test_references_are_unique(tmp_path):
    manager, offer = new_manager(tmp_path, seats=50)
    references = {manager.book(offer.offer_id, f"T{i}").reference for i in range(40)}
    assert len(references) == 40


def test_unknown_offer_and_empty_name(tmp_path):
    manager, offer = new_manager(tmp_path)
    with pytest.raises(UnknownOfferError):
        manager.book("SOL-MAL-20990101-01", "Ana")
    with pytest.raises(BookingError):
        manager.book(offer.offer_id, "   ")


def test_cancel_refundable_releases_seat_and_refunds(tmp_path):
    manager, offer = new_manager(tmp_path, seats=2, refundable=True)
    booking = manager.book(offer.offer_id, "Ana")
    cancelled = manager.cancel(booking.reference.lower())
    assert offer.available_seats == 2
    assert cancelled.refund_amount == booking.total_price
    with pytest.raises(BookingError):
        manager.cancel(booking.reference)  # already cancelled


def test_cancel_non_refundable_gives_no_refund(tmp_path):
    manager, offer = new_manager(tmp_path)
    booking = manager.book(offer.offer_id, "Ana")
    assert manager.cancel(booking.reference).payment_status == "NO_REFUND"
    with pytest.raises(UnknownBookingError):
        manager.cancel("BB-2026-ZZZZZZ")


def test_corrupt_ledger_is_reported(tmp_path):
    (tmp_path / "bookings.json").write_text("[{", encoding="utf-8")
    with pytest.raises(DataFileError):
        BookingManager(tmp_path / "bookings.json", Marketplace())


# ---------------------------------------------------------------- CLI tests
def run_cli(data_dir, tmp_path, *args):
    return main(["--data-dir", str(data_dir), "--output-dir", str(tmp_path), *args])


def test_cli_validate_writes_reports(data_dir, tmp_path):
    assert run_cli(data_dir, tmp_path, "validate") == 0
    assert (tmp_path / "rejected_records.txt").exists()
    assert (tmp_path / "busbidder.log").exists()


def test_cli_compare_gives_different_recommendations(data_dir, tmp_path):
    assert run_cli(data_dir, tmp_path, "compare") == 0
    rows = (tmp_path / "profile_comparison.csv").read_text(encoding="utf-8").splitlines()[1:]
    top_offers = {row.split(",")[3] for row in rows if row.split(",")[2] == "1"}
    assert len(top_offers) >= 3


def test_cli_book_rejects_offer_that_violates_constraints(data_dir, tmp_path, capsys):
    code = run_cli(data_dir, tmp_path, "book", "--profile", "spec_example", "--offer", "CAM-MAL-20260714-01")
    assert code == 1
    assert "budget" in capsys.readouterr().err


def test_cli_book_and_cancel(data_dir, tmp_path):
    assert run_cli(data_dir, tmp_path, "book", "--profile", "business", "--offer", "CAM-MAL-20260714-01") == 0
    reference = json.loads((tmp_path / "bookings.json").read_text(encoding="utf-8"))[0]["reference"]
    assert run_cli(data_dir, tmp_path, "cancel", reference) == 0


def test_cli_unknown_profile_and_missing_data(data_dir, tmp_path):
    assert run_cli(data_dir, tmp_path, "rank", "--profile", "nobody") == 1
    assert main(["--data-dir", str(tmp_path / "nothing"), "--output-dir", str(tmp_path), "validate"]) == 1


def test_cli_interactive_session(data_dir, tmp_path, monkeypatch, capsys):
    answers = iter(["4", "5", "1", "Test Person", "y", "6", "0"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert run_cli(data_dir, tmp_path, "interactive") == 0
    output = capsys.readouterr().out
    assert "BOOKING CONFIRMATION" in output
    assert "Test Person" in output


def test_cli_q_cancels_weight_prompt(data_dir, tmp_path, monkeypatch, capsys):
    answers = iter(["3", "200", "1", "q", "0"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert run_cli(data_dir, tmp_path, "interactive") == 0
    assert "Cancelled, nothing was changed." in capsys.readouterr().out