from __future__ import annotations

import pytest
from click.testing import CliRunner

from research_harness.storage.db import Database


@pytest.fixture(autouse=True)
def _no_external_providers(monkeypatch):
    """Prevent real HTTP calls to search providers in all tests."""
    monkeypatch.setattr(
        "research_harness.primitives.impls.build_provider_suite",
        lambda **kw: [],
    )


@pytest.fixture
def db(tmp_path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    return db


@pytest.fixture
def conn(db):
    connection = db.connect()
    yield connection
    connection.close()


@pytest.fixture
def runner(tmp_path, monkeypatch):
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))
    return CliRunner()
