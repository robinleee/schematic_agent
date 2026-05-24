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


def unload_model():
    """Release the embedding model from memory (free ~400MB GPU/CPU RAM).
    Called after batch operations to avoid OOM when Ollama is also running."""
    global _model
    if _model is not None:
        with _lock:
            if _model is not None:
                logger.info("Unloading embedding model to free memory")
                del _model
                _model = None
                # Force garbage collection
                import gc
                gc.collect()


def embed(text: str, keep_loaded: bool = True) -> list[float]:
    """Generate a 384-dim semantic embedding for the given text.
    
    Args:
        keep_loaded: If False, unload model after encoding (saves ~400MB RAM).
    """
    model = get_model()
    vector = model.encode([text], normalize_embeddings=True)
    result = vector[0].tolist()
    if not keep_loaded:
        unload_model()
    return result


def embed_batch(texts: list[str], keep_loaded: bool = True) -> list[list[float]]:
    """Generate embeddings for multiple texts in one call (more efficient).
    
    Args:
        keep_loaded: If False, unload model after encoding (saves ~400MB RAM).
    """
    if not texts:
        return []
    model = get_model()
    vectors = model.encode(texts, normalize_embeddings=True)
    result = [v.tolist() for v in vectors]
    if not keep_loaded:
        unload_model()
    return result
