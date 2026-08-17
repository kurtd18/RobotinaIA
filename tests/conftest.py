"""
Fixture de aislamiento de base de datos para tests.

Los tests que necesitan la base de datos piden explícitamente el
fixture `db_path` (no es autouse): crea un archivo SQLite temporal,
apunta Settings.DATABASE_NAME hacia él (monkeypatch) y crea el
esquema completo antes de entregarlo al test.
"""

import pytest

from app.core.settings import Settings
from app.database.schema import create_tables


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    temp_db = tmp_path / "test_robotinaia.db"
    monkeypatch.setattr(Settings, "DATABASE_NAME", str(temp_db))
    create_tables()
    yield str(temp_db)
