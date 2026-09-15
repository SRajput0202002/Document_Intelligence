# Storage backends for extracted documents (e.g. Azure Blob)

from .blob_storage import (
    upload_document_for_job,
    read_blob_text,
    stream_blob_bytes,
    is_azure_storage_path,
    move_document_to_deleted,
)

__all__ = [
    "upload_document_for_job",
    "read_blob_text",
    "stream_blob_bytes",
    "is_azure_storage_path",
    "move_document_to_deleted",
]
