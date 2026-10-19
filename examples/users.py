"""Run with `uv run python examples/users.py`."""

import json
from dataclasses import dataclass, replace

from enforce_type import compile_type


@dataclass
class User:
    name: str
    age: int
    active: bool = True


users = compile_type(User)


def demo():
    user = users.load({"name": "Ella", "age": 34})
    assert users.check(user) is user
    changes = users.load_partial({"active": False})
    updated = replace(user, **changes)
    users.check(updated)
    return users.dump(updated)


if __name__ == "__main__":
    print(json.dumps(demo()))
