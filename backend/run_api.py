#!/usr/bin/env python3
"""
Run the API server with proper logging configuration.

IMPORTANT: Run this script using the virtual environment's Python:
    ./venv/bin/python run_api.py

Or activate the venv first:
    source venv/bin/activate
    python run_api.py

This script properly configures uvicorn to suppress verbose WebSocket and HTTP logs
while still showing important application logs.
"""

import uvicorn
from pathlib import Path

# Load environment variables
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

# Custom uvicorn log config to suppress WebSocket noise
UVICORN_LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        },
        "access": {
            "format": "%(asctime)s - %(levelname)s - %(message)s",
        },
    },
    "handlers": {
        "default": {
            "formatter": "default",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
        },
        "access": {
            "formatter": "access",
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "WARNING", "propagate": False},
        "uvicorn.error": {"handlers": ["default"], "level": "WARNING", "propagate": False},
        "uvicorn.access": {"handlers": ["access"], "level": "WARNING", "propagate": False},
    },
}

if __name__ == "__main__":
    print("Starting OCR Extraction API on http://localhost:8001")
    print("API docs available at http://localhost:8001/docs")
    print("-" * 50)

    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_config=UVICORN_LOG_CONFIG,
        log_level="warning",  # Suppress uvicorn's own startup logs
    )
