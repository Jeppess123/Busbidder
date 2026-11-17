"""Custom exceptions for the project."""


class BusBidderError(Exception):
    """Base class for all expected failures in the application."""


class DataFileError(BusBidderError):
    """Raised when a data file is missing, unreadable or has the wrong columns."""

    def __init__(self, path, reason):
        self.path = path
        self.reason = reason
        super().__init__(f"{path}: {reason}")


class FieldValueError(BusBidderError, ValueError):
    """Raised by a descriptor when a field receives an impossible value."""

    def __init__(self, field, message):
        self.field = field
        super().__init__(message)


class FieldTypeError(BusBidderError, TypeError):
    """Raised by a descriptor when a field receives a value of the wrong type."""

    def __init__(self, field, message):
        self.field = field
        super().__init__(message)


class InvalidRecordError(BusBidderError, ValueError):
    """Raised when one CSV record cannot be accepted."""

    def __init__(self, reason, field=None, filename=None, row_number=None):
        self.reason = reason
        self.field = field
        self.filename = filename
        self.row_number = row_number
        super().__init__(self.describe())

    def describe(self):
        location = f"{self.filename or '?'} row {self.row_number or '?'}"
        field = f" [{self.field}]" if self.field else ""
        return f"{location}{field}: {self.reason}"


class InvalidIdentifierError(InvalidRecordError):
    """Raised when an identifier does not follow its required format."""


class ConfigurationError(BusBidderError, ValueError):
    """Raised for invalid traveller profiles, weights or requests."""


class UnknownCriterionError(ConfigurationError):
    """Raised when a weight refers to a criterion that is not registered."""


class BookingError(BusBidderError):
    """Base class for booking failures."""


class SeatsUnavailableError(BookingError):
    """Raised when an offer no longer has enough seats."""


class UnknownOfferError(BookingError):
    """Raised when a booking refers to an offer that does not exist."""


class UnknownBookingError(BookingError):
    """Raised when a booking reference cannot be found."""
