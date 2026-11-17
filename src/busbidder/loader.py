"""Reads and validates the CSV and JSON files."""

import csv
import json
import logging
from pathlib import Path

from .exceptions import (DataFileError, FieldTypeError, FieldValueError,
                         InvalidIdentifierError, InvalidRecordError)
from .logging_utils import log_call
from .models import Company, Destination, FareConditions, Marketplace, Offer, TravelRequest
from .validation import (COMPANY_ID, DESTINATION_ID, parse_bool, parse_float, parse_int,
                         parse_offer_id, parse_optional_float, parse_timestamp, validate_code)

logger = logging.getLogger(__name__)

COMPANY_COLUMNS = ["company_id", "name", "profile"]
DESTINATION_COLUMNS = ["destination_id", "name", "distance_km", "coastal"]
OFFER_COLUMNS = ["offer_id", "company_id", "destination_id", "departure", "arrival",
                 "duration_min", "price_eur", "transfers", "luggage_kg", "changeable",
                 "change_fee_eur", "refundable", "available_seats", "rating", "co2_kg"]
OPTIONAL_OFFER_COLUMNS = {"co2_kg"}
DURATION_TOLERANCE_MIN = 5
# attribute names that are different from the CSV columns
ATTRIBUTE_TO_COLUMN = {"price": "price_eur"}


class LoadReport:
    """Collects what happened while loading, for the console and output files."""

    def __init__(self):
        self.accepted = {}
        self.rejected = []    # InvalidRecordError objects
        self.corrected = []   # readable messages
        self.set_aside = []   # readable messages

    def count_accepted(self, filename):
        self.accepted[filename] = self.accepted.get(filename, 0) + 1

    def reject(self, error):
        self.rejected.append(error)
        logger.warning("rejected %s", error.describe())

    def correct(self, filename, row_number, message):
        text = f"{filename} row {row_number}: {message}"
        self.corrected.append(text)
        logger.info("corrected %s", text)

    def set_aside_record(self, filename, row_number, message):
        text = f"{filename} row {row_number}: {message}"
        self.set_aside.append(text)
        logger.info("set aside %s", text)

    def summary_lines(self):
        lines = [f"Accepted records : {sum(self.accepted.values())} "
                 + "(" + ", ".join(f"{name}: {count}" for name, count in self.accepted.items()) + ")",
                 f"Rejected records : {len(self.rejected)}",
                 f"Corrected records: {len(self.corrected)}",
                 f"Set aside (sold out, kept but not bookable): {len(self.set_aside)}"]
        return lines

    def write(self, output_dir):
        """Write rejected_records.txt: one line per rejected row."""
        output_dir.mkdir(parents=True, exist_ok=True)
        rejected_path = output_dir / "rejected_records.txt"
        with open(rejected_path, "w", encoding="utf-8") as file:
            file.write("file\trow\tfield\treason\n")
            for error in self.rejected:
                file.write(f"{error.filename}\t{error.row_number}\t{error.field or '-'}\t{error.reason}\n")
        return rejected_path


def read_csv_rows(path, required_columns):
    """Yield (row_number, row) pairs from a CSV file."""
    path = Path(path)
    try:
        with open(path, encoding="utf-8", newline="") as file:
            reader = csv.DictReader(file)
            header = reader.fieldnames or []
            missing = [column for column in required_columns if column not in header]
            if missing:
                raise DataFileError(path, f"missing column(s): {', '.join(missing)}")
            for row in reader:
                yield reader.line_num, row
    except FileNotFoundError:
        raise DataFileError(path, "file not found") from None
    except PermissionError:
        raise DataFileError(path, "permission denied") from None
    except IsADirectoryError:
        raise DataFileError(path, "expected a file but found a directory") from None
    except UnicodeDecodeError:
        raise DataFileError(path, "file is not valid UTF-8 text") from None
    except csv.Error as error:
        raise DataFileError(path, f"CSV format error: {error}") from None


def check_row_shape(row, columns):
    """Detect rows with too many or too few values."""
    if None in row:  # DictReader stores surplus values under the key None
        raise InvalidRecordError(f"row has {len(row[None])} value(s) too many")
    missing = [column for column in columns if row.get(column) is None]
    if missing:
        raise InvalidRecordError(f"row is too short: {len(columns) - len(missing)} of {len(columns)} values",
                                 field=missing[0])


def clean_row(row):
    """Strip surrounding whitespace from every value."""
    return {key: value.strip() for key, value in row.items() if key is not None}


@log_call(logging.INFO)
def load_companies(path, report):
    companies = {}
    filename = Path(path).name
    for row_number, raw in read_csv_rows(path, COMPANY_COLUMNS):
        try:
            check_row_shape(raw, COMPANY_COLUMNS)
            row = clean_row(raw)
            company_id = validate_code(row["company_id"].upper(), COMPANY_ID, "company_id")
            if company_id in companies:
                raise InvalidIdentifierError(f"duplicate company {company_id}", field="company_id")
            if not row["name"]:
                raise InvalidRecordError("company name is missing", field="name")
            companies[company_id] = Company(company_id, row["name"], row["profile"])
            report.count_accepted(filename)
        except InvalidRecordError as error:
            error.filename, error.row_number = filename, row_number
            report.reject(error)
    return companies


@log_call(logging.INFO)
def load_destinations(path, report):
    destinations = {}
    filename = Path(path).name
    for row_number, raw in read_csv_rows(path, DESTINATION_COLUMNS):
        try:
            check_row_shape(raw, DESTINATION_COLUMNS)
            row = clean_row(raw)
            code = validate_code(row["destination_id"].upper(), DESTINATION_ID, "destination_id")
            if code in destinations:
                raise InvalidIdentifierError(f"duplicate destination {code}", field="destination_id")
            distance = parse_int(row["distance_km"], "distance_km")
            if distance <= 0:
                raise InvalidRecordError("distance must be positive", field="distance_km")
            destinations[code] = Destination(code, row["name"], distance,
                                             parse_bool(row["coastal"], "coastal"))
            report.count_accepted(filename)
        except InvalidRecordError as error:
            error.filename, error.row_number = filename, row_number
            report.reject(error)
    return destinations


def build_offer(row, companies, destinations):
    """Convert one cleaned CSV row into (Offer, corrections), or raise InvalidRecordError."""
    corrections = []
    for column in OFFER_COLUMNS:
        if column not in OPTIONAL_OFFER_COLUMNS and row[column] == "":
            raise InvalidRecordError("required value is missing", field=column)

    # codes should be upper case, fix it and note the correction
    for column in ("offer_id", "company_id", "destination_id"):
        if row[column] != row[column].upper():
            corrections.append(f"{column} '{row[column]}' upper-cased")
            row[column] = row[column].upper()

    parts = parse_offer_id(row["offer_id"])
    company = companies.get(validate_code(row["company_id"], COMPANY_ID, "company_id"))
    if company is None:
        raise InvalidRecordError(f"unknown company '{row['company_id']}'", field="company_id")
    destination = destinations.get(validate_code(row["destination_id"], DESTINATION_ID, "destination_id"))
    if destination is None:
        raise InvalidRecordError(f"unknown destination '{row['destination_id']}'", field="destination_id")
    if parts["company"] != company.company_id or parts["destination"] != destination.destination_id:
        raise InvalidIdentifierError(
            f"offer_id {row['offer_id']} does not match company {company.company_id} "
            f"and destination {destination.destination_id}", field="offer_id")

    departure = parse_timestamp(row["departure"], "departure")
    arrival = parse_timestamp(row["arrival"], "arrival")
    if parts["date"] != f"{departure:%Y%m%d}":
        raise InvalidIdentifierError(
            f"offer_id date {parts['date']} does not match departure date {departure:%Y-%m-%d}",
            field="offer_id")

    fare = FareConditions(
        changeable=parse_bool(row["changeable"], "changeable"),
        refundable=parse_bool(row["refundable"], "refundable"),
        change_fee=parse_float(row["change_fee_eur"], "change_fee_eur"),
    )
    offer = Offer(
        offer_id=row["offer_id"],
        company=company,
        destination=destination,
        departure=departure,
        arrival=arrival,
        price=parse_float(row["price_eur"], "price_eur"),
        transfers=parse_int(row["transfers"], "transfers"),
        luggage_kg=parse_float(row["luggage_kg"], "luggage_kg"),
        fare=fare,
        available_seats=parse_int(row["available_seats"], "available_seats"),
        rating=parse_float(row["rating"], "rating"),
        co2_kg=parse_optional_float(row["co2_kg"], "co2_kg"),
    )

    recorded = parse_int(row["duration_min"], "duration_min")
    if abs(recorded - offer.duration_min) > DURATION_TOLERANCE_MIN:
        corrections.append(f"duration_min {recorded} replaced by {offer.duration_min} from timestamps")
    return offer, corrections


@log_call(logging.INFO)
def load_offers(path, companies, destinations, report, existing=None):
    """Load offers from one CSV file. existing is used to find duplicates across files."""
    offers = dict(existing or {})
    filename = Path(path).name
    for row_number, raw in read_csv_rows(path, OFFER_COLUMNS):
        try:
            check_row_shape(raw, OFFER_COLUMNS)
            offer, corrections = build_offer(clean_row(raw), companies, destinations)
            if offer.offer_id in offers:
                raise InvalidIdentifierError(f"duplicate offer_id {offer.offer_id}", field="offer_id")
        except InvalidRecordError as error:
            error.filename, error.row_number = filename, row_number
            report.reject(error)
            continue
        except (FieldValueError, FieldTypeError) as error:
            # from the descriptors, add the row info
            column = ATTRIBUTE_TO_COLUMN.get(error.field, error.field)
            report.reject(InvalidRecordError(str(error), field=column,
                                             filename=filename, row_number=row_number))
            continue
        for message in corrections:
            report.correct(filename, row_number, message)
        if offer.is_sold_out:
            report.set_aside_record(filename, row_number, f"{offer.offer_id} is sold out (0 seats)")
        offers[offer.offer_id] = offer
        report.count_accepted(filename)
    return offers


def load_profiles(path):
    """Return {name: TravelRequest} from profiles.json."""
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as file:
            data = json.load(file)
    except FileNotFoundError:
        raise DataFileError(path, "file not found") from None
    except json.JSONDecodeError as error:
        raise DataFileError(path, f"invalid JSON at line {error.lineno}: {error.msg}") from None
    try:
        journey = data["journey"]
        profiles = data["profiles"]
    except (KeyError, TypeError):
        raise DataFileError(path, "expected top-level 'journey' and 'profiles'") from None
    return {name: TravelRequest.from_profile(name, profile, journey)
            for name, profile in profiles.items()}


def load_journey(path):
    """Return the default journey section of profiles.json."""
    with open(path, encoding="utf-8") as file:
        return json.load(file)["journey"]


def load_marketplace(data_dir, offer_files=None):
    """Load every data file and return (Marketplace, LoadReport)."""
    data_dir = Path(data_dir)
    report = LoadReport()
    companies = load_companies(data_dir / "companies.csv", report)
    destinations = load_destinations(data_dir / "destinations.csv", report)
    offers = {}
    for offer_file in offer_files or [data_dir / "offers.csv"]:
        offers = load_offers(offer_file, companies, destinations, report, existing=offers)
    logger.info("marketplace loaded: %d companies, %d destinations, %d offers",
                len(companies), len(destinations), len(offers))
    return Marketplace(companies, destinations, offers), report

