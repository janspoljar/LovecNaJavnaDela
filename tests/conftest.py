"""
conftest.py — Testna konfiguracija.
DB_PATH preusmeri na začasno test bazo PRED importom config/db modulov.
"""

import os
import sys
import pathlib

# Test baza v tests/ mapi — pobriše se po koncu testov
TEST_DB = str(pathlib.Path(__file__).parent / "test_narocila.db")
os.environ["DB_PATH"] = TEST_DB

# Repo root v sys.path, da testi najdejo module (db, scraper, ...)
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))


def pytest_sessionfinish(session, exitstatus):
    """Po testih pobriši test bazo."""
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(TEST_DB + suffix)
        except FileNotFoundError:
            pass
