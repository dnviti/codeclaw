"""Discord webhook posting adapter.

Posts release announcements to a Discord channel via webhook URL.
The webhook URL is stored in CTDF_DISCORD_WEBHOOK.

Zero external dependencies -- stdlib only (uses urllib.request).
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any

from . import SocialPlatform, register, validate_webhook_url


@register
class DiscordPlatform(SocialPlatform):
    """Discord webhook posting."""

    name = "discord"
    env_vars = ["CTDF_DISCORD_WEBHOOK"]
    max_length = 2000

    def post(self, message: str) -> dict[str, Any]:
        """Post a message to Discord via webhook."""
        if not self.is_configured():
            return {
                "success": False,
                "platform": self.name,
                "error": "Missing credentials. Set CTDF_DISCORD_WEBHOOK.",
            }

        webhook_url = os.environ.get("CTDF_DISCORD_WEBHOOK", "")

        try:
            validate_webhook_url(webhook_url, ["discord.com", "discordapp.com"])
        except ValueError as e:
            return {
                "success": False,
                "platform": self.name,
                "error": f"Invalid webhook URL: {e}",
            }

        try:
            data = json.dumps({"content": message[:self.max_length]}).encode()
            req = urllib.request.Request(
                webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                # Discord returns 204 No Content on success
                pass

            return {
                "success": True,
                "platform": self.name,
                "message": "Posted to Discord successfully.",
            }

        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else str(e)
            return {
                "success": False,
                "platform": self.name,
                "error": f"Discord webhook error ({e.code}): {body}",
            }
        except (urllib.error.URLError, OSError, ValueError) as e:
            return {
                "success": False,
                "platform": self.name,
                "error": f"Discord posting failed: {e}",
            }
