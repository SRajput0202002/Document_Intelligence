"""
Provider Registry for unified OCR and LLM extraction.

This module provides:
    - ProviderRegistry: Central registry for all providers
    - Factory methods for creating provider instances
    - Provider discovery and availability checking

The registry automatically discovers and registers all available
OCR processors and LLM extractors.

Usage:
    from core.registry import ProviderRegistry

    # List all available providers
    ocr_providers = ProviderRegistry.list_ocr_providers()
    llm_providers = ProviderRegistry.list_llm_providers()

    # Create provider instances
    ocr = ProviderRegistry.get_ocr_processor("mistral")
    llm = ProviderRegistry.get_llm_extractor("nuextract")

    # Process document
    result = ocr.process_pdf("document.pdf")
    extracted = llm.extract(result.full_text, schema, "part-0")
"""

import logging
import os
from typing import Dict, List, Optional, Type, Any

from .base.models import ProviderInfo, ProviderType, CostTier
from .base.ocr_processor import BaseOCRProcessor
from .base.llm_extractor import BaseLLMExtractor

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """
    Central registry for OCR processors and LLM extractors.

    This class manages:
        - Provider registration and discovery
        - Factory methods for creating instances
        - Availability checking based on API keys

    Providers are registered using the register_* methods and can be
    retrieved using the get_* methods.

    Example:
        # Register a provider
        ProviderRegistry.register_ocr_provider("mistral", MistralOCRAdapter)

        # Get provider instance
        processor = ProviderRegistry.get_ocr_processor("mistral")

        # List all providers
        providers = ProviderRegistry.list_ocr_providers()
    """

    # Registry storage
    _ocr_processors: Dict[str, Type[BaseOCRProcessor]] = {}
    _llm_extractors: Dict[str, Type[BaseLLMExtractor]] = {}

    # Config factories (for creating configs from env)
    _ocr_configs: Dict[str, callable] = {}
    _llm_configs: Dict[str, callable] = {}

    # ==========================================================================
    # OCR Provider Registration
    # ==========================================================================

    @classmethod
    def register_ocr_provider(
        cls,
        name: str,
        processor_class: Type[BaseOCRProcessor],
        config_factory: Optional[callable] = None,
    ) -> None:
        """
        Register an OCR processor.

        Args:
            name: Provider name (e.g., "mistral", "paddle")
            processor_class: BaseOCRProcessor subclass
            config_factory: Callable that returns config from environment

        Example:
            ProviderRegistry.register_ocr_provider(
                "mistral",
                MistralOCRAdapter,
                lambda: MistralConfig.from_env()
            )
        """
        cls._ocr_processors[name] = processor_class
        if config_factory:
            cls._ocr_configs[name] = config_factory
        logger.debug(f"Registered OCR provider: {name}")

    @classmethod
    def get_ocr_processor(
        cls,
        name: str,
        config: Optional[Any] = None,
    ) -> BaseOCRProcessor:
        """
        Get an OCR processor instance.

        Args:
            name: Provider name
            config: Optional config (uses env if not provided)

        Returns:
            OCR processor instance

        Raises:
            ValueError: If provider not found
            RuntimeError: If config cannot be created

        Example:
            processor = ProviderRegistry.get_ocr_processor("mistral")
            result = processor.process_pdf("document.pdf")
        """
        if name not in cls._ocr_processors:
            available = ", ".join(cls._ocr_processors.keys())
            raise ValueError(
                f"Unknown OCR provider: '{name}'. Available: {available}"
            )

        processor_class = cls._ocr_processors[name]

        if config is None:
            if name not in cls._ocr_configs:
                raise RuntimeError(
                    f"No config factory for OCR provider '{name}'. "
                    "Pass config explicitly."
                )
            config = cls._ocr_configs[name]()

        return processor_class(config)

    @classmethod
    def list_ocr_providers(cls) -> List[ProviderInfo]:
        """
        List all registered OCR providers with their info.

        Returns:
            List of ProviderInfo objects
        """
        providers = []

        for name, processor_class in cls._ocr_processors.items():
            try:
                info = processor_class.get_provider_info()
                # Check availability
                if info.requires_api_key and info.api_key_env_var:
                    if not os.environ.get(info.api_key_env_var):
                        info.is_available = False
                        info.error = f"Missing API key: {info.api_key_env_var}"
                providers.append(info)
            except Exception as e:
                # Create basic info if get_provider_info fails
                providers.append(ProviderInfo(
                    name=name,
                    display_name=name.title(),
                    description=f"OCR provider: {name}",
                    provider_type=ProviderType.LOCAL,
                    cost_tier=CostTier.FREE,
                    is_available=False,
                    error=str(e),
                ))

        return providers

    # ==========================================================================
    # LLM Extractor Registration
    # ==========================================================================

    @classmethod
    def register_llm_provider(
        cls,
        name: str,
        extractor_class: Type[BaseLLMExtractor],
        config_factory: Optional[callable] = None,
    ) -> None:
        """
        Register an LLM extractor.

        Args:
            name: Provider name (e.g., "nuextract", "ollama")
            extractor_class: BaseLLMExtractor subclass
            config_factory: Callable that returns config from environment

        Example:
            ProviderRegistry.register_llm_provider(
                "nuextract",
                NuExtractAdapter,
                lambda: FunctionGemmaConfig.from_env()
            )
        """
        cls._llm_extractors[name] = extractor_class
        if config_factory:
            cls._llm_configs[name] = config_factory
        logger.debug(f"Registered LLM provider: {name}")

    @classmethod
    def get_llm_extractor(
        cls,
        name: str,
        config: Optional[Any] = None,
    ) -> BaseLLMExtractor:
        """
        Get an LLM extractor instance.

        Args:
            name: Provider name
            config: Optional config (uses env if not provided)

        Returns:
            LLM extractor instance

        Raises:
            ValueError: If provider not found
            RuntimeError: If config cannot be created

        Example:
            extractor = ProviderRegistry.get_llm_extractor("nuextract")
            result = extractor.extract(text, schema, "part-0")
        """
        if name not in cls._llm_extractors:
            available = ", ".join(cls._llm_extractors.keys())
            raise ValueError(
                f"Unknown LLM provider: '{name}'. Available: {available}"
            )

        extractor_class = cls._llm_extractors[name]

        if config is None:
            if name not in cls._llm_configs:
                raise RuntimeError(
                    f"No config factory for LLM provider '{name}'. "
                    "Pass config explicitly."
                )
            config = cls._llm_configs[name]()

        return extractor_class(config)

    @classmethod
    def list_llm_providers(cls) -> List[ProviderInfo]:
        """
        List all registered LLM providers with their info.

        Returns:
            List of ProviderInfo objects
        """
        providers = []

        for name, extractor_class in cls._llm_extractors.items():
            try:
                info = extractor_class.get_provider_info()
                # Check availability
                if info.requires_api_key and info.api_key_env_var:
                    if not os.environ.get(info.api_key_env_var):
                        info.is_available = False
                        info.error = f"Missing API key: {info.api_key_env_var}"
                providers.append(info)
            except Exception as e:
                # Create basic info if get_provider_info fails
                providers.append(ProviderInfo(
                    name=name,
                    display_name=name.title(),
                    description=f"LLM extractor: {name}",
                    provider_type=ProviderType.LOCAL,
                    cost_tier=CostTier.FREE,
                    is_available=False,
                    error=str(e),
                ))

        return providers

    # ==========================================================================
    # Combined Listing
    # ==========================================================================

    @classmethod
    def list_providers(cls) -> Dict[str, List[ProviderInfo]]:
        """
        List all providers (both OCR and LLM).

        Returns:
            Dictionary with 'ocr_providers' and 'llm_providers' keys
        """
        return {
            "ocr_providers": cls.list_ocr_providers(),
            "llm_providers": cls.list_llm_providers(),
        }

    @classmethod
    def is_ocr_available(cls, name: str) -> bool:
        """Check if an OCR provider is available."""
        if name not in cls._ocr_processors:
            return False

        try:
            info = cls._ocr_processors[name].get_provider_info()
            if info.requires_api_key and info.api_key_env_var:
                return bool(os.environ.get(info.api_key_env_var))
            return True
        except:
            return False

    @classmethod
    def is_llm_available(cls, name: str) -> bool:
        """Check if an LLM provider is available."""
        if name not in cls._llm_extractors:
            return False

        try:
            info = cls._llm_extractors[name].get_provider_info()
            if info.requires_api_key and info.api_key_env_var:
                return bool(os.environ.get(info.api_key_env_var))
            return True
        except:
            return False

    # ==========================================================================
    # Clear Registry (for testing)
    # ==========================================================================

    @classmethod
    def clear(cls) -> None:
        """Clear all registered providers (useful for testing)."""
        cls._ocr_processors.clear()
        cls._llm_extractors.clear()
        cls._ocr_configs.clear()
        cls._llm_configs.clear()
        logger.debug("Cleared provider registry")


# =============================================================================
# Auto-register providers on module import
# =============================================================================

def _register_default_providers():
    """
    Register all available providers.

    This function imports and registers all provider adapters.
    Called automatically on module import.
    """
    # Import providers package to trigger registration
    try:
        from . import providers
        logger.debug("Loaded provider adapters")
    except ImportError as e:
        logger.warning(f"Failed to load provider adapters: {e}")


# Auto-register on import
_register_default_providers()
