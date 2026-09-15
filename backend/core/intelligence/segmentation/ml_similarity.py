"""
ML-based page similarity detection for document segmentation.

Provides CPU-friendly similarity detection using:
- TF-IDF vectorization with cosine similarity (fastest, ~1ms/page)
- MiniLM sentence embeddings (better accuracy, ~10ms/page)

These detectors help verify uncertain boundaries by measuring content
similarity between consecutive pages. High similarity suggests pages
belong to the same document, even if heuristics flagged a boundary.

Usage:
    from .ml_similarity import TFIDFSimilarityDetector, MiniLMSimilarityDetector

    # TF-IDF (fastest)
    detector = TFIDFSimilarityDetector()
    detector.fit_pages(page_texts)
    similarity = detector.compute_similarity(0, 1)
    is_same, reason = detector.is_same_document(similarity)

    # MiniLM (better accuracy)
    detector = MiniLMSimilarityDetector()
    detector.compute_page_embeddings(page_texts)
    similarity = detector.compute_similarity(0, 1)
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class BaseSimilarityDetector(ABC):
    """Base class for page similarity detectors."""

    @abstractmethod
    def fit_pages(self, page_texts: List[str]) -> None:
        """Fit the detector on all page texts."""
        pass

    @abstractmethod
    def compute_similarity(self, page1_idx: int, page2_idx: int) -> float:
        """Compute similarity between two pages by index."""
        pass

    def is_same_document(self, similarity: float) -> Tuple[Optional[bool], str]:
        """
        Determine if pages are from the same document based on similarity.

        Note: Thresholds are conservative to avoid merging similar-looking documents
        (e.g., multiple invoices from the same vendor with similar templates).

        Returns:
            Tuple of (is_same_document, reason)
            - True: Pages are definitely from the same document
            - False: Pages are definitely from different documents
            - None: Uncertain, use other signals
        """
        if similarity > 0.95:
            return True, "Near-identical content - same document or exact copy"
        elif similarity > 0.90:
            return True, "Very high content similarity - likely same document"
        elif similarity < 0.25:
            return False, "Very low content similarity - different documents"
        else:
            # Wide uncertainty band to avoid false positives/negatives
            # Similar templates (invoices, etc.) often have 0.4-0.85 similarity
            return None, "Uncertain - defer to heuristic signals"


class TFIDFSimilarityDetector(BaseSimilarityDetector):
    """
    Fast TF-IDF based page similarity using scikit-learn.

    CPU-only, no model loading required, ~1ms per comparison.
    Best for high-volume processing where speed is critical.

    Features:
    - TF-IDF vectorization with bigrams
    - Cosine similarity for comparison
    - Fits on all pages for vocabulary consistency
    """

    def __init__(
        self,
        max_features: int = 5000,
        ngram_range: Tuple[int, int] = (1, 2),
    ):
        """
        Initialize TF-IDF detector.

        Args:
            max_features: Maximum vocabulary size
            ngram_range: N-gram range for tokenization (1,2) = unigrams + bigrams
        """
        self.max_features = max_features
        self.ngram_range = ngram_range
        self._vectorizer = None
        self._page_vectors = None
        self._fitted = False

    def fit_pages(self, page_texts: List[str]) -> None:
        """
        Fit TF-IDF vectorizer on all pages and transform to vectors.

        Args:
            page_texts: List of page text content
        """
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer

            self._vectorizer = TfidfVectorizer(
                max_features=self.max_features,
                ngram_range=self.ngram_range,
                stop_words="english",
                lowercase=True,
                strip_accents="unicode",
            )

            # Filter out empty pages
            processed_texts = [text if text.strip() else " " for text in page_texts]

            self._page_vectors = self._vectorizer.fit_transform(processed_texts)
            self._fitted = True

            logger.debug(
                f"TF-IDF fitted on {len(page_texts)} pages, "
                f"vocabulary size: {len(self._vectorizer.vocabulary_)}"
            )

        except ImportError:
            logger.error("scikit-learn not installed. Run: pip install scikit-learn")
            self._fitted = False
        except Exception as e:
            logger.error(f"Error fitting TF-IDF vectorizer: {e}")
            self._fitted = False

    def compute_similarity(self, page1_idx: int, page2_idx: int) -> float:
        """
        Compute cosine similarity between two pages.

        Args:
            page1_idx: Index of first page
            page2_idx: Index of second page

        Returns:
            Cosine similarity (0.0 to 1.0)
        """
        if not self._fitted or self._page_vectors is None:
            logger.warning("TF-IDF not fitted, returning default similarity")
            return 0.5

        try:
            from sklearn.metrics.pairwise import cosine_similarity

            vec1 = self._page_vectors[page1_idx]
            vec2 = self._page_vectors[page2_idx]

            similarity = cosine_similarity(vec1, vec2)[0, 0]
            return float(similarity)

        except IndexError:
            logger.error(f"Page index out of range: {page1_idx} or {page2_idx}")
            return 0.5
        except Exception as e:
            logger.error(f"Error computing TF-IDF similarity: {e}")
            return 0.5

    def get_page_vector(self, page_idx: int) -> Optional[np.ndarray]:
        """Get the TF-IDF vector for a specific page."""
        if not self._fitted or self._page_vectors is None:
            return None
        try:
            return self._page_vectors[page_idx].toarray().flatten()
        except IndexError:
            return None


class MiniLMSimilarityDetector(BaseSimilarityDetector):
    """
    Sentence-transformer based similarity using all-MiniLM-L6-v2.

    CPU-optimized, 22MB model, ~10ms per comparison.
    Better semantic understanding than TF-IDF for:
    - Paraphrased content
    - Synonym matching
    - Semantic similarity

    Features:
    - 384-dimensional dense embeddings
    - Batch processing for efficiency
    - Cosine similarity for comparison
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        device: str = "cpu",
    ):
        """
        Initialize MiniLM detector.

        Args:
            model_name: Sentence-transformers model name
            device: Device to run model on ("cpu" or "cuda")
        """
        self.model_name = model_name
        self.device = device
        self._model = None
        self._page_embeddings: Dict[int, np.ndarray] = {}
        self._fitted = False

    def _load_model(self) -> bool:
        """Lazy-load the sentence transformer model."""
        if self._model is not None:
            return True

        try:
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading MiniLM model: {self.model_name}")
            self._model = SentenceTransformer(self.model_name, device=self.device)
            logger.info(f"MiniLM model loaded successfully")
            return True

        except ImportError:
            logger.error(
                "sentence-transformers not installed. "
                "Run: pip install sentence-transformers"
            )
            return False
        except Exception as e:
            logger.error(f"Error loading MiniLM model: {e}")
            return False

    def fit_pages(self, page_texts: List[str]) -> None:
        """
        Generate embeddings for all pages (batch processing).

        Args:
            page_texts: List of page text content
        """
        self.compute_page_embeddings(page_texts)

    def compute_page_embeddings(self, page_texts: List[str]) -> None:
        """
        Generate embeddings for all pages at once (batch processing).

        Args:
            page_texts: List of page text content
        """
        if not self._load_model():
            return

        try:
            # Truncate very long texts to avoid memory issues
            max_chars = 10000
            processed_texts = [
                text[:max_chars] if text.strip() else " "
                for text in page_texts
            ]

            logger.debug(f"Computing embeddings for {len(processed_texts)} pages")

            embeddings = self._model.encode(
                processed_texts,
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True,  # Pre-normalize for cosine similarity
            )

            for i, emb in enumerate(embeddings):
                self._page_embeddings[i] = emb

            self._fitted = True

            logger.debug(
                f"MiniLM embeddings computed: {len(self._page_embeddings)} pages, "
                f"dimension: {embeddings.shape[1]}"
            )

        except Exception as e:
            logger.error(f"Error computing MiniLM embeddings: {e}")
            self._fitted = False

    def compute_similarity(self, page1_idx: int, page2_idx: int) -> float:
        """
        Compute cosine similarity between page embeddings.

        Args:
            page1_idx: Index of first page
            page2_idx: Index of second page

        Returns:
            Cosine similarity (0.0 to 1.0)
        """
        emb1 = self._page_embeddings.get(page1_idx)
        emb2 = self._page_embeddings.get(page2_idx)

        if emb1 is None or emb2 is None:
            logger.warning(f"Embedding not found for page {page1_idx} or {page2_idx}")
            return 0.5

        try:
            # Embeddings are pre-normalized, so dot product = cosine similarity
            similarity = float(np.dot(emb1, emb2))
            return max(0.0, min(1.0, similarity))  # Clamp to [0, 1]

        except Exception as e:
            logger.error(f"Error computing MiniLM similarity: {e}")
            return 0.5

    def get_page_embedding(self, page_idx: int) -> Optional[np.ndarray]:
        """Get the embedding vector for a specific page."""
        return self._page_embeddings.get(page_idx)


def create_similarity_detector(
    method: str = "tfidf",
    **kwargs,
) -> BaseSimilarityDetector:
    """
    Factory function to create a similarity detector.

    Args:
        method: "tfidf" or "minilm"
        **kwargs: Additional arguments for the detector

    Returns:
        Configured similarity detector
    """
    if method == "minilm":
        return MiniLMSimilarityDetector(**kwargs)
    else:
        return TFIDFSimilarityDetector(**kwargs)
