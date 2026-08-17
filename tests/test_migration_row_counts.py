"""Tests de migrations/0000_apply_constraints.py."""

import importlib
import sqlite3
import sys
from pathlib import Path

from app.core.settings import Settings
from app.database.schema import (
    SCHEMA_PORTFOLIO,
    SCHEMA_PORTFOLIO_DECISIONS,
    SCHEMA_SIGNALS,
)

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
if str(_MIGRATIONS_DIR) not in sys.path:
    sys.path.insert(0, str(_MIGRATIONS_DIR))

apply_constraints = importlib.import_module("0000_apply_constraints")


def test_running_against_already_migrated_db_reports_identical_counts(db_path):
    # db_path (conftest.py) ya corrió create_tables() -> ya migrada.
    exit_code = apply_constraints.main()
    assert exit_code == 0


def test_running_twice_is_idempotent_and_counts_match(db_path):
    apply_constraints.main()

    conn = sqlite3.connect(db_path)
    tablas = ("signals", "portfolio", "portfolio_decisions")
    counts_before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tablas}
    conn.close()

    exit_code = apply_constraints.main()

    conn = sqlite3.connect(db_path)
    counts_after = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tablas}
    conn.close()

    assert exit_code == 0
    assert counts_before == counts_after


def test_orphaned_portfolio_decisions_row_blocks_migration_and_reports_it(
    tmp_path, monkeypatch, capsys
):
    """Construye una base pre-migración (sin constraints todavía) con una
    fila huérfana en portfolio_decisions, y confirma que el script se
    detiene antes de tocar nada."""
    temp_db = tmp_path / "orphan_test.db"
    monkeypatch.setattr(Settings, "DATABASE_NAME", str(temp_db))

    conn = sqlite3.connect(str(temp_db))
    conn.execute(SCHEMA_SIGNALS)
    conn.execute(SCHEMA_PORTFOLIO)
    conn.execute(SCHEMA_PORTFOLIO_DECISIONS)
    conn.execute(
        "INSERT INTO portfolio_decisions (position_id, decision, timestamp) "
        "VALUES (999999, 'HOLD', '2026-01-01T00:00:00');"
    )
    conn.commit()
    version_before = conn.execute("PRAGMA user_version;").fetchone()[0]
    conn.close()

    exit_code = apply_constraints.main()
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "999999" in captured.out

    conn = sqlite3.connect(str(temp_db))
    version_after = conn.execute("PRAGMA user_version;").fetchone()[0]
    row_still_there = conn.execute(
        "SELECT COUNT(*) FROM portfolio_decisions WHERE position_id = 999999"
    ).fetchone()[0]
    conn.close()

    assert version_after == version_before  # no se aplicó nada
    assert row_still_there == 1  # la fila huérfana sigue intacta, no se tocó
