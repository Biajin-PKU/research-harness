"""SQLite database management for research hub."""

from __future__ import annotations

import logging
import shutil
import sqlite3
import subprocess
from pathlib import Path

from ..config import GLOBAL_DB_PATH

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"
DEFAULT_DB_PATH = GLOBAL_DB_PATH


class Database:
    """SQLite database manager with lightweight file-based migrations."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self._ensure_dir()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        # Wait up to 10 s when another writer holds the lock instead of failing
        # immediately with "database is locked".
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    def check_integrity(self) -> bool:
        """Run PRAGMA integrity_check; return True if DB is healthy."""
        if not self.db_path.exists():
            return True
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.execute("PRAGMA busy_timeout=5000")
            result = conn.execute("PRAGMA integrity_check").fetchone()
            return result is not None and result[0] == "ok"
        except Exception:
            return False
        finally:
            if conn is not None:
                conn.close()

    def auto_recover(self) -> bool:
        """Attempt to recover a corrupted DB using sqlite3 .recover.

        Returns True if recovery succeeded and the DB was replaced.
        """
        if not self.db_path.exists():
            return False

        recovered_path = self.db_path.with_suffix(".recovered.db")
        backup_path = self.db_path.with_suffix(".corrupted.bak")

        try:
            result = subprocess.run(
                f'sqlite3 "{self.db_path}" ".recover" | sqlite3 "{recovered_path}"',
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0 or not recovered_path.exists():
                logger.error("DB recovery failed: %s", result.stderr[:500])
                recovered_path.unlink(missing_ok=True)
                return False

            # Verify recovered DB
            test_conn = sqlite3.connect(str(recovered_path))
            check = test_conn.execute("PRAGMA integrity_check").fetchone()
            test_conn.close()
            if check is None or check[0] != "ok":
                logger.error("Recovered DB also failed integrity check")
                recovered_path.unlink(missing_ok=True)
                return False

            # Swap: corrupted → backup, recovered → active
            shutil.move(str(self.db_path), str(backup_path))
            shutil.move(str(recovered_path), str(self.db_path))
            logger.warning(
                "DB recovered successfully. Corrupted backup: %s", backup_path
            )
            return True
        except Exception as exc:
            logger.error("DB recovery exception: %s", exc)
            recovered_path.unlink(missing_ok=True)
            return False

    def migrate(self) -> None:
        # Integrity check before migration
        if self.db_path.exists() and not self.check_integrity():
            logger.warning("DB integrity check failed: %s", self.db_path)
            if self.auto_recover():
                logger.info("DB auto-recovered, proceeding with migration")
            else:
                raise RuntimeError(
                    f"DB is corrupted and auto-recovery failed: {self.db_path}\n"
                    "Manual recovery: sqlite3 <db> '.recover' | sqlite3 recovered.db\n"
                    "Or pass --db /path/to/healthy.db to use an alternate DB."
                )

        conn = self.connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT DEFAULT (datetime('now'))
                )
                """
            )
            applied = {
                row[0]
                for row in conn.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
                version = int(sql_file.name.split("_")[0])
                if version in applied:
                    continue
                try:
                    conn.executescript(sql_file.read_text())
                except sqlite3.OperationalError as exc:
                    # Some historical migrations add columns that may already exist in
                    # long-lived local DBs. Treat duplicate-column errors as idempotent.
                    if "duplicate column name" not in str(exc).lower():
                        raise
                    logger.warning(
                        "Migration %s already satisfied (%s); marking as applied",
                        sql_file.name,
                        exc,
                    )
                conn.execute(
                    "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                    (version, sql_file.stem),
                )
                conn.commit()
        finally:
            conn.close()

    def _ensure_dir(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
