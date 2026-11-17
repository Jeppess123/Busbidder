"""Weighted ranking and the explanation of the top offer."""

import logging
from dataclasses import dataclass, field

from .criteria import CRITERIA, REQUIRED_CRITERIA
from .exceptions import ConfigurationError, UnknownCriterionError
from .logging_utils import log_call

logger = logging.getLogger(__name__)

WEIGHT_TOLERANCE = 0.001
DOMINANCE_WARNING = 0.70
STRENGTH_THRESHOLD = 70
WEAKNESS_THRESHOLD = 40


def validate_weights(weights):
    """Return weights as fractions that total 1.0, or raise ConfigurationError."""
    if not isinstance(weights, dict) or not weights:
        raise ConfigurationError("weights must be a non-empty mapping of criterion to weight")
    cleaned = {}
    for name, value in weights.items():
        if name not in CRITERIA:
            raise UnknownCriterionError(
                f"unknown criterion '{name}' (available: {', '.join(sorted(CRITERIA))})")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigurationError(f"weight for '{name}' must be a number, got {value!r}")
        if value < 0:
            raise ConfigurationError(f"weight for '{name}' cannot be negative")
        cleaned[name] = float(value)

    missing = [name for name in REQUIRED_CRITERIA if name not in cleaned]
    if missing:
        raise ConfigurationError(f"weights must include the required criteria: {', '.join(missing)}")

    total = sum(cleaned.values())
    if abs(total - 1.0) <= WEIGHT_TOLERANCE:
        return cleaned
    if abs(total - 100.0) <= WEIGHT_TOLERANCE * 100:
        return {name: value / 100 for name, value in cleaned.items()}
    raise ConfigurationError(f"weights total {total:g}; they must total 1.0 (or 100%)")


def dominance_warnings(weights):
    """Warn when one criterion carries most of the total weight."""
    return [f"'{name}' carries {value:.0%} of the weight and will largely decide the ranking"
            for name, value in weights.items() if value > DOMINANCE_WARNING]


@dataclass
class RankedOffer:
    offer: object
    scores: dict
    contributions: dict
    total: float
    rank: int = 0
    tied: bool = False
    notes: list = field(default_factory=list)


class Ranker:
    """Scores and orders acceptable offers for one set of weights."""

    def __init__(self, weights):
        self.weights = validate_weights(weights)
        self.criteria = {name: CRITERIA[name]() for name in self.weights}

    @log_call()
    def rank(self, offers, request):
        if not offers:
            return []
        all_scores = {name: criterion.score_all(offers, request)
                      for name, criterion in self.criteria.items()}
        ranked = []
        for offer in offers:
            scores = {name: all_scores[name][offer.offer_id] for name in self.criteria}
            contributions = {name: self.weights[name] * score for name, score in scores.items()}
            item = RankedOffer(offer, scores, contributions, sum(contributions.values()))
            if "emissions" in self.criteria and offer.co2_kg is None:
                item.notes.append("no emissions data, scored as neutral")
            ranked.append(item)

        ranked.sort(key=lambda r: (-round(r.total, 2), r.offer.price, r.offer.duration_min, r.offer.offer_id))
        for position, item in enumerate(ranked, start=1):
            item.rank = position
            if position > 1 and round(item.total, 2) == round(ranked[position - 2].total, 2):
                item.tied = ranked[position - 2].tied = True
        logger.info("ranked %d offers for %s; top: %s", len(ranked), request.name, ranked[0].offer.offer_id)
        return ranked

    def explain(self, ranked, request):
        """Generate a short, data-driven explanation of the top offer."""
        if not ranked:
            return "No offer satisfies all hard constraints. Try relaxing the budget, dates or transfers."
        top = ranked[0]
        weighted = [name for name, weight in self.weights.items() if weight > 0]

        def line(name, item):
            criterion = self.criteria[name]
            return (f"{criterion.describe(item.offer, request)} "
                    f"({criterion.label.lower()} score {item.scores[name]:.0f}/100, "
                    f"weight {self.weights[name]:.0%})")

        strengths = sorted((n for n in weighted if top.scores[n] >= STRENGTH_THRESHOLD),
                           key=lambda n: top.contributions[n], reverse=True)[:3]
        weaknesses = sorted((n for n in weighted if top.scores[n] <= WEAKNESS_THRESHOLD),
                            key=lambda n: self.weights[n], reverse=True)[:2]

        lines = [f"Recommendation: {top.offer}",
                 f"Total score {top.total:.1f}/100 under the {request.label.lower()} settings.",
                 "Strengths:"]
        lines += [f"  + {line(n, top)}" for n in strengths] or \
                 ["  + no single standout feature; it scores evenly across the criteria"]
        lines.append("Trade-offs:")
        lines += [f"  - {line(n, top)}" for n in weaknesses] or \
                 ["  - no weighted criterion scores below 40"]

        if len(ranked) == 1:
            lines.append("It is the only offer that passed every hard constraint.")
        else:
            second = ranked[1]
            difference = {n: top.contributions[n] - second.contributions[n] for n in weighted}
            gain = max(difference, key=difference.get)
            loss = min(difference, key=difference.get)
            if top.tied:
                lines.append(f"It is tied with {second.offer.offer_id}; the tie is broken by lower price, "
                             "then shorter duration.")
            else:
                margin = top.total - second.total
                margin_text = f"{margin:.2f}" if margin < 1 else f"{margin:.1f}"
                lines.append(f"It leads {second.offer.offer_id} ({second.offer.company.name}) by "
                             f"{margin_text} points, mostly through "
                             f"{self.criteria[gain].label.lower()} (+{difference[gain]:.1f}).")
            if difference[loss] < 0:
                lines.append(f"{second.offer.offer_id} is better on {self.criteria[loss].label.lower()} "
                             f"({difference[loss]:.1f} points).")
        lines.append("This is the best match for the chosen constraints and weights, "
                     "not an objectively best ticket. Other weights can change the order.")
        return "\n".join(lines)
