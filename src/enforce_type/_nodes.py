"""Immutable compiled representation. Mutable traversal state lives elsewhere."""

from dataclasses import dataclass

from .constraints import Length, Max, Min
from .errors import SchemaError


@dataclass(frozen=True, slots=True)
class Limits:
    max_depth: int = 32
    max_items: int = 1000
    max_errors: int = 20

    def __post_init__(self):
        for value, minimum in ((self.max_depth, 0), (self.max_items, 0), (self.max_errors, 1)):
            if type(value) is not int or value < minimum:
                raise SchemaError("Limits require nonnegative depth/items and a positive error count.")


@dataclass(frozen=True, slots=True)
class FieldInfo:
    name: str
    annotation: object
    required: bool
    init: bool
    has_default_factory: bool


@dataclass(frozen=True, slots=True)
class _Node:
    kind: str
    annotation: object
    label: str
    children: tuple[_Node, ...] = ()
    choices: tuple[object, ...] = ()
    fields: tuple[_FieldNode, ...] = ()
    field_names: frozenset[str] = frozenset()
    height: int = 0
    rules: tuple[Min | Max | Length, ...] = ()


@dataclass(frozen=True, slots=True)
class _FieldNode:
    info: FieldInfo
    node: _Node
