"""Simulated bookings. bookings.json is the ledger, the offer files are never changed."""

import json
import logging
import random
import string
from datetime import datetime
from pathlib import Path

from .exceptions import (BookingError, DataFileError, SeatsUnavailableError,
                         UnknownBookingError, UnknownOfferError)
from .logging_utils import log_call
from .models import Booking
from .validation import is_valid_booking_reference

logger = logging.getLogger(__name__)

REFERENCE_ALPHABET = string.ascii_uppercase + string.digits
MAX_REFERENCE_ATTEMPTS = 100


class BookingManager:
    def __init__(self, path, marketplace, rng=None, clock=datetime.now):
        self.path = Path(path)
        self.marketplace = marketplace
        self.rng = rng or random.SystemRandom()
        self.clock = clock  # injectable so tests get predictable timestamps
        self.bookings = {}
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        try:
            with open(self.path, encoding="utf-8") as file:
                records = json.load(file)
        except json.JSONDecodeError as error:
            raise DataFileError(self.path, f"invalid JSON at line {error.lineno}") from None
        except PermissionError:
            raise DataFileError(self.path, "permission denied") from None
        for record in records:
            booking = Booking.from_dict(record)
            self.bookings[booking.reference] = booking
            if booking.is_active:
                self._apply_existing(booking)
        logger.info("loaded %d booking(s) from %s", len(self.bookings), self.path)

    def _apply_existing(self, booking):
        offer = self.marketplace.get_offer(booking.offer_id)
        if offer is None:
            logger.warning("booking %s refers to unknown offer %s", booking.reference, booking.offer_id)
            return
        try:
            offer.reserve(booking.seats)
        except SeatsUnavailableError as error:
            logger.warning("booking %s could not be applied: %s", booking.reference, error)

    def _save(self):
        """Write to a temp file first, then replace the real one."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with open(temporary, "w", encoding="utf-8") as file:
            json.dump([booking.to_dict() for booking in self.bookings.values()], file, indent=2)
        temporary.replace(self.path)

    def new_reference(self, year):
        for _ in range(MAX_REFERENCE_ATTEMPTS):
            code = "".join(self.rng.choice(REFERENCE_ALPHABET) for _ in range(6))
            reference = f"BB-{year}-{code}"
            if reference not in self.bookings and is_valid_booking_reference(reference):
                return reference
        raise BookingError("could not generate a unique booking reference")

    @log_call(logging.INFO)
    def book(self, offer_id, traveller, seats=1):
        offer = self.marketplace.get_offer(offer_id)
        if offer is None:
            raise UnknownOfferError(f"no offer with id {offer_id}")
        if not traveller.strip():
            raise BookingError("traveller name is required")
        offer.reserve(seats)  # raises SeatsUnavailableError when seats are gone
        booking = Booking(
            reference=self.new_reference(offer.departure.year),
            offer_id=offer.offer_id,
            traveller=traveller.strip(),
            seats=seats,
            total_price=round(offer.price * seats, 2),
            fare={"changeable": offer.fare.changeable, "refundable": offer.fare.refundable,
                  "change_fee": offer.fare.change_fee},
            departure=f"{offer.departure:%Y-%m-%d %H:%M}",
            created_at=self.clock().isoformat(timespec="seconds"),
        )
        self.bookings[booking.reference] = booking
        try:
            self._save()
        except OSError as error:
            # undo the reservation if saving failed
            offer.release(seats)
            del self.bookings[booking.reference]
            raise BookingError(f"booking could not be saved: {error}") from error
        logger.info("booked %s: %s x%d for %s", booking.reference, offer_id, seats, booking.traveller)
        return booking

    @log_call(logging.INFO)
    def cancel(self, reference):
        """Cancel a booking. Refundable fares get a full simulated refund."""
        booking = self.bookings.get(reference.strip().upper())
        if booking is None:
            raise UnknownBookingError(f"no booking with reference {reference}")
        if not booking.is_active:
            raise BookingError(f"booking {booking.reference} is already cancelled")
        booking.status = "CANCELLED"
        if booking.fare["refundable"]:
            booking.refund_amount = booking.total_price
            booking.payment_status = "SIMULATED_REFUNDED"
        else:
            booking.payment_status = "NO_REFUND"
        offer = self.marketplace.get_offer(booking.offer_id)
        if offer is not None:
            offer.release(booking.seats)
        self._save()
        return booking

    def active_bookings(self):
        return [booking for booking in self.bookings.values() if booking.is_active]
