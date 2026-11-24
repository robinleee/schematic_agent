"""
Unified semantic embedding module.

Default model is bge-m3 (1024-dim, multilingual, hardware/Chinese-friendly).
Override via SCHEMATIC_EMBEDDING_MODEL to fall back to all-MiniLM-L6-v2 (384-dim)
or another sentence-transformers model.

Environment variables:
  SCHEMATIC_EMBEDDING_MODEL   sentence-transformers model name/path
  SCHEMATIC_EMBEDDING_DIM     optional expected dimension override
  SCHEMATIC_EMBEDDING_DEVICE  optional sentence-transformers device
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_MODEL_NAME = "BAAI/bge-m3"
DEFAULT_EMBEDDING_DIM = 1024
MODEL_NAME = os.environ.get("SCHEMATIC_EMBEDDING_MODEL", DEFAULT_MODEL_NAME)
EMBEDDING_DIM = int(os.environ.get("SCHEMATIC_EMBEDDING_DIM", str(DEFAULT_EMBEDDING_DIM)))
DEVICE = os.environ.get("SCHEMATIC_EMBEDDING_DEVICE") or None

_model = None
_model_name = None
_lock = threading.Lock()


@dataclass(frozen=True)
class EmbeddingInfo:
    model_name: str
    embedding_dim: int
    device: str | None


def get_embedding_info() -> EmbeddingInfo:
    """Return the configured embedding model metadata without loading the model."""
    return EmbeddingInfo(model_name=MODEL_NAME, embedding_dim=EMBEDDING_DIM, device=DEVICE)


def get_model(model_name: str | None = None):
    """Lazy-load and return the singleton SentenceTransformer model."""
    global _model, _model_name
    requested = model_name or MODEL_NAME
    if _model is None or _model_name != requested:
        with _lock:
            if _model is None or _model_name != requested:
                try:
                    from sentence_transformers import SentenceTransformer
                    logger.info("Loading embedding model: %s", requested)
                    kwargs = {"device": DEVICE} if DEVICE else {}
                    _model = SentenceTransformer(requested, **kwargs)
                    _model_name = requested
                    logger.info("Model loaded, dim=%s", _model.get_sentence_embedding_dimension())
                except ImportError as exc:
                    raise RuntimeError(
                        "sentence-transformers not installed. Run: pip install sentence-transformers"
                    ) from exc
    return _model


def get_actual_embedding_dim(model_name: str | None = None) -> int:
    """Load the model and return its actual output dimension."""
    return int(get_model(model_name).get_sentence_embedding_dimension())


def unload_model():
    """Release the embedding model from memory."""
    global _model, _model_name
    if _model is not None:
        with _lock:
            if _model is not None:
                logger.info("Unloading embedding model to free memory")
                del _model
                _model = None
                _model_name = None
                import gc
                gc.collect()


def _encode(texts: list[str], model_name: str | None = None):
    model = get_model(model_name)
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=False)


def embed(text: str, keep_loaded: bool = True, model_name: str | None = None) -> list[float]:
    """Generate a normalized semantic embedding for text."""
    vector = _encode([text], model_name=model_name)
    result = vector[0].tolist()
    if not keep_loaded:
        unload_model()
    return result


def embed_batch(texts: list[str], keep_loaded: bool = True,
                model_name: str | None = None) -> list[list[float]]:
    """Generate normalized embeddings for multiple texts in one call."""
    if not texts:
        return []
    vectors = _encode(texts, model_name=model_name)
    result = [v.tolist() for v in vectors]
    if not keep_loaded:
        unload_model()
    return result
