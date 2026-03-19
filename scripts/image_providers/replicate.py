"""Replicate image generation provider.

Uses the Replicate HTTP API for cloud-based image generation
with models like SDXL, Flux, etc.

Zero external dependencies -- stdlib only (urllib, json, base64, time).
"""

import base64
import json
import time
import urllib.error
import urllib.request

from image_providers import ImageProvider


# ── Replicate Configuration ──────────────────────────────────────────────────

_API_BASE = "https://api.replicate.com/v1"
_DEFAULT_MODEL = "stability-ai/sdxl:7762fd07cf82c948538e41f63f77d685e02b063e37e496e96eefd46c929f9bdc"
_DEFAULT_TIMEOUT = 120
_POLL_INTERVAL = 2  # seconds between status checks
_MAX_POLLS = 60  # maximum number of polling attempts


class ReplicateProvider(ImageProvider):
    """Image provider using Replicate API."""

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL,
                 timeout: int = _DEFAULT_TIMEOUT):
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def generate(self, prompt: str, size: str = "1024x1024",
                 style: str = "natural") -> bytes:
        """Generate an image via the Replicate API.

        Creates a prediction, polls for completion, and downloads
        the resulting image.
        """
        if not self._api_key:
            raise RuntimeError(
                "Replicate API token not configured. Set REPLICATE_API_TOKEN "
                "environment variable or configure api_key in "
                "project-config.json > image_generation."
            )

        width, height = self._parse_size(size)

        # Build prompt with style modifiers
        full_prompt = prompt
        if style == "vivid":
            full_prompt = f"{prompt}, vibrant colors, high contrast, detailed"
        elif style == "anime":
            full_prompt = f"{prompt}, anime style, illustration, detailed"

        # Create prediction
        prediction = self._create_prediction(full_prompt, width, height)

        # Poll for completion
        output_url = self._poll_prediction(prediction)

        # Download image
        return self._download_image(output_url)

    def provider_name(self) -> str:
        model_short = self._model.split(":")[0] if ":" in self._model else self._model
        return f"replicate ({model_short})"

    def is_available(self) -> bool:
        """Check if API token is configured."""
        return bool(self._api_key)

    def _create_prediction(self, prompt: str, width: int,
                           height: int) -> dict:
        """Create a new prediction on Replicate."""
        # Parse model version
        if ":" in self._model:
            version = self._model.split(":")[-1]
            url = f"{_API_BASE}/predictions"
            payload = {
                "version": version,
                "input": {
                    "prompt": prompt,
                    "width": width,
                    "height": height,
                    "negative_prompt": "blurry, low quality, distorted",
                },
            }
        else:
            url = f"{_API_BASE}/models/{self._model}/predictions"
            payload = {
                "input": {
                    "prompt": prompt,
                    "width": width,
                    "height": height,
                    "negative_prompt": "blurry, low quality, distorted",
                },
            }

        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "Prefer": "wait",
        }

        req = urllib.request.Request(url, data=data, headers=headers,
                                     method="POST")

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # S-4: Sanitize error body — extract only the structured error
            # message to avoid leaking credentials that might be echoed back
            error_msg = f"HTTP {e.code}"
            try:
                error_data = json.loads(e.read().decode("utf-8"))
                api_msg = error_data.get("detail", "")
                if api_msg:
                    error_msg = f"HTTP {e.code}: {str(api_msg)[:200]}"
            except Exception:
                pass
            raise RuntimeError(f"Replicate API error ({error_msg})")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Failed to connect to Replicate API: {e}")

    def _poll_prediction(self, prediction: dict) -> str:
        """Poll a prediction until it completes, return the output URL."""
        status = prediction.get("status", "")

        # If the prediction already completed (via Prefer: wait header)
        if status == "succeeded":
            return self._extract_output_url(prediction)

        poll_url = prediction.get("urls", {}).get("get", "")
        if not poll_url:
            pred_id = prediction.get("id", "")
            poll_url = f"{_API_BASE}/predictions/{pred_id}"

        headers = {"Authorization": f"Bearer {self._api_key}"}

        for _ in range(_MAX_POLLS):
            time.sleep(_POLL_INTERVAL)

            req = urllib.request.Request(poll_url, headers=headers,
                                         method="GET")
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    result = json.loads(resp.read().decode("utf-8"))
            except (urllib.error.URLError, urllib.error.HTTPError) as e:
                raise RuntimeError(f"Failed to poll Replicate prediction: {e}")

            status = result.get("status", "")
            if status == "succeeded":
                return self._extract_output_url(result)
            elif status in ("failed", "canceled"):
                error = result.get("error", "Unknown error")
                raise RuntimeError(
                    f"Replicate prediction {status}: {error}"
                )

        raise RuntimeError("Replicate prediction timed out.")

    @staticmethod
    def _extract_output_url(prediction: dict) -> str:
        """Extract the first image URL from a prediction result."""
        output = prediction.get("output")
        if isinstance(output, list) and output:
            return output[0]
        elif isinstance(output, str):
            return output
        raise RuntimeError("Replicate prediction returned no output.")

    @staticmethod
    def _download_image(url: str) -> bytes:
        """Download an image from a URL.

        Validates the URL to prevent SSRF attacks (S-3): only HTTPS
        URLs on public hostnames are allowed.
        """
        # S-3: Validate URL to prevent SSRF via spoofed API response
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.scheme not in ("https",):
            raise RuntimeError(
                f"Refusing to download from non-HTTPS URL: {url}"
            )
        hostname = parsed.hostname or ""
        # Block internal/metadata IPs
        _blocked = ("169.254.", "127.", "10.", "192.168.", "172.16.",
                     "0.", "localhost", "[::1]")
        if any(hostname.startswith(b) for b in _blocked):
            raise RuntimeError(
                f"Refusing to download from internal/private URL: {url}"
            )

        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            raise RuntimeError(f"Failed to download image from {url}: {e}")

    @staticmethod
    def _parse_size(size: str) -> tuple[int, int]:
        """Parse 'WIDTHxHEIGHT' string into (width, height) tuple."""
        try:
            parts = size.lower().split("x")
            return int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            return 1024, 1024
