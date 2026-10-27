"""Runs the test_* functions without pytest: python3 -m tests.run"""
import importlib
import pathlib
import sys
import traceback

failed = 0
for path in sorted(pathlib.Path(__file__).parent.glob("test_*.py")):
    mod = importlib.import_module(f"tests.{path.stem}")
    for name in sorted(n for n in dir(mod) if n.startswith("test_")):
        try:
            getattr(mod, name)()
            print(f"ok   {path.stem}.{name}")
        except Exception:
            failed += 1
            print(f"FAIL {path.stem}.{name}")
            traceback.print_exc()
sys.exit(1 if failed else 0)
