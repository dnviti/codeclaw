"""Image provider abstraction for CodeClaw image generation.

Supports:
- Local diffuser (REST API to local diffusion model, e.g. OllamaDiffuser)
- OpenAI DALL-E (cloud API)
- Replicate (cloud API)
- Stability AI (cloud API)

Each provider implements the ImageProvider ABC with a generate() method
that returns raw image bytes.

Zero external dependencies -- stdlib only for the base interface.
API providers use urllib (stdlib) for HTTP calls.
"""

import os
from abc import ABC, abstractmethod
from typing import Optional


class ImageProvider(ABC):
    """Abstract base class for image generation providers."""

    @abstractmethod
    def generate(self, prompt: str, size: str = "1024x1024",
                 style: str = "natural") -> bytes:
        """Generate an image from a text prompt.

        Parameters
        ----------
        prompt : str
            Text description of the desired image.
        size : str
            Image dimensions as "WIDTHxHEIGHT" (e.g. "1024x1024").
        style : str
            Style hint (e.g. "natural", "vivid", "anime"). Provider-specific.

        Returns
        -------
        bytes
            Raw image data (PNG format preferred).
        """
        ...

    @abstractmethod
    def provider_name(self) -> str:
        """Return a human-readable provider identifier."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check whether the provider is configured and reachable."""
        ...


def create_provider(config: dict) -> ImageProvider:
    """Factory: create an image provider from config dict.

    Config keys:
        provider: "local" | "dalle" | "replicate" | "stability"
        api_key: API key (for cloud providers) -- direct value, avoid for production
        api_key_env: Name of the environment variable holding the API key.
            Preferred over api_key for security: the key is read from the
            process environment at runtime and never persisted in config files.
            Example: "OPENAI_API_KEY", "REPLICATE_API_TOKEN", "STABILITY_API_KEY".
        base_url: base URL override (for local provider)
    """
    provider_type = config.get("provider", "local")

    # Resolve API key from config or environment
    # API keys: standard env-var pattern; never logged or serialized to disk
    api_key = config.get("api_key", "")
    if not api_key:
        env_var = config.get("api_key_env", "")
        if env_var:
            api_key = os.environ.get(env_var, "")

    if provider_type == "local":
        from image_providers.local_diffuser import LocalDiffuserProvider
        base_url = config.get("base_url", "http://localhost:7860")
        return LocalDiffuserProvider(base_url=base_url)

    elif provider_type == "dalle":
        from image_providers.dalle import DallEProvider
        if not api_key:
            api_key = os.environ.get("OPENAI_API_KEY", "")
        return DallEProvider(api_key=api_key)

    elif provider_type == "replicate":
        from image_providers.replicate import ReplicateProvider
        if not api_key:
            api_key = os.environ.get("REPLICATE_API_TOKEN", "")
        return ReplicateProvider(api_key=api_key)

    elif provider_type == "stability":
        from image_providers.stability import StabilityProvider
        if not api_key:
            api_key = os.environ.get("STABILITY_API_KEY", "")
        return StabilityProvider(api_key=api_key)

    else:
        raise ValueError(
            f"Unknown image provider: {provider_type!r}. "
            f"Supported: local, dalle, replicate, stability"
        )
