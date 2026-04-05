from __future__ import annotations

from pathlib import Path

from orbit.store.factory import create_default_store
from orbit.store.sqlite_store import SQLiteStore


class _FakePostgresStore:
    def __init__(self, config):
        self.config = config


class _BoomPostgresStore:
    def __init__(self, config):
        raise RuntimeError("postgres unavailable")


def test_create_default_store_prefers_postgres_when_configured(monkeypatch):
    import orbit.store.factory as factory

    monkeypatch.setattr(factory, "DEFAULT_STORE_BACKEND", "postgres")
    monkeypatch.setattr(factory, "PostgresStore", _FakePostgresStore)

    store = create_default_store()

    assert isinstance(store, _FakePostgresStore)
    assert store.config.dbname == factory.DEFAULT_PG_DBNAME


def test_create_default_store_falls_back_to_sqlite_when_postgres_unavailable(monkeypatch, tmp_path):
    import orbit.store.factory as factory

    monkeypatch.setattr(factory, "DEFAULT_STORE_BACKEND", "postgres")
    monkeypatch.setattr(factory, "PostgresStore", _BoomPostgresStore)
    monkeypatch.setattr(factory, "DEFAULT_DB_PATH", Path(tmp_path) / "fallback.db")

    store = create_default_store()

    assert isinstance(store, SQLiteStore)
    assert store.db_path == Path(tmp_path) / "fallback.db"
