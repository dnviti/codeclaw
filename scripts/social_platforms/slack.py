"""Slack webhook posting adapter.

Posts release announcements to a Slack channel via incoming webhook URL.
The webhook URL is stored in CTDF_SLACK_WEBHOOK.

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
class SlackPlatform(SocialPlatform):
    """Slack incoming webhook posting."""

    name = "slack"
    env_vars = ["CTDF_SLACK_WEBHOOK"]
    max_length = 4000

    def post(self, message: str) -> dict[str, Any]:
        """Post a message to Slack via incoming webhook."""
        if not self.is_configured():
            return {
                "success": False,
                "platform": self.name,
                "error": "Missing credentials. Set CTDF_SLACK_WEBHOOK.",
            }

        webhook_url = os.environ.get("CTDF_SLACK_WEBHOOK", "")

        try:
            validate_webhook_url(webhook_url, ["hooks.slack.com"])
        except ValueError as e:
            return {
                "success": False,
                "platform": self.name,
                "error": f"Invalid webhook URL: {e}",
            }

        try:
            data = json.dumps({"text": message[:self.max_length]}).encode()
            req = urllib.request.Request(
                webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                resp.read()  # Slack returns "ok" on success

            return {
                "success": True,
                "platform": self.name,
                "message": "Posted to Slack successfully.",
            }

        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else str(e)
            return {
                "success": False,
                "platform": self.name,
                "error": f"Slack webhook error ({e.code}): {body}",
            }
        except (urllib.error.URLError, OSError, ValueError) as e:
            return {
                "success": False,
                "platform": self.name,
                "error": f"Slack posting failed: {e}",
            }
