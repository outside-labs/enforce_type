"""Public immutable validation plans."""

from dataclasses import dataclass
from typing import cast

from ._engine import execute, execute_partial
from ._nodes import FieldInfo, Limits, _Node


@dataclass(frozen=True, slots=True)
class TypePlan[T]:
    """Compile once, then reuse check/load/dump across independent callers."""

    _root: _Node
    limits: Limits
    coerce: bool = False

    @property
    def annotation(self) -> object:
        return self._root.annotation

    @property
    def fields(self) -> tuple[FieldInfo, ...]:
        return tuple(field.info for field in self._root.fields)

    def check(self, value: object) -> T:
        """Validate native Python values and return the original object."""
        return cast(T, execute(self._root, value, "check", "python", self.limits))

    def load(self, data: object, *, mode: str = "json") -> T:
        """Construct from decoded JSON-shaped data or explicit native input."""
        return cast(T, execute(self._root, data, "load", mode, self.limits, coerce=self.coerce))

    def dump(self, value: T, *, mode: str = "json") -> object:
        """Validate and serialize a native value into JSON or Python data."""
        return execute(self._root, value, "dump", mode, self.limits)

    def load_partial(self, data: object, *, mode: str = "json") -> dict[str, object]:
        """Load supplied dataclass fields without constructing the root model."""
        return execute_partial(self._root, data, mode, self.limits, coerce=self.coerce)
