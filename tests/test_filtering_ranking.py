"""Constraint, normalisation, weight-validation and ranking tests."""

import pytest

from busbidder.constraints import build_constraints, filter_offers
from busbidder.criteria import CRITERIA, NEUTRAL_SCORE, register_criterion, PriceCriterion
from busbidder.exceptions import ConfigurationError, UnknownCriterionError
from busbidder.ranking import Ranker, dominance_warnings, validate_weights

from conftest import make_offer, make_request


# -------------------------------------------------------------- constraints
def test_budget_boundary_is_inclusive():
    request = make_request(max_budget=40)
    result = filter_offers([make_offer(price=40.0), make_offer(offer_id="SOL-MAL-20260712-02", price=40.01)],
                           build_constraints(request))
    assert [o.offer_id for o in result.accepted] == ["SOL-MAL-20260712-01"]
    assert "budget" in result.removed["SOL-MAL-20260712-02"][0]


def test_all_failed_constraints_are_reported():
    request = make_request(max_budget=30, max_transfers=0, require_changeable=True)
    offer = make_offer(price=45, transfers=1, changeable=False)
    result = filter_offers([offer], build_constraints(request))
    assert len(result.removed[offer.offer_id]) == 3
    assert result.removal_counts == {"budget": 1, "maximum transfers": 1, "changeable ticket": 1}


def test_sold_out_offer_is_removed():
    result = filter_offers([make_offer(seats=0)], build_constraints(make_request()))
    assert result.accepted == []


def test_other_routes_and_dates_are_not_candidates():
    outside = make_offer(offer_id="SOL-MAL-20260720-01", departure="2026-07-20 09:00")
    result = filter_offers([outside], build_constraints(make_request()))
    assert result.considered == 0


def test_duration_and_luggage_constraints():
    request = make_request(max_duration_min=420, min_luggage_kg=20)
    ok = make_offer(minutes=420, luggage_kg=20)
    too_long = make_offer(offer_id="SOL-MAL-20260712-02", minutes=425)
    too_small = make_offer(offer_id="SOL-MAL-20260712-03", luggage_kg=15)
    result = filter_offers([ok, too_long, too_small], build_constraints(request))
    assert [o.offer_id for o in result.accepted] == [ok.offer_id]


# ------------------------------------------------------------ normalisation
def test_price_lower_is_better_and_best_gets_100():
    offers = [make_offer(price=30), make_offer(offer_id="SOL-MAL-20260712-02", price=50)]
    scores = CRITERIA["price"]().score_all(offers, make_request())
    assert scores["SOL-MAL-20260712-01"] == 100
    assert scores["SOL-MAL-20260712-02"] == 0


def test_min_spread_stops_tiny_differences_from_dominating():
    offers = [make_offer(price=40.00), make_offer(offer_id="SOL-MAL-20260712-02", price=40.50)]
    scores = CRITERIA["price"]().score_all(offers, make_request())
    assert scores["SOL-MAL-20260712-02"] == pytest.approx(90)  # not 0, because spread floor is EUR 5


def test_identical_values_all_get_full_score():
    offers = [make_offer(), make_offer(offer_id="SOL-MAL-20260712-02")]
    assert set(CRITERIA["duration"]().score_all(offers, make_request()).values()) == {100}


def test_missing_emissions_get_neutral_score():
    offers = [make_offer(co2_kg=None), make_offer(offer_id="SOL-MAL-20260712-02", co2_kg=6.0)]
    scores = CRITERIA["emissions"]().score_all(offers, make_request())
    assert scores["SOL-MAL-20260712-01"] == NEUTRAL_SCORE


@pytest.mark.parametrize("departure, expected", [
    ("2026-07-12 09:00", 100), ("2026-07-12 14:00", 50), ("2026-07-12 16:00", 0), ("2026-07-12 20:00", 0),
])
def test_departure_convenience_scale(departure, expected):
    offer = make_offer(departure=departure)
    assert CRITERIA["departure_time"]().score(offer, make_request(preferred="morning")) == pytest.approx(expected)


def test_no_departure_preference_gives_everyone_full_score():
    assert CRITERIA["departure_time"]().score(make_offer(), make_request(preferred="any")) == 100


@pytest.mark.parametrize("changeable, fee, refundable, expected", [
    (False, 0, False, 0), (True, 10, False, 40), (True, 0, False, 60), (True, 0, True, 100),
])
def test_flexibility_scale(changeable, fee, refundable, expected):
    offer = make_offer(changeable=changeable, change_fee=fee, refundable=refundable)
    assert CRITERIA["flexibility"]().score(offer, make_request()) == expected


# ----------------------------------------------------------------- weights
def test_percent_weights_are_converted():
    weights = validate_weights({"price": 40, "duration": 25, "departure_time": 15, "flexibility": 20})
    assert weights["price"] == pytest.approx(0.4)


@pytest.mark.parametrize("weights, error", [
    ({"price": 0.5, "duration": 0.25, "departure_time": 0.15, "flexibility": 0.2}, ConfigurationError),
    ({"price": -0.1, "duration": 0.5, "departure_time": 0.3, "flexibility": 0.3}, ConfigurationError),
    ({"price": 0.4, "duration": 0.25, "departure_time": 0.15, "comfort": 0.2}, UnknownCriterionError),
    ({"price": 0.6, "duration": 0.4}, ConfigurationError),          # required criteria missing
    ({"price": "0.4", "duration": 0.25, "departure_time": 0.15, "flexibility": 0.2}, ConfigurationError),
    ({}, ConfigurationError),
])
def test_invalid_weights_are_rejected(weights, error):
    with pytest.raises(error):
        validate_weights(weights)


def test_dominance_warning():
    assert dominance_warnings({"price": 0.8, "duration": 0.2})
    assert dominance_warnings({"price": 0.5, "duration": 0.5}) == []


# ----------------------------------------------------------------- registry
def test_duplicate_criterion_registration_is_rejected():
    with pytest.raises(ConfigurationError):
        register_criterion("price")(type("AnotherPrice", (PriceCriterion,), {}))


def test_new_criterion_is_available_without_changing_the_ranker():
    @register_criterion("test_luggage")
    class LuggageCriterion(PriceCriterion):
        lower_is_better = False

        def raw_value(self, offer, request):
            return offer.luggage_kg

    try:
        weights = {"price": 0.3, "duration": 0.2, "departure_time": 0.1, "flexibility": 0.1, "test_luggage": 0.3}
        ranked = Ranker(weights).rank([make_offer(luggage_kg=25),
                                       make_offer(offer_id="SOL-MAL-20260712-02", luggage_kg=10)], make_request())
        assert ranked[0].offer.luggage_kg == 25
    finally:
        del CRITERIA["test_luggage"]


# ------------------------------------------------------------------ ranking
def test_total_score_is_weighted_sum():
    offers = [make_offer(price=30, minutes=500), make_offer(offer_id="SOL-MAL-20260712-02", price=50, minutes=400)]
    ranked = Ranker(make_request().weights).rank(offers, make_request())
    for item in ranked:
        assert item.total == pytest.approx(sum(item.contributions.values()))
        assert 0 <= item.total <= 100


def test_ties_are_broken_by_price_then_id():
    a = make_offer(offer_id="SOL-MAL-20260712-02")
    b = make_offer(offer_id="SOL-MAL-20260712-01")
    ranked = Ranker(make_request().weights).rank([a, b], make_request())
    assert [r.offer.offer_id for r in ranked] == ["SOL-MAL-20260712-01", "SOL-MAL-20260712-02"]
    assert ranked[0].tied and ranked[1].tied


def test_ranking_is_reproducible():
    offers = [make_offer(price=p, offer_id=f"SOL-MAL-20260712-{i:02d}") for i, p in enumerate([35, 42, 38], 1)]
    first = [r.offer.offer_id for r in Ranker(make_request().weights).rank(offers, make_request())]
    second = [r.offer.offer_id for r in Ranker(make_request().weights).rank(list(reversed(offers)), make_request())]
    assert first == second


def test_explanation_mentions_strength_tradeoff_and_caveat():
    offers = [make_offer(price=30, minutes=520), make_offer(offer_id="SOL-MAL-20260712-02", price=48, minutes=400)]
    ranker = Ranker(make_request().weights)
    text = ranker.explain(ranker.rank(offers, make_request()), make_request())
    assert "Strengths" in text and "Trade-offs" in text
    assert "not an objectively best" in text


def test_explanation_without_offers():
    ranker = Ranker(make_request().weights)
    assert "No offer satisfies" in ranker.explain([], make_request())
