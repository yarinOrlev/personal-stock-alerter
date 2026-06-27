#!/usr/bin/env python3
"""
run_tests.py
------------
Run the test suite without needing pytest installed:

    python run_tests.py

(If you have pytest, `pytest -q` works too.)
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tests import test_all  # noqa: E402


def main() -> int:
    fns = [v for k, v in sorted(vars(test_all).items())
           if k.startswith("test_") and callable(v)]
    passed, failed = 0, 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
            passed += 1
        except Exception:
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed, {len(fns)} total")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
