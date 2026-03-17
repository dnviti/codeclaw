"""Bluesky (AT Protocol) posting adapter.

Posts release announcements to Bluesky via the AT Protocol public API.
Authentication uses an app password stored in CTDF_BLUESKY_APP_PASSWORD.
The handle is stored in CTDF_BLUESKY_HANDLE.

Zero external dependencies -- stdlib only (uses urllib.request).
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Any

from . import SocialPlatform, register


@register
class BlueskyPlatform(SocialPlatform):
    """Bluesky AT Protocol posting."""

    name = "bluesky"
    env_vars = ["CTDF_BLUESKY_HANDLE", "CTDF_BLUESKY_APP_PASSWORD"]
    max_length = 300

    BSKY_API = "https://bsky.social/xrpc"

    def _create_session(self) -> dict[str, Any]:
        """Authenticate and create an AT Protocol session."""
        handle = os.environ.get("CTDF_BLUESKY_HANDLE", "")
        password = os.environ.get("CTDF_BLUESKY_APP_PASSWORD", "")

        url = f"{self.BSKY_API}/com.atproto.server.createSession"
        data = json.dumps({"identifier": handle, "password": password}).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())

    def post(self, message: str) -> dict[str, Any]:
        """Post a message to Bluesky."""
        if not self.is_configured():
            return {
                "success": False,
                "platform": self.name,
                "error": "Missing credentials. Set CTDF_BLUESKY_HANDLE and CTDF_BLUESKY_APP_PASSWORD.",
            }

        try:
            session = self._create_session()
            did = session["did"]
            access_token = session["accessJwt"]

            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            record = {
                "repo": did,
                "collection": "app.bsky.feed.post",
                "record": {
                    "$type": "app.bsky.feed.post",
                    "text": message[:self.max_length],
                    "createdAt": now,
                },
            }

            url = f"{self.BSKY_API}/com.atproto.repo.createRecord"
            data = json.dumps(record).encode()
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {access_token}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode())

            post_uri = result.get("uri", "")
            # Build a web URL from the AT URI
            # at://did:plc:xxx/app.bsky.feed.post/rkey -> profile URL
            handle = os.environ.get("CTDF_BLUESKY_HANDLE", "")
            rkey = post_uri.rsplit("/", 1)[-1] if "/" in post_uri else ""
            web_url = f"https://bsky.app/profile/{handle}/post/{rkey}" if rkey else ""

            return {
                "success": True,
                "platform": self.name,
                "message": "Posted to Bluesky successfully.",
                "url": web_url,
            }

        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else str(e)
            return {
                "success": False,
                "platform": self.name,
                "error": f"Bluesky API error ({e.code}): {body}",
            }
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            return {
                "success": False,
                "platform": self.name,
                "error": f"Bluesky posting failed: {e}",
            }
