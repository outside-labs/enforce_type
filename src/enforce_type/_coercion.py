"""The opt-in scalar loading table; native validation stays separate."""

import re

_INTEGER = re.compile(r"[+-]?[0-9]+")
_FLOAT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def convert(annotation, value):
    """Convert only exact supported input types; never invoke user callbacks."""
    if annotation is int and type(value) is str:
        if not _INTEGER.fullmatch(value):
            raise ValueError
        return int(value)
    if annotation is float:
        if type(value) is int:
            return float(value)
        if type(value) is str:
            if not _FLOAT.fullmatch(value):
                raise ValueError
            return float(value)
    if annotation is bool and type(value) is str:
        if value == "true":
            return True
        if value == "false":
            return False
        raise ValueError
    return value
