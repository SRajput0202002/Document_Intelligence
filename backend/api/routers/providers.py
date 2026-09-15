"""
Provider endpoints.

Lists available OCR processors and LLM extractors with their status.
Manages provider configurations (API keys, settings).
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.database.engine import get_db
from api.database import crud

logger = logging.getLogger(__name__)

router = APIRouter()


class ProviderInfo(BaseModel):
    """Provider information model."""
    name: str
    display_name: str
    description: str
    provider_type: str  # local or cloud
    cost_tier: str  # free, low, medium, high
    requires_api_key: bool
    api_key_env_var: Optional[str] = None
    is_available: bool
    error: Optional[str] = None
    capabilities: List[str] = []
    config_options: dict = {}


class ProvidersResponse(BaseModel):
    """Response model for provider listing."""
    ocr_providers: List[ProviderInfo]
    llm_providers: List[ProviderInfo]


@router.get("", response_model=ProvidersResponse)
async def list_providers():
    """
    List all available OCR and LLM providers.

    Returns providers with their availability status, cost tier,
    and capabilities.
    """
    try:
        from core.registry import ProviderRegistry

        ocr_list = ProviderRegistry.list_ocr_providers()
        llm_list = ProviderRegistry.list_llm_providers()

        return {
            "ocr_providers": [p.to_dict() for p in ocr_list],
            "llm_providers": [p.to_dict() for p in llm_list],
        }
    except Exception as e:
        logger.error(f"Failed to list providers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ocr", response_model=List[ProviderInfo])
async def list_ocr_providers():
    """List available OCR providers."""
    try:
        from core.registry import ProviderRegistry

        providers = ProviderRegistry.list_ocr_providers()
        return [p.to_dict() for p in providers]
    except Exception as e:
        logger.error(f"Failed to list OCR providers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm", response_model=List[ProviderInfo])
async def list_llm_providers():
    """List available LLM providers."""
    try:
        from core.registry import ProviderRegistry

        providers = ProviderRegistry.list_llm_providers()
        return [p.to_dict() for p in providers]
    except Exception as e:
        logger.error(f"Failed to list LLM providers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ocr/{name}", response_model=ProviderInfo)
async def get_ocr_provider(name: str):
    """Get details for a specific OCR provider."""
    try:
        from core.registry import ProviderRegistry

        providers = ProviderRegistry.list_ocr_providers()
        for p in providers:
            if p.name == name:
                return p.to_dict()

        raise HTTPException(status_code=404, detail=f"OCR provider not found: {name}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get OCR provider {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/llm/{name}", response_model=ProviderInfo)
async def get_llm_provider(name: str):
    """Get details for a specific LLM provider."""
    try:
        from core.registry import ProviderRegistry

        providers = ProviderRegistry.list_llm_providers()
        for p in providers:
            if p.name == name:
                return p.to_dict()

        raise HTTPException(status_code=404, detail=f"LLM provider not found: {name}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get LLM provider {name}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =============================================================================
# Provider Configuration Endpoints
# =============================================================================

class ProviderConfigCreate(BaseModel):
    """Request model for creating/updating provider config."""
    provider_name: str
    provider_type: str  # 'ocr' or 'llm'
    display_name: Optional[str] = None
    config: Dict[str, Any]  # {api_key, model, options...}
    is_enabled: bool = True


class ProviderConfigUpdate(BaseModel):
    """Request model for updating provider config."""
    display_name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    is_enabled: Optional[bool] = None


class ProviderConfigResponse(BaseModel):
    """Response model for provider config."""
    id: str
    provider_name: str
    provider_type: str
    display_name: Optional[str]
    config: Dict[str, Any]  # API key is masked
    has_api_key: bool
    is_enabled: bool
    last_test_at: Optional[str]
    last_test_success: Optional[bool]
    created_at: Optional[str]
    updated_at: Optional[str]


class TestConnectionRequest(BaseModel):
    """Request model for testing provider connection."""
    provider_name: str
    provider_type: str  # 'ocr' or 'llm'
    api_key: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class TestConnectionResponse(BaseModel):
    """Response model for connection test."""
    success: bool
    message: str
    response_time_ms: Optional[float] = None


@router.get("/configs", response_model=List[ProviderConfigResponse])
async def list_provider_configs(
    provider_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    List all provider configurations.

    Args:
        provider_type: Filter by 'ocr' or 'llm'
    """
    configs = crud.list_provider_configs(db, provider_type=provider_type)
    return [c.to_dict() for c in configs]


@router.post("/configs", response_model=ProviderConfigResponse)
async def create_provider_config(
    request: ProviderConfigCreate,
    db: Session = Depends(get_db),
):
    """
    Create or update a provider configuration.

    If a config with the same provider_name exists, it will be updated.
    """
    try:
        config = crud.create_provider_config(
            db,
            provider_name=request.provider_name,
            provider_type=request.provider_type,
            config=request.config,
            display_name=request.display_name,
            is_enabled=request.is_enabled,
        )
        return config.to_dict()
    except Exception as e:
        logger.error(f"Failed to create provider config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/configs/{config_id}", response_model=ProviderConfigResponse)
async def get_provider_config(
    config_id: str,
    db: Session = Depends(get_db),
):
    """Get a provider configuration by ID."""
    config = crud.get_provider_config(db, config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Provider config not found")
    return config.to_dict()


@router.put("/configs/{config_id}", response_model=ProviderConfigResponse)
async def update_provider_config(
    config_id: str,
    request: ProviderConfigUpdate,
    db: Session = Depends(get_db),
):
    """Update a provider configuration."""
    config = crud.update_provider_config(
        db,
        config_id,
        config=request.config,
        display_name=request.display_name,
        is_enabled=request.is_enabled,
    )
    if not config:
        raise HTTPException(status_code=404, detail="Provider config not found")
    return config.to_dict()


@router.delete("/configs/{config_id}")
async def delete_provider_config(
    config_id: str,
    db: Session = Depends(get_db),
):
    """Delete a provider configuration."""
    success = crud.delete_provider_config(db, config_id)
    if not success:
        raise HTTPException(status_code=404, detail="Provider config not found")
    return {"message": "Provider config deleted"}


@router.post("/test", response_model=TestConnectionResponse)
async def test_provider_connection(
    request: TestConnectionRequest,
    db: Session = Depends(get_db),
):
    """
    Test a provider connection.

    Tests the provider with provided credentials or saved config.
    """
    import time

    start_time = time.time()

    try:
        # Get API key from request or saved config
        api_key = request.api_key
        if not api_key:
            api_key = crud.get_provider_api_key(db, request.provider_name)

        if not api_key and request.provider_type == "cloud":
            return TestConnectionResponse(
                success=False,
                message="API key required for cloud providers",
            )

        # Test based on provider type
        if request.provider_type == "ocr":
            success, message = await _test_ocr_provider(request.provider_name, api_key, request.config)
        else:
            success, message = await _test_llm_provider(request.provider_name, api_key, request.config)

        elapsed_ms = (time.time() - start_time) * 1000

        # Update last test status if config exists
        config = crud.get_provider_config_by_name(db, request.provider_name)
        if config:
            crud.update_provider_config(
                db,
                config.id,
                last_test_at=datetime.utcnow(),
                last_test_success=success,
            )

        return TestConnectionResponse(
            success=success,
            message=message,
            response_time_ms=round(elapsed_ms, 2),
        )
    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        logger.error(f"Provider test failed: {e}")
        return TestConnectionResponse(
            success=False,
            message=str(e),
            response_time_ms=round(elapsed_ms, 2),
        )


async def _test_ocr_provider(name: str, api_key: Optional[str], config: Optional[Dict]) -> tuple[bool, str]:
    """Test an OCR provider connection."""
    # Local providers don't need API keys
    local_providers = ["paddle_ocr", "marker", "surya", "chandra"]

    if name in local_providers:
        # Try to import and check availability
        try:
            if name == "paddle_ocr":
                from paddle_ocr.ocr_processor import PaddleOCRProcessor
                return True, "PaddleOCR is available"
            elif name == "marker":
                # Check if marker is installed
                import importlib.util
                if importlib.util.find_spec("marker"):
                    return True, "Marker is available"
                return False, "Marker is not installed"
            elif name == "surya":
                import importlib.util
                if importlib.util.find_spec("surya"):
                    return True, "Surya is available"
                return False, "Surya is not installed"
            elif name == "chandra":
                from chandra_ocr.ocr_processor import ChandraOCRProcessor
                return True, "Chandra OCR is available"
        except ImportError as e:
            return False, f"Provider not available: {e}"

    elif name == "mistral_ocr":
        if not api_key:
            return False, "Mistral API key required"
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.mistral.ai/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10.0,
                )
                if response.status_code == 200:
                    return True, "Mistral OCR connection successful"
                return False, f"Mistral API error: {response.status_code}"
        except Exception as e:
            return False, f"Connection failed: {e}"

    return False, f"Unknown OCR provider: {name}"


async def _test_llm_provider(name: str, api_key: Optional[str], config: Optional[Dict]) -> tuple[bool, str]:
    """Test an LLM provider connection."""
    local_providers = ["nuextract", "ollama"]

    if name in local_providers:
        try:
            if name == "nuextract":
                # Check if model can be loaded
                import importlib.util
                if importlib.util.find_spec("transformers"):
                    return True, "NuExtract/transformers is available"
                return False, "transformers library not installed"
            elif name == "ollama":
                import httpx
                base_url = (config or {}).get("base_url", "http://localhost:11434")
                async with httpx.AsyncClient() as client:
                    response = await client.get(f"{base_url}/api/tags", timeout=5.0)
                    if response.status_code == 200:
                        return True, "Ollama is running"
                    return False, f"Ollama not responding: {response.status_code}"
        except Exception as e:
            return False, f"Provider not available: {e}"

    elif name == "gemini":
        if not api_key:
            return False, "Gemini API key required"
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://generativelanguage.googleapis.com/v1/models?key={api_key}",
                    timeout=10.0,
                )
                if response.status_code == 200:
                    return True, "Gemini connection successful"
                return False, f"Gemini API error: {response.status_code}"
        except Exception as e:
            return False, f"Connection failed: {e}"

    elif name == "mistral_chat":
        if not api_key:
            return False, "Mistral API key required"
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.mistral.ai/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=10.0,
                )
                if response.status_code == 200:
                    return True, "Mistral Chat connection successful"
                return False, f"Mistral API error: {response.status_code}"
        except Exception as e:
            return False, f"Connection failed: {e}"

    elif name == "azure_openai":
        if not api_key:
            return False, "Azure OpenAI API key required"
        endpoint = (config or {}).get("endpoint", "")
        if not endpoint:
            return False, "Azure OpenAI endpoint required"
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{endpoint}/openai/models?api-version=2024-02-15-preview",
                    headers={"api-key": api_key},
                    timeout=10.0,
                )
                if response.status_code == 200:
                    return True, "Azure OpenAI connection successful"
                return False, f"Azure API error: {response.status_code}"
        except Exception as e:
            return False, f"Connection failed: {e}"

    return False, f"Unknown LLM provider: {name}"
