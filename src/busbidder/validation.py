"""Regex patterns and parsing of single fields."""

import re
from datetime import datetime

from .exceptions import InvalidIdentifierError, InvalidRecordError

COMPANY_ID = re.compile(r"[A-Z]{3}")
DESTINATION_ID = re.compile(r"[A-Z]{3}")

OFFER_ID = re.compile(
    r"""
    (?P<company>[A-Z]{3})       # company code, e.g. SOL
    -
    (?P<destination>[A-Z]{3})   # destination code, e.g. MAL
    -
    (?P<date>\d{8})             # travel date as YYYYMMDD
    -
    (?P<sequence>\d{2})         # departure number on that day
    """,
    re.VERBOSE,
)

BOOKING_REFERENCE = re.compile(r"BB-(?P<year>\d{4})-(?P<code>[A-Z0-9]{6})")

TIMESTAMP = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{2}:\d{2})")
CLOCK_TIME = re.compile(r"(?P<hour>\d{2}):(?P<minute>\d{2})")
TIME_WINDOW = re.compile(r"(?P<start>\d{2}:\d{2})-(?P<end>\d{2}:\d{2})")

TRUE_WORDS = {"yes", "y", "true", "1"}
FALSE_WORDS = {"no", "n", "false", "0"}


def validate_code(value, pattern, field):
    """Validate a three-letter company or destination code."""
    if not pattern.fullmatch(value):
        raise InvalidIdentifierError(f"'{value}' is not a valid three-letter code", field=field)
    return value


def parse_offer_id(value):
    """Validate an offer identifier and return its named parts."""
    match = OFFER_ID.fullmatch(value)
    if match is None:
        raise InvalidIdentifierError(
            f"'{value}' does not follow the format CMP-DST-YYYYMMDD-NN", field="offer_id"
        )
    return match.groupdict()


def is_valid_booking_reference(value):
    return BOOKING_REFERENCE.fullmatch(value) is not None


def parse_timestamp(value, field):
    """Parse 'YYYY-MM-DD HH:MM'. Regex checks shape, datetime checks meaning."""
    if not TIMESTAMP.fullmatch(value):
        raise InvalidRecordError(f"'{value}' is not in the format YYYY-MM-DD HH:MM", field=field)
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        raise InvalidRecordError(f"'{value}' is not a real calendar date or time", field=field) from None


def parse_clock_time(value, field="time"):
    """Parse 'HH:MM' into minutes after midnight."""
    match = CLOCK_TIME.fullmatch(value)
    if match is None:
        raise ValueError(f"{field}: '{value}' is not in the format HH:MM")
    hour, minute = int(match["hour"]), int(match["minute"])
    if hour > 23 or minute > 59:
        raise ValueError(f"{field}: '{value}' is not a real clock time")
    return hour * 60 + minute


def parse_int(value, field):
    try:
        return int(value)
    except ValueError:
        raise InvalidRecordError(f"'{value}' is not a whole number", field=field) from None


def parse_float(value, field):
    try:
        return float(value)
    except ValueError:
        raise InvalidRecordError(f"'{value}' is not a number", field=field) from None


def parse_optional_float(value, field):
    return None if value == "" else parse_float(value, field)


def parse_bool(value, field):
    word = value.lower()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    raise InvalidRecordError(f"'{value}' is not yes or no", field=field)
