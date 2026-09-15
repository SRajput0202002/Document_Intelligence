"""
Prompt Service - Manages prompt retrieval and caching from the database.

This service provides centralized access to prompts stored in the prompt_lib table,
with in-memory caching for performance. All prompts MUST exist in the database -
NO FALLBACKS are provided. If a prompt is missing, an error is raised.
"""

import logging
from typing import Dict, Optional, List, Any
import threading

from sqlalchemy.orm import Session

from ..database.models import PromptLib, PromptCategory
from ..database.engine import SessionLocal, engine

logger = logging.getLogger(__name__)

# Thread-safe cache for prompts
_prompt_cache: Dict[str, str] = {}
_cache_lock = threading.Lock()
_cache_initialized = False


class PromptNotFoundError(Exception):
    """Raised when a required prompt is not found in the database."""
    pass


class PromptService:
    """
    Service for managing and retrieving prompts from the database.

    Provides:
        - Caching of frequently used prompts
        - Methods to refresh cache
        - Category-based prompt retrieval
        - CRUD operations for prompts

    NO FALLBACKS - all prompts must exist in the database.
    """

    def __init__(self, db_session: Optional[Session] = None):
        """
        Initialize the prompt service.

        Args:
            db_session: Optional SQLAlchemy session. If not provided,
                       will create one when needed.
        """
        self._db_session = db_session

    def _get_session(self) -> Session:
        """Get or create a database session."""
        if self._db_session:
            return self._db_session
        return SessionLocal()

    def get_prompt(
        self,
        name: str,
        use_cache: bool = True,
        required: bool = True,
    ) -> Optional[str]:
        """
        Get a prompt by name from the database.

        Args:
            name: Unique name of the prompt (e.g., 'base_system_prompt')
            use_cache: Whether to use cached value if available
            required: If True, raises PromptNotFoundError when not found

        Returns:
            Prompt text

        Raises:
            PromptNotFoundError: If required=True and prompt not found
        """
        # Check cache first
        if use_cache and name in _prompt_cache:
            return _prompt_cache[name]

        session = self._get_session()
        owns_session = self._db_session is None  # We created the session
        prompt_text = None
        try:
            prompt = session.query(PromptLib).filter(
                PromptLib.name == name,
                PromptLib.is_active == True
            ).first()

            if prompt:
                prompt_text = prompt.prompt
                # Update cache
                with _cache_lock:
                    _prompt_cache[name] = prompt_text

        except Exception as e:
            logger.error(f"Database error fetching prompt '{name}': {e}")
            if owns_session:
                session.close()
            if required:
                raise PromptNotFoundError(
                    f"Failed to fetch prompt '{name}' from database: {e}"
                )
            return None
        finally:
            if owns_session:
                session.close()

        if prompt_text:
            return prompt_text

        # Prompt not found
        if required:
            raise PromptNotFoundError(
                f"Prompt '{name}' not found in database. "
                f"Run 'python -m api.database.seed_prompts' to initialize prompts."
            )
        return None

    def get_prompts_by_category(
        self,
        category: str,
        active_only: bool = True,
    ) -> List[PromptLib]:
        """
        Get all prompts in a category.

        Args:
            category: Category name (system, extraction, classification, validation, custom)
            active_only: Whether to only return active prompts

        Returns:
            List of PromptLib objects
        """
        session = self._get_session()
        try:
            query = session.query(PromptLib).filter(PromptLib.category == category)

            if active_only:
                query = query.filter(PromptLib.is_active == True)

            return query.order_by(PromptLib.name).all()

        except Exception as e:
            logger.error(f"Error fetching prompts for category '{category}': {e}")
            raise

    def get_all_prompts(self, active_only: bool = True) -> List[PromptLib]:
        """
        Get all prompts.

        Args:
            active_only: Whether to only return active prompts

        Returns:
            List of PromptLib objects
        """
        session = self._get_session()
        try:
            query = session.query(PromptLib)

            if active_only:
                query = query.filter(PromptLib.is_active == True)

            return query.order_by(PromptLib.category, PromptLib.name).all()

        except Exception as e:
            logger.error(f"Error fetching all prompts: {e}")
            raise

    def refresh_cache(self) -> None:
        """
        Refresh the prompt cache from the database.

        Call this after updating prompts to ensure cache is current.
        """
        global _cache_initialized

        session = self._get_session()
        try:
            prompts = session.query(PromptLib).filter(
                PromptLib.is_active == True
            ).all()

            with _cache_lock:
                _prompt_cache.clear()
                for prompt in prompts:
                    _prompt_cache[prompt.name] = prompt.prompt
                _cache_initialized = True

            logger.info(f"Prompt cache refreshed with {len(prompts)} prompts")

        except Exception as e:
            logger.error(f"Error refreshing prompt cache: {e}")
            raise

    def create_prompt(
        self,
        name: str,
        description: str,
        prompt: str,
        category: str = PromptCategory.CUSTOM.value,
        tags: Optional[List[str]] = None,
        created_by_id: Optional[str] = None,
    ) -> PromptLib:
        """
        Create a new prompt.

        Args:
            name: Unique name for the prompt
            description: Detailed description
            prompt: The prompt text
            category: Prompt category
            tags: Optional list of tags
            created_by_id: Optional creator user ID

        Returns:
            Created PromptLib object
        """
        session = self._get_session()
        try:
            new_prompt = PromptLib(
                name=name,
                description=description,
                prompt=prompt,
                category=category,
                tags=tags or [],
                is_active=True,
                version=1,
                created_by_id=created_by_id,
            )

            session.add(new_prompt)
            session.commit()
            session.refresh(new_prompt)

            # Update cache
            with _cache_lock:
                _prompt_cache[name] = prompt

            logger.info(f"Created prompt: {name}")
            return new_prompt

        except Exception as e:
            logger.error(f"Error creating prompt '{name}': {e}")
            session.rollback()
            raise

    def update_prompt(
        self,
        name: str,
        prompt: Optional[str] = None,
        description: Optional[str] = None,
        is_active: Optional[bool] = None,
        updated_by_id: Optional[str] = None,
    ) -> PromptLib:
        """
        Update an existing prompt.

        Args:
            name: Name of the prompt to update
            prompt: New prompt text (optional)
            description: New description (optional)
            is_active: New active status (optional)
            updated_by_id: User ID making the update

        Returns:
            Updated PromptLib object
        """
        session = self._get_session()
        try:
            existing = session.query(PromptLib).filter(
                PromptLib.name == name
            ).first()

            if not existing:
                raise PromptNotFoundError(f"Prompt not found: {name}")

            if prompt is not None:
                existing.prompt = prompt
                existing.version += 1

            if description is not None:
                existing.description = description

            if is_active is not None:
                existing.is_active = is_active

            if updated_by_id:
                existing.updated_by_id = updated_by_id

            session.commit()
            session.refresh(existing)

            # Update cache
            if existing.is_active:
                with _cache_lock:
                    _prompt_cache[name] = existing.prompt
            else:
                with _cache_lock:
                    _prompt_cache.pop(name, None)

            logger.info(f"Updated prompt: {name}")
            return existing

        except PromptNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error updating prompt '{name}': {e}")
            session.rollback()
            raise


# =============================================================================
# Convenience Functions
# =============================================================================

def get_prompt(name: str, use_cache: bool = True) -> str:
    """
    Get a prompt by name (convenience function).

    Args:
        name: Unique name of the prompt
        use_cache: Whether to use cached value

    Returns:
        Prompt text

    Raises:
        PromptNotFoundError: If prompt not found in database
    """
    service = PromptService()
    return service.get_prompt(name, use_cache=use_cache, required=True)


def get_prompt_optional(name: str, use_cache: bool = True) -> Optional[str]:
    """
    Get a prompt by name, returning None if not found.

    Args:
        name: Unique name of the prompt
        use_cache: Whether to use cached value

    Returns:
        Prompt text or None if not found
    """
    service = PromptService()
    return service.get_prompt(name, use_cache=use_cache, required=False)


def get_prompts_by_category(category: str) -> List[PromptLib]:
    """
    Get all active prompts in a category (convenience function).

    Args:
        category: Category name

    Returns:
        List of PromptLib objects
    """
    service = PromptService()
    return service.get_prompts_by_category(category)


def initialize_prompt_cache() -> None:
    """
    Initialize the prompt cache on application startup.

    Call this during app initialization to pre-load prompts.
    """
    service = PromptService()
    service.refresh_cache()
