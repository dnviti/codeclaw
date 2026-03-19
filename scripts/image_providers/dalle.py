"""OpenAI DALL-E image generation provider.

Uses the OpenAI Images API (DALL-E 3 / DALL-E 2) for cloud-based
image generation via REST.

Zero external dependencies -- stdlib only (urllib, json, base64).
"""

import base64
import json
import urllib.error
import urllib.request

from image_providers import ImageProvider


# ── DALL-E Configuration ─────────────────────────────────────────────────────

_API_URL = "https://api.openai.com/v1/images/generations"
_DEFAULT_MODEL = "dall-e-3"
_DEFAULT_TIMEOUT = 60

# DALL-E 3 supported sizes
_VALID_SIZES_DALLE3 = {"1024x1024", "1024x1792", "1792x1024"}
_VALID_SIZES_DALLE2 = {"256x256", "512x512", "1024x1024"}


class DallEProvider(ImageProvider):
    """Image provider using OpenAI DALL-E API."""

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL,
                 timeout: int = _DEFAULT_TIMEOUT):
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def generate(self, prompt: str, size: str = "1024x1024",
                 style: str = "natural") -> bytes:
        """Generate an image via the OpenAI DALL-E API.

        Returns raw PNG image bytes.
        """
        if not self._api_key:
            raise RuntimeError(
                "DALL-E API key not configured. Set OPENAI_API_KEY "
                "environment variable or configure api_key in "
                "project-config.json > image_generation."
            )

        # Validate and normalize size
        size = self._normalize_size(size)

        # Map style to DALL-E style parameter
        dalle_style = "natural"
        if style in ("vivid", "anime"):
            dalle_style = "vivid"

        payload = {
            "model": self._model,
            "prompt": prompt,
            "n": 1,
            "size": size,
            "response_format": "b64_json",
        }

        # DALL-E 3 supports style parameter; DALL-E 2 does not
        if self._model == "dall-e-3":
            payload["style"] = dalle_style

        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        req = urllib.request.Request(_API_URL, data=data, headers=headers,
                                     method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # S-4: Sanitize error body — extract only the error message
            # field to avoid leaking credentials that might be echoed back
            error_msg = f"HTTP {e.code}"
            try:
                error_data = json.loads(e.read().decode("utf-8"))
                api_msg = error_data.get("error", {}).get("message", "")
                if api_msg:
                    error_msg = f"HTTP {e.code}: {api_msg[:200]}"
            except Exception:
                pass
            raise RuntimeError(f"DALL-E API error ({error_msg})")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Failed to connect to OpenAI API: {e}")

        # Extract base64 image data
        data_list = result.get("data", [])
        if not data_list:
            raise RuntimeError("DALL-E API returned no images.")

        b64_image = data_list[0].get("b64_json", "")
        if not b64_image:
            raise RuntimeError("DALL-E API returned empty image data.")

        return base64.b64decode(b64_image)

    def provider_name(self) -> str:
        return f"dalle ({self._model})"

    def is_available(self) -> bool:
        """Check if API key is configured."""
        return bool(self._api_key)

    def _normalize_size(self, size: str) -> str:
        """Normalize size to a DALL-E supported value."""
        valid = (_VALID_SIZES_DALLE3 if self._model == "dall-e-3"
                 else _VALID_SIZES_DALLE2)
        if size in valid:
            return size
        # Fall back to default
        return "1024x1024"
