"""API-based embedding providers (OpenAI, Voyage).

Supports OpenAI text-embedding-3-large and Voyage Code-3 via their
respective REST APIs using only stdlib (urllib).

Zero external dependencies — stdlib only (urllib, json).
"""

import json
import os
import urllib.request
import urllib.error
from typing import Optional

from embeddings import EmbeddingProvider


# ── Provider Configurations ──────────────────────────────────────────────────

_PROVIDER_CONFIG = {
    "openai": {
        "url": "https://api.openai.com/v1/embeddings",
        "default_model": "text-embedding-3-large",
        "dimension": 3072,
        "max_batch": 2048,
        "key_env": "OPENAI_API_KEY",
        "models": {
            "text-embedding-3-large": 3072,
            "text-embedding-3-small": 1536,
            "text-embedding-ada-002": 1536,
        },
    },
    "voyage": {
        "url": "https://api.voyageai.com/v1/embeddings",
        "default_model": "voyage-code-3",
        "dimension": 1024,
        "max_batch": 128,
        "key_env": "VOYAGE_API_KEY",
        "models": {
            "voyage-code-3": 1024,
            "voyage-3": 1024,
            "voyage-3-lite": 512,
        },
    },
}


class ApiEmbeddingProvider(EmbeddingProvider):
    """Embedding provider using external APIs (OpenAI, Voyage)."""

    def __init__(self, provider: str, api_key: str = "",
                 model: str = ""):
        if provider not in _PROVIDER_CONFIG:
            raise ValueError(
                f"Unknown API provider: {provider!r}. "
                f"Supported: {', '.join(_PROVIDER_CONFIG.keys())}"
            )

        self._config = _PROVIDER_CONFIG[provider]
        self._provider = provider
        self._model = model or self._config["default_model"]

        # Resolve API key
        self._api_key = api_key
        if not self._api_key:
            self._api_key = os.environ.get(self._config["key_env"], "")
        if not self._api_key:
            raise ValueError(
                f"API key required for {provider} embeddings. "
                f"Set {self._config['key_env']} environment variable or "
                f"pass api_key in config."
            )

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using the configured API provider."""
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        max_batch = self._config["max_batch"]

        # Process in batches
        for i in range(0, len(texts), max_batch):
            batch = texts[i:i + max_batch]
            embeddings = self._api_call(batch)
            all_embeddings.extend(embeddings)

        return all_embeddings

    def _api_call(self, texts: list[str]) -> list[list[float]]:
        """Make a single API call for a batch of texts."""
        url = self._config["url"]

        # Build request body (OpenAI and Voyage share the same format)
        body = {"input": texts, "model": self._model}

        data = json.dumps(body).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        req = urllib.request.Request(url, data=data, headers=headers,
                                     method="POST")

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")[:500]  # Truncate to avoid leaking sensitive data
            except Exception:
                pass
            raise RuntimeError(
                f"{self._provider} API error (HTTP {e.code}): {error_body}"
            )
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Failed to connect to {self._provider} API: {e}"
            )

        # Parse response — both OpenAI and Voyage use the same format
        if "data" not in result:
            raise RuntimeError(
                f"Unexpected API response from {self._provider}: "
                f"{json.dumps(result)[:200]}"
            )

        # Sort by index to maintain order
        sorted_data = sorted(result["data"], key=lambda x: x.get("index", 0))
        return [item["embedding"] for item in sorted_data]

    def dimension(self) -> int:
        models = self._config.get("models", {})
        if self._model in models:
            return models[self._model]
        return self._config["dimension"]

    def model_name(self) -> str:
        return f"{self._provider}/{self._model}"
