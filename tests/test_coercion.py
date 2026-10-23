import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, dataclass, field
from enum import Enum
from typing import Annotated, Literal
from unittest.mock import patch
from uuid import UUID

from enforce_type import Length, Limits, Max, Min, SchemaError, ValidationError, compile_type


class Color(Enum):
    RED = "red"


@dataclass(frozen=True, slots=True)
class Reading:
    count: Annotated[int, Min(0), Max(20)]
    active: bool = False
    samples: list[float] = field(default_factory=list, metadata={"enforce_type": {"max_length": 3}})


class CoercionTests(unittest.TestCase):
    def test_explicit_conversion_table_in_both_modes(self):
        cases = ((int, "42", 42), (int, "+0042", 42), (int, "-0", 0), (int, "-12", -12),
                 (float, "1", 1.0), (float, "-.5", -0.5), (float, "+1.", 1.0),
                 (float, "2e3", 2000.0), (float, "1.25E-2", 0.0125), (float, 2, 2.0),
                 (bool, "true", True), (bool, "false", False))
        for annotation, data, expected in cases:
            for mode in ("json", "python"):
                with self.subTest(annotation=annotation, data=data, mode=mode):
                    result = compile_type(annotation, coerce=True).load(data, mode=mode)
                    self.assertEqual(result, expected)
                    self.assertIs(type(result), annotation)

    def test_default_plans_check_and_dump_remain_strict(self):
        for annotation, data in ((int, "1"), (float, "1.5"), (bool, "true")):
            strict = compile_type(annotation)
            self.assertFalse(strict.coerce)
            enabled = compile_type(annotation, coerce=True)
            for mode in ("json", "python"):
                with self.assertRaises(ValidationError):
                    strict.load(data, mode=mode)
                with self.assertRaises(ValidationError):
                    enabled.dump(data, mode=mode)
            with self.assertRaises(ValidationError):
                enabled.check(data)
        schema = compile_type(float, coerce=True)
        self.assertEqual(schema.load(2, mode="python"), 2.0)
        for call in (lambda: schema.check(2), lambda: schema.dump(2), lambda: schema.dump(2, mode="python")):
            with self.assertRaises(ValidationError):
                call()

    def test_refused_text_forms_are_value_free(self):
        cases = ((int, ("", " 1", "1 ", "1\n", "1_000", "0x10", "1.0", "1e2", "١", "１２", "+", "private-value")),
                 (float, ("", " 1", "1 ", "1\n", "1_000", "0x1p0", "NaN", "inf", ".", "1e", "١.٥")),
                 (bool, ("", "True", "FALSE", "1", "0", "yes", " true", "false\n")))
        for annotation, values in cases:
            for value in values:
                for mode in ("json", "python"):
                    with self.subTest(annotation=annotation, value=value), self.assertRaises(ValidationError) as caught:
                        compile_type(annotation, coerce=True).load(value, mode=mode)
                    self.assertEqual(caught.exception.issues[0].code, "coercion")
                    self.assertNotIn("private", str(caught.exception) + repr(caught.exception.issues))

    def test_numeric_boolean_and_string_interchanges_are_not_added(self):
        for annotation, values in ((int, (True, False, 1.0, None)), (float, (True, False, None)),
                                   (bool, (0, 1, 1.0, None)), (str, (0, 1.0, True, None))):
            for value in values:
                with self.subTest(annotation=annotation, value=value), self.assertRaises(ValidationError) as caught:
                    compile_type(annotation, coerce=True).load(value)
                self.assertEqual(caught.exception.issues[0].code, "type")

    def test_finite_float_validation_follows_conversion(self):
        schema = compile_type(float, coerce=True)
        for value in ("1e400", "-1e400", 10**1000, float("nan"), float("inf")):
            for mode in ("json", "python"):
                with self.assertRaises(ValidationError) as caught:
                    schema.load(value, mode=mode)
                self.assertEqual(caught.exception.issues[0].code, "finite")

    def test_only_exact_input_types_are_converted_without_callbacks(self):
        class Trap:
            def __int__(self):
                raise AssertionError("int callback")
            def __float__(self):
                raise AssertionError("float callback")
            def __bool__(self):
                raise AssertionError("bool callback")
            def __str__(self):
                raise AssertionError("str callback")
        class Text(str):
            def __int__(self):
                raise AssertionError("subclass callback")
        class Number(int):
            def __float__(self):
                raise AssertionError("subclass callback")
        for annotation in (int, float, bool, str):
            with self.assertRaises(ValidationError):
                compile_type(annotation, coerce=True).load(Trap())
        for annotation, value in ((int, Text("1")), (float, Number(1))):
            with self.assertRaises(ValidationError):
                compile_type(annotation, coerce=True).load(value)

    def test_constraints_apply_after_conversion_and_partial_roots_are_not_built(self):
        calls = []
        @dataclass
        class Model:
            count: Annotated[int, Max(10)] = field(metadata={"enforce_type": {"min": 2}})
            def __post_init__(self):
                calls.append(self.count)
        schema = compile_type(Model, coerce=True)
        self.assertEqual(schema.load_partial({"count": "3"}), {"count": 3})
        self.assertEqual(calls, [])
        self.assertEqual(schema.load({"count": "3"}), Model(3))
        calls.clear()
        for data, code in (("1", "min"), ("11", "max"), ("private-value", "coercion")):
            for method in ("load", "load_partial"):
                with self.assertRaises(ValidationError) as caught:
                    getattr(schema, method)({"count": data})
                self.assertEqual([(i.path, i.code) for i in caught.exception.issues], [(("count",), code)])
        self.assertEqual(calls, [])

    def test_defaults_post_init_and_existing_models_are_checked_without_coercion(self):
        @dataclass
        class BadDefault:
            count: int = "1"
        @dataclass
        class BadFactory:
            values: list[int] = field(default_factory=lambda: ["1"])
        @dataclass
        class BadPostInit:
            count: int
            def __post_init__(self):
                self.count = "1"
        for model, data in ((BadDefault, {}), (BadFactory, {}), (BadPostInit, {"count": "1"})):
            with self.assertRaises(ValidationError) as caught:
                compile_type(model, coerce=True).load(data)
            self.assertEqual(caught.exception.issues[0].code, "type")
        with self.assertRaises(ValidationError):
            compile_type(Reading, coerce=True).load(Reading("1"), mode="python")
        value = Reading(1)
        self.assertIs(compile_type(Reading, coerce=True).load(value, mode="python"), value)

    def test_nested_values_convert_without_changing_input_or_dictionary_keys(self):
        schema = compile_type(dict[Annotated[str, Length(min=1)], list[int]], coerce=True)
        data = {"values": ["1", "2"]}
        self.assertEqual(schema.load(data), {"values": [1, 2]})
        self.assertEqual(data, {"values": ["1", "2"]})
        for mode in ("json", "python"):
            with self.assertRaises(ValidationError) as caught:
                compile_type(dict[int, int], coerce=True).load({"1": "2"}, mode=mode)
            self.assertEqual(caught.exception.issues[0].path, ("*",))
        self.assertEqual(compile_type(dict[int, int], coerce=True).load({1: "2"}, mode="python"), {1: 2})

    def test_union_order_and_literal_matching_include_enabled_conversions(self):
        self.assertEqual(compile_type(int | str, coerce=True).load("12"), 12)
        self.assertEqual(compile_type(str | int, coerce=True).load("12"), "12")
        schema = compile_type(Annotated[int, Min(10)] | bool, coerce=True)
        self.assertIs(schema.load("true"), True)
        with self.assertRaises(ValidationError) as caught:
            schema.load("1")
        self.assertEqual([i.code for i in caught.exception.issues], ["union"])
        self.assertEqual(compile_type(Literal[1], coerce=True).load("1"), 1)
        self.assertIs(compile_type(Literal[True], coerce=True).load("true"), True)
        with self.assertRaises(ValidationError):
            compile_type(Literal[1], coerce=True).load(True)

    def test_uuid_enum_tuple_and_none_modes_keep_their_existing_contracts(self):
        identity = UUID(int=1)
        self.assertEqual(compile_type(UUID, coerce=True).load(str(identity)), identity)
        self.assertIs(compile_type(Color, coerce=True).load("red"), Color.RED)
        self.assertEqual(compile_type(tuple[int, ...], coerce=True).load(["1"]), (1,))
        self.assertEqual(compile_type(tuple[int, ...], coerce=True).load(("1",), mode="python"), (1,))
        self.assertIsNone(compile_type(type(None), coerce=True).load(None))
        for annotation, data, mode in ((UUID, str(identity), "python"), (Color, "red", "python"),
                                       (tuple[int, ...], ["1"], "python"), (tuple[int, ...], ("1",), "json"),
                                       (type(None), "null", "json")):
            with self.assertRaises(ValidationError):
                compile_type(annotation, coerce=True).load(data, mode=mode)

    def test_error_caps_size_and_depth_stop_later_construction(self):
        calls = []
        @dataclass
        class Model:
            count: int
            def __post_init__(self):
                calls.append(self.count)
        data = [{"count": "bad"}, {"count": "2"}]
        for annotation, limits, code in ((list[Model], Limits(max_errors=1), "coercion"),
                                         (Annotated[list[Model], Length(max=1)], Limits(), "max_length"),
                                         (list[Model], Limits(max_items=1), "collection_size"),
                                         (list[Model], Limits(max_depth=0), "depth")):
            with self.assertRaises(ValidationError) as caught:
                compile_type(annotation, limits=limits, coerce=True).load(data)
            self.assertEqual(caught.exception.issues[0].code, code)
            self.assertEqual(calls, [])

    def test_plan_configuration_is_exact_and_immutable(self):
        for value in (None, 0, 1, "true", [], {}):
            with self.assertRaises(SchemaError):
                compile_type(int, coerce=value)
        schema = compile_type(int, coerce=True)
        with self.assertRaises(FrozenInstanceError):
            schema.coerce = False
        with self.assertRaises(ValidationError) as caught:
            compile_type(dict[str, int], coerce=True).load({"private-key": "private-value"})
        self.assertEqual(caught.exception.issues[0].as_dict(), {"path": ["*"], "code": "coercion", "expected": "int"})
        self.assertNotIn("private", str(caught.exception) + repr(caught.exception.issues))

    def test_constrained_coercing_plan_reuse_is_isolated_without_introspection(self):
        schema = compile_type(Reading, coerce=True, limits=Limits(max_errors=1))
        barrier = threading.Barrier(8)
        def worker(index):
            barrier.wait(timeout=10)
            for _ in range(10):
                loaded = schema.load({"count": str(index), "active": "true", "samples": ["1.5", "2"]})
                self.assertEqual(loaded, Reading(index, True, [1.5, 2.0]))
                self.assertIs(schema.check(loaded), loaded)
                self.assertEqual(schema.dump(loaded)["count"], index)
                self.assertEqual(schema.load_partial({"count": str(index)}), {"count": index})
                with self.assertRaises(ValidationError) as caught:
                    schema.load({"count": "-1"})
                self.assertEqual([(i.path, i.code) for i in caught.exception.issues], [(("count",), "min")])
            return index
        with ExitStack() as stack:
            for name in ("get_origin", "get_args", "get_type_hints"):
                stack.enter_context(patch("enforce_type._compiler." + name, side_effect=AssertionError("introspection")))
            stack.enter_context(patch("enforce_type._compiler.inspect.signature", side_effect=AssertionError("signature")))
            with ThreadPoolExecutor(max_workers=8) as pool:
                self.assertEqual(list(pool.map(worker, range(8))), list(range(8)))


if __name__ == "__main__":
    unittest.main()
