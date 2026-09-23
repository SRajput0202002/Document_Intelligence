"""
Database engine configuration.

Sets up PostgreSQL connection with SQLAlchemy using DB_* environment variables.
"""

import os
import logging
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker

from .models import Base

logger = logging.getLogger(__name__)

# Build PostgreSQL URL from environment variables
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_PORT = os.environ.get("DB_PORT", "5432")
DB_NAME = os.environ.get("DB_NAME", "extraction_jobs")
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

# URL-encode password in case it contains special characters
_password = quote_plus(DB_PASSWORD) if DB_PASSWORD else ""
DATABASE_URL = f"postgresql://{DB_USER}:{_password}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Create engine (no connect_args needed for PostgreSQL)
engine = create_engine(
    DATABASE_URL,
    echo=False,  # Set True for SQL logging
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def run_migrations():
    """
    Run database migrations for schema changes.

    Adds new columns to existing tables without losing data.
    Also creates new tables (like prompt_lib) if they don't exist.
    """
    # PostgreSQL uses TIMESTAMP for datetime columns
    datetime_type = "TIMESTAMP"

    inspector = inspect(engine)
    table_names = inspector.get_table_names()

    # Users table migrations
    if "users" in table_names:
        users_columns = {col["name"] for col in inspector.get_columns("users")}
        with engine.connect() as conn:
            if "password_version" not in users_columns:
                logger.info("Adding password_version column to users table")
                conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN password_version INTEGER NOT NULL DEFAULT 0"
                    )
                )
                conn.commit()

            if "azure_oid" not in users_columns:
                logger.info("Adding azure_oid column to users table")
                conn.execute(text("ALTER TABLE users ADD COLUMN azure_oid VARCHAR(64)"))
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_azure_oid "
                        "ON users (azure_oid) WHERE azure_oid IS NOT NULL"
                    )
                )
                conn.commit()

            if "azure_email" in users_columns:
                logger.info("Dropping azure_email column from users table")
                conn.execute(text("ALTER TABLE users DROP COLUMN IF EXISTS azure_email"))
                conn.commit()

            if "auth_provider" not in users_columns:
                logger.info("Adding auth_provider column to users table")
                conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN auth_provider VARCHAR(20) "
                        "NOT NULL DEFAULT 'local'"
                    )
                )
                conn.commit()

    # Schemas table migrations
    if "schemas" in table_names:
        # Get existing columns in schemas table
        existing_columns = {col["name"] for col in inspector.get_columns("schemas")}

        with engine.connect() as conn:
            # Add owner_id column if it doesn't exist
            if "owner_id" not in existing_columns:
                logger.info("Adding owner_id column to schemas table")
                conn.execute(text("ALTER TABLE schemas ADD COLUMN owner_id VARCHAR(36)"))
                conn.commit()

            # Add status column if it doesn't exist
            if "status" not in existing_columns:
                logger.info("Adding status column to schemas table")
                conn.execute(text("ALTER TABLE schemas ADD COLUMN status VARCHAR(20) DEFAULT 'published'"))
                conn.commit()
                # Update all existing schemas to be published
                conn.execute(text("UPDATE schemas SET status = 'published' WHERE status IS NULL"))
                conn.commit()

            # Add reviewed_by_id column if it doesn't exist
            if "reviewed_by_id" not in existing_columns:
                logger.info("Adding reviewed_by_id column to schemas table")
                conn.execute(text("ALTER TABLE schemas ADD COLUMN reviewed_by_id VARCHAR(36)"))
                conn.commit()

            # Add reviewed_at column if it doesn't exist
            if "reviewed_at" not in existing_columns:
                logger.info("Adding reviewed_at column to schemas table")
                conn.execute(text(f"ALTER TABLE schemas ADD COLUMN reviewed_at {datetime_type}"))
                conn.commit()

            # Add review_notes column if it doesn't exist
            if "review_notes" not in existing_columns:
                logger.info("Adding review_notes column to schemas table")
                conn.execute(text("ALTER TABLE schemas ADD COLUMN review_notes TEXT"))
                conn.commit()

            # Add submit_notes column if it doesn't exist
            if "submit_notes" not in existing_columns:
                logger.info("Adding submit_notes column to schemas table")
                conn.execute(text("ALTER TABLE schemas ADD COLUMN submit_notes TEXT"))
                conn.commit()

            # Add custom_instructions column if it doesn't exist
            if "custom_instructions" not in existing_columns:
                logger.info("Adding custom_instructions column to schemas table")
                conn.execute(text("ALTER TABLE schemas ADD COLUMN custom_instructions TEXT"))
                conn.commit()

            # Create indexes if they don't exist (PostgreSQL supports IF NOT EXISTS)
            try:
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_schemas_owner ON schemas (owner_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_schemas_status ON schemas (status)"))
                conn.commit()
            except Exception as e:
                logger.warning(f"Could not create indexes: {e}")

            logger.info("Schema migrations completed")

    # Jobs table migrations
    if "jobs" in table_names:
        jobs_columns = {col["name"] for col in inspector.get_columns("jobs")}

        with engine.connect() as conn:
            # Add workflow_id column if it doesn't exist
            if "workflow_id" not in jobs_columns:
                logger.info("Adding workflow_id column to jobs table")
                conn.execute(text("ALTER TABLE jobs ADD COLUMN workflow_id VARCHAR(36)"))
                conn.commit()

                # Create index for workflow_id
                try:
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_jobs_workflow ON jobs (workflow_id)"))
                    conn.commit()
                except Exception as e:
                    logger.warning(f"Could not create workflow_id index: {e}")

            # Add ocr_model_config column if it doesn't exist
            if "ocr_model_config" not in jobs_columns:
                logger.info("Adding ocr_model_config column to jobs table")
                conn.execute(text("ALTER TABLE jobs ADD COLUMN ocr_model_config JSON"))
                conn.commit()

            # Add document_cache_id column if it doesn't exist
            if "document_cache_id" not in jobs_columns:
                logger.info("Adding document_cache_id column to jobs table")
                conn.execute(text("ALTER TABLE jobs ADD COLUMN document_cache_id VARCHAR(36)"))
                conn.commit()

            # Add segmentation_cache_id column if it doesn't exist
            if "segmentation_cache_id" not in jobs_columns:
                logger.info("Adding segmentation_cache_id column to jobs table")
                conn.execute(text("ALTER TABLE jobs ADD COLUMN segmentation_cache_id VARCHAR(36)"))
                conn.commit()

            # Add ocr_text_storage_path column if it doesn't exist (Azure blob URL for OCR .md)
            if "ocr_text_storage_path" not in jobs_columns:
                logger.info("Adding ocr_text_storage_path column to jobs table")
                conn.execute(text("ALTER TABLE jobs ADD COLUMN ocr_text_storage_path VARCHAR(1024)"))
                conn.commit()

            # Add text_index_storage_path column if it doesn't exist (Azure blob URL for text-index JSON)
            if "text_index_storage_path" not in jobs_columns:
                logger.info("Adding text_index_storage_path column to jobs table")
                conn.execute(text("ALTER TABLE jobs ADD COLUMN text_index_storage_path VARCHAR(1024)"))
                conn.commit()

            if "final_response" not in jobs_columns:
                logger.info("Adding final_response column to jobs table")
                conn.execute(text("ALTER TABLE jobs ADD COLUMN final_response JSON"))
                conn.commit()


    # extraction_cache: extraction + optional final_response for workflow cache hits
    if "extraction_cache" in table_names:
        ext_columns = {col["name"] for col in inspector.get_columns("extraction_cache")}
        with engine.connect() as conn:
            if "final_response" not in ext_columns:
                logger.info("Adding final_response column to extraction_cache table")
                conn.execute(text("ALTER TABLE extraction_cache ADD COLUMN final_response JSON"))
                conn.commit()

    # document_cache: canonical OCR markdown blob URL for reuse (workflow cache hits)
    if "document_cache" in table_names:
        dc_columns = {col["name"] for col in inspector.get_columns("document_cache")}
        with engine.connect() as conn:
            if "ocr_text_storage_path" not in dc_columns:
                logger.info("Adding ocr_text_storage_path column to document_cache table")
                conn.execute(text("ALTER TABLE document_cache ADD COLUMN ocr_text_storage_path VARCHAR(1024)"))
                conn.commit()

    # Workflows table migrations
    if "workflows" in table_names:
        workflows_columns = {col["name"] for col in inspector.get_columns("workflows")}

        with engine.connect() as conn:
            # Add publish_status column if it doesn't exist
            if "publish_status" not in workflows_columns:
                logger.info("Adding publish_status column to workflows table")
                conn.execute(text("ALTER TABLE workflows ADD COLUMN publish_status VARCHAR(20) DEFAULT 'draft'"))
                conn.commit()
                # Update all existing workflows to be draft
                conn.execute(text("UPDATE workflows SET publish_status = 'draft' WHERE publish_status IS NULL"))
                conn.commit()

            # Add reviewed_by_id column if it doesn't exist
            if "reviewed_by_id" not in workflows_columns:
                logger.info("Adding reviewed_by_id column to workflows table")
                conn.execute(text("ALTER TABLE workflows ADD COLUMN reviewed_by_id VARCHAR(36)"))
                conn.commit()

            # Add reviewed_at column if it doesn't exist
            if "reviewed_at" not in workflows_columns:
                logger.info("Adding reviewed_at column to workflows table")
                conn.execute(text(f"ALTER TABLE workflows ADD COLUMN reviewed_at {datetime_type}"))
                conn.commit()

            # Add review_notes column if it doesn't exist
            if "review_notes" not in workflows_columns:
                logger.info("Adding review_notes column to workflows table")
                conn.execute(text("ALTER TABLE workflows ADD COLUMN review_notes TEXT"))
                conn.commit()

            # Add submit_notes column if it doesn't exist
            if "submit_notes" not in workflows_columns:
                logger.info("Adding submit_notes column to workflows table")
                conn.execute(text("ALTER TABLE workflows ADD COLUMN submit_notes TEXT"))
                conn.commit()

            # Add status_reason column if it doesn't exist
            if "status_reason" not in workflows_columns:
                logger.info("Adding status_reason column to workflows table")
                conn.execute(text("ALTER TABLE workflows ADD COLUMN status_reason TEXT"))
                conn.commit()

            # Add status_changed_by_id column if it doesn't exist
            if "status_changed_by_id" not in workflows_columns:
                logger.info("Adding status_changed_by_id column to workflows table")
                conn.execute(text("ALTER TABLE workflows ADD COLUMN status_changed_by_id VARCHAR(36)"))
                conn.commit()

            # Add status_changed_at column if it doesn't exist
            if "status_changed_at" not in workflows_columns:
                logger.info("Adding status_changed_at column to workflows table")
                conn.execute(text(f"ALTER TABLE workflows ADD COLUMN status_changed_at {datetime_type}"))
                conn.commit()

            # Add ocr_model_config column if it doesn't exist
            if "ocr_model_config" not in workflows_columns:
                logger.info("Adding ocr_model_config column to workflows table")
                conn.execute(text("ALTER TABLE workflows ADD COLUMN ocr_model_config JSON"))
                conn.commit()

            # Multi-document workflow: segmentation + per-segment extraction
            if "is_multidoc" not in workflows_columns:
                logger.info("Adding is_multidoc column to workflows table")
                conn.execute(text("ALTER TABLE workflows ADD COLUMN is_multidoc BOOLEAN DEFAULT FALSE NOT NULL"))
                conn.commit()

            if "segmentation_settings" not in workflows_columns:
                logger.info("Adding segmentation_settings column to workflows table")
                conn.execute(text("ALTER TABLE workflows ADD COLUMN segmentation_settings JSON"))
                conn.commit()

            # Create index for publish_status if it doesn't exist
            try:
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_workflows_publish_status ON workflows (publish_status)"))
                conn.commit()
            except Exception as e:
                logger.warning(f"Could not create publish_status index: {e}")

        logger.info("Workflows migrations completed")

    # Workflow API Keys table migrations
    if "workflow_api_keys" in table_names:
        api_keys_columns = {col["name"] for col in inspector.get_columns("workflow_api_keys")}

        with engine.connect() as conn:
            # Add encrypted_key column if it doesn't exist
            if "encrypted_key" not in api_keys_columns:
                logger.info("Adding encrypted_key column to workflow_api_keys table")
                conn.execute(text("ALTER TABLE workflow_api_keys ADD COLUMN encrypted_key VARCHAR(500)"))
                conn.commit()

        logger.info("Workflow API Keys migrations completed")

    # Segmentation Profiles table migrations
    if "segmentation_profiles" in table_names:
        seg_profiles_columns = {col["name"] for col in inspector.get_columns("segmentation_profiles")}

        with engine.connect() as conn:
            # Add default_detection_method column if it doesn't exist
            if "default_detection_method" not in seg_profiles_columns:
                logger.info("Adding default_detection_method column to segmentation_profiles table")
                conn.execute(text("ALTER TABLE segmentation_profiles ADD COLUMN default_detection_method VARCHAR(100)"))
                conn.commit()

            # Add ocr_method column if it doesn't exist
            if "ocr_method" not in seg_profiles_columns:
                logger.info("Adding ocr_method column to segmentation_profiles table")
                conn.execute(text("ALTER TABLE segmentation_profiles ADD COLUMN ocr_method VARCHAR(50)"))
                conn.commit()

        logger.info("Segmentation Profiles migrations completed")


def seed_segmentation_profiles():
    """
    Seed builtin segmentation profiles from code-defined profiles.

    This populates the database with system profiles on first run.
    Existing profiles are not overwritten to preserve user modifications.
    """
    from .models import SegmentationProfile

    try:
        # Import code-defined profiles
        from core.intelligence.segmentation.document_profiles import PROFILES
    except ImportError as e:
        logger.warning(f"Could not import document profiles for seeding: {e}")
        return

    db = SessionLocal()
    try:
        for name, profile in PROFILES.items():
            # Check if profile already exists
            existing = db.query(SegmentationProfile).filter(
                SegmentationProfile.name == name
            ).first()

            if existing:
                continue  # Don't overwrite user modifications

            # Convert code profile to DB format
            veto_fields = [
                {"name": k, "pattern": v[0], "bidirectional": v[1], "enabled": True}
                for k, v in profile.veto_fields.items()
            ]

            section_patterns = [
                {"pattern": p[0], "capture_group": p[1]}
                for p in profile.section_patterns
            ]

            start_keywords = [
                {"pattern": p[0], "confidence": p[1]}
                for p in profile.start_keywords
            ]

            supporting_fields = [
                {"name": k, "pattern": v}
                for k, v in profile.supporting_fields.items()
            ]

            db_profile = SegmentationProfile(
                id=name,  # Use name as ID for builtin profiles
                name=name,
                display_name=profile.display_name,
                description=profile.description,
                veto_fields=veto_fields,
                section_patterns=section_patterns,
                start_keywords=start_keywords,
                supporting_fields=supporting_fields,
                continuity_patterns=profile.continuity_patterns,
                enable_section_splitting=profile.enable_section_splitting,
                is_builtin=True
            )
            db.add(db_profile)
            logger.info(f"Seeded segmentation profile: {name}")

        db.commit()
        logger.info("Segmentation profiles seeding completed")
    except Exception as e:
        logger.error(f"Error seeding segmentation profiles: {e}")
        db.rollback()
    finally:
        db.close()


def init_db():
    """
    Initialize the database.

    Creates all tables if they don't exist, and runs migrations for existing tables.
    """
    # Run migrations first to add any new columns to existing tables
    run_migrations()

    # Then create any new tables
    Base.metadata.create_all(bind=engine)

    # Seed builtin segmentation profiles
    seed_segmentation_profiles()


def get_db():
    """
    Get database session.

    Yields a database session and ensures it's closed after use.
    Use as a FastAPI dependency.

    Example:
        @app.get("/items")
        def get_items(db: Session = Depends(get_db)):
            return db.query(Item).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def reset_db():
    """
    Reset the database.

    Drops all tables and recreates them. USE WITH CAUTION!
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
