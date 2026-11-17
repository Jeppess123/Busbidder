"""Tables for the console and the comparison CSV."""

import csv

from .models import format_duration

LEGEND = ("Fare: C = changeable free, C* = changeable with fee, R = refundable, - = neither. "
          "Criterion columns are scores 0-100; Total is the weighted sum.")


def ranking_table(ranked, ranker, limit=None):
    names = list(ranker.criteria)
    header = (f"{'#':>3} {'Offer':<20} {'Company':<15} {'Date':<6} {'Dep':<5} {'Dur':<5} "
              f"{'Price':>7} {'Tr':>2} {'Fare':<4} | "
              + " ".join(f"{ranker.criteria[n].short:>5}" for n in names) + " | Total")
    lines = [header, "-" * len(header)]
    for item in ranked[:limit]:
        offer = item.offer
        tie = "=" if item.tied else " "
        lines.append(
            f"{item.rank:>3} {offer.offer_id:<20} {offer.company.name:<15} "
            f"{offer.departure:%d %b} {offer.departure:%H:%M} {format_duration(offer.duration_min):<5} "
            f"{offer.price:>7.2f} {offer.transfers:>2} {offer.fare.short_code():<4} | "
            + " ".join(f"{item.scores[n]:>5.0f}" for n in names)
            + f" | {item.total:5.1f}{tie}"
        )
    if limit is not None and len(ranked) > limit:
        lines.append(f"... {len(ranked) - limit} more offer(s); use --top to show more")
    weights = ", ".join(f"{ranker.criteria[n].short} {w:.0%}" for n, w in ranker.weights.items())
    lines.append(f"Weights: {weights}")
    lines.append(LEGEND)
    if any(item.tied for item in ranked[:limit]):
        lines.append("= marks equal totals; order then follows lower price, shorter duration, offer id.")
    return "\n".join(lines)


def filter_summary(request, result):
    lines = [f"Traveller profile: {request.label} ({request.name})",
             "Hard constraints (offers violating any of these are removed):"]
    lines += [f"  * {text}" for text in request.hard_constraints_text()]
    preference = request.preferred_departure or "no preference"
    lines.append(f"Soft preferences (affect the score only): departure {preference}; weights below")
    lines.append(f"Candidates on this route and dates: {result.considered}; "
                 f"acceptable: {len(result.accepted)}; removed: {len(result.removed)}")
    for name, count in sorted(result.removal_counts.items(), key=lambda pair: -pair[1]):
        lines.append(f"  removed by {name}: {count}")
    return "\n".join(lines)


def removed_details(result):
    return "\n".join(f"  {offer_id}: {'; '.join(reasons)}" for offer_id, reasons in sorted(result.removed.items()))


def comparison_table(rows):
    """rows: list of (request, accepted_count, ranked) tuples."""
    header = (f"{'Profile':<32} {'OK':>3}  {'Top offer':<20} {'Company':<15} {'Dep':<12} "
              f"{'Price':>7} {'Score':>6}  Runner-up")
    lines = [header, "-" * len(header)]
    for request, accepted, ranked in rows:
        if not ranked:
            lines.append(f"{request.label:<32} {accepted:>3}  (no acceptable offer)")
            continue
        top = ranked[0]
        runner_up = ranked[1].offer.offer_id if len(ranked) > 1 else "-"
        lines.append(f"{request.label:<32} {accepted:>3}  {top.offer.offer_id:<20} "
                     f"{top.offer.company.name:<15} {top.offer.departure:%d %b %H:%M} "
                     f"{top.offer.price:>7.2f} {top.total:>6.1f}  {runner_up}")
    return "\n".join(lines)


def write_comparison_csv(path, rows, top_n=3):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["profile", "acceptable_offers", "rank", "offer_id", "company", "departure",
                         "price_eur", "duration_min", "transfers", "fare", "total"])
        for request, accepted, ranked in rows:
            for item in ranked[:top_n]:
                offer = item.offer
                writer.writerow([request.name, accepted, item.rank, offer.offer_id, offer.company.name,
                                 f"{offer.departure:%Y-%m-%d %H:%M}", f"{offer.price:.2f}",
                                 offer.duration_min, offer.transfers, offer.fare.short_code(),
                                 f"{item.total:.2f}"])
    return path
