"""Public leaf operations for the optional resource adapter; no HTTP policy."""

from uuid import UUID

from enforce_type import compile_type


def demo():
    number = compile_type(float)
    identity = compile_type(UUID)
    native = identity.load("00000000-0000-0000-0000-000000000001")
    return {"number": number.dump(number.load(2)), "identity": identity.dump(native)}


if __name__ == "__main__":
    print(demo())
