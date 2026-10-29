import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import translations  # noqa: E402


def pytest_sessionstart(session):
    translations.compile_all()
