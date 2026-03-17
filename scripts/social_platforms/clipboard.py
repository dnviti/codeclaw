"""Cross-platform clipboard copy adapter.

Copies release announcement text to the system clipboard for manual posting
to platforms without free API access (Twitter/X, LinkedIn, Reddit, etc.).

Supports macOS (pbcopy), Linux (xclip/xsel), and Windows (clip.exe / WSL).

Zero external dependencies -- stdlib only.
"""

from __future__ import annotations

import platform
import subprocess
from typing import Any

from . import SocialPlatform, register

IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"


def _copy_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard. Returns True on success."""
    if IS_MACOS:
        try:
            proc = subprocess.run(
                ["pbcopy"],
                input=text.encode(),
                timeout=5,
            )
            return proc.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    if IS_WINDOWS:
        try:
            proc = subprocess.run(
                ["clip.exe"],
                input=text.encode(),
                timeout=5,
            )
            return proc.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return False

    # Linux: try xclip, then xsel
    for cmd in [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]:
        try:
            proc = subprocess.run(
                cmd,
                input=text.encode(),
                timeout=5,
            )
            if proc.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    # WSL fallback
    try:
        proc = subprocess.run(
            ["clip.exe"],
            input=text.encode(),
            timeout=5,
        )
        return proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return False


@register
class ClipboardPlatform(SocialPlatform):
    """Clipboard copy for manual posting (Twitter/X, LinkedIn, Reddit, etc.)."""

    name = "clipboard"
    env_vars = []  # No credentials needed
    max_length = 0  # Unlimited

    def post(self, message: str) -> dict[str, Any]:
        """Copy message to system clipboard."""
        success = _copy_to_clipboard(message)

        if success:
            return {
                "success": True,
                "platform": self.name,
                "message": "Announcement copied to clipboard. Paste it into the target platform.",
            }

        return {
            "success": False,
            "platform": self.name,
            "error": (
                "Could not copy to clipboard. No clipboard tool found. "
                "Install xclip (Linux) or use pbcopy (macOS) / clip.exe (Windows)."
            ),
        }

    def is_configured(self) -> bool:
        """Clipboard is always available (no credentials needed)."""
        return True
