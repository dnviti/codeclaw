"""Mastodon API posting adapter.

Posts release announcements to a Mastodon instance via the REST API.
Requires an access token (CLAW_MASTODON_TOKEN) and instance URL
(CLAW_MASTODON_INSTANCE, e.g. https://mastodon.social).

Zero external dependencies -- stdlib only (uses urllib.request).
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
import urllib.error
from typing import Any

from . import SocialPlatform, register


@register
class MastodonPlatform(SocialPlatform):
    """Mastodon REST API posting."""

    name = "mastodon"
    env_vars = ["CLAW_MASTODON_INSTANCE", "CLAW_MASTODON_TOKEN"]
    max_length = 500

    def post(self, message: str) -> dict[str, Any]:
        """Post a status to Mastodon."""
        if not self.is_configured():
            return {
                "success": False,
                "platform": self.name,
                "error": "Missing credentials. Set CLAW_MASTODON_INSTANCE and CLAW_MASTODON_TOKEN.",
            }

        instance = os.environ.get("CLAW_MASTODON_INSTANCE", "").rstrip("/")
        token = os.environ.get("CLAW_MASTODON_TOKEN", "")

        # Validate instance URL scheme
        parsed = urllib.parse.urlparse(instance)
        if parsed.scheme != "https":
            return {
                "success": False,
                "platform": self.name,
                "error": f"Mastodon instance URL must use HTTPS, got: {parsed.scheme!r}",
            }

        try:
            url = f"{instance}/api/v1/statuses"
            data = json.dumps({
                "status": message[:self.max_length],
                "visibility": "public",
            }).encode()
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())

            return {
                "success": True,
                "platform": self.name,
                "message": "Posted to Mastodon successfully.",
                "url": result.get("url", ""),
            }

        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else str(e)
            return {
                "success": False,
                "platform": self.name,
                "error": f"Mastodon API error ({e.code}): {body}",
            }
        except (urllib.error.URLError, OSError, ValueError) as e:
            return {
                "success": False,
                "platform": self.name,
                "error": f"Mastodon posting failed: {e}",
            }
