import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from greet import greet


class TestGreet(unittest.TestCase):
    def test_ada(self) -> None:
        self.assertEqual(greet("ada"), "Hello, Ada!")


if __name__ == "__main__":
    unittest.main()
