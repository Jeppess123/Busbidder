"""Descriptor that checks type and range every time a value is set."""

from .exceptions import FieldTypeError, FieldValueError


class RangeValidated:
    """Numeric attribute that must be of a given type and within a range."""

    def __init__(self, min_value=None, max_value=None, types=(int, float), allow_none=False):
        self.min_value = min_value
        self.max_value = max_value
        self.types = types
        self.allow_none = allow_none


    def __repr__(self):
        return f"RangeValidated(min={self.min_value}, max={self.max_value})"

    def __set_name__(self, owner, name):
        # called once when the class is created
        self.public_name = name
        self.private_name = "_" + name

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return getattr(instance, self.private_name)

    def __set__(self, instance, value):
        setattr(instance, self.private_name, self.validate(value))

    def validate(self, value):
        name = self.public_name
        if value is None:
            if self.allow_none:
                return None
            raise FieldValueError(name, f"{name} is required")
        # bool counts as int in Python, so check it first
        if isinstance(value, bool) or not isinstance(value, self.types):
            expected = " or ".join(t.__name__ for t in self.types)
            raise FieldTypeError(name, f"{name} must be {expected}, got {type(value).__name__}")
        if self.min_value is not None and value < self.min_value:
            raise FieldValueError(name, f"{name} must be at least {self.min_value}, got {value}")
        if self.max_value is not None and value > self.max_value:
            raise FieldValueError(name, f"{name} must be at most {self.max_value}, got {value}")
        return value
