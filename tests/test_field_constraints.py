import unittest
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Annotated

from enforce_type import Length, Limits, Max, Min, SchemaError, ValidationError, compile_type


@dataclass(frozen=True, slots=True, kw_only=True)
class Inventory:
    name: str = field(metadata={"enforce_type": {"min_length": 1, "max_length": 20}})
    quantity: Annotated[int, Max(100)] = field(default=0, metadata={"enforce_type": {"min": 0}})
    tags: list[Annotated[str, Length(min=1)]] = field(default_factory=list, metadata={"enforce_type": {"max_length": 2}})


class FieldConstraintTests(unittest.TestCase):
    def test_metadata_applies_to_all_operations_and_partial_inputs(self):
        schema = compile_type(Inventory)
        value = schema.load({"name": "stock", "quantity": 2, "tags": ["one"]})
        self.assertEqual(value, Inventory(name="stock", quantity=2, tags=["one"]))
        self.assertIs(schema.check(value), value)
        self.assertEqual(schema.dump(value), {"name": "stock", "quantity": 2, "tags": ["one"]})
        self.assertEqual(schema.load_partial({"quantity": 4}), {"quantity": 4})
        for mode in ("json", "python"):
            for data, path, code in (({"name": ""}, ("name",), "min_length"),
                                     ({"quantity": -1}, ("quantity",), "min"),
                                     ({"quantity": 101}, ("quantity",), "max"),
                                     ({"tags": [""]}, ("tags", 0), "min_length"),
                                     ({"tags": ["a", "b", "c"]}, ("tags",), "max_length")):
                with self.assertRaises(ValidationError) as caught:
                    schema.load_partial(data, mode=mode)
                self.assertEqual([(i.path, i.code) for i in caught.exception.issues], [(path, code)])
        invalid = Inventory(name="", quantity=-1)
        for method in ("check", "dump"):
            with self.assertRaises(ValidationError) as caught:
                getattr(schema, method)(invalid)
            self.assertEqual([i.path for i in caught.exception.issues], [("name",), ("quantity",)])

    def test_invalid_supplied_fields_prevent_root_construction(self):
        calls = []
        @dataclass
        class Model:
            count: int = field(metadata={"enforce_type": {"min": 0}})
            generated: list[int] = field(default_factory=lambda: calls.append("factory") or [])
            def __post_init__(self):
                calls.append("constructor")
        schema = compile_type(Model)
        for method in ("load", "load_partial"):
            with self.assertRaises(ValidationError):
                getattr(schema, method)({"count": -1})
        self.assertEqual(schema.load_partial({}), {})
        self.assertEqual(schema.load_partial({"count": 1}), {"count": 1})
        self.assertEqual(calls, [])

    def test_defaults_factories_and_computed_results_are_validated(self):
        @dataclass
        class BadDefault:
            count: int = field(default=-1, metadata={"enforce_type": {"min": 0}})
        @dataclass
        class BadFactory:
            tags: list[str] = field(default_factory=list, metadata={"enforce_type": {"min_length": 1}})
        @dataclass
        class BadComputed:
            count: int = field(init=False, default=-1, metadata={"enforce_type": {"min": 0}})
        @dataclass
        class BadPostInit:
            count: int = field(metadata={"enforce_type": {"max": 10}})
            def __post_init__(self):
                self.count = 11
        for model, data in ((BadDefault, {}), (BadFactory, {}), (BadComputed, {}), (BadPostInit, {"count": 1})):
            schema = compile_type(model)
            with self.assertRaises(ValidationError):
                schema.load(data)
            self.assertEqual(schema.load_partial({}), {})
        with self.assertRaises(ValidationError) as caught:
            compile_type(BadComputed).load_partial({"count": 1})
        self.assertEqual(caught.exception.issues[0].code, "init_field")

    def test_rules_are_snapshotted_and_unrelated_metadata_is_ignored(self):
        config = {"min": 0, "max": 10}
        @dataclass
        class Model:
            count: int = field(metadata={"enforce_type": config, "other": {"read_only": True}})
        schema = compile_type(Model)
        config["min"] = -100
        config["max"] = 0
        self.assertEqual(schema.load({"count": 10}), Model(10))
        with self.assertRaises(ValidationError) as caught:
            schema.load({"count": -1})
        self.assertEqual(caught.exception.issues[0].code, "min")
        self.assertEqual(schema.dump(Model(1)), {"count": 1})
        self.assertIs(schema.fields[0].annotation, int)

    def test_inheritance_frozen_slots_and_keyword_only_models(self):
        @dataclass(frozen=True, slots=True, kw_only=True)
        class Child(Inventory):
            price: float = field(default=1.0, metadata={"enforce_type": MappingProxyType({"min": 0, "max": 10})})
        schema = compile_type(Child)
        value = schema.load({"name": "item", "price": 2})
        self.assertEqual(value.price, 2.0)
        self.assertEqual([f.name for f in schema.fields], ["name", "quantity", "tags", "price"])
        for data in ({"name": ""}, {"price": -1}):
            with self.assertRaises(ValidationError):
                schema.load_partial(data)

    def test_metadata_and_annotation_rules_compose_without_cache_contamination(self):
        @dataclass
        class Model:
            limited: Annotated[int, Min(0)] = field(metadata={"enforce_type": {"max": 5}})
            ordinary: Annotated[int, Min(0)]
            text: Annotated[str, Length(min=1)] = field(metadata={"enforce_type": {"min_length": 2, "max_length": 4}})
        schema = compile_type(Model)
        self.assertEqual(schema.load({"limited": 5, "ordinary": 10, "text": "ab"}), Model(5, 10, "ab"))
        with self.assertRaises(ValidationError) as caught:
            schema.load({"limited": 6, "ordinary": 10, "text": "a"})
        self.assertEqual([(i.path, i.code) for i in caught.exception.issues],
                         [(("limited",), "max"), (("text",), "min_length")])

    def test_invalid_metadata_fails_at_compilation_without_exposing_it(self):
        cases = ((int, None), (int, (Min(0),)), (int, {"private-key": 1}), (int, {1: 2}),
                 (int, {"min": True}), (int, {"max": float("inf")}), (str, {"min": 0}),
                 (int, {"max_length": 2}), (str, {"min_length": -1}),
                 (str, {"min_length": 3, "max_length": 2}),
                 (Annotated[int, Max(2)], {"min": 3}),
                 (Annotated[str, Length(max=2)], {"min_length": 3}))
        for annotation, config in cases:
            @dataclass
            class Model:
                value: annotation = field(metadata={"enforce_type": config})
            with self.subTest(config=config), self.assertRaises(SchemaError) as caught:
                compile_type(Model)
            self.assertNotIn("private", str(caught.exception))
        @dataclass
        class Empty:
            value: int = field(metadata={"enforce_type": {}})
        self.assertEqual(compile_type(Empty).load({"value": 1}), Empty(1))

    def test_bounds_apply_to_constrained_fields_and_issue_allocation(self):
        schema = compile_type(Inventory, limits=Limits(max_errors=1))
        with self.assertRaises(ValidationError) as caught:
            schema.load_partial({"name": "", "quantity": -1})
        self.assertEqual([(i.path, i.code) for i in caught.exception.issues], [(("name",), "min_length")])
        schema = compile_type(Inventory, limits=Limits(max_depth=1))
        self.assertEqual(schema.load_partial({"quantity": 1}), {"quantity": 1})
        with self.assertRaises(ValidationError) as caught:
            schema.load_partial({"tags": ["one"]})
        self.assertEqual(caught.exception.issues[0].code, "depth")


if __name__ == "__main__":
    unittest.main()
