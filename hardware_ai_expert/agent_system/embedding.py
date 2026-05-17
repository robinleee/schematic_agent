"""
Unified semantic embedding module.

Provides a singleton SentenceTransformer model (all-MiniLM-L6-v2, 384-dim)
shared across all subsystems (GraphRAG, KnowledgeRouter, DatasheetProcessor).

Replaces the previous fragmented approaches:
  - _simple_embed (char frequency hash, 512-dim)
  - _local_embed (weighted hash, 768-dim)
  - _ollama_embed (gemma4 API, 768-dim)
  - _tfidf_embed (sklearn TF-IDF, 768-dim)
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

_model = None
_lock = threading.Lock()


def get_model():
    """Lazy-load and return the singleton SentenceTransformer model."""
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                try:
                    from sentence_transformers import SentenceTransformer
                    logger.info(f"Loading embedding model: {MODEL_NAME}")
                    _model = SentenceTransformer(MODEL_NAME)
                    logger.info(f"Model loaded, dim={_model.get_sentence_embedding_dimension()}")
                except ImportError:
                    raise RuntimeError(
                        "sentence-transformers not installed. "
                        "Run: pip install sentence-transformers"
                    )
    return _model


def embed(text: str) -> list[float]:
    """Generate a 384-dim semantic embedding for the given text."""
    model = get_model()
    vector = model.encode([text], normalize_embeddings=True)
    return vector[0].tolist()


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for multiple texts in one call (more efficient)."""
    if not texts:
        return []
    model = get_model()
    vectors = model.encode(texts, normalize_embeddings=True)
    return [v.tolist() for v in vectors]
