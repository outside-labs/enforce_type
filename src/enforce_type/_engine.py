"""Execute compiled plans without annotation introspection or shared call state."""

import math
from dataclasses import dataclass, field
from uuid import UUID

from ._nodes import Limits, _Node
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


def _visit(node: _Node, value, operation: str, mode: str, context: _Context, path=(), depth=0):
    if context.full:
        return _INVALID
    if depth > context.limits.max_depth:
        return context.fail(path, "depth", node.label)
    kind = node.kind
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
    raise SchemaError("Unsupported compiled node.")


def execute(node: _Node, value, operation: str, mode: str, limits: Limits):
    if mode not in ("json", "python"):
        raise SchemaError("mode must be 'json' or 'python'.")
    context = _Context(limits)
    result = _visit(node, value, operation, mode, context)
    if context.issues:
        raise ValidationError(*context.issues) from None
    return value if operation == "check" else result
