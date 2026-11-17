"""Hard constraints. Offers that break one of these are removed before ranking."""

import logging
from dataclasses import dataclass, field

from .logging_utils import log_call
from .models import format_duration

logger = logging.getLogger(__name__)


class Constraint:
    """Base class. Subclasses override check() and reason()."""

    name = "constraint"

    def __call__(self, offer):
        return self.check(offer)

    def check(self, offer):
        raise NotImplementedError

    def reason(self, offer):
        raise NotImplementedError

    def describe(self):
        return self.name


class DestinationConstraint(Constraint):
    name = "destination"

    def __init__(self, destination_id):
        self.destination_id = destination_id

    def check(self, offer):
        return offer.destination.destination_id == self.destination_id

    def reason(self, offer):
        return f"goes to {offer.destination.name}, not {self.destination_id}"


class TravelWindowConstraint(Constraint):
    name = "travel window"

    def __init__(self, date_from, date_to):
        self.date_from = date_from
        self.date_to = date_to

    def check(self, offer):
        return self.date_from <= offer.travel_date <= self.date_to

    def reason(self, offer):
        return f"departs {offer.travel_date}, outside {self.date_from} to {self.date_to}"


class SeatAvailabilityConstraint(Constraint):
    name = "seat availability"

    def __init__(self, seats):
        self.seats = seats

    def check(self, offer):
        return offer.available_seats >= self.seats

    def reason(self, offer):
        return f"only {offer.available_seats} seat(s) left, {self.seats} needed"


class BudgetConstraint(Constraint):
    name = "budget"

    def __init__(self, max_price):
        self.max_price = max_price

    def check(self, offer):
        return offer.price <= self.max_price

    def reason(self, offer):
        return f"costs EUR {offer.price:.2f}, budget is EUR {self.max_price:.2f}"


class MaxTransfersConstraint(Constraint):
    name = "maximum transfers"

    def __init__(self, max_transfers):
        self.max_transfers = max_transfers

    def check(self, offer):
        return offer.transfers <= self.max_transfers

    def reason(self, offer):
        return f"{offer.transfers} transfer(s), maximum is {self.max_transfers}"


class ChangeableConstraint(Constraint):
    name = "changeable ticket"

    def check(self, offer):
        return offer.fare.changeable

    def reason(self, offer):
        return "ticket cannot be changed"


class RefundableConstraint(Constraint):
    name = "refundable ticket"

    def check(self, offer):
        return offer.fare.refundable

    def reason(self, offer):
        return "ticket is not refundable"


class MinLuggageConstraint(Constraint):
    name = "luggage allowance"

    def __init__(self, min_kg):
        self.min_kg = min_kg

    def check(self, offer):
        return offer.luggage_kg >= self.min_kg

    def reason(self, offer):
        return f"luggage {offer.luggage_kg:.0f} kg, {self.min_kg:.0f} kg required"


class MaxDurationConstraint(Constraint):
    name = "maximum duration"

    def __init__(self, max_minutes):
        self.max_minutes = max_minutes

    def check(self, offer):
        return offer.duration_min <= self.max_minutes

    def reason(self, offer):
        return (f"journey takes {format_duration(offer.duration_min)}, "
                f"maximum is {format_duration(self.max_minutes)}")


def build_constraints(request):
    """Translate a TravelRequest into the list of hard constraints that apply."""
    constraints = [
        DestinationConstraint(request.destination),
        TravelWindowConstraint(request.date_from, request.date_to),
        SeatAvailabilityConstraint(request.seats),
    ]
    if request.max_budget is not None:
        constraints.append(BudgetConstraint(request.max_budget))
    if request.max_transfers is not None:
        constraints.append(MaxTransfersConstraint(request.max_transfers))
    if request.require_changeable:
        constraints.append(ChangeableConstraint())
    if request.require_refundable:
        constraints.append(RefundableConstraint())
    if request.min_luggage_kg is not None:
        constraints.append(MinLuggageConstraint(request.min_luggage_kg))
    if request.max_duration_min is not None:
        constraints.append(MaxDurationConstraint(request.max_duration_min))
    return constraints


@dataclass
class FilterResult:
    accepted: list = field(default_factory=list)
    removed: dict = field(default_factory=dict)       # offer_id -> list of reasons
    removal_counts: dict = field(default_factory=dict)  # constraint name -> count

    @property
    def considered(self):
        return len(self.accepted) + len(self.removed)


@log_call()
def filter_offers(offers, constraints):
    """Split offers into accepted ones and removed ones with all reasons."""
    result = FilterResult()
    journey_rules = constraints[:2]
    other_rules = constraints[2:]
    for offer in offers:
        if not all(rule(offer) for rule in journey_rules):
            continue
        reasons = []
        for rule in other_rules:
            if not rule(offer):
                reasons.append(f"{rule.name}: {rule.reason(offer)}")
                result.removal_counts[rule.name] = result.removal_counts.get(rule.name, 0) + 1
        if reasons:
            result.removed[offer.offer_id] = reasons
        else:
            result.accepted.append(offer)
    logger.info("filter: %d candidate offers, %d accepted, %d removed",
                result.considered, len(result.accepted), len(result.removed))
    return result
