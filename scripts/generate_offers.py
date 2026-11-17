"""Makes data/offers.csv with simulated bus offers.

Uses a fixed seed, so the file is the same every time it is generated.
Run from the project root: python scripts/generate_offers.py
"""

import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

SEED = 5823
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FIRST_DAY = date(2026, 7, 10)
NUMBER_OF_DAYS = 7

# made up values for each company, based on the profiles in the task
COMPANY_RULES = {
    "SOL": {  # SolRuta, cheap daytime buses
        "speed_kmh": 66, "price_per_km": 0.052, "departure_hours": (7, 16),
        "changeable_share": 0.30, "change_fee": 9, "refundable_share": 0.0,
        "luggage_kg": 15, "rating": 3.3, "co2_per_km": 0.031,
    },
    "CAM": {  # Camino Express, fast and direct
        "speed_kmh": 86, "price_per_km": 0.105, "departure_hours": (6, 19),
        "changeable_share": 0.80, "change_fee": 0, "refundable_share": 0.45,
        "luggage_kg": 23, "rating": 4.4, "co2_per_km": 0.027,
    },
    "CST": {  # CostaLink, good on the coast
        "speed_kmh": 80, "price_per_km": 0.072, "departure_hours": (6, 14),
        "changeable_share": 0.50, "change_fee": 7, "refundable_share": 0.25,
        "luggage_kg": 20, "rating": 3.8, "co2_per_km": 0.029,
    },
    "VRD": {  # VerdeBus, green and modern
        "speed_kmh": 75, "price_per_km": 0.085, "departure_hours": (8, 20),
        "changeable_share": 0.75, "change_fee": 0, "refundable_share": 0.45,
        "luggage_kg": 20, "rating": 4.2, "co2_per_km": 0.011,
    },
    "NOC": {  # NocheVia, late evening and night
        "speed_kmh": 60, "price_per_km": 0.058, "departure_hours": (20, 23),
        "changeable_share": 0.35, "change_fee": 6, "refundable_share": 0.10,
        "luggage_kg": 25, "rating": 3.5, "co2_per_km": 0.024,
    },
}

TRANSFER_PENALTY_MIN = 40  # extra minutes for each transfer
FIELDNAMES = [
    "offer_id", "company_id", "destination_id", "departure", "arrival",
    "duration_min", "price_eur", "transfers", "luggage_kg", "changeable",
    "change_fee_eur", "refundable", "available_seats", "rating", "co2_kg",
]


def read_destinations(path):
    with open(path, encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def choose_transfers(rng, company_id, distance, coastal):
    """Number of transfers, depends on the company."""
    if company_id == "CAM":
        return 0
    if company_id == "CST":
        return 0 if coastal else 1
    if company_id == "SOL":
        if distance < 350:
            return rng.choice([0, 0, 1])
        return rng.choice([0, 1, 1, 2])
    if company_id == "VRD":
        return 0 if distance < 450 else rng.choice([0, 1])
    return rng.choice([0, 0, 1])  # NOC


def make_offer(rng, company_id, destination, travel_day, sequence):
    rules = COMPANY_RULES[company_id]
    distance = int(destination["distance_km"])
    coastal = destination["coastal"] == "yes"

    first_hour, last_hour = rules["departure_hours"]
    departure = datetime.combine(travel_day, datetime.min.time()).replace(
        hour=rng.randint(first_hour, last_hour), minute=rng.choice([0, 15, 30, 45])
    )

    transfers = choose_transfers(rng, company_id, distance, coastal)
    speed = rules["speed_kmh"]
    if company_id == "CST" and not coastal:
        speed -= 8  # CostaLink is slower inland
    minutes = distance / speed * 60 + transfers * TRANSFER_PENALTY_MIN
    minutes = int(round(minutes * rng.uniform(0.95, 1.08) / 5) * 5)
    arrival = departure + timedelta(minutes=minutes)

    changeable = rng.random() < rules["changeable_share"]
    refundable = changeable and rng.random() < rules["refundable_share"] / max(rules["changeable_share"], 0.01)

    price = distance * rules["price_per_km"] + 4
    if changeable:
        price += 3
    if refundable:
        price += 6
    if travel_day.weekday() >= 4:  # weekend is a bit more expensive
        price *= 1.10
    price *= rng.uniform(0.88, 1.12)

    seats = 0 if rng.random() < 0.04 else rng.randint(1, 40)
    rating = min(5.0, max(1.0, rng.gauss(rules["rating"], 0.25)))
    co2 = distance * rules["co2_per_km"] * (1 + 0.1 * transfers)
    co2_text = "" if rng.random() < 0.05 else f"{co2:.1f}"  # some offers have no CO2 value

    offer_id = f"{company_id}-{destination['destination_id']}-{travel_day:%Y%m%d}-{sequence:02d}"
    return {
        "offer_id": offer_id,
        "company_id": company_id,
        "destination_id": destination["destination_id"],
        "departure": f"{departure:%Y-%m-%d %H:%M}",
        "arrival": f"{arrival:%Y-%m-%d %H:%M}",
        "duration_min": minutes,
        "price_eur": f"{price:.2f}",
        "transfers": transfers,
        "luggage_kg": rules["luggage_kg"],
        "changeable": "yes" if changeable else "no",
        "change_fee_eur": rules["change_fee"] if changeable else 0,
        "refundable": "yes" if refundable else "no",
        "available_seats": seats,
        "rating": f"{rating:.1f}",
        "co2_kg": co2_text,
    }


def generate():
    rng = random.Random(SEED)
    destinations = read_destinations(DATA_DIR / "destinations.csv")
    offers = []
    for company_id in COMPANY_RULES:
        for destination in destinations:
            for day_number in range(NUMBER_OF_DAYS):
                travel_day = FIRST_DAY + timedelta(days=day_number)
                departures_today = rng.choice([1, 2, 2])
                for sequence in range(1, departures_today + 1):
                    offers.append(make_offer(rng, company_id, destination, travel_day, sequence))
    return offers


def main():
    offers = generate()
    output_path = DATA_DIR / "offers.csv"
    with open(output_path, "w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(offers)
    print(f"Wrote {len(offers)} offers to {output_path}")


if __name__ == "__main__":
    main()
