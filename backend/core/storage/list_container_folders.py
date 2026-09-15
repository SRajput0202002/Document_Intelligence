"""
List folders (prefixes) and files in the Azure Blob Storage documents container.

Run from backend directory:
  python -m core.storage.list_container_folders

Requires: azure-storage-blob (and python-dotenv if you use .env).
"""

import os
import sys
from collections import defaultdict
from pathlib import Path

# Load .env from backend directory so env vars are available when run from anywhere
_backend_dir = Path(__file__).resolve().parent.parent.parent
_env_file = _backend_dir / ".env"
if _env_file.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_file)
    except ImportError:
        pass

CONNECTION_STRING_KEY = "AZURE_STORAGE_CONNECTION_STRING"
CONTAINER_KEY = "AZURE_STORAGE_DOCUMENTS_CONTAINER"
DEFAULT_CONTAINER = "idp-docstore"


def main():
    conn_str = os.environ.get(CONNECTION_STRING_KEY)
    container_name = (os.environ.get(CONTAINER_KEY) or DEFAULT_CONTAINER).strip()

    if not conn_str or not container_name:
        print("Set AZURE_STORAGE_CONNECTION_STRING and optionally AZURE_STORAGE_DOCUMENTS_CONTAINER")
        print("(e.g. in backend/.env)")
        sys.exit(1)

    from azure.storage.blob import BlobServiceClient

    client = BlobServiceClient.from_connection_string(conn_str)
    container = client.get_container_client(container_name)

    # folders[folder_name] = list of (subpath, full blob name)
    folders = defaultdict(list)

    for blob in container.list_blobs(name_starts_with=None):
        name = blob.name
        parts = name.split("/")
        if len(parts) >= 2:
            folder = parts[0]
            subpath = "/".join(parts[1:])
            folders[folder].append((subpath, name))
        else:
            folders["(root)"].append((name, name))

    print(f"Container: {container_name}\n")
    for folder in sorted(folders.keys()):
        print(f"  [{folder}]")
        for subpath, blob_name in sorted(folders[folder], key=lambda x: x[0]):
            print(f"    {blob_name}")
        print()

    print("Summary:")
    for folder in sorted(folders.keys()):
        print(f"  {folder}: {len(folders[folder])} blob(s)")


if __name__ == "__main__":
    main()
