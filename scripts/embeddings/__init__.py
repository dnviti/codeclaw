"""Embedding provider abstraction for the vector memory layer.

Supports:
- Local ONNX-based embeddings (all-MiniLM-L6-v2) — default, zero-server
- API-based providers (OpenAI text-embedding-3-large, Voyage Code-3)

Embedding results are cached by content hash to avoid redundant computation.

The local ONNX provider requires: onnxruntime, tokenizers, numpy.
API providers require: urllib (stdlib) + valid API key.
"""

import hashlib
import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts. Returns list of embedding vectors."""
        ...

    @abstractmethod
    def dimension(self) -> int:
        """Return the dimensionality of embedding vectors."""
        ...

    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier string."""
        ...


class EmbeddingCache:
    """Content-hash based embedding cache to avoid re-embedding unchanged text.

    Stores embeddings as JSON files in a cache directory, keyed by SHA-256
    of the input text. This is independent of the vector DB and persists
    across index rebuilds.
    """

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        # Use 2-level directory structure to avoid too many files in one dir
        return self.cache_dir / key[:2] / f"{key}.json"

    def get(self, text: str) -> list[float] | None:
        """Retrieve cached embedding for text, or None if not cached."""
        key = self._key(text)
        path = self._path(key)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return data.get("embedding")
            except (json.JSONDecodeError, OSError):
                return None
        return None

    def put(self, text: str, embedding: list[float]):
        """Cache an embedding for the given text."""
        key = self._key(text)
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(json.dumps({
                "hash": key,
                "embedding": embedding,
            }), encoding="utf-8")
        except OSError:
            pass  # Non-fatal: cache write failure

    def embed_with_cache(self, provider: EmbeddingProvider,
                         texts: list[str]) -> list[list[float]]:
        """Embed texts using cache where possible, provider for misses.

        Returns embeddings in the same order as the input texts.
        """
        results: list[list[float] | None] = [None] * len(texts)
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        # Check cache first
        for i, text in enumerate(texts):
            cached = self.get(text)
            if cached is not None:
                results[i] = cached
            else:
                uncached_indices.append(i)
                uncached_texts.append(text)

        # Embed uncached texts
        if uncached_texts:
            new_embeddings = provider.embed(uncached_texts)
            for idx, text, emb in zip(uncached_indices, uncached_texts,
                                       new_embeddings):
                results[idx] = emb
                self.put(text, emb)

        return results  # type: ignore[return-value]

    def clear(self):
        """Remove all cached embeddings."""
        import shutil
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)


def create_provider(config: dict) -> EmbeddingProvider:
    """Factory: create an embedding provider from config dict.

    Config keys:
        provider: "local" | "openai" | "voyage"
        model: model name (optional, defaults per provider)
        api_key: API key (required for API providers)
        api_key_env: env var name for API key (alternative to api_key)
    """
    provider_type = config.get("provider", "local")

    if provider_type == "local":
        from embeddings.local_onnx import LocalOnnxProvider
        model = config.get("model", "all-MiniLM-L6-v2")
        model_dir = config.get("model_dir")
        return LocalOnnxProvider(model_name_or_path=model,
                                 model_dir=model_dir)

    elif provider_type in ("openai", "voyage"):
        from embeddings.api_provider import ApiEmbeddingProvider
        api_key = config.get("api_key", "")
        if not api_key:
            env_var = config.get("api_key_env", "")
            if env_var:
                api_key = os.environ.get(env_var, "")
        model = config.get("model", "")
        return ApiEmbeddingProvider(
            provider=provider_type,
            api_key=api_key,
            model=model,
        )

    else:
        raise ValueError(f"Unknown embedding provider: {provider_type!r}. "
                         f"Supported: local, openai, voyage")
