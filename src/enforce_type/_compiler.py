"""Trusted annotation resolution, performed only during compilation."""

import inspect
import math
import types
from dataclasses import MISSING, fields, is_dataclass, replace
from enum import Enum
from typing import Literal, Union, get_args, get_origin, get_type_hints
from uuid import UUID

from ._nodes import FieldInfo, Limits, _FieldNode, _Node
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
            cached = self.memo[annotation]
            if depth + cached.height > _MAX_SCHEMA_DEPTH:
                raise SchemaError("Schema nesting exceeds the compilation limit.")
            return cached
        active = active | {annotation}
        node = self._node(annotation, active, depth)
        heights = [child.height + 1 for child in node.children]
        heights.extend(field.node.height + 1 for field in node.fields)
        height = max(heights, default=0)
        if depth + height > _MAX_SCHEMA_DEPTH:
            raise SchemaError("Schema nesting exceeds the compilation limit.")
        node = replace(node, height=height)
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
        if origin is list and len(args) == 1:
            return _Node("list", annotation, "list", (self.compile(args[0], active, depth + 1),))
        if origin is tuple and args:
            if len(args) == 2 and args[1] is Ellipsis:
                return _Node("variadic_tuple", annotation, "tuple", (self.compile(args[0], active, depth + 1),))
            if Ellipsis not in args:
                return _Node("tuple", annotation, "tuple", tuple(self.compile(a, active, depth + 1) for a in args))
        if origin is dict and len(args) == 2:
            key = self.compile(args[0], active, depth + 1)
            if not self._key_type(key):
                raise SchemaError("Dictionary keys require supported scalar annotations.")
            return _Node("dict", annotation, "dict", (key, self.compile(args[1], active, depth + 1)))
        if isinstance(annotation, type) and is_dataclass(annotation):
            if not annotation.__dataclass_params__.init:
                raise SchemaError("Dataclasses require an initializable constructor.")
            try:
                hints = get_type_hints(annotation, include_extras=True)
                signature = inspect.signature(annotation)
            except Exception:
                raise SchemaError("Dataclass annotations and constructor must be resolvable.") from None
            compiled = []
            for item in fields(annotation):
                if "enforce_type" in item.metadata:
                    raise SchemaError("enforce_type field metadata is not supported in this release.")
                required = item.init and item.default is MISSING and item.default_factory is MISSING
                info = FieldInfo(item.name, hints[item.name], required, item.init, item.default_factory is not MISSING)
                compiled.append(_FieldNode(info, self.compile(hints[item.name], active, depth + 1)))
            initializable = {field.info.name for field in compiled if field.info.init}
            if set(signature.parameters) != initializable or any(
                p.kind not in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY) for p in signature.parameters.values()
            ):
                raise SchemaError("InitVars and incompatible constructor signatures are unsupported.")
            return _Node("dataclass", annotation, annotation.__name__, fields=tuple(compiled),
                         field_names=frozenset(field.info.name for field in compiled))
        raise SchemaError("Unsupported annotation; no implicit Any fallback is available.")

    @staticmethod
    def _key_type(node):
        if node.kind in ("scalar", "uuid", "enum", "literal"):
            return True
        return node.kind == "union" and all(_Compiler._key_type(child) for child in node.children)


def compile_type[T](annotation: type[T], *, limits: Limits | None = None) -> TypePlan[T]:
    """Compile a trusted Python annotation into an independent immutable plan."""
    if limits is None:
        limits = Limits()
    if type(limits) is not Limits:
        raise SchemaError("limits must be a Limits instance.")
    return TypePlan(_Compiler().compile(annotation), limits)
