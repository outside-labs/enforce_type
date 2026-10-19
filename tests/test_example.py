import runpy
import unittest
from pathlib import Path


class ExampleTests(unittest.TestCase):
    def test_users_example(self):
        example = runpy.run_path(str(Path(__file__).resolve().parents[1] / "examples" / "users.py"))
        self.assertEqual(example["demo"](), {"name": "Ella", "age": 34, "active": False})
        self.assertEqual([field.name for field in example["users"].fields], ["name", "age", "active"])
