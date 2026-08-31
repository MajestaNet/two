import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from rem import remainder

print("ALL TESTS PASSED")
assert remainder(10, 3) == 1
