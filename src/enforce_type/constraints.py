"""Immutable rules for Annotated types and dataclass field metadata."""

import math
from dataclasses import dataclass

from .errors import SchemaError


def _numeric_bound(value):
    if type(value) not in (int, float) or type(value) is float and not math.isfinite(value):
        raise SchemaError("Numeric bounds require finite int or float values.")


@dataclass(frozen=True, slots=True)
class Min:
    """Inclusive lower bound for an int or float annotation."""

    value: int | float

    def __post_init__(self):
        _numeric_bound(self.value)


@dataclass(frozen=True, slots=True)
class Max:
    """Inclusive upper bound for an int or float annotation."""

    value: int | float

    def __post_init__(self):
        _numeric_bound(self.value)


@dataclass(frozen=True, slots=True)
class Length:
    """Inclusive code-point or collection-entry bounds."""

    min: int = 0
    max: int | None = None

    def __post_init__(self):
        if type(self.min) is not int or self.min < 0 or (
            self.max is not None and (type(self.max) is not int or self.max < self.min)
        ):
            raise SchemaError("Length bounds require nonnegative ordered integers.")
