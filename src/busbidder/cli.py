"""Command line interface and interactive menu."""

import argparse
import logging
import sys
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from .booking import BookingManager
from .constraints import build_constraints, filter_offers
from .criteria import CRITERIA, REQUIRED_CRITERIA
from .exceptions import BookingError, BusBidderError, ConfigurationError
from .loader import load_journey, load_marketplace, load_profiles
from .logging_utils import configure_logging
from .models import DepartureWindow, Offer, TravelRequest
from .ranking import Ranker, dominance_warnings
from .reporting import (comparison_table, filter_summary, ranking_table, removed_details,
                        write_comparison_csv)

logger = logging.getLogger(__name__)


@dataclass
class Session:
    """Everything a command needs: loaded data, profiles and bookings."""

    args: argparse.Namespace
    marketplace: object
    report: object
    profiles: dict
    bookings: BookingManager
    journey: dict

    @property
    def output_dir(self):
        return Path(self.args.output_dir)


@dataclass
class RankingRun:
    request: TravelRequest
    result: object
    ranker: Ranker
    ranked: list


def open_session(args):
    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    offer_files = [Path(path) for path in args.offers] if args.offers else None
    marketplace, report = load_marketplace(data_dir, offer_files)
    report.write(output_dir)
    profiles_path = data_dir / "profiles.json"
    profiles = load_profiles(profiles_path)
    bookings_path = Path(args.bookings) if args.bookings else output_dir / "bookings.json"
    bookings = BookingManager(bookings_path, marketplace)
    return Session(args, marketplace, report, profiles, bookings, load_journey(profiles_path))


def run_ranking(session, request):
    ranker = Ranker(request.weights)
    result = filter_offers(session.marketplace.all_offers(), build_constraints(request))
    ranked = ranker.rank(result.accepted, request)
    return RankingRun(request, result, ranker, ranked)


def get_profile(session, name):
    try:
        return session.profiles[name]
    except KeyError:
        raise ConfigurationError(
            f"unknown profile '{name}' (available: {', '.join(session.profiles)})") from None


def apply_overrides(request, args):
    """Let the command line change the journey of a stored profile."""
    changes = {}
    if getattr(args, "destination", None):
        changes["destination"] = args.destination.upper()
    if getattr(args, "date_from", None):
        changes["date_from"] = parse_date(args.date_from)
    if getattr(args, "date_to", None):
        changes["date_to"] = parse_date(args.date_to)
    return replace(request, **changes) if changes else request


def parse_date(text):
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ConfigurationError(f"'{text}' is not a date in the format YYYY-MM-DD") from None


def ranking_text(run, top):
    parts = [filter_summary(run.request, run.result)]
    parts += [f"Warning: {text}" for text in dominance_warnings(run.ranker.weights)]
    if run.ranked:
        parts += ["", ranking_table(run.ranked, run.ranker, limit=top), "", run.ranker.explain(run.ranked, run.request)]
    else:
        parts += ["", run.ranker.explain(run.ranked, run.request)]
    return "\n".join(parts)


def command_validate(session):
    print("\n".join(session.report.summary_lines()))
    for error in session.report.rejected[:25]:
        print(f"  rejected {error.describe()}")
    if len(session.report.rejected) > 25:
        print(f"  ... {len(session.report.rejected) - 25} more in rejected_records.txt")
    for message in session.report.corrected:
        print(f"  corrected {message}")
    for message in session.report.set_aside:
        print(f"  set aside {message}")
    print(f"Rejected rows written to {session.output_dir / 'rejected_records.txt'}")
    return 0


def command_rank(session):
    request = apply_overrides(get_profile(session, session.args.profile), session.args)
    run = run_ranking(session, request)
    text = ranking_text(run, session.args.top)
    print(text)
    if session.args.show_removed and run.result.removed:
        print("\nRemoved offers:\n" + removed_details(run.result))
    return 0


def command_compare(session):
    names = session.args.profiles or list(session.profiles)
    rows = []
    for name in names:
        request = apply_overrides(get_profile(session, name), session.args)
        run = run_ranking(session, request)
        rows.append((request, len(run.result.accepted), run.ranked))
        if session.args.details:
            print(f"=== {request.label} ===\n{ranking_text(run, session.args.top)}\n")
    print(comparison_table(rows))
    csv_path = write_comparison_csv(session.output_dir / "profile_comparison.csv", rows)
    print(f"\nSaved {csv_path}")
    return 0


def command_book(session):
    request = apply_overrides(get_profile(session, session.args.profile), session.args)
    run = run_ranking(session, request)
    offer_id = session.args.offer.strip().upper()
    if offer_id not in {item.offer.offer_id for item in run.ranked}:
        reasons = run.result.removed.get(offer_id)
        detail = "; ".join(reasons) if reasons else "it is not on this traveller's route or dates"
        raise BookingError(f"{offer_id} is not an acceptable offer for {request.label}: {detail}")
    traveller = session.args.traveller or request.label
    booking = session.bookings.book(offer_id, traveller, seats=request.seats)
    print(booking.confirmation_text())
    print(f"Seats left on {offer_id}: {session.marketplace.get_offer(offer_id).available_seats}")
    return 0


def command_bookings(session):
    if not session.bookings.bookings:
        print("No bookings yet.")
        return 0
    for booking in session.bookings.bookings.values():
        print(f"{booking.reference}  {booking.status:<9}  {booking.offer_id:<20} {booking.traveller:<25} "
              f"EUR {booking.total_price:>7.2f}  {booking.payment_status}")
    return 0


def command_cancel(session):
    booking = session.bookings.cancel(session.args.reference)
    print(f"Cancelled {booking.reference}. Payment status: {booking.payment_status}, "
          f"refund EUR {booking.refund_amount:.2f}.")
    return 0


class InputCancelled(Exception):
    """Raised when the user types q to leave a prompt."""


def ask(prompt, convert=str, default=None):
    """Ask until convert() accepts the answer. Empty input returns default."""
    while True:
        suffix = f" [{default}]" if default not in (None, "") else ""
        answer = input(f"{prompt}{suffix}: ").strip()
        if answer.lower() == "q":
            raise InputCancelled
        if answer == "" and default is not None:
            answer = str(default)
        try:
            return convert(answer)
        except ValueError as error:  # ConfigurationError is also a ValueError
            print(f"  Invalid input: {error}")


def yes_no(text):
    if text.lower() in {"y", "yes"}:
        return True
    if text.lower() in {"n", "no"}:
        return False
    raise ValueError("answer y or n")


def optional_number(convert, max_value=None):
    def parse(text):
        if text.lower() in {"", "none", "-"}:
            return None
        value = convert(text)
        if value < 0:
            raise ValueError("value cannot be negative")
        if max_value is not None and value > max_value:
            raise ValueError(f"value cannot be more than {max_value}")
        return value
    return parse


def prompt_weights(current):
    """Let the traveller set the importance of each criterion in percent."""
    from .ranking import validate_weights
    print("Set the importance of each criterion in percent (0-100, the total must be 100). Type q to cancel.")
    print(f"Required: {', '.join(REQUIRED_CRITERIA)}. Others may be 0.")
    while True:
        weights = {}
        remaining = 100.0
        for name in CRITERIA:
            default = round(current.get(name, 0) * 100)
            value = ask(f"  {CRITERIA[name].label} (0-100, {remaining:g} left)",
                        optional_number(float, 100), default)
            if value:
                weights[name] = value
                remaining -= value
            elif name in REQUIRED_CRITERIA:
                weights[name] = 0.0
        print(f"  Total: {100 - remaining:g}")
        try:
            return validate_weights(weights)
        except ConfigurationError as error:
            print(f"  {error}. Please try again.")


def prompt_custom_request(session, base):
    destinations = session.marketplace.destinations
    print("Destinations: " + ", ".join(f"{code} {d.name}" for code, d in destinations.items()))
    offers = session.marketplace.all_offers()
    dates = ""
    if offers:
        dates = f", {min(o.travel_date for o in offers)} to {max(o.travel_date for o in offers)}"
    max_seats = Offer.available_seats.max_value
    max_price = Offer.price.max_value
    max_transfers = Offer.transfers.max_value

    def destination(text):
        code = text.upper()
        if code not in destinations:
            raise ValueError(f"unknown destination code '{text}'")
        return code

    while True:
        try:
            return TravelRequest(
                name="custom",
                label="Custom traveller",
                destination=ask("Destination code", destination, base.destination),
                date_from=ask(f"Travel from (YYYY-MM-DD{dates})", parse_date, base.date_from),
                date_to=ask(f"Travel to (YYYY-MM-DD{dates})", parse_date, base.date_to),
                seats=ask(f"Seats (1-{max_seats})", optional_number(int, max_seats), base.seats),
                max_budget=ask(f"Maximum price in EUR (1-{max_price}, blank = none)",
                               optional_number(float, max_price), base.max_budget or ""),
                max_transfers=ask(f"Maximum transfers (0-{max_transfers}, blank = none)",
                                  optional_number(int, max_transfers),
                                  "" if base.max_transfers is None else base.max_transfers),
                require_changeable=ask("Changeable ticket required? (y/n)", yes_no,
                                       "y" if base.require_changeable else "n"),
                require_refundable=ask("Refundable ticket required? (y/n)", yes_no,
                                       "y" if base.require_refundable else "n"),
                preferred_departure=ask("Preferred departure (any, morning, afternoon, evening, night, HH:MM-HH:MM)",
                                        DepartureWindow.parse, base.preferred_departure.label
                                        if base.preferred_departure else "any"),
                weights=prompt_weights(base.weights),
            )
        except ConfigurationError as error:
            print(f"  {error}. Please enter the request again.")


def command_interactive(session):
    names = list(session.profiles)
    request = session.profiles[names[0]]
    last_run = None
    menu = ("\n1) Choose traveller profile   2) Create custom request   3) Adjust weights\n"
            "4) Show ranking              5) Book an offer from the ranking\n"
            "6) List bookings             7) Cancel a booking         8) Data validation summary\n"
            "0) Quit")
    print("BusBidder Spain - bus offers from Madrid, ranked for you.")
    print("Type q at any question to go back to the menu.")
    while True:
        print(f"\nCurrent traveller: {request.label} -> {request.destination}, "
              f"{request.date_from} to {request.date_to}")
        print(menu)
        try:
            choice = input("Choice: ").strip()
            if choice == "1":
                for number, name in enumerate(names, start=1):
                    print(f"  {number}) {session.profiles[name].label}")
                index = ask("Profile number", int, 1)
                if 1 <= index <= len(names):
                    request, last_run = session.profiles[names[index - 1]], None
                else:
                    print("  No profile with that number.")
            elif choice == "2":
                request, last_run = prompt_custom_request(session, request), None
            elif choice == "3":
                request, last_run = replace(request, weights=prompt_weights(Ranker(request.weights).weights)), None
            elif choice == "4":
                last_run = run_ranking(session, request)
                print(ranking_text(last_run, 15))
            elif choice == "5":
                if last_run is None or not last_run.ranked:
                    print("  Show a ranking with acceptable offers first (option 4).")
                    continue
                rank = ask("Rank number to book", int, 1)
                if not 1 <= rank <= len(last_run.ranked):
                    print("  No offer with that rank.")
                    continue
                offer = last_run.ranked[rank - 1].offer
                traveller = ask("Traveller name", str, request.label)
                if ask(f"Book {offer} for {traveller}? (y/n)", yes_no, "y"):
                    booking = session.bookings.book(offer.offer_id, traveller, seats=request.seats)
                    print(booking.confirmation_text())
                    last_run = None  # seat counts changed; rank again before the next booking
            elif choice == "6":
                command_bookings(session)
            elif choice == "7":
                booking = session.bookings.cancel(ask("Booking reference"))
                print(f"  Cancelled. Payment status {booking.payment_status}, refund EUR {booking.refund_amount:.2f}")
            elif choice == "8":
                command_validate(session)
            elif choice == "0":
                print("Goodbye.")
                return 0
            else:
                print("  Please choose a number from the menu.")
        except InputCancelled:
            print("  Cancelled, nothing was changed.")
        except BookingError as error:
            print(f"  Booking failed: {error}")
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="busbidder", description="BusBidder Spain: filter and rank bus offers.")
    parser.add_argument("--data-dir", default="data", help="folder with the CSV and JSON input (default: data)")
    parser.add_argument("--output-dir", default="output", help="folder for reports and logs (default: output)")
    parser.add_argument("--offers", action="append", metavar="CSV",
                        help="offer file to load; repeat for several files (default: DATA_DIR/offers.csv)")
    parser.add_argument("--bookings", help="booking ledger (default: OUTPUT_DIR/bookings.json)")
    sub = parser.add_subparsers(dest="command")

    def journey_options(command):
        command.add_argument("--destination", help="override the destination code, e.g. BCN")
        command.add_argument("--date-from", help="override the first travel date (YYYY-MM-DD)")
        command.add_argument("--date-to", help="override the last travel date (YYYY-MM-DD)")

    sub.add_parser("validate", help="load all data and report rejected records").set_defaults(handler=command_validate)

    rank = sub.add_parser("rank", help="rank offers for one traveller profile")
    rank.add_argument("--profile", required=True)
    rank.add_argument("--top", type=int, default=10, help="rows to show (default 10)")
    rank.add_argument("--show-removed", action="store_true", help="list every removed offer and why")
    journey_options(rank)
    rank.set_defaults(handler=command_rank)

    compare = sub.add_parser("compare", help="compare recommendations for several profiles")
    compare.add_argument("--profiles", nargs="+", help="profile names (default: all)")
    compare.add_argument("--details", action="store_true", help="also print each profile's ranking")
    compare.add_argument("--top", type=int, default=3, help="rows per profile with --details (default 3)")
    journey_options(compare)
    compare.set_defaults(handler=command_compare)

    book = sub.add_parser("book", help="book an acceptable offer for a profile")
    book.add_argument("--profile", required=True)
    book.add_argument("--offer", required=True)
    book.add_argument("--traveller", help="name on the booking")
    journey_options(book)
    book.set_defaults(handler=command_book)

    sub.add_parser("bookings", help="list bookings").set_defaults(handler=command_bookings)
    cancel = sub.add_parser("cancel", help="cancel a booking")
    cancel.add_argument("reference")
    cancel.set_defaults(handler=command_cancel)

    sub.add_parser("interactive", help="menu-driven mode (default)").set_defaults(handler=command_interactive)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    handler = getattr(args, "handler", command_interactive)
    configure_logging(Path(args.output_dir) / "busbidder.log")
    try:
        session = open_session(args)
        return handler(session)
    except BusBidderError as error:
        logger.error("%s", error)
        print(f"Error: {error}", file=sys.stderr)
        return 1