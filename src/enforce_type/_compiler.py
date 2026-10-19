"""Trusted annotation resolution, performed only during compilation."""

import math
import types
from enum import Enum
from typing import Literal, Union, get_args, get_origin
from uuid import UUID

from ._nodes import Limits, _Node
from .errors import SchemaError
from .plans import TypePlan

_PRIMITIVES = {str: "str", bool: "bool", int: "int", float: "float", type(None): "None"}
_MAX_SCHEMA_DEPTH = 64


class _Compiler:
    def __init__(self):
        self.memo: dict[object, _Node] = {}

    def compile(self, annotation, active=frozenset(), depth=0):
        if annotation is None:
            annotation = type(None)
        try:
            hash(annotation)
        except TypeError:
            raise SchemaError("Annotations must be supported hashable type expressions.") from None
        if depth > _MAX_SCHEMA_DEPTH:
            raise SchemaError("Schema nesting exceeds the compilation limit.")
        if annotation in active:
            raise SchemaError("Recursive type graphs are not supported.")
        if annotation in self.memo:
            return self.memo[annotation]
        active = active | {annotation}
        node = self._node(annotation, active, depth)
        self.memo[annotation] = node
        return node

    def _node(self, annotation, active, depth):
        if annotation in _PRIMITIVES:
            return _Node("scalar", annotation, _PRIMITIVES[annotation])
        if annotation is UUID:
            return _Node("uuid", annotation, "UUID")
        origin, args = get_origin(annotation), get_args(annotation)
        if origin in (Union, types.UnionType):
            return _Node("union", annotation, "union", tuple(self.compile(a, active, depth + 1) for a in args))
        if origin is Literal and args:
            if not all(type(choice) in (str, int, bool, type(None)) or isinstance(choice, Enum) for choice in args):
                raise SchemaError("Unsupported literal choice type.")
            children = tuple(self.compile(type(choice), active, depth + 1) for choice in args)
            return _Node("literal", annotation, "literal choice", children, args)
        if isinstance(annotation, type) and issubclass(annotation, Enum):
            members = tuple(annotation)
            if not members or not all(type(m.value) in _PRIMITIVES and
                                      (type(m.value) is not float or math.isfinite(m.value)) for m in members):
                raise SchemaError("Enums require finite primitive values.")
            return _Node("enum", annotation, annotation.__name__, choices=members)
        raise SchemaError("Unsupported annotation; no implicit Any fallback is available.")


def compile_type[T](annotation: type[T], *, limits: Limits | None = None) -> TypePlan[T]:
    """Compile a trusted Python annotation into an independent immutable plan."""
    if limits is None:
        limits = Limits()
    if type(limits) is not Limits:
        raise SchemaError("limits must be a Limits instance.")
    return TypePlan(_Compiler().compile(annotation), limits)
