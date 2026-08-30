import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from greet import greet
from names import format_name


class TestGreet(unittest.TestCase):
    def test_ada(self) -> None:
        self.assertEqual(greet("ada"), "Hello, Ada!")


class TestNames(unittest.TestCase):
    def test_title(self) -> None:
        self.assertEqual(format_name(" ada "), "Ada")


if __name__ == "__main__":
    unittest.main()
