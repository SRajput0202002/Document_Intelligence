"""
Azure Blob Storage helper for extracted documents.

Uploads documents after extraction and streams them for the "get document" endpoint.
"""

import logging
import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional, Iterator
from urllib.parse import urlparse, unquote

logger = logging.getLogger(__name__)

# Env keys
CONNECTION_STRING_KEY = "AZURE_STORAGE_CONNECTION_STRING"
CONTAINER_KEY = "AZURE_STORAGE_DOCUMENTS_CONTAINER"
DEFAULT_CONTAINER = "idp-docstore"


def _is_configured() -> bool:
    """Return True if Azure Blob Storage is configured."""
    conn_str = os.environ.get(CONNECTION_STRING_KEY)
    container = os.environ.get(CONTAINER_KEY, DEFAULT_CONTAINER).strip()
    return bool(conn_str and container)


def _get_container_name() -> str:
    return os.environ.get(CONTAINER_KEY, DEFAULT_CONTAINER).strip()


def is_azure_storage_path(path: Optional[str]) -> bool:
    """
    Return True if the given path is an Azure Blob reference (URL).
    Used to identify Azure Blob URLs when serving documents.
    """
    if not path:
        return False
    return path.startswith("https://") and ".blob.core.windows.net" in path


def upload_document_for_job(
    local_file_path: Path,
    job_id: str,
    filename: str,
) -> Optional[str]:
    """
    Upload a document to Azure Blob Storage for a job.

    Blob path: jobs/{job_id}/{filename}

    Azure Blob Storage must be configured via AZURE_STORAGE_CONNECTION_STRING.
    Returns the blob URL if successful, None if not configured or upload failed.
    """
    if not _is_configured():
        return None

    conn_str = os.environ.get(CONNECTION_STRING_KEY)
    container_name = _get_container_name()
    blob_name = f"jobs/{job_id}/{filename}"

    try:
        from azure.storage.blob import BlobServiceClient

        service = BlobServiceClient.from_connection_string(conn_str)
        container = service.get_container_client(container_name)
        blob_client = container.get_blob_client(blob_name)

        with open(local_file_path, "rb") as f:
            blob_client.upload_blob(f, overwrite=True)

        return blob_client.url
    except Exception as e:
        logger.warning("Azure Blob upload failed: %s", e, exc_info=True)
        return None


def read_blob_text(blob_url: str) -> str:
    """
    Download full blob content and decode as UTF-8 text.

    Used for small artifacts like OCR markdown (not for large streaming downloads).
    """
    data = b"".join(stream_blob_bytes(blob_url))
    return data.decode("utf-8")


def stream_blob_bytes(blob_url: str) -> Iterator[bytes]:
    """
    Stream blob content as bytes. Yields chunks for use with StreamingResponse.

    Uses connection string for auth; parses blob_url to get container and blob path.
    """
    conn_str = os.environ.get(CONNECTION_STRING_KEY)
    if not conn_str:
        raise ValueError("AZURE_STORAGE_CONNECTION_STRING not set")

    # Parse URL: https://<account>.blob.core.windows.net/<container>/<blob_path>
    parsed = urlparse(blob_url)
    path_parts = parsed.path.lstrip("/").split("/", 1)
    if len(path_parts) != 2:
        raise ValueError(f"Invalid blob URL: {blob_url}")
    container_name = path_parts[0]
    blob_path = unquote(path_parts[1])  # decode %23 -> # etc. so path matches upload

    from azure.storage.blob import BlobServiceClient

    service = BlobServiceClient.from_connection_string(conn_str)
    container = service.get_container_client(container_name)
    blob_client = container.get_blob_client(blob_path)
    downloader = blob_client.download_blob()
    yield from downloader.chunks()


def move_document_to_deleted(blob_url: str) -> bool:
    """
    Move a document blob from jobs/{job_id}/{filename} to deleted_jobs/{job_id}/{filename}.

    Uses download + upload (stream through app), then deletes the source blob.
    Returns True on success, False on failure or if not configured.
    """
    if not _is_configured():
        return False

    conn_str = os.environ.get(CONNECTION_STRING_KEY)
    parsed = urlparse(blob_url)
    path_parts = parsed.path.lstrip("/").split("/", 1)
    if len(path_parts) != 2:
        logger.warning("move_document_to_deleted: invalid blob URL %s", blob_url)
        return False

    container_name = path_parts[0]
    blob_path = unquote(path_parts[1])

    if not blob_path.startswith("jobs/"):
        logger.debug("move_document_to_deleted: path does not start with jobs/, skipping: %s", blob_path)
        return False

    # deleted_jobs/{job_id}/{filename}
    new_blob_path = "deleted_jobs/" + blob_path[len("jobs/"):]

    try:
        from azure.storage.blob import BlobServiceClient

        service = BlobServiceClient.from_connection_string(conn_str)
        container = service.get_container_client(container_name)
        source_client = container.get_blob_client(blob_path)
        dest_client = container.get_blob_client(new_blob_path)

        downloader = source_client.download_blob()
        dest_client.upload_blob(downloader.readall(), overwrite=True)
        source_client.delete_blob()
        logger.info("Moved blob to deleted_jobs: %s -> %s", blob_path, new_blob_path)
        return True
    except Exception as e:
        logger.warning("move_document_to_deleted failed: %s", e, exc_info=True)
        return False


def download_blob_to_temp(blob_url: str, temp_dir: Optional[Path] = None) -> Optional[str]:
    """
    Download a document from Azure Blob Storage to a temporary file.

    Used for retry operations where the original document needs to be
    re-processed but only exists in Azure Blob Storage.

    Args:
        blob_url: The Azure Blob URL of the document
        temp_dir: Optional directory to store the temp file.
                  If not provided, uses system temp directory.

    Returns:
        Path to the downloaded temp file, or None if download failed.
        The caller is responsible for cleaning up the temp file.
    """
    if not _is_configured():
        logger.error("download_blob_to_temp: Azure Blob Storage not configured")
        return None

    if not is_azure_storage_path(blob_url):
        logger.error(f"download_blob_to_temp: Invalid Azure Blob URL: {blob_url}")
        return None

    conn_str = os.environ.get(CONNECTION_STRING_KEY)
    if not conn_str:
        logger.error("download_blob_to_temp: AZURE_STORAGE_CONNECTION_STRING not set")
        return None

    # Parse URL to get blob path and extract filename
    parsed = urlparse(blob_url)
    path_parts = parsed.path.lstrip("/").split("/", 1)
    if len(path_parts) != 2:
        logger.error(f"download_blob_to_temp: Invalid blob URL format: {blob_url}")
        return None

    container_name = path_parts[0]
    blob_path = unquote(path_parts[1])

    # Extract filename from blob path (e.g., "jobs/{job_id}/{filename}" -> "{filename}")
    filename = Path(blob_path).name

    # Determine temp directory
    if temp_dir:
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / f"{uuid.uuid4().hex[:8]}_{filename}"
    else:
        # Use system temp directory with unique prefix
        temp_fd, temp_path_str = tempfile.mkstemp(suffix=f"_{filename}")
        os.close(temp_fd)
        temp_path = Path(temp_path_str)

    try:
        from azure.storage.blob import BlobServiceClient

        service = BlobServiceClient.from_connection_string(conn_str)
        container = service.get_container_client(container_name)
        blob_client = container.get_blob_client(blob_path)

        # Download blob to temp file
        with open(temp_path, "wb") as f:
            downloader = blob_client.download_blob()
            for chunk in downloader.chunks():
                f.write(chunk)

        logger.info(f"Downloaded blob to temp file: {blob_url} -> {temp_path}")
        return str(temp_path)

    except Exception as e:
        logger.error(f"download_blob_to_temp failed: {e}", exc_info=True)
        # Clean up partial file if it exists
        if temp_path.exists():
            temp_path.unlink()
        return None
