"""
Enhanced API for unified OCR extraction platform.

This package provides:
    - FastAPI application with WebSocket support
    - PostgreSQL database for job persistence
    - Azure Blob Storage for document storage
    - REST endpoints for providers, extraction, schemas
    - Real-time progress updates via WebSocket

Routers:
    - /api/providers - Provider listing and availability
    - /api/extract - Document extraction jobs
    - /api/schemas - Schema management
    - /api/jobs - Job history
    - /ws/jobs/{job_id} - WebSocket for real-time updates
"""

__version__ = "2.0.0"
