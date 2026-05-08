"""Verify Alembic migrations apply cleanly to a fresh test DB."""
from __future__ import annotations

import os
import subprocess

import pytest


def test_alembic_upgrade_to_head():
    test_url = os.environ.get("DATABASE_URL_TEST")
    if not test_url:
        pytest.skip("DATABASE_URL_TEST not set")
    env = os.environ.copy()
    env["DATABASE_URL"] = test_url
    # Drop and recreate to verify a clean migration.
    # Use the postgres superuser to drop/create.
    subprocess.run(
        ["dropdb", "-h", "localhost", "-U", "alfanowski", "--if-exists", "streamload_test"],
        check=False, env=env,
    )
    subprocess.run(
        ["createdb", "-h", "localhost", "-U", "alfanowski", "-O", "streamload", "streamload_test"],
        check=True, env=env,
    )
    result = subprocess.run(
        ["venv/bin/alembic", "upgrade", "head"],
        env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, f"alembic failed: {result.stderr}"
