"""
Enhanced FastAPI application for unified OCR extraction platform.

This is the main entry point for the API server. It provides:
    - REST endpoints for providers, extraction, schemas, jobs
    - WebSocket support for real-time progress updates
    - PostgreSQL database for job persistence
    - Azure Blob Storage for document storage
    - CORS support for frontend integration

Run with:
    uvicorn api.main:app --reload --port 8001
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# Load .env file before any other imports that might need env vars
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")  # backend/.env

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .database.engine import init_db
from .database.crud import load_default_schemas, get_or_create_default_user, update_user_settings
from .database.models import DEFAULT_USER_SETTINGS
from .database import SessionLocal
from .routers import providers, extraction, schemas, jobs, websocket, users, auth, admin
from .routers import workflows, workflow_keys, workflow_api, document_router
from .routers import segmentation_profiles, compare

# Configure logging
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Reduce noise from verbose loggers
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
logging.getLogger("mistralai").setLevel(logging.WARNING)
logging.getLogger("pdfminer").setLevel(logging.WARNING)
logging.getLogger("api.routers.websocket").setLevel(logging.WARNING)
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("websockets.server").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)
# Suppress Azure SDK verbose logging
logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("azure.core").setLevel(logging.WARNING)
logging.getLogger("azure.core.pipeline").setLevel(logging.WARNING)
logging.getLogger("azure.core.pipeline.policies").setLevel(logging.WARNING)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
# Suppress Mistral SDK OpenTelemetry warnings
logging.getLogger("mistralai.extra").setLevel(logging.ERROR)
logging.getLogger("mistralai.extra.observability").setLevel(logging.ERROR)
logging.getLogger("mistralai.extra.observability.otel").setLevel(logging.ERROR)
logging.getLogger("opentelemetry").setLevel(logging.ERROR)
# Suppress AGUI event noise
logging.getLogger("core.agents.events").setLevel(logging.WARNING)

# Custom uvicorn log config to suppress WebSocket noise
UVICORN_LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "WARNING"},
        "uvicorn.error": {"handlers": ["default"], "level": "WARNING"},
        "uvicorn.access": {"handlers": ["default"], "level": "WARNING"},
    },
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan events.

    Runs on startup and shutdown.
    """
    # Startup
    logger.info("Starting up OCR extraction API...")

    # Initialize database
    init_db()
    logger.info("Database initialized")

    # Sync default user settings (default schemas loading disabled)
    db = SessionLocal()
    try:
        # load_default_schemas(db)  # Disabled - BE/SB schemas removed
        # logger.info("Default schemas loaded")

        # Ensure default user has current defaults applied
        default_user = get_or_create_default_user(db)
        current_settings = default_user.settings or {}

        # Log current settings for debugging (classifier id + actual Azure deployment)
        from core.utils.azure_chat import get_azure_deployment
        logger.info(
            "Default user settings: document_classifier=%s (Azure deployment=%s)",
            current_settings.get("document_classifier"),
            get_azure_deployment(),
        )

        # Check if settings need updating with new default keys
        needs_update = False
        for key, default_value in DEFAULT_USER_SETTINGS.items():
            if key not in current_settings:
                needs_update = True
                break

        if needs_update:
            # Merge with defaults (existing values take precedence)
            merged_settings = DEFAULT_USER_SETTINGS.copy()
            merged_settings.update(current_settings)
            update_user_settings(db, default_user.id, merged_settings, merge=False)
            logger.info("Updated default user settings with new default keys")
    finally:
        db.close()

    yield

    # Shutdown
    logger.info("Shutting down...")


# Create FastAPI app
# Note: redirect_slashes=False prevents 307 redirects when behind a reverse proxy
# that terminates SSL (like Azure Container Apps), which would redirect to HTTP
app = FastAPI(
    title="OCR Extraction Platform",
    redirect_slashes=False,
    description="""
    Unified document extraction platform with multiple OCR and LLM providers.

    ## Features
    - Mix-and-match OCR providers (Mistral, PaddleOCR, Marker, Surya, Chandra)
    - Mix-and-match LLM extractors (NuExtract, Ollama, Azure OpenAI, Mistral, Gemini)
    - Real-time extraction progress via WebSocket
    - Custom schema support
    - Job history and persistence

    ## Endpoints
    - `/api/providers` - List available providers
    - `/api/extract` - Run document extraction
    - `/api/schemas` - Manage extraction schemas
    - `/api/jobs` - View job history
    - `/api/compare/fields` - Soft-match fields between two documents
    - `/ws/jobs/{job_id}` - WebSocket for real-time updates
    """,
    version="2.0.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify allowed origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])
app.include_router(providers.router, prefix="/api/providers", tags=["Providers"])
app.include_router(extraction.router, prefix="/api/extract", tags=["Extraction"])
app.include_router(schemas.router, prefix="/api/schemas", tags=["Schemas"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["Jobs"])
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(segmentation_profiles.router, prefix="/api/segmentation-profiles", tags=["Segmentation Profiles"])
app.include_router(websocket.router, tags=["WebSocket"])

# Workflow API routers
app.include_router(workflows.router, prefix="/api/workflows", tags=["Workflows"])
app.include_router(workflow_keys.router, prefix="/api/workflows", tags=["Workflow API Keys"])
app.include_router(workflow_api.router, prefix="/api/v1/workflows", tags=["Workflow External API"])
app.include_router(document_router.router, prefix="/api/document-router", tags=["Document router"])
app.include_router(compare.router, prefix="/api/compare", tags=["Field Comparison"])

# Mount static files for frontend
STATIC_DIR = Path(__file__).parent.parent.parent / "frontend" / "out"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", include_in_schema=False)
async def root():
    """
    Serve frontend or API info.
    """
    # Try to serve Next.js frontend
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))

    # Return API info
    return {
        "name": "OCR Extraction Platform",
        "version": "2.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "endpoints": {
            "providers": "/api/providers",
            "extract": "/api/extract",
            "schemas": "/api/schemas",
            "jobs": "/api/jobs",
        },
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


# =============================================================================
# Run with: uvicorn api.main:app --reload --port 8001
# =============================================================================
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_config=UVICORN_LOG_CONFIG,
    )
