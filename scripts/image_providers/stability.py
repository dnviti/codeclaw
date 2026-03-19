"""Stability AI image generation provider.

Uses the Stability AI REST API for cloud-based image generation
with Stable Diffusion models.

Zero external dependencies -- stdlib only (urllib, json, base64).
"""

import base64
import json
import urllib.error
import urllib.request

from image_providers import ImageProvider


# ── Stability Configuration ──────────────────────────────────────────────────

_API_BASE = "https://api.stability.ai"
_DEFAULT_ENGINE = "stable-diffusion-xl-1024-v1-0"
_DEFAULT_TIMEOUT = 60

# Supported sizes for SDXL
_VALID_DIMENSIONS = {
    "1024x1024", "1152x896", "896x1152",
    "1216x832", "832x1216", "1344x768",
    "768x1344", "1536x640", "640x1536",
}


class StabilityProvider(ImageProvider):
    """Image provider using Stability AI API."""

    def __init__(self, api_key: str, engine: str = _DEFAULT_ENGINE,
                 timeout: int = _DEFAULT_TIMEOUT):
        self._api_key = api_key
        self._engine = engine
        self._timeout = timeout

    def generate(self, prompt: str, size: str = "1024x1024",
                 style: str = "natural") -> bytes:
        """Generate an image via the Stability AI API.

        Returns raw PNG image bytes.
        """
        if not self._api_key:
            raise RuntimeError(
                "Stability AI API key not configured. Set STABILITY_API_KEY "
                "environment variable or configure api_key in "
                "project-config.json > image_generation."
            )

        width, height = self._normalize_size(size)

        # Map style to style_preset
        style_preset = self._map_style(style)

        payload = {
            "text_prompts": [
                {"text": prompt, "weight": 1.0},
                {"text": "blurry, low quality, distorted", "weight": -1.0},
            ],
            "cfg_scale": 7,
            "height": height,
            "width": width,
            "samples": 1,
            "steps": 30,
        }

        if style_preset:
            payload["style_preset"] = style_preset

        url = (
            f"{_API_BASE}/v1/generation/{self._engine}/text-to-image"
        )
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        req = urllib.request.Request(url, data=data, headers=headers,
                                     method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # S-4: Sanitize error body — extract only the structured error
            # message to avoid leaking credentials that might be echoed back
            error_msg = f"HTTP {e.code}"
            try:
                error_data = json.loads(e.read().decode("utf-8"))
                api_msg = error_data.get("message", "")
                if api_msg:
                    error_msg = f"HTTP {e.code}: {api_msg[:200]}"
            except Exception:
                pass
            raise RuntimeError(f"Stability AI API error ({error_msg})")
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Failed to connect to Stability AI API: {e}"
            )

        # Extract base64 image data
        artifacts = result.get("artifacts", [])
        if not artifacts:
            raise RuntimeError("Stability AI API returned no images.")

        b64_image = artifacts[0].get("base64", "")
        if not b64_image:
            raise RuntimeError("Stability AI API returned empty image data.")

        return base64.b64decode(b64_image)

    def provider_name(self) -> str:
        return f"stability ({self._engine})"

    def is_available(self) -> bool:
        """Check if API key is configured."""
        return bool(self._api_key)

    def _normalize_size(self, size: str) -> tuple[int, int]:
        """Normalize size to Stability AI supported dimensions.

        O-5: Simplified — parse once, validate once, fall back to default.
        """
        try:
            parts = size.lower().split("x")
            w, h = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            return 1024, 1024

        if f"{w}x{h}" in _VALID_DIMENSIONS:
            return w, h
        return 1024, 1024

    @staticmethod
    def _map_style(style: str) -> str:
        """Map generic style name to Stability AI style_preset."""
        style_map = {
            "natural": "",
            "vivid": "enhance",
            "anime": "anime",
            "photographic": "photographic",
            "digital-art": "digital-art",
            "comic-book": "comic-book",
            "fantasy-art": "fantasy-art",
            "3d-model": "3d-model",
            "pixel-art": "pixel-art",
        }
        return style_map.get(style, "")
