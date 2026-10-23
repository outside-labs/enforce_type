"""Execute compiled plans without annotation introspection or shared call state."""

import math
from dataclasses import dataclass, field
from uuid import UUID

from ._nodes import Limits, _Node
from .constraints import Length, Max, Min
from .errors import Issue, SchemaError, ValidationError

_INVALID = object()


@dataclass(slots=True)
class _Context:
    limits: Limits
    issues: list[Issue] = field(default_factory=list)

    @property
    def full(self) -> bool:
        return len(self.issues) >= self.limits.max_errors

    def fail(self, path: tuple, code: str, expected: str):
        if not self.full:
            self.issues.append(Issue(path, code, expected))
        return _INVALID


def _unicode(value: str) -> bool:
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _load_fields(node, value, mode, context, path=(), depth=0, *, partial=False):
    if type(value) is not dict:
        return context.fail(path, "type", node.label)
    if len(value) > context.limits.max_items:
        return context.fail(path, "collection_size", node.label)
    if any(type(key) is not str for key in value):
        return context.fail(path, "unknown_field", node.label)
    before = len(context.issues)
    result = {}
    for field in node.fields:
        if context.full:
            break
        name = field.info.name
        if name in value:
            if not field.info.init:
                context.fail((*path, name), "init_field", field.node.label)
            else:
                result[name] = _visit(field.node, value[name], "load", mode, context, (*path, name), depth + 1)
        elif field.info.required and not partial:
            context.fail((*path, name), "missing", field.node.label)
    for key in value:
        if context.full:
            break
        if key not in node.field_names:
            context.fail(path, "unknown_field", node.label)
    return _INVALID if len(context.issues) != before or context.full else result


def _visit(node: _Node, value, operation: str, mode: str, context: _Context, path=(), depth=0):
    if context.full:
        return _INVALID
    if depth > context.limits.max_depth:
        return context.fail(path, "depth", node.label)
    kind = node.kind
    if kind == "constrained":
        child = node.children[0]
        expected = {"list": list, "dict": dict, "tuple": tuple, "variadic_tuple": tuple}.get(child.kind)
        if child.kind in ("tuple", "variadic_tuple") and operation == "load" and mode == "json":
            expected = list
        if child.kind == "scalar" and child.annotation is str:
            expected = str
        # Reject invalid collection lengths before constructing their elements.
        if expected is not None and type(value) is expected:
            if child.kind != "scalar" and len(value) > context.limits.max_items:
                return context.fail(path, "collection_size", node.label)
            before = len(context.issues)
            for rule in node.rules:
                if type(rule) is Length:
                    if len(value) < rule.min:
                        context.fail(path, "min_length", node.label)
                    elif rule.max is not None and len(value) > rule.max:
                        context.fail(path, "max_length", node.label)
            if len(context.issues) != before:
                return _INVALID
        before = len(context.issues)
        result = _visit(child, value, operation, mode, context, path, depth)
        if len(context.issues) != before or result is _INVALID:
            return _INVALID
        candidate = result if operation == "load" else value
        for rule in node.rules:
            if type(rule) is Min and candidate < rule.value:
                context.fail(path, "min", node.label)
            elif type(rule) is Max and candidate > rule.value:
                context.fail(path, "max", node.label)
        return result
    if kind == "scalar":
        if node.annotation is float:
            if operation == "load" and mode == "json" and type(value) in (int, float):
                try:
                    number = float(value)
                except OverflowError:
                    return context.fail(path, "finite", node.label)
            elif type(value) is float:
                number = value
            else:
                return context.fail(path, "type", node.label)
            if not math.isfinite(number):
                return context.fail(path, "finite", node.label)
            return number
        if type(value) is not node.annotation:
            return context.fail(path, "type", node.label)
        if node.annotation is str and mode == "json" and not _unicode(value):
            return context.fail(path, "unicode", node.label)
        return value
    if kind == "uuid":
        if operation == "load" and mode == "json":
            if type(value) is not str:
                return context.fail(path, "type", node.label)
            try:
                return UUID(value)
            except ValueError:
                return context.fail(path, "uuid", node.label)
        if not isinstance(value, UUID):
            return context.fail(path, "type", node.label)
        return str(value) if operation == "dump" and mode == "json" else value
    if kind == "enum":
        if operation == "load" and mode == "json":
            for member in node.choices:
                if type(value) is type(member.value) and value == member.value:
                    if type(value) is str and not _unicode(value):
                        return context.fail(path, "unicode", node.label)
                    return member
            return context.fail(path, "enum", node.label)
        if not isinstance(value, node.annotation):
            return context.fail(path, "type", node.label)
        if operation == "dump" and mode == "json":
            if type(value.value) is str and not _unicode(value.value):
                return context.fail(path, "unicode", node.label)
            return value.value
        return value
    if kind == "literal":
        for choice, child in zip(node.choices, node.children):
            attempt = _Context(context.limits)
            candidate = _visit(child, value, operation, mode, attempt, path, depth)
            if attempt.issues:
                continue
            if operation == "load":
                matches = type(candidate) is type(choice) and candidate == choice
            else:
                matches = type(value) is type(choice) and value == choice
            if matches:
                return candidate
        return context.fail(path, "literal", node.label)
    if kind == "union":
        for child in node.children:
            attempt = _Context(context.limits)
            candidate = _visit(child, value, operation, mode, attempt, path, depth)
            if not attempt.issues:
                return candidate
        return context.fail(path, "union", node.label)
    if kind in ("list", "tuple", "variadic_tuple"):
        expected = list if kind == "list" or operation == "load" and mode == "json" else tuple
        if type(value) is not expected:
            return context.fail(path, "type", node.label)
        if len(value) > context.limits.max_items:
            return context.fail(path, "collection_size", node.label)
        if kind == "tuple" and len(value) != len(node.children):
            return context.fail(path, "length", node.label)
        result = [] if operation != "check" else None
        for index, item in enumerate(value):
            if context.full:
                break
            child = node.children[index] if kind == "tuple" else node.children[0]
            converted = _visit(child, item, operation, mode, context, (*path, index), depth + 1)
            if result is not None:
                result.append(converted)
        if operation == "check":
            return value
        return tuple(result) if kind != "list" and (operation == "load" or mode == "python") else result
    if kind == "dict":
        if type(value) is not dict:
            return context.fail(path, "type", node.label)
        if len(value) > context.limits.max_items:
            return context.fail(path, "collection_size", node.label)
        result = {} if operation != "check" else None
        for key, item in value.items():
            if context.full:
                break
            position = (*path, "*")
            if mode == "json" and (type(key) is not str or not _unicode(key)):
                context.fail(position, "json_key", "str")
                continue
            # Key conversion could collapse distinct entries. Always check native
            # keys, even when values use JSON representations.
            checked_key = _visit(node.children[0], key, "check", "python", context, position, depth + 1)
            converted = _visit(node.children[1], item, operation, mode, context, position, depth + 1)
            if result is not None and checked_key is not _INVALID and converted is not _INVALID:
                result[key] = converted
        return value if operation == "check" else result
    if kind == "dataclass":
        if len(node.fields) > context.limits.max_items:
            return context.fail(path, "collection_size", node.label)
        if operation == "load" and type(value) is dict:
            kwargs = _load_fields(node, value, mode, context, path, depth)
            if kwargs is _INVALID:
                return _INVALID
            try:
                constructed = node.annotation(**kwargs)
            except Exception:
                return context.fail(path, "construction", node.label)
            _visit(node, constructed, "check", "python", context, path, depth)
            return constructed
        if operation == "load":
            if mode == "python" and isinstance(value, node.annotation):
                return _visit(node, value, "check", "python", context, path, depth)
            return context.fail(path, "type", node.label)
        if not isinstance(value, node.annotation):
            return context.fail(path, "type", node.label)
        result = {} if operation == "dump" else None
        for field in node.fields:
            if context.full:
                break
            name = field.info.name
            try:
                item = getattr(value, name)
            except Exception:
                context.fail((*path, name), "attribute", field.node.label)
                continue
            converted = _visit(field.node, item, operation, mode, context, (*path, name), depth + 1)
            if result is not None:
                result[name] = converted
        return value if operation == "check" else result
    raise SchemaError("Unsupported compiled node.")


def execute(node: _Node, value, operation: str, mode: str, limits: Limits):
    if mode not in ("json", "python"):
        raise SchemaError("mode must be 'json' or 'python'.")
    context = _Context(limits)
    result = _visit(node, value, operation, mode, context)
    if context.issues:
        raise ValidationError(*context.issues) from None
    return value if operation == "check" else result


def execute_partial(node: _Node, value, mode: str, limits: Limits):
    if node.kind != "dataclass":
        raise SchemaError("load_partial requires a dataclass plan.")
    if mode not in ("json", "python"):
        raise SchemaError("mode must be 'json' or 'python'.")
    context = _Context(limits)
    result = _load_fields(node, value, mode, context, partial=True)
    if context.issues:
        raise ValidationError(*context.issues) from None
    return result
