#!/usr/bin/env python3
"""
One-off script: migrate data from SQLite to PostgreSQL.

Run from the backend directory so that 'api' is importable and .env is loaded:

    cd backend
    python scripts/migrate_sqlite_to_postgres.py

Prerequisites:
  - PostgreSQL schema already created (run the app once against the target DB).
  - .env has DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD set for Postgres.
  - SQLite DB at backend/data/extraction_jobs.db exists.

Tables are copied in FK order. One transaction per table; counts are verified after each.

Re-running will duplicate rows; truncate the Postgres tables (in reverse FK order) or use
a fresh DB if you need to run the migration again.
"""

import os
import sys
import logging
from pathlib import Path

# Ensure backend is on path and load .env before any api imports
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")

from sqlalchemy import create_engine, select, insert, text
from sqlalchemy.orm import sessionmaker

# Import after env is loaded so engine uses DB_* vars for Postgres
from api.database.models import (
    Base,
    User,
    Schema,
    ProviderConfig,
    PromptLib,
    Workflow,
    Job,
    JobPart,
    WorkflowCollaborator,
    WorkflowApiKey,
    WorkflowUsageLog,
    WorkflowStatusChangeLog,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# SQLite DB path (relative to backend)
SQLITE_PATH = BACKEND_DIR / "data" / "extraction_jobs.db"

# Tables in dependency order (parents before children)
MODELS_IN_ORDER = [
    User,
    Schema,
    ProviderConfig,
    PromptLib,
    Workflow,
    Job,
    JobPart,
    WorkflowCollaborator,
    WorkflowApiKey,
    WorkflowUsageLog,
    WorkflowStatusChangeLog,
]


def get_postgres_url():
    """Build Postgres URL from env (same logic as api.database.engine)."""
    import os
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
        for Model in MODELS_IN_ORDER:
            table = Model.__table__
            name = table.name
            try:
                # Check table exists in SQLite
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
                    # row is a Row; ._mapping gives column name -> value
                    session_pg.execute(insert(table).values(**row._mapping))
                session_pg.commit()
                total_copied += count

                # Verify count in Postgres
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
                # Continue with next table; you can fix and re-run from this script
                # (re-run will duplicate rows unless you truncate or use a fresh DB)

    if errors:
        logger.error("Migration had %s error(s): %s", len(errors), errors)
        sys.exit(1)
    logger.info("Migration completed. Total rows copied: %s", total_copied)


if __name__ == "__main__":
    main()
