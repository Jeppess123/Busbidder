"""Scoring criteria. Each one gives an offer a score from 0 to 100."""

from .exceptions import ConfigurationError
from .models import format_duration

CRITERIA = {}

NEUTRAL_SCORE = 50.0  # used when a value is missing, see RelativeCriterion


def register_criterion(name):
    """Class decorator factory that adds a criterion class to CRITERIA."""

    def decorator(cls):
        if name in CRITERIA:
            raise ConfigurationError(f"criterion '{name}' is already registered by {CRITERIA[name].__name__}")
        cls.name = name
        CRITERIA[name] = cls
        return cls

    return decorator


class Criterion:
    """Base class for all criteria."""

    name = "criterion"
    label = "Criterion"
    short = "crit"

    def score_all(self, offers, request):
        """Return {offer_id: score from 0 to 100}. Overridden by subclasses."""
        raise NotImplementedError

    def describe(self, offer, request):
        """Readable description of the offer's raw value for this criterion."""
        raise NotImplementedError


class RelativeCriterion(Criterion):
    """Min-max normalisation against the acceptable offers."""

    lower_is_better = True
    min_spread = 1.0  # smallest spread used, so tiny differences are not blown up to 0-100

    def raw_value(self, offer, request):
        raise NotImplementedError

    def score_all(self, offers, request):
        values = {offer.offer_id: self.raw_value(offer, request) for offer in offers}
        present = [value for value in values.values() if value is not None]
        if not present:
            return {offer_id: NEUTRAL_SCORE for offer_id in values}
        low, high = min(present), max(present)
        spread = max(high - low, self.min_spread)
        scores = {}
        for offer_id, value in values.items():
            if value is None:
                scores[offer_id] = NEUTRAL_SCORE
            elif self.lower_is_better:
                scores[offer_id] = 100 * (1 - (value - low) / spread)
            else:
                scores[offer_id] = 100 * (1 - (high - value) / spread)
        return scores


class AbsoluteCriterion(Criterion):
    """Fixed scale per offer, independent of the other offers."""

    def score(self, offer, request):
        raise NotImplementedError

    def score_all(self, offers, request):
        return {offer.offer_id: self.score(offer, request) for offer in offers}


@register_criterion("price")
class PriceCriterion(RelativeCriterion):
    label, short = "Price", "Price"
    min_spread = 5.0  # euros

    def raw_value(self, offer, request):
        return offer.price

    def describe(self, offer, request):
        return f"costs EUR {offer.price:.2f}"


@register_criterion("duration")
class DurationCriterion(RelativeCriterion):
    label, short = "Duration", "Dur"
    min_spread = 30.0  # minutes

    def raw_value(self, offer, request):
        return offer.duration_min

    def describe(self, offer, request):
        return f"takes {format_duration(offer.duration_min)}"


@register_criterion("departure_time")
class DepartureTimeCriterion(AbsoluteCriterion):
    """100 inside the preferred window, then down to 0 at 4 hours outside it."""

    label, short = "Departure convenience", "Time"
    TOLERANCE_MIN = 240  # score falls from 100 to 0 over 4 hours outside the window

    def score(self, offer, request):
        window = request.preferred_departure
        if window is None:
            return 100.0
        outside = window.minutes_outside(offer.departure_minutes)
        return max(0.0, 100 * (1 - outside / self.TOLERANCE_MIN))

    def describe(self, offer, request):
        window = request.preferred_departure
        clock = f"{offer.departure:%H:%M}"
        if window is None:
            return f"departs {clock} (no time preference)"
        outside = window.minutes_outside(offer.departure_minutes)
        if outside == 0:
            return f"departs {clock}, inside the preferred {window}"
        return f"departs {clock}, {format_duration(outside)} outside the preferred {window}"


@register_criterion("flexibility")
class FlexibilityCriterion(AbsoluteCriterion):
    """Categorical scale: changing is worth up to 60 points, refunds 40."""

    label, short = "Flexibility", "Flex"
    # changing is worth up to 60 points, refund adds 40
    CHANGE_WITH_FEE = 40
    CHANGE_FREE = 60
    REFUNDABLE = 40

    def score(self, offer, request):
        fare = offer.fare
        points = 0
        if fare.changeable:
            points += self.CHANGE_FREE if fare.free_changes else self.CHANGE_WITH_FEE
        if fare.refundable:
            points += self.REFUNDABLE
        return float(points)

    def describe(self, offer, request):
        return f"ticket is {offer.fare.describe()}"


@register_criterion("transfers")
class TransfersCriterion(AbsoluteCriterion):
    label, short = "Transfers", "Trf"
    SCALE = {0: 100.0, 1: 50.0}

    def score(self, offer, request):
        return self.SCALE.get(offer.transfers, 0.0)

    def describe(self, offer, request):
        return "direct route" if offer.transfers == 0 else f"{offer.transfers} transfer(s)"


@register_criterion("rating")
class RatingCriterion(AbsoluteCriterion):
    label, short = "Customer rating", "Rate"

    def score(self, offer, request):
        return (offer.rating - 1) / 4 * 100

    def describe(self, offer, request):
        return f"rated {offer.rating:.1f}/5 by customers"


@register_criterion("emissions")
class EmissionsCriterion(RelativeCriterion):
    label, short = "Emissions", "CO2"
    min_spread = 2.0  # kg CO2 per passenger

    def raw_value(self, offer, request):
        return offer.co2_kg

    def describe(self, offer, request):
        if offer.co2_kg is None:
            return "has no emissions data (scored as neutral)"
        return f"emits about {offer.co2_kg:.1f} kg CO2 per passenger"


REQUIRED_CRITERIA = ("price", "duration", "departure_time", "flexibility")
