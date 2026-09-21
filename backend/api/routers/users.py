"""
User Settings API Endpoints.

Provides endpoints for managing user settings including:
- Document classifier selection
- PDF extractor preference
- Fallback OCR provider
- Default providers for extraction
- UI preferences
- Processing options
"""

import logging
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db, crud
from ..database.models import DEFAULT_USER_SETTINGS, User
from ..auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Pydantic Models
# =============================================================================

class UserSettings(BaseModel):
    """User settings model with all configurable options."""
    # Document Classification Settings
    document_classifier: Optional[str] = None  # gemini, gpt-5.5, mistral, pattern, custom
    pdf_extractor: Optional[str] = None        # pymupdf4llm, pymupdf, pdfplumber, pypdf
    fallback_ocr: Optional[str] = None         # mistral, paddle, azure, marker, surya
    min_text_threshold: Optional[int] = None   # Minimum chars before falling back to OCR

    # Default Extraction Providers
    default_ocr_provider: Optional[str] = None
    default_llm_provider: Optional[str] = None

    # Consensus Extraction Settings
    consensus_enabled: Optional[bool] = None
    consensus_ocr_providers: Optional[List[str]] = None
    consensus_llm_providers: Optional[List[str]] = None
    consensus_threshold: Optional[float] = None

    # UI Preferences
    theme: Optional[str] = None  # light, dark, system
    compact_view: Optional[bool] = None
    show_confidence_scores: Optional[bool] = None
    auto_expand_results: Optional[bool] = None

    # Processing Options
    auto_detect_document_type: Optional[bool] = None
    auto_infer_schema: Optional[bool] = None
    save_ocr_text: Optional[bool] = None
    max_pages_for_classification: Optional[int] = None


class UserResponse(BaseModel):
    """Response model for user data."""
    id: str
    username: str
    email: Optional[str]
    display_name: Optional[str]
    settings: Dict[str, Any]
    is_active: bool
    created_at: Optional[str]
    updated_at: Optional[str]


class SettingsResponse(BaseModel):
    """Response model for settings only."""
    settings: Dict[str, Any]
    defaults: Dict[str, Any]


class SettingsUpdateRequest(BaseModel):
    """Request model for updating settings."""
    settings: Dict[str, Any]
    merge: bool = True  # If true, merge with existing. If false, replace.


# =============================================================================
# Settings Endpoints (for current/default user)
# =============================================================================

@router.get("/settings", response_model=SettingsResponse)
async def get_current_settings(
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Get current user's settings.

    Returns the settings for the authenticated user, or default user if not logged in.
    Includes both current settings and default values for reference.
    """
    if current_user:
        user = current_user
        logger.info(f"[GET /settings] Using authenticated user: {user.username}")
    else:
        user = crud.get_or_create_default_user(db)
        logger.info(f"[GET /settings] Using default user: {user.username}")

    # Log the raw settings for debugging
    logger.info(f"[GET /settings] Raw user.settings: {user.settings}")
    logger.info(f"[GET /settings] document_classifier in settings: {user.settings.get('document_classifier') if user.settings else 'N/A'}")

    # ALWAYS merge user settings with defaults to return complete settings
    # This ensures all keys are present even if user has partial settings
    merged_settings = DEFAULT_USER_SETTINGS.copy()
    if user.settings:
        merged_settings.update(user.settings)

    return {
        "settings": merged_settings,
        "defaults": DEFAULT_USER_SETTINGS.copy(),
    }


@router.put("/settings", response_model=SettingsResponse)
async def update_current_settings(
    request: SettingsUpdateRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Update current user's settings.

    By default, merges the provided settings with existing settings.
    Set merge=false to replace all settings entirely.
    """
    if current_user:
        user = current_user
    else:
        user = crud.get_or_create_default_user(db)

    updated_user = crud.update_user_settings(
        db,
        user.id,
        request.settings,
        merge=request.merge,
    )

    if not updated_user:
        raise HTTPException(status_code=500, detail="Failed to update settings")

    return {
        "settings": updated_user.settings,
        "defaults": DEFAULT_USER_SETTINGS.copy(),
    }


@router.patch("/settings", response_model=SettingsResponse)
async def patch_current_settings(
    settings: UserSettings,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Partially update current user's settings.

    Only updates the fields that are provided (non-null).
    """
    if current_user:
        user = current_user
    else:
        user = crud.get_or_create_default_user(db)

    # Convert to dict, excluding None values
    updates = {k: v for k, v in settings.model_dump().items() if v is not None}

    if not updates:
        return {
            "settings": user.settings or DEFAULT_USER_SETTINGS.copy(),
            "defaults": DEFAULT_USER_SETTINGS.copy(),
        }

    updated_user = crud.update_user_settings(db, user.id, updates, merge=True)

    if not updated_user:
        raise HTTPException(status_code=500, detail="Failed to update settings")

    return {
        "settings": updated_user.settings,
        "defaults": DEFAULT_USER_SETTINGS.copy(),
    }


@router.post("/settings/reset", response_model=SettingsResponse)
async def reset_current_settings(
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Reset current user's settings to defaults.
    """
    if current_user:
        user = current_user
    else:
        user = crud.get_or_create_default_user(db)

    updated_user = crud.reset_user_settings(db, user.id)

    if not updated_user:
        raise HTTPException(status_code=500, detail="Failed to reset settings")

    return {
        "settings": updated_user.settings,
        "defaults": DEFAULT_USER_SETTINGS.copy(),
    }


# =============================================================================
# Debug Endpoint for Settings (MUST be before /settings/{key} to avoid conflict)
# =============================================================================

@router.get("/settings/debug")
async def debug_current_settings(
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Debug endpoint to see exactly what settings are stored in the database.

    Returns both the raw stored settings and the effective settings after defaults.
    Useful for debugging settings synchronization issues.
    """
    if current_user:
        user = current_user
    else:
        user = crud.get_or_create_default_user(db)

    raw_settings = user.settings
    effective_settings = user.settings or {}

    # Show which values come from defaults vs stored
    settings_source = {}
    for key in DEFAULT_USER_SETTINGS:
        if raw_settings and key in raw_settings:
            settings_source[key] = {
                "value": raw_settings[key],
                "source": "stored",
            }
        else:
            settings_source[key] = {
                "value": DEFAULT_USER_SETTINGS[key],
                "source": "default",
            }

    return {
        "user_id": user.id,
        "username": user.username,
        "raw_settings": raw_settings,
        "defaults": DEFAULT_USER_SETTINGS,
        "settings_source": settings_source,
        "critical_for_schema_inference": {
            "document_classifier": effective_settings.get("document_classifier", DEFAULT_USER_SETTINGS["document_classifier"]),
            "mapped_llm_provider": {
                "gpt-5.5": "azure_openai",
                "gpt-4o": "azure_openai",  # legacy alias
                "gemini": "gemini",
                "mistral": "mistral_chat",
            }.get(
                effective_settings.get("document_classifier", DEFAULT_USER_SETTINGS["document_classifier"]),
                "azure_openai"
            ),
        },
    }


@router.get("/settings/{key}")
async def get_setting_value(
    key: str,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Get a specific setting value.

    Returns the value for the given setting key, or the default if not set.
    """
    if key not in DEFAULT_USER_SETTINGS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown setting key: {key}. Valid keys: {list(DEFAULT_USER_SETTINGS.keys())}"
        )

    if current_user:
        user = current_user
    else:
        user = crud.get_or_create_default_user(db)
    value = crud.get_user_setting(db, user.id, key)

    return {
        "key": key,
        "value": value,
        "default": DEFAULT_USER_SETTINGS.get(key),
    }


# =============================================================================
# Settings Options (MUST be before /{user_id} to avoid route conflict)
# =============================================================================

@router.get("/settings-options")
async def get_settings_options(db: Session = Depends(get_db)):
    """
    Get available options for all configurable settings.

    Returns a list of valid values for each setting that has
    predefined options (like document_classifier, pdf_extractor, etc.)
    """
    # Get available providers from registry
    try:
        from core.registry import ProviderRegistry
        ocr_providers = ProviderRegistry.list_ocr_providers()
        llm_providers = ProviderRegistry.list_llm_providers()

        available_ocr = [p["name"] if isinstance(p, dict) else p.name for p in ocr_providers]
        available_llm = [p["name"] if isinstance(p, dict) else p.name for p in llm_providers]
    except Exception as e:
        logger.warning(f"Could not load providers: {e}")
        available_ocr = ["mistral", "paddle", "azure", "marker", "surya", "pymupdf", "pymupdf4llm", "pdfplumber", "pypdf"]
        available_llm = ["nuextract", "mistral_chat", "gemini", "azure_openai"]

    return {
        "document_classifier": {
            "options": ["pattern", "gpt-5.5", "gemini", "mistral", "custom"],
            "description": "AI model for document type detection and schema generation",
            "default": DEFAULT_USER_SETTINGS["document_classifier"],
            "note": "This model is also used for automatic schema inference",
        },
        "pdf_extractor": {
            "options": ["pymupdf4llm", "pymupdf", "pdfplumber", "pypdf"],
            "description": "PDF text extraction library for initial parsing",
            "default": DEFAULT_USER_SETTINGS["pdf_extractor"],
        },
        "fallback_ocr": {
            "options": available_ocr,
            "description": "OCR provider for scanned documents and schema inference",
            "default": DEFAULT_USER_SETTINGS["fallback_ocr"],
            "note": "Also used as the default OCR for schema generation",
        },
        "default_ocr_provider": {
            "options": available_ocr,
            "description": "Default OCR provider for document extraction",
            "default": DEFAULT_USER_SETTINGS["default_ocr_provider"],
        },
        "default_llm_provider": {
            "options": available_llm,
            "description": "Default LLM provider for structured data extraction",
            "default": DEFAULT_USER_SETTINGS["default_llm_provider"],
        },
        "consensus_ocr_providers": {
            "options": available_ocr,
            "description": "OCR providers to use for consensus extraction",
            "default": DEFAULT_USER_SETTINGS["consensus_ocr_providers"],
            "multi_select": True,
        },
        "consensus_llm_providers": {
            "options": available_llm,
            "description": "LLM providers to use for consensus extraction",
            "default": DEFAULT_USER_SETTINGS["consensus_llm_providers"],
            "multi_select": True,
        },
        "theme": {
            "options": ["light", "dark", "system"],
            "description": "UI color theme",
            "default": DEFAULT_USER_SETTINGS["theme"],
        },
    }


# =============================================================================
# User Management Endpoints (for future multi-user support)
# IMPORTANT: These routes with {user_id} MUST be LAST to avoid matching other routes
# =============================================================================

@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Get current user's profile and settings.
    """
    if current_user:
        user = current_user
    else:
        user = crud.get_or_create_default_user(db)
    return user.to_dict()


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: str, db: Session = Depends(get_db)):
    """
    Get a user by ID.
    """
    user = crud.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user.to_dict()


@router.get("/{user_id}/settings", response_model=SettingsResponse)
async def get_user_settings(user_id: str, db: Session = Depends(get_db)):
    """
    Get a specific user's settings.
    """
    user = crud.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "settings": user.settings or DEFAULT_USER_SETTINGS.copy(),
        "defaults": DEFAULT_USER_SETTINGS.copy(),
    }


@router.put("/{user_id}/settings", response_model=SettingsResponse)
async def update_user_settings(
    user_id: str,
    request: SettingsUpdateRequest,
    db: Session = Depends(get_db),
):
    """
    Update a specific user's settings.
    """
    user = crud.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    updated_user = crud.update_user_settings(
        db,
        user_id,
        request.settings,
        merge=request.merge,
    )

    if not updated_user:
        raise HTTPException(status_code=500, detail="Failed to update settings")

    return {
        "settings": updated_user.settings,
        "defaults": DEFAULT_USER_SETTINGS.copy(),
    }
