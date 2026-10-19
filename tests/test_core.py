import unittest
from dataclasses import FrozenInstanceError
from enum import Enum, IntEnum
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from enforce_type import Limits, SchemaError, ValidationError, compile_type


class Color(Enum):
    RED = "red"
    BLUE = "blue"


class Number(IntEnum):
    ONE = 1


class CoreTests(unittest.TestCase):
    def test_primitives_are_strict_and_check_preserves_identity(self):
        for annotation, value in ((str, "hello"), (bool, False), (int, 12), (float, 1.5), (type(None), None)):
            schema = compile_type(annotation)
            self.assertIs(schema.check(value), value)
            self.assertEqual(schema.load(value), value)
            self.assertEqual(schema.dump(value), value)
        for annotation, value in ((int, True), (int, "12"), (bool, 1), (str, 12), (float, "1.5"), (type(None), "null")):
            for method in ("check", "load", "dump"):
                with self.subTest(annotation=annotation, value=value, method=method), self.assertRaises(ValidationError):
                    getattr(compile_type(annotation), method)(value)

    def test_float_modes_and_nonfinite_values(self):
        schema = compile_type(float)
        self.assertIs(type(schema.load(2)), float)
        self.assertEqual(schema.load(2), 2.0)
        for call in (lambda: schema.check(2), lambda: schema.load(2, mode="python"), lambda: schema.dump(2)):
            with self.assertRaises(ValidationError):
                call()
        for value in (float("nan"), float("inf"), -float("inf"), 10**1000):
            with self.assertRaises(ValidationError):
                schema.load(value)

    def test_uuid_modes(self):
        value = uuid4()
        schema = compile_type(UUID)
        self.assertEqual(schema.load(str(value)), value)
        self.assertIs(schema.check(value), value)
        self.assertIs(schema.load(value, mode="python"), value)
        self.assertEqual(schema.dump(value), str(value))
        self.assertIs(schema.dump(value, mode="python"), value)
        for call in (lambda: schema.load(value), lambda: schema.check(str(value)),
                     lambda: schema.load(str(value), mode="python"), lambda: schema.load("bad")):
            with self.assertRaises(ValidationError):
                call()

    def test_enum_and_enum_literals(self):
        schema = compile_type(Color)
        self.assertIs(schema.load("red"), Color.RED)
        self.assertIs(schema.check(Color.BLUE), Color.BLUE)
        self.assertEqual(schema.dump(Color.BLUE), "blue")
        self.assertIs(schema.dump(Color.RED, mode="python"), Color.RED)
        with self.assertRaises(ValidationError):
            schema.check("red")
        literal = compile_type(Literal[Color.RED])
        self.assertIs(literal.load("red"), Color.RED)
        self.assertEqual(literal.dump(Color.RED), "red")
        with self.assertRaises(ValidationError):
            literal.load("blue")
        for value in (True, "1", Number.ONE):
            with self.assertRaises(ValidationError):
                compile_type(Number).load(value)
        self.assertIs(compile_type(Number).load(1), Number.ONE)

    def test_literals_do_not_confuse_bool_and_int(self):
        self.assertEqual(compile_type(Literal[1]).load(1), 1)
        with self.assertRaises(ValidationError):
            compile_type(Literal[1]).load(True)
        with self.assertRaises(ValidationError):
            compile_type(Literal[False]).load(0)
        self.assertIsNone(compile_type(Literal[None]).load(None))

    def test_union_branch_failures_are_one_deterministic_issue(self):
        schema = compile_type(int | UUID | None)
        self.assertEqual(schema.load(2), 2)
        self.assertIsNone(schema.load(None))
        identity = uuid4()
        self.assertEqual(schema.load(str(identity)), identity)
        with self.assertRaises(ValidationError) as caught:
            schema.load("private-secret")
        self.assertEqual([(i.path, i.code, i.expected) for i in caught.exception.issues], [((), "union", "union")])
        self.assertNotIn("private-secret", repr(caught.exception))

    def test_python_and_json_unicode_are_distinct(self):
        schema = compile_type(str)
        self.assertEqual(schema.check("\ud800"), "\ud800")
        self.assertEqual(schema.load("\ud800", mode="python"), "\ud800")
        for method in ("load", "dump"):
            with self.assertRaises(ValidationError):
                getattr(schema, method)("\ud800")

    def test_immutable_limits_and_plans(self):
        schema = compile_type(int, limits=Limits(max_errors=1))
        for value, name, replacement in ((schema, "limits", Limits()), (schema.limits, "max_errors", 10),
                                          (schema._root, "label", "changed")):
            with self.assertRaises((FrozenInstanceError, AttributeError)):
                setattr(value, name, replacement)
        self.assertEqual(schema.fields, ())

    def test_invalid_schema_configuration_fails_at_compilation(self):
        for annotation in (Any, object, list, dict, set[int], Annotated[int, "rule"], Literal[1.5]):
            with self.subTest(annotation=annotation), self.assertRaises(SchemaError):
                compile_type(annotation)
        for kwargs in ({"max_errors": 0}, {"max_items": -1}, {"max_depth": True}):
            with self.assertRaises(SchemaError):
                Limits(**kwargs)
        with self.assertRaises(SchemaError):
            compile_type(int, limits={})
        with self.assertRaises(SchemaError):
            compile_type(int).load(1, mode="unknown")

    def test_errors_are_value_free_and_issue_dictionaries_are_detached(self):
        with self.assertRaises(ValidationError) as caught:
            compile_type(int).load("secret-token")
        error = caught.exception
        detail = error.issues[0].as_dict()
        detail["path"].append("changed")
        self.assertEqual(error.issues[0].path, ())
        self.assertNotIn("secret-token", str(error) + repr(error.issues))


if __name__ == "__main__":
    unittest.main()
