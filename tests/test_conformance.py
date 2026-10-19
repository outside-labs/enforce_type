import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import FrozenInstanceError, dataclass, field
from enum import Enum
from typing import Literal, NewType, TypeVar, TypedDict
from unittest.mock import patch
from uuid import UUID

from enforce_type import Limits, SchemaError, ValidationError, compile_type


@dataclass(frozen=True, slots=True)
class Item:
    count: int
    labels: list[str] = field(default_factory=list)


class ConformanceTests(unittest.TestCase):
    def test_one_plan_is_shared_by_simultaneous_threaded_callers(self):
        schema = compile_type(Item)
        barrier = threading.Barrier(8)
        def worker(index):
            barrier.wait(timeout=10)
            result = []
            for offset in range(20):
                number = index * 20 + offset
                if number % 7 == 0:
                    try:
                        schema.load({"count": "private-value"})
                    except ValidationError as exc:
                        result.append((number, [(i.path, i.code) for i in exc.issues]))
                    else:
                        raise AssertionError("Invalid input accepted")
                else:
                    loaded = schema.load({"count": number, "labels": [str(number)]})
                    schema.check(loaded)
                    result.append((number, schema.dump(loaded)))
            return result
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(worker, range(8)))
        for result in results:
            for number, value in result:
                expected = [(("count",), "type")] if number % 7 == 0 else {"count": number, "labels": [str(number)]}
                self.assertEqual(value, expected)
        self.assertEqual(schema.load({"count": 999}), Item(999))

    def test_all_operations_use_compiled_nodes_without_reintrospection(self):
        schema = compile_type(Item)
        sequence = compile_type(list[Item])
        coordinates = compile_type(tuple[UUID, int])
        identity = UUID(int=1)
        with ExitStack() as stack:
            for name in ("get_type_hints", "get_args", "get_origin"):
                stack.enter_context(patch("enforce_type._compiler." + name, side_effect=AssertionError("reintrospection")))
            stack.enter_context(patch("enforce_type._compiler.inspect.signature", side_effect=AssertionError("signature")))
            value = schema.load({"count": 1})
            self.assertIs(schema.check(value), value)
            self.assertEqual(schema.dump(value), {"count": 1, "labels": []})
            self.assertEqual(schema.load_partial({"count": 2}), {"count": 2})
            self.assertEqual(sequence.load([{"count": 3}]), [Item(3)])
            self.assertEqual(coordinates.load([str(identity), 1]), (identity, 1))

    def test_error_cap_stops_later_constructor_execution(self):
        calls = []
        @dataclass
        class Model:
            count: int
            def __post_init__(self):
                calls.append(self.count)
        schema = compile_type(list[Model], limits=Limits(max_errors=1))
        with self.assertRaises(ValidationError) as caught:
            schema.load([{"count": "bad"}, {"count": 2}])
        self.assertEqual(len(caught.exception.issues), 1)
        self.assertEqual(calls, [])
        schema = compile_type(list[Model], limits=Limits(max_items=1))
        with self.assertRaises(ValidationError):
            schema.load([{"count": 1}, {"count": 2}])
        self.assertEqual(calls, [])

    def test_failed_union_branch_errors_do_not_poison_success(self):
        @dataclass
        class Rejects:
            count: int
            def __post_init__(self):
                raise ValueError("private-credential")
        @dataclass
        class Accepts:
            count: int
        schema = compile_type(Rejects | Accepts)
        self.assertEqual(schema.load({"count": 2}), Accepts(2))
        with self.assertRaises(ValidationError) as caught:
            schema.load({"count": "private-value"})
        self.assertEqual([issue.code for issue in caught.exception.issues], ["union"])
        self.assertNotIn("private", str(caught.exception) + repr(caught.exception.issues))
        self.assertEqual(schema.load({"count": 3}), Accepts(3))

    def test_control_flow_exceptions_propagate(self):
        class Abort(BaseException):
            pass
        @dataclass
        class Model:
            count: int
            def __post_init__(self):
                raise Abort
        schema = compile_type(Model)
        with self.assertRaises(Abort):
            schema.load({"count": 1})
        self.assertEqual(schema.load_partial({"count": 1}), {"count": 1})

    def test_attribute_exceptions_are_value_free(self):
        @dataclass
        class Model:
            count: int
            def __getattribute__(self, name):
                if name == "count":
                    raise ValueError("private-credential")
                return object.__getattribute__(self, name)
        schema = compile_type(Model)
        for call in (lambda: schema.load({"count": 1}), lambda: schema.check(Model(1)), lambda: schema.dump(Model(1))):
            with self.assertRaises(ValidationError) as caught:
                call()
            self.assertEqual(caught.exception.issues[0].code, "attribute")
            self.assertNotIn("private", str(caught.exception) + repr(caught.exception.issues))

    def test_paths_are_deterministic_bounded_and_redacted(self):
        schema = compile_type(dict[str, list[int]], limits=Limits(max_errors=2))
        for _ in range(5):
            with self.assertRaises(ValidationError) as caught:
                schema.load({"private-key": [False, "private-value", None], "other-private": [1]})
            self.assertEqual([issue.path for issue in caught.exception.issues], [("*", 0), ("*", 1)])
            self.assertNotIn("private", repr(caught.exception.issues))

    def test_zero_bounds_and_schema_depth_limit(self):
        limits = Limits(max_depth=0, max_items=0)
        self.assertEqual(compile_type(int, limits=limits).load(1), 1)
        self.assertEqual(compile_type(list[int], limits=limits).load([]), [])
        self.assertEqual(compile_type(Item, limits=limits).load_partial({}), {})
        annotation = int
        for _ in range(80):
            annotation = list[annotation]
        with self.assertRaises(SchemaError):
            compile_type(annotation)

    def test_custom_container_callbacks_are_not_executed(self):
        class Trap(list):
            def __iter__(self):
                raise AssertionError("Unexpected iteration")
        class DictionaryTrap(dict):
            def items(self):
                raise AssertionError("Unexpected iteration")
        with self.assertRaises(ValidationError):
            compile_type(list[int]).load(Trap([1]))
        with self.assertRaises(ValidationError):
            compile_type(dict[str, int]).load(DictionaryTrap(one=1))

    def test_model_subclasses_only_dump_declared_fields(self):
        @dataclass
        class Base:
            count: int
        @dataclass
        class Child(Base):
            extra: str = "extra"
        value = Child(1)
        self.assertIs(compile_type(Base).check(value), value)
        self.assertEqual(compile_type(Base).dump(value), {"count": 1})
        self.assertEqual(compile_type(Child).dump(value), {"count": 1, "extra": "extra"})

    def test_json_dump_is_accepted_by_the_standard_json_encoder(self):
        schema = compile_type(list[tuple[UUID, Item]])
        data = [[str(UUID(int=i)), {"count": i, "labels": ["one", "two"]}] for i in range(10)]
        loaded = schema.load(data)
        self.assertEqual(json.loads(json.dumps(schema.dump(loaded), allow_nan=False)), data)
        self.assertEqual(data[0][1]["labels"], ["one", "two"])

    def test_public_metadata_remains_immutable_across_calls(self):
        schema = compile_type(Item)
        before = schema.fields
        for index in range(5):
            schema.load({"count": index})
        self.assertEqual(schema.fields, before)
        self.assertIsInstance(schema.fields, tuple)
        self.assertIsInstance(schema._root.field_names, frozenset)
        with self.assertRaises(FrozenInstanceError):
            schema.fields[0].required = False

    def test_unsupported_typing_forms_never_degrade_to_any(self):
        class Record(TypedDict):
            count: int
        type Alias = list[int]
        identifier = NewType("Identifier", int)
        variable = TypeVar("Variable")
        for annotation in (Record, Alias, identifier, variable, tuple[()], frozenset[int]):
            with self.subTest(annotation=annotation), self.assertRaises(SchemaError):
                compile_type(annotation)

    def test_literal_caching_keeps_boolean_and_integer_choices_distinct(self):
        @dataclass
        class Model:
            flag: Literal[False]
            number: Literal[0]
        schema = compile_type(Model)
        self.assertEqual(schema.load({"flag": False, "number": 0}), Model(False, 0))
        for data in ({"flag": 0, "number": 0}, {"flag": False, "number": False}):
            with self.assertRaises(ValidationError):
                schema.load(data)


if __name__ == "__main__":
    unittest.main()
