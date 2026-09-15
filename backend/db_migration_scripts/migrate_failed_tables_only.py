#!/usr/bin/env python3
"""
One-off script: copy only the tables that failed in the first migration run.

Copies job_parts, workflow_api_keys, workflow_usage_logs from SQLite to Postgres.
Run this after you have:
  - Run ALTER TABLE in Postgres to widen part_name and key_prefix.
  - Updated models.py (part_name String(255), key_prefix String(50)).

Run from the backend directory:

    cd backend
    python scripts/migrate_failed_tables_only.py
"""

import os
import sys
import logging
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")

from sqlalchemy import create_engine, select, insert, text
from sqlalchemy.orm import sessionmaker

from api.database.models import JobPart, WorkflowApiKey, WorkflowUsageLog

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

SQLITE_PATH = BACKEND_DIR / "data" / "extraction_jobs.db"

# Only the 3 tables that failed (order: job_parts, then workflow_api_keys, then workflow_usage_logs)
MODELS_TO_COPY = [JobPart, WorkflowApiKey, WorkflowUsageLog]


def get_postgres_url():
    """Build Postgres URL from env (same logic as api.database.engine)."""
    from urllib.parse import quote_plus
    host = os.environ.get("DB_HOST", "localhost")
    port = os.environ.get("DB_PORT", "5432")
    name = os.environ.get("DB_NAME", "extraction_jobs")
    user = os.environ.get("DB_USER", "postgres")
    password = os.environ.get("DB_PASSWORD", "")
    password = quote_plus(password) if password else ""
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


def main():
    if not SQLITE_PATH.exists():
        logger.error("SQLite DB not found at %s", SQLITE_PATH)
        sys.exit(1)

    sqlite_url = f"sqlite:///{SQLITE_PATH}"
    pg_url = get_postgres_url()

    logger.info("Connecting to SQLite: %s", SQLITE_PATH)
    sqlite_engine = create_engine(sqlite_url)
    logger.info("Connecting to PostgreSQL (DB_NAME=%s)", os.environ.get("DB_NAME", "?"))
    pg_engine = create_engine(pg_url)

    SessionSqlite = sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False)
    SessionPg = sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)

    total_copied = 0
    errors = []

    with SessionSqlite() as session_sqlite, SessionPg() as session_pg:
        for Model in MODELS_TO_COPY:
            table = Model.__table__
            name = table.name
            try:
                r = session_sqlite.execute(
                    text(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=:n"
                    ),
                    {"n": name},
                )
                if not r.scalar():
                    logger.warning("Table %s not in SQLite, skipping", name)
                    continue

                rows = session_sqlite.execute(select(table)).fetchall()
                count = len(rows)
                if count == 0:
                    logger.info("%s: 0 rows (ok)", name)
                    continue

                for row in rows:
                    session_pg.execute(insert(table).values(**row._mapping))
                session_pg.commit()
                total_copied += count

                pg_count = session_pg.execute(
                    text(f"SELECT count(*) FROM {table.name}")
                ).scalar()
                if pg_count != count:
                    errors.append(f"{name}: count mismatch sqlite={count} pg={pg_count}")
                    logger.error("%s: count mismatch sqlite=%s pg=%s", name, count, pg_count)
                else:
                    logger.info("%s: %s rows copied and verified", name, count)

            except Exception as e:
                session_pg.rollback()
                errors.append(f"{name}: {e}")
                logger.exception("Failed to copy table %s", name)

    if errors:
        logger.error("Migration had %s error(s): %s", len(errors), errors)
        sys.exit(1)
    logger.info("Done. Total rows copied: %s", total_copied)


if __name__ == "__main__":
    main()
