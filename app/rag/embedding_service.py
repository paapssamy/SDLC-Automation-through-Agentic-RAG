"""Embedding service (Strategy): sentence-transformers locally, or a hashing fallback.

`EMBEDDING_MODEL=hash` selects the deterministic, dependency-free embedder (fast tests/offline).
Vectors are always 384-dimensional and L2-normalised.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
from abc import ABC, abstractmethod

from app.config import get_settings

log = logging.getLogger(__name__)
DIMENSIONS = 384


class EmbeddingService(ABC):
    dimensions = DIMENSIONS

    @abstractmethod
    def embed_many(self, texts: list[str]) -> list[list[float]]: ...

    def embed(self, text: str) -> list[float]:
        return self.embed_many([text])[0]


class SentenceTransformerEmbedder(EmbeddingService):
    """all-MiniLM-L6-v2 (384 dims). The model is loaded once and cached."""

    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        try:  # prefer the local cache: no network round-trips, works offline
            self._model = SentenceTransformer(model_name, local_files_only=True)
        except Exception:
            log.info("Model %s not cached yet – downloading once", model_name)
            self._model = SentenceTransformer(model_name)

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        vecs = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vecs]


class HashEmbedder(EmbeddingService):
    """Bag-of-words feature hashing. Similar wording => similar vectors; unrelated => ~0."""

    _stop = {"the", "and", "for", "with", "that", "this", "are", "from", "all", "has", "will"}

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        tokens = [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in self._stop]
        # split camelCase-ish words are already lowercased; add bigrams for a little context
        feats = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False)]
        vec = [0.0] * DIMENSIONS
        for f in feats:
            h = int(hashlib.md5(f.encode()).hexdigest(), 16)
            vec[h % DIMENSIONS] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            vec[0] = 1.0
            return vec
        return [v / norm for v in vec]


_lock = threading.Lock()
_instance: EmbeddingService | None = None


def get_embedder() -> EmbeddingService:
    """Singleton accessor – the model is loaded only once."""
    global _instance
    with _lock:
        if _instance is None:
            name = get_settings().embedding_model
            if name == "hash":
                _instance = HashEmbedder()
            else:
                try:
                    _instance = SentenceTransformerEmbedder(name)
                except Exception as exc:  # offline / model missing
                    log.warning("Could not load %s (%s); using hash embedder", name, exc)
                    _instance = HashEmbedder()
        return _instance


def set_embedder(e: EmbeddingService | None) -> None:
    global _instance
    _instance = e
