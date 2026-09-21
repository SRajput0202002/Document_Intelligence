"""
LLM extractor adapters.

Each adapter wraps an existing LLM extractor implementation
to conform to the BaseLLMExtractor interface.

Available providers:
    - nuextract: NuExtract model (local, free)
    - ollama: Ollama/Llama (local, free)
    - azure_openai: Azure OpenAI GPT-5.5 (cloud)
    - mistral_chat: Mistral Chat API (cloud)
    - gemini: Google Gemini Vision (cloud)
"""

import logging

logger = logging.getLogger(__name__)

# Import and register providers
_ADAPTERS_LOADED = False


def _load_adapters():
    """Load all LLM adapters and register them."""
    global _ADAPTERS_LOADED
    if _ADAPTERS_LOADED:
        return

    adapters = [
        ("nuextract", ".nuextract"),
        ("ollama", ".ollama"),
        ("azure_openai", ".azure_openai"),
        ("mistral_chat", ".mistral_chat"),
        ("gemini", ".gemini"),
    ]

    for name, module_path in adapters:
        try:
            import importlib
            module = importlib.import_module(module_path, package=__name__)
            logger.debug(f"Loaded LLM adapter: {name}")
        except ImportError as e:
            logger.warning(f"Failed to load LLM adapter '{name}': {e}")
        except Exception as e:
            logger.error(f"Error loading LLM adapter '{name}': {e}")

    _ADAPTERS_LOADED = True


# Load adapters on import
_load_adapters()
