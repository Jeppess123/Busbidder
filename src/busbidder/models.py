"""The main classes: companies, destinations, offers, requests and bookings."""

from dataclasses import asdict, dataclass, field
from datetime import date, datetime

from .descriptors import RangeValidated
from .exceptions import ConfigurationError, FieldValueError, SeatsUnavailableError
from .validation import TIME_WINDOW, parse_clock_time


@dataclass(frozen=True)
class Company:
    company_id: str
    name: str
    profile: str

    def __str__(self):
        return self.name


@dataclass(frozen=True)
class Destination:
    destination_id: str
    name: str
    distance_km: int
    coastal: bool

    def __str__(self):
        return self.name


@dataclass(frozen=True)
class FareConditions:
    """Ticket flexibility attached to an offer and copied into a booking."""

    changeable: bool
    refundable: bool
    change_fee: float = 0.0

    def __post_init__(self):
        if self.change_fee < 0:
            raise FieldValueError("change_fee_eur", "change fee cannot be negative")
        if not self.changeable and self.change_fee > 0:
            raise FieldValueError("change_fee_eur", "change fee given for a non-changeable fare")

    @property
    def free_changes(self):
        return self.changeable and self.change_fee == 0

    def short_code(self):
        """Compact label for tables: R refundable, C changeable, * change fee."""
        if not self.changeable:
            return "R" if self.refundable else "-"
        code = "C" if self.free_changes else "C*"
        return ("R+" + code) if self.refundable else code

    def describe(self):
        if not self.changeable and not self.refundable:
            return "not changeable or refundable"
        parts = []
        if self.changeable:
            parts.append("changeable" + (" free of charge" if self.free_changes else f" (fee EUR {self.change_fee:.0f})"))
        if self.refundable:
            parts.append("refundable")
        return " and ".join(parts)


class Offer:
    """One bus departure offered by one company."""

    price = RangeValidated(min_value=0, max_value=1000)
    transfers = RangeValidated(min_value=0, max_value=3, types=(int,))
    luggage_kg = RangeValidated(min_value=0, max_value=50)
    available_seats = RangeValidated(min_value=0, max_value=100, types=(int,))
    rating = RangeValidated(min_value=1.0, max_value=5.0)
    co2_kg = RangeValidated(min_value=0, allow_none=True)

    def __init__(self, offer_id, company, destination, departure, arrival, price,
                 transfers, luggage_kg, fare, available_seats, rating, co2_kg=None):
        if arrival <= departure:
            raise FieldValueError("arrival", f"arrival {arrival:%Y-%m-%d %H:%M} is not after departure")
        self.offer_id = offer_id
        self.company = company
        self.destination = destination
        self.departure = departure
        self.arrival = arrival
        self.price = price
        self.transfers = transfers
        self.luggage_kg = luggage_kg
        self.fare = fare
        self.available_seats = available_seats
        self.rating = rating
        self.co2_kg = co2_kg

    @property
    def duration_min(self):
        return int((self.arrival - self.departure).total_seconds() // 60)

    @property
    def travel_date(self):
        return self.departure.date()

    @property
    def departure_minutes(self):
        """Departure time as minutes after midnight."""
        return self.departure.hour * 60 + self.departure.minute

    @property
    def is_sold_out(self):
        return self.available_seats == 0

    def reserve(self, seats):
        if seats < 1:
            raise ValueError("at least one seat must be reserved")
        if seats > self.available_seats:
            raise SeatsUnavailableError(
                f"{self.offer_id} has {self.available_seats} seat(s) left, {seats} requested"
            )
        self.available_seats -= seats

    def release(self, seats):
        self.available_seats += seats

    def __str__(self):
        return (f"{self.offer_id} {self.company.name} to {self.destination.name}, "
                f"{self.departure:%d %b %H:%M}, EUR {self.price:.2f}")

    def __repr__(self):
        return f"Offer({self.offer_id!r})"


def format_duration(minutes):
    return f"{minutes // 60}h{minutes % 60:02d}"


class DepartureWindow:
    """A preferred departure period, e.g. 'morning' or '07:00-10:00'."""

    NAMED_PERIODS = {
        "early_morning": "05:00-08:00",
        "morning": "06:00-12:00",
        "afternoon": "12:00-18:00",
        "evening": "18:00-23:00",
        "night": "21:00-05:00",
    }
    DAY = 24 * 60

    def __init__(self, start, end, label):
        self.start = start
        self.end = end
        self.label = label

    @classmethod
    def parse(cls, text):
        """Return a DepartureWindow, or None when the traveller has no preference."""
        text = (text or "any").strip().lower()
        if text == "any":
            return None
        window_text = cls.NAMED_PERIODS.get(text, text)
        match = TIME_WINDOW.fullmatch(window_text)
        if match is None:
            options = ", ".join(["any", *cls.NAMED_PERIODS, "HH:MM-HH:MM"])
            raise ConfigurationError(f"unknown departure preference '{text}' (use {options})")
        try:
            start = parse_clock_time(match["start"], "start")
            end = parse_clock_time(match["end"], "end")
        except ValueError as error:
            raise ConfigurationError(str(error)) from None
        if start == end:
            raise ConfigurationError("departure window start and end cannot be equal")
        return cls(start, end, text)

    def contains(self, minute):
        if self.start < self.end:
            return self.start <= minute < self.end
        return minute >= self.start or minute < self.end  # wraps past midnight

    def minutes_outside(self, minute):
        """0 inside the window, otherwise distance to the nearest edge."""
        if self.contains(minute):
            return 0

        def circular(a, b):
            difference = abs(a - b) % self.DAY
            return min(difference, self.DAY - difference)

        return min(circular(minute, self.start), circular(minute, self.end))

    def __str__(self):
        start = f"{self.start // 60:02d}:{self.start % 60:02d}"
        end = f"{self.end // 60:02d}:{self.end % 60:02d}"
        return f"{self.label} ({start}-{end})" if self.label in self.NAMED_PERIODS else f"{start}-{end}"


@dataclass
class TravelRequest:
    """What one traveller wants: hard constraints plus soft preferences."""

    name: str
    label: str
    destination: str
    date_from: date
    date_to: date
    weights: dict
    preferred_departure: DepartureWindow = None
    seats: int = 1
    max_budget: float = None
    max_transfers: int = None
    require_changeable: bool = False
    require_refundable: bool = False
    min_luggage_kg: float = None
    max_duration_min: int = None

    CONSTRAINT_KEYS = ("max_budget", "max_transfers", "require_changeable", "require_refundable",
                       "min_luggage_kg", "max_duration_min", "seats")

    def __post_init__(self):
        if self.date_from > self.date_to:
            raise ConfigurationError(f"{self.name}: date_from is after date_to")
        if self.seats < 1:
            raise ConfigurationError(f"{self.name}: at least one seat is required")
        if self.max_budget is not None and self.max_budget <= 0:
            raise ConfigurationError(f"{self.name}: max_budget must be positive")
        if self.max_transfers is not None and self.max_transfers < 0:
            raise ConfigurationError(f"{self.name}: max_transfers cannot be negative")
        if self.max_duration_min is not None and self.max_duration_min <= 0:
            raise ConfigurationError(f"{self.name}: max_duration_min must be positive")

    @classmethod
    def from_profile(cls, name, profile, journey):
        """Build a request from one entry in profiles.json."""
        constraints = profile.get("constraints", {})
        unknown = set(constraints) - set(cls.CONSTRAINT_KEYS)
        if unknown:
            # catch typos like max_budjet
            raise ConfigurationError(f"{name}: unknown constraint(s) {sorted(unknown)}")
        try:
            return cls(
                name=name,
                label=profile.get("label", name),
                destination=journey["destination"].upper(),
                date_from=date.fromisoformat(journey["date_from"]),
                date_to=date.fromisoformat(journey["date_to"]),
                weights=dict(profile["weights"]),
                preferred_departure=DepartureWindow.parse(profile.get("preferred_departure", "any")),
                **constraints,
            )
        except KeyError as error:
            raise ConfigurationError(f"{name}: missing setting {error}") from None
        except (TypeError, ValueError) as error:
            if isinstance(error, ConfigurationError):
                raise
            raise ConfigurationError(f"{name}: {error}") from None

    def hard_constraints_text(self):
        """Readable list of the hard constraints, shown to the user."""
        lines = [f"destination {self.destination}",
                 f"travel between {self.date_from} and {self.date_to}",
                 f"{self.seats} seat(s) available"]
        if self.max_budget is not None:
            lines.append(f"price at most EUR {self.max_budget:.2f}")
        if self.max_transfers is not None:
            lines.append(f"at most {self.max_transfers} transfer(s)")
        if self.require_changeable:
            lines.append("ticket must be changeable")
        if self.require_refundable:
            lines.append("ticket must be refundable")
        if self.min_luggage_kg is not None:
            lines.append(f"luggage allowance at least {self.min_luggage_kg} kg")
        if self.max_duration_min is not None:
            lines.append(f"journey at most {format_duration(self.max_duration_min)}")
        return lines


@dataclass
class Booking:
    reference: str
    offer_id: str
    traveller: str
    seats: int
    total_price: float
    fare: dict
    departure: str
    created_at: str
    status: str = "CONFIRMED"
    payment_status: str = "SIMULATED_PAID"
    refund_amount: float = 0.0

    @property
    def is_active(self):
        return self.status == "CONFIRMED"

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    def confirmation_text(self):
        fare = FareConditions(**self.fare)
        return "\n".join([
            "BOOKING CONFIRMATION (simulated, no payment collected)",
            f"  Reference : {self.reference}",
            f"  Traveller : {self.traveller}",
            f"  Offer     : {self.offer_id}",
            f"  Departure : {self.departure}",
            f"  Seats     : {self.seats}",
            f"  Total     : EUR {self.total_price:.2f}",
            f"  Fare      : {fare.describe()}",
            f"  Payment   : {self.payment_status}",
        ])


@dataclass
class Marketplace:
    """Container for all loaded data. Composition: it owns the collections."""

    companies: dict = field(default_factory=dict)
    destinations: dict = field(default_factory=dict)
    offers: dict = field(default_factory=dict)

    def get_offer(self, offer_id):
        return self.offers.get(offer_id)

    def all_offers(self):
        return list(self.offers.values())
