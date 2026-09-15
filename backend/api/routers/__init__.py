"""
API routers.

Each router handles a specific domain:
    - providers: OCR and LLM provider listing
    - extraction: Document extraction jobs
    - schemas: Custom schema management
    - jobs: Job history and status
    - websocket: Real-time updates
"""

from . import providers
from . import extraction
from . import schemas
from . import jobs
from . import websocket

__all__ = ["providers", "extraction", "schemas", "jobs", "websocket"]
