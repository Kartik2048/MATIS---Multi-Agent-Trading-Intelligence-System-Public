import os
import sys
import pytest

# Ensure matis_backend directory is on sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "matis_backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import database
import ml_database


@pytest.fixture(autouse=True)
def isolated_databases(tmp_path, monkeypatch):
    """
    Direct all SQLite connections to a temporary directory for each test run.
    Ensures tests never touch or mutate the live trading databases.
    """
    test_db = str(tmp_path / "test_paper_trading.db")
    test_ml_db = str(tmp_path / "test_ml_training.db")

    monkeypatch.setattr(database, "DB_PATH", test_db)
    monkeypatch.setattr(ml_database, "ML_DB_PATH", test_ml_db)

    database.init_db()
    ml_database.init_ml_db()

    yield
