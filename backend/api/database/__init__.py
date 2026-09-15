"""
Database module for job persistence.

Uses PostgreSQL with SQLAlchemy ORM.
"""

from .engine import get_db, init_db, SessionLocal, engine
from .models import (
    Job, JobPart, Schema, Base, PromptLib, PromptCategory,
    Workflow, WorkflowCollaborator, WorkflowApiKey, WorkflowUsageLog,
    WorkflowStatus, WorkflowResponseMode, WorkflowCollaboratorRole,
)
from .crud import (
    create_job,
    get_job,
    update_job,
    delete_job,
    list_jobs,
    create_job_part,
    update_job_part,
    get_job_parts,
    create_schema,
    get_schema,
    list_schemas,
    get_default_schemas,
)

__all__ = [
    "get_db",
    "init_db",
    "SessionLocal",
    "engine",
    "Job",
    "JobPart",
    "Schema",
    "Base",
    "PromptLib",
    "PromptCategory",
    "Workflow",
    "WorkflowCollaborator",
    "WorkflowApiKey",
    "WorkflowUsageLog",
    "WorkflowStatus",
    "WorkflowResponseMode",
    "WorkflowCollaboratorRole",
    "create_job",
    "get_job",
    "update_job",
    "delete_job",
    "list_jobs",
    "create_job_part",
    "update_job_part",
    "get_job_parts",
    "create_schema",
    "get_schema",
    "list_schemas",
    "get_default_schemas",
]
