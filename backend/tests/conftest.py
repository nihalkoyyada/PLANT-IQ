"""Global PyTest Configuration and Test Database Isolation.

This conftest guarantees that pytest runs STRICTLY in the isolated test database
`plantiq_test`, completely shielding the live development/production database
(`plantiq`) from dummy entities, test users, test plants, and duplicate records.
"""

import os
import sys
from pathlib import Path

# Force isolated test database URL BEFORE any application modules are loaded
TEST_DB_URL = "postgresql+psycopg://plantiq:plantiq_dev_password@localhost:5432/plantiq_test"
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["TESTING"] = "true"

# Ensure backend root is on sys.path
backend_dir = str(Path(__file__).resolve().parents[1])
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

