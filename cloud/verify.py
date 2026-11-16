"""Offline verification entry point; no credentials and no paid requests."""
from pathlib import Path
import sys
import unittest

root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / 'service'))
sys.path.insert(0, str(root / 'tests'))
suite = unittest.TestSuite()
suite.addTests(unittest.defaultTestLoader.discover(str(root / 'tests')))
for name in ('test_google_provider', 'test_google_live'):
    if (root / 'service' / (name + '.py')).is_file():
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName(name))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
