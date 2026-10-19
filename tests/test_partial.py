import unittest
from dataclasses import dataclass, field, replace
from uuid import UUID, uuid4

from enforce_type import Limits, SchemaError, ValidationError, compile_type


@dataclass
class Details:
    title: str
    content: str = ""


@dataclass
class Record:
    id: UUID
    details: Details
    active: bool = True
    computed: int = field(init=False)

    def __post_init__(self):
        self.computed = len(self.details.title)


class PartialTests(unittest.TestCase):
    def test_partial_values_are_loaded_without_required_fields(self):
        schema = compile_type(Record)
        identity = uuid4()
        self.assertEqual(schema.load_partial({}), {})
        self.assertEqual(schema.load_partial({"active": False}), {"active": False})
        self.assertEqual(schema.load_partial({"id": str(identity)}), {"id": identity})
        self.assertEqual(schema.load_partial({"id": identity}, mode="python"), {"id": identity})
        with self.assertRaises(ValidationError):
            schema.load_partial({"active": 1})

    def test_nested_values_are_complete_replacements(self):
        schema = compile_type(Record)
        patch = schema.load_partial({"details": {"title": "new"}})
        self.assertEqual(patch, {"details": Details("new")})
        with self.assertRaises(ValidationError):
            schema.load_partial({"details": {"content": "not complete"}})
        original = Record(uuid4(), Details("original", "old content"))
        updated = replace(original, **patch)
        self.assertEqual(updated.details, Details("new", ""))
        self.assertEqual(original.details, Details("original", "old content"))

    def test_partial_does_not_call_root_constructor_or_factories(self):
        calls = []
        @dataclass
        class Model:
            name: str
            generated: list[int] = field(default_factory=lambda: calls.append("factory") or [])
            def __post_init__(self):
                calls.append("constructor")
        schema = compile_type(Model)
        self.assertEqual(schema.load_partial({"name": "one"}), {"name": "one"})
        self.assertEqual(schema.load_partial({}), {})
        self.assertEqual(calls, [])
        schema.load({"name": "one"})
        self.assertEqual(calls, ["factory", "constructor"])

    def test_init_false_fields_are_checked_dumped_and_reject_input(self):
        schema = compile_type(Record)
        value = schema.load({"id": str(uuid4()), "details": {"title": "abc"}})
        self.assertEqual(value.computed, 3)
        self.assertEqual(schema.dump(value)["computed"], 3)
        self.assertIs(schema.check(value), value)
        self.assertFalse(next(f for f in schema.fields if f.name == "computed").init)
        for call in (lambda: schema.load_partial({"computed": 99}),
                     lambda: schema.load({"id": str(uuid4()), "details": {"title": "x"}, "computed": 99})):
            with self.assertRaises(ValidationError) as caught:
                call()
            self.assertEqual(caught.exception.issues[0].code, "init_field")
        value.computed = "bad"
        with self.assertRaises(ValidationError):
            schema.dump(value)

    def test_missing_output_attribute_fails_without_exposing_exception(self):
        @dataclass
        class Model:
            name: str
            absent: int = field(init=False)
        with self.assertRaises(ValidationError) as caught:
            compile_type(Model).load({"name": "one"})
        self.assertEqual(caught.exception.issues[0].code, "attribute")

    def test_partial_has_no_identity_or_http_visibility_policy(self):
        @dataclass
        class Model:
            id: str
            secret: str = field(default="", metadata={"expose_api": {"write_only": True}})
        schema = compile_type(Model)
        self.assertEqual(schema.load_partial({"id": "new/id"}), {"id": "new/id"})
        self.assertEqual(schema.dump(schema.load({"id": "old", "secret": "test-fixture"}))["secret"], "test-fixture")

    def test_partial_bounds_and_unknown_keys(self):
        schema = compile_type(Record, limits=Limits(max_items=1))
        self.assertEqual(schema.load_partial({"active": False}), {"active": False})
        with self.assertRaises(ValidationError) as caught:
            schema.load_partial({"active": False, "id": str(uuid4())})
        self.assertEqual(caught.exception.issues[0].code, "collection_size")
        for data in ({"private-key": "private-value"}, {1: "private-value"}, []):
            with self.assertRaises(ValidationError) as caught:
                compile_type(Record).load_partial(data)
            self.assertNotIn("private", str(caught.exception) + repr(caught.exception.issues))
        with self.assertRaises(SchemaError):
            compile_type(int).load_partial({})
        with self.assertRaises(SchemaError):
            compile_type(Record).load_partial({}, mode="unknown")


if __name__ == "__main__":
    unittest.main()
