"""Value-free, structured diagnostics for explicit validation boundaries."""

from dataclasses import dataclass


class SchemaError(TypeError):
    """An annotation or plan configuration is unsupported."""


@dataclass(frozen=True, slots=True)
class Issue:
    path: tuple[str | int, ...]
    code: str
    expected: str

    def as_dict(self) -> dict[str, object]:
        return {"path": list(self.path), "code": self.code, "expected": self.expected}


class ValidationError(ValueError):
    """Issue data omits submitted values and dynamic dictionary keys."""

    def __init__(self, *issues: Issue):
        self._issues = tuple(issues)
        super().__init__(f"Validation failed ({len(issues)} issue(s)).")

    @property
    def issues(self) -> tuple[Issue, ...]:
        return self._issues
