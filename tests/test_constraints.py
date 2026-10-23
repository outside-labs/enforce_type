import unittest
from dataclasses import FrozenInstanceError, dataclass, field
from typing import Annotated
from unittest.mock import patch

from enforce_type import Length, Limits, Max, Min, SchemaError, ValidationError, compile_type


class ConstraintTests(unittest.TestCase):
    def test_numeric_boundaries_apply_to_every_operation(self):
        for annotation, values, invalid, label in (
            (Annotated[int, Min(0), Max(9)], (0, 4, 9), (-1, 10), "int"),
            (Annotated[float, Min(0.5), Max(9)], (0.5, 4.0, 9.0), (-1.0, 10.0), "float"),
        ):
            schema = compile_type(annotation)
            self.assertIs(schema.annotation, annotation)
            for value in values:
                self.assertIs(schema.check(value), value)
                for mode in ("json", "python"):
                    self.assertEqual(schema.load(value, mode=mode), value)
                    self.assertEqual(schema.dump(value, mode=mode), value)
            for value, code in zip(invalid, ("min", "max")):
                for method in ("check", "load", "dump"):
                    with self.subTest(method=method), self.assertRaises(ValidationError) as caught:
                        getattr(schema, method)(value)
                    self.assertEqual([(i.code, i.expected) for i in caught.exception.issues], [(code, label)])

    def test_float_constraints_follow_json_number_conversion(self):
        schema = compile_type(Annotated[float, Min(1.5), Max(3)])
        self.assertEqual(schema.load(2), 2.0)
        self.assertIs(type(schema.load(2)), float)
        for call in (lambda: schema.load(1), lambda: schema.check(2), lambda: schema.load(2, mode="python"),
                     lambda: schema.dump(2), lambda: schema.load(float("inf"))):
            with self.assertRaises(ValidationError):
                call()

    def test_length_counts_code_points_and_collection_entries(self):
        for annotation, good, short, long in (
            (str, "é🙂", "a", "abcd"),
            (list[int], [1, 2], [1], [1, 2, 3, 4]),
            (tuple[int, ...], (1, 2), (1,), (1, 2, 3, 4)),
            (dict[str, int], {"a": 1, "b": 2}, {"a": 1}, dict.fromkeys("abcd", 1)),
        ):
            schema = compile_type(Annotated[annotation, Length(min=2, max=3)])
            self.assertIs(schema.check(good), good)
            self.assertEqual(schema.load(good, mode="python"), good)
            self.assertEqual(schema.dump(good, mode="python"), good)
            for value, code in ((short, "min_length"), (long, "max_length")):
                for method in ("check", "load", "dump"):
                    with self.assertRaises(ValidationError) as caught:
                        if method == "load":
                            schema.load(value, mode="python")
                        else:
                            getattr(schema, method)(value)
                    self.assertEqual(caught.exception.issues[0].code, code)
        pair = compile_type(Annotated[tuple[int, str], Length(min=2, max=2)])
        self.assertEqual(pair.load([1, "a"]), (1, "a"))
        self.assertEqual(pair.dump((1, "a")), [1, "a"])

    def test_rules_do_not_change_strict_types_or_unicode_validation(self):
        for annotation, value in ((Annotated[int, Min(0)], True), (Annotated[str, Length(min=1)], 12),
                                   (Annotated[list[int], Length(max=2)], (1,))):
            with self.assertRaises(ValidationError) as caught:
                compile_type(annotation).check(value)
            self.assertEqual(caught.exception.issues[0].code, "type")
        schema = compile_type(Annotated[str, Length(min=1)])
        self.assertEqual(schema.check("\ud800"), "\ud800")
        with self.assertRaises(ValidationError) as caught:
            schema.load("\ud800")
        self.assertEqual(caught.exception.issues[0].code, "unicode")

    def test_length_failure_prevents_element_construction(self):
        calls = []
        @dataclass
        class Item:
            count: int
            def __post_init__(self):
                calls.append(self.count)
        schema = compile_type(Annotated[list[Item], Length(max=1)])
        with self.assertRaises(ValidationError) as caught:
            schema.load([{"count": 1}, {"count": 2}])
        self.assertEqual(caught.exception.issues[0].code, "max_length")
        self.assertEqual(calls, [])

    def test_nested_paths_dictionary_keys_and_union_isolation(self):
        schema = compile_type(dict[Annotated[str, Length(min=2)], list[Annotated[int, Min(0)]]])
        with self.assertRaises(ValidationError) as caught:
            schema.load({"x": [-1, -2]})
        self.assertEqual([(i.path, i.code) for i in caught.exception.issues],
                         [(("*",), "min_length"), (("*", 0), "min"), (("*", 1), "min")])
        union = compile_type(Annotated[int, Min(10)] | Annotated[int, Max(0)])
        self.assertEqual(union.load(-1), -1)
        with self.assertRaises(ValidationError) as caught:
            union.load(5)
        self.assertEqual([i.code for i in caught.exception.issues], ["union"])

    def test_dataclass_defaults_factories_and_post_init_obey_constraints(self):
        @dataclass
        class BadDefault:
            count: Annotated[int, Min(0)] = -1
        @dataclass
        class BadFactory:
            values: Annotated[list[int], Length(min=1)] = field(default_factory=list)
        @dataclass
        class BadPostInit:
            count: Annotated[int, Min(0)]
            def __post_init__(self):
                self.count = -1
        for model, data in ((BadDefault, {}), (BadFactory, {}), (BadPostInit, {"count": 1})):
            with self.assertRaises(ValidationError):
                compile_type(model).load(data)

    def test_bounds_and_error_caps_remain_effective(self):
        schema = compile_type(list[Annotated[int, Min(0)]], limits=Limits(max_errors=2))
        with self.assertRaises(ValidationError) as caught:
            schema.load([-1, -2, -3])
        self.assertEqual([i.path for i in caught.exception.issues], [(0,), (1,)])
        schema = compile_type(Annotated[list[int], Length(max=0)], limits=Limits(max_items=0))
        with self.assertRaises(ValidationError) as caught:
            schema.load([1])
        self.assertEqual(caught.exception.issues[0].code, "collection_size")
        schema = compile_type(Annotated[list[Annotated[int, Min(0)]], Length(min=1)], limits=Limits(max_depth=1))
        self.assertEqual(schema.load([1]), [1])
        with self.assertRaises(ValidationError) as caught:
            compile_type(Annotated[list[int], Length()], limits=Limits(max_depth=0)).load([1])
        self.assertEqual(caught.exception.issues[0].code, "depth")

    def test_invalid_rules_and_conflicting_schemas_fail_explicitly(self):
        for factory in (lambda: Min(True), lambda: Max("secret"), lambda: Min(float("nan")),
                        lambda: Max(float("inf")), lambda: Length(min=-1), lambda: Length(max=True),
                        lambda: Length(min=2, max=1), lambda: Length(min=1.5)):
            with self.assertRaises(SchemaError):
                factory()
        for annotation in (Annotated[str, Min(0)], Annotated[bool, Max(1)], Annotated[int, Length()],
                           Annotated[int | None, Min(0)], Annotated[int, "unknown"],
                           Annotated[int, Min(5), Max(2)], Annotated[str, Length(min=3), Length(max=2)],
                           Annotated[tuple[int, str], Length(max=1)], Annotated[int, {"min": 0}]):
            with self.subTest(annotation=annotation), self.assertRaises(SchemaError):
                compile_type(annotation)

    def test_rules_are_immutable_and_runtime_does_not_reintrospect(self):
        rule = Min(0)
        schema = compile_type(Annotated[int, rule])
        with self.assertRaises(FrozenInstanceError):
            rule.value = -1
        with patch("enforce_type._compiler.get_origin", side_effect=AssertionError("introspection")):
            self.assertEqual(schema.load(2), 2)
            self.assertEqual(schema.dump(2), 2)
            self.assertEqual(schema.check(2), 2)
        with self.assertRaises(ValidationError) as caught:
            compile_type(dict[str, Annotated[str, Length(max=1)]]).load({"private-key": "private-value"})
        self.assertEqual(caught.exception.issues[0].path, ("*",))
        self.assertNotIn("private", str(caught.exception) + repr(caught.exception.issues))


if __name__ == "__main__":
    unittest.main()
