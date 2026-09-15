#!/usr/bin/env python3
"""
Configuration management for Bill of Entry Extractor
Handles API keys, model settings, and application configuration
"""

import os
from typing import List
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


@dataclass
class GeminiConfig:
    """Gemini API configuration"""
    api_keys: List[str] = field(default_factory=list)
    model_preferences: List[str] = field(default_factory=lambda: [
        'models/gemini-2.5-flash',
        'models/gemini-2.5-pro-preview-05-06',
        'models/gemini-1.5-flash',
        'models/gemini-1.5-pro',
    ])
    max_retries: int = 3
    retry_delay: float = 2.0  # seconds
    timeout: int = 300  # seconds
    requests_per_minute: int = 15  # Rate limit per API key


@dataclass
class ExtractionConfig:
    """Extraction pipeline configuration"""
    temp_dir: str = "temp_extraction"
    output_dir: str = "output"
    enable_validation: bool = True
    enable_cross_validation: bool = True
    validation_strictness: str = "medium"  # low, medium, high
    save_intermediate_results: bool = True
    confidence_threshold: float = 0.7


@dataclass
class LoggingConfig:
    """Logging configuration"""
    log_level: str = "INFO"
    log_file: str = "extraction.log"
    log_to_console: bool = True
    log_to_file: bool = True


class Config:
    """Main configuration class"""

    def __init__(self):
        self.gemini = GeminiConfig()
        self.extraction = ExtractionConfig()
        self.logging = LoggingConfig()

        # Load API keys from environment
        self._load_api_keys()

    def _load_api_keys(self):
        """Load API keys from environment variables"""
        # Primary API key
        primary_key = os.getenv('GEMINI_API_KEY')
        if primary_key:
            self.gemini.api_keys.append(primary_key)

        # Additional API keys for load balancing (GEMINI_API_KEY_1, GEMINI_API_KEY_2, etc.)
        i = 1
        while True:
            key = os.getenv(f'GEMINI_API_KEY_{i}')
            if key:
                self.gemini.api_keys.append(key)
                i += 1
            else:
                break

        # Warn if no API keys found
        if not self.gemini.api_keys:
            print("WARNING: No GEMINI_API_KEY found in environment variables.")
            print("Please set GEMINI_API_KEY in your .env file or export it:")

    def validate(self) -> bool:
        """Validate configuration"""
        if not self.gemini.api_keys:
            raise ValueError("No Gemini API keys configured")

        if self.gemini.max_retries < 1:
            raise ValueError("max_retries must be at least 1")

        if self.extraction.confidence_threshold < 0 or self.extraction.confidence_threshold > 1:
            raise ValueError("confidence_threshold must be between 0 and 1")

        return True


# Global config instance
config = Config()
