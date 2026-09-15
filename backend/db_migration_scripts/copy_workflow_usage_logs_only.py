#!/usr/bin/env python3
"""
One-off script: copy only workflow_usage_logs from SQLite to PostgreSQL.

Run after deleting any orphan rows from SQLite workflow_usage_logs
(rows whose job_id or api_key_id are not present in jobs / workflow_api_keys).

Run from the backend directory:

    cd backend
    python scripts/copy_workflow_usage_logs_only.py
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

from api.database.models import WorkflowUsageLog

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

SQLITE_PATH = BACKEND_DIR / "data" / "extraction_jobs.db"


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

    table = WorkflowUsageLog.__table__
    name = table.name

    with SessionSqlite() as session_sqlite, SessionPg() as session_pg:
        try:
            r = session_sqlite.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=:n"
                ),
                {"n": name},
            )
            if not r.scalar():
                logger.error("Table %s not in SQLite", name)
                sys.exit(1)

            rows = session_sqlite.execute(select(table)).fetchall()
            count = len(rows)
            if count == 0:
                logger.info("%s: 0 rows (nothing to copy)", name)
                return

            for row in rows:
                session_pg.execute(insert(table).values(**row._mapping))
            session_pg.commit()

            pg_count = session_pg.execute(
                text(f"SELECT count(*) FROM {table.name}")
            ).scalar()
            if pg_count != count:
                logger.error("%s: count mismatch sqlite=%s pg=%s", name, count, pg_count)
                sys.exit(1)
            logger.info("%s: %s rows copied and verified", name, count)

        except Exception as e:
            session_pg.rollback()
            logger.exception("Failed to copy table %s: %s", name, e)
            sys.exit(1)


if __name__ == "__main__":
    main()
