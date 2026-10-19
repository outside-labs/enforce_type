import unittest
from dataclasses import InitVar, dataclass, field
from enum import Enum
from typing import Annotated, ClassVar
from uuid import UUID, uuid4

from enforce_type import Limits, SchemaError, ValidationError, compile_type


class Color(Enum):
    RED = "red"


@dataclass(frozen=True, slots=True)
class Address:
    city: str
    coordinates: tuple[float, float] = (0.0, 0.0)


@dataclass(kw_only=True)
class User:
    name: str
    address: Address
    id: UUID = field(default_factory=uuid4)
    tags: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    color: Color = Color.RED
    category: ClassVar[str] = "person"

    @property
    def display(self):
        return self.name


class ModelTests(unittest.TestCase):
    def test_nested_model_round_trip(self):
        schema = compile_type(User)
        data = {"name": "Ella", "address": {"city": "Paris", "coordinates": [1, 2.5]},
                "tags": ["a"], "counts": {"one": 1}, "color": "red"}
        user = schema.load(data)
        self.assertIsInstance(user.id, UUID)
        self.assertEqual(user.address.coordinates, (1.0, 2.5))
        self.assertIs(schema.check(user), user)
        dumped = schema.dump(user)
        self.assertEqual(dumped["address"], {"city": "Paris", "coordinates": [1.0, 2.5]})
        self.assertEqual(schema.load(dumped), user)
        self.assertNotIn("category", dumped)
        self.assertNotIn("display", dumped)
        native = schema.dump(user, mode="python")
        self.assertIs(native["id"], user.id)
        self.assertIs(native["color"], Color.RED)
        self.assertIsInstance(native["address"]["coordinates"], tuple)

    def test_existing_python_models_and_subclasses(self):
        @dataclass(frozen=True)
        class Child(Address):
            pass
        schema = compile_type(Address)
        value = Address("Paris")
        self.assertIs(schema.load(value, mode="python"), value)
        with self.assertRaises(ValidationError):
            schema.load(value)
        self.assertEqual(schema.dump(Child("Lyon")), {"city": "Lyon", "coordinates": [0.0, 0.0]})

    def test_defaults_are_validated_and_factories_are_per_load(self):
        schema = compile_type(User)
        data = {"name": "Ella", "address": {"city": "Paris"}}
        first, second = schema.load(data), schema.load(data)
        self.assertNotEqual(first.id, second.id)
        self.assertIsNot(first.tags, second.tags)
        @dataclass
        class Bad:
            count: int = True
        with self.assertRaises(ValidationError):
            compile_type(Bad).load({})

    def test_post_init_and_constructor_failure_are_checked(self):
        @dataclass
        class Bad:
            count: int
            def __post_init__(self):
                self.count = "wrong"
        with self.assertRaises(ValidationError):
            compile_type(Bad).load({"count": 2})
        @dataclass
        class Throws:
            count: int
            def __post_init__(self):
                raise RuntimeError("private-credential")
        with self.assertRaises(ValidationError) as caught:
            compile_type(Throws).load({"count": 1})
        self.assertEqual(caught.exception.issues[0].code, "construction")
        self.assertNotIn("private-credential", str(caught.exception) + repr(caught.exception.issues))

    def test_bad_supplied_fields_do_not_construct_model(self):
        calls = []
        @dataclass
        class Record:
            count: int
            def __post_init__(self):
                calls.append(self.count)
        with self.assertRaises(ValidationError):
            compile_type(Record).load({"count": "bad"})
        self.assertEqual(calls, [])

    def test_unknown_and_missing_fields_have_no_dynamic_keys(self):
        with self.assertRaises(ValidationError) as caught:
            compile_type(Address).load({"secret-key": "secret-value"})
        self.assertEqual([i.code for i in caught.exception.issues], ["missing", "unknown_field"])
        self.assertNotIn("secret", str(caught.exception) + repr(caught.exception.issues))

    def test_readonly_field_introspection_metadata(self):
        schema = compile_type(User)
        info = {field.name: field for field in schema.fields}
        self.assertEqual(set(info), {"name", "address", "id", "tags", "counts", "color"})
        self.assertTrue(info["name"].required)
        self.assertFalse(info["id"].required)
        self.assertTrue(info["id"].has_default_factory)
        with self.assertRaises((AttributeError, TypeError)):
            info["name"].name = "changed"

    def test_recursive_and_unsupported_models_fail_compilation(self):
        @dataclass
        class Recursive:
            child: object = None
        Recursive.__annotations__["child"] = Recursive | None
        @dataclass
        class WithInitVar:
            name: str
            extra: InitVar[int] = 1
        @dataclass
        class Constrained:
            value: Annotated[int, "constraint"]
        @dataclass
        class Metadata:
            value: int = field(metadata={"enforce_type": {"min": 0}})
        for model in (Recursive, WithInitVar, Constrained, Metadata, Address("x")):
            with self.subTest(model=model), self.assertRaises(SchemaError):
                compile_type(model)


class CollectionTests(unittest.TestCase):
    def test_lists_and_tuples_in_each_mode(self):
        cases = [(list[int], [1, 2], [1, 2]), (tuple[int, str], [1, "x"], (1, "x")),
                 (tuple[int, ...], [1, 2], (1, 2))]
        for annotation, data, native in cases:
            with self.subTest(annotation=annotation):
                schema = compile_type(annotation)
                self.assertEqual(schema.load(data), native)
                self.assertIs(schema.check(native), native)
                self.assertEqual(schema.dump(native), data)
                self.assertEqual(schema.dump(native, mode="python"), native)
                self.assertEqual(schema.load(native, mode="python"), native)
        for data in ([1], [1, "x", 3]):
            with self.assertRaises(ValidationError):
                compile_type(tuple[int, str]).load(data)
        with self.assertRaises(ValidationError):
            compile_type(tuple[int, ...]).load((1, 2))

    def test_dictionary_keys_are_not_converted_or_leaked(self):
        schema = compile_type(dict[int, str])
        self.assertEqual(schema.load({1: "one"}, mode="python"), {1: "one"})
        for call in (lambda: schema.load({"1": "one"}), lambda: schema.dump({1: "one"})):
            with self.assertRaises(ValidationError):
                call()
        with self.assertRaises(ValidationError) as caught:
            compile_type(dict[str, int]).load({"private-key": "private-value"})
        self.assertEqual(caught.exception.issues[0].path, ("*",))
        self.assertNotIn("private", repr(caught.exception.issues))
        with self.assertRaises(SchemaError):
            compile_type(dict[list[int], str])

    def test_load_and_dump_containers_do_not_alias_inputs(self):
        schema = compile_type(list[dict[str, list[int]]])
        original = [{"items": [1, 2]}]
        loaded = schema.load(original)
        loaded[0]["items"].append(3)
        self.assertEqual(original, [{"items": [1, 2]}])
        dumped = schema.dump(original)
        dumped[0]["items"].append(4)
        self.assertEqual(original, [{"items": [1, 2]}])

    def test_limits_bound_containers_depth_and_errors(self):
        schema = compile_type(list[int], limits=Limits(max_items=2))
        with self.assertRaises(ValidationError) as caught:
            schema.load([1, 2, "secret"])
        self.assertEqual([i.code for i in caught.exception.issues], ["collection_size"])
        schema = compile_type(list[list[int]], limits=Limits(max_depth=1))
        with self.assertRaises(ValidationError) as caught:
            schema.load([[1]])
        self.assertEqual(caught.exception.issues[0].code, "depth")
        schema = compile_type(list[int], limits=Limits(max_errors=2))
        with self.assertRaises(ValidationError) as caught:
            schema.load(["a", "b", "c"])
        self.assertEqual([i.path for i in caught.exception.issues], [(0,), (1,)])


if __name__ == "__main__":
    unittest.main()
