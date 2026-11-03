import runpy
import unittest
from pathlib import Path


class ExampleTests(unittest.TestCase):
    def test_api_value_example(self):
        example = runpy.run_path(str(Path(__file__).resolve().parents[1] / "examples" / "api_values.py"))
        result = example["demo"]()
        self.assertEqual(result, {"number": 2.0, "identity": "00000000-0000-0000-0000-000000000001"})
        self.assertIs(type(result["number"]), float)

    def test_users_example(self):
        example = runpy.run_path(str(Path(__file__).resolve().parents[1] / "examples" / "users.py"))
        self.assertEqual(example["demo"](), {"name": "Ella", "age": 34, "active": False})
        self.assertEqual([field.name for field in example["users"].fields], ["name", "age", "active"])
