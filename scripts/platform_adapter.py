#!/usr/bin/env python3
"""Platform adapter base class for CTDF multi-agent compatibility.

Provides a platform-agnostic abstraction layer so CTDF skills can run on
Claude Code, OpenCode, OpenClaw, Cursor, Windsurf, Continue, Copilot,
Aider, and any future platform that speaks the adapter interface.

Zero external dependencies -- stdlib only.
"""

import json
import os
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


# ── Constants ───────────────────────────────────────────────────────────────

ADAPTER_CONFIG_FILE = "platform-adapters.json"
ADAPTER_CONFIG_EXAMPLE = "platform-adapters.example.json"

# Environment variable that can force a specific platform
PLATFORM_ENV_VAR = "CTDF_PLATFORM"

# Known platform identifiers
PLATFORM_CLAUDE_CODE = "claude-code"
PLATFORM_OPENCODE = "opencode"
PLATFORM_OPENCLAW = "openclaw"
PLATFORM_CURSOR = "cursor"
PLATFORM_WINDSURF = "windsurf"
PLATFORM_CONTINUE = "continue"
PLATFORM_COPILOT = "copilot"
PLATFORM_AIDER = "aider"
PLATFORM_GENERIC = "generic"

ALL_PLATFORMS = [
    PLATFORM_CLAUDE_CODE,
    PLATFORM_OPENCODE,
    PLATFORM_OPENCLAW,
    PLATFORM_CURSOR,
    PLATFORM_WINDSURF,
    PLATFORM_CONTINUE,
    PLATFORM_COPILOT,
    PLATFORM_AIDER,
    PLATFORM_GENERIC,
]


# ── Base Class ──────────────────────────────────────────────────────────────

class PlatformAdapter(ABC):
    """Abstract base for platform-specific adapters.

    Each concrete adapter translates CTDF's platform-neutral skill interface
    into the native mechanism of a specific AI coding tool.  The adapter is
    responsible for:

    * Discovering available skills on disk
    * Invoking tools / running commands through the host platform
    * Prompting the user for input when the platform supports it
    * Loading project and adapter configuration
    * Resolving the project root directory
    """

    # Subclasses MUST set this to their platform identifier.
    platform_id: str = ""

    def __init__(self, project_root: Path | None = None) -> None:
        self._project_root = project_root or self._detect_project_root()
        self._config: dict[str, Any] = {}

    # ── Abstract interface ──────────────────────────────────────────────

    @abstractmethod
    def discover_skills(self) -> list[dict[str, Any]]:
        """Return a list of available skill descriptors.

        Each descriptor is a dict with at least:
            name     -- skill name (e.g. "task", "release")
            path     -- absolute path to the SKILL.md or equivalent
            metadata -- any extra platform-specific metadata
        """

    @abstractmethod
    def invoke_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke a tool by name with the given arguments.

        Returns a dict with at least:
            success -- bool
            output  -- str or dict with tool output
            error   -- str (only when success is False)
        """

    @abstractmethod
    def ask_user(self, prompt: str, choices: list[str] | None = None) -> str:
        """Prompt the user for input.

        Parameters
        ----------
        prompt : str
            The question to display.
        choices : list[str] | None
            Optional list of valid choices.  The adapter should present
            them in whatever way is native to the platform.

        Returns
        -------
        str
            The user's response text.
        """

    @abstractmethod
    def get_config(self) -> dict[str, Any]:
        """Return the merged configuration for this platform.

        The result combines the project-level platform-adapters.json
        settings with any environment or runtime overrides.
        """

    # ── Concrete helpers (shared across all adapters) ───────────────────

    def get_project_root(self) -> Path:
        """Return the resolved project root directory."""
        return self._project_root

    def run_command(
        self,
        cmd: list[str],
        *,
        cwd: str | None = None,
        capture: bool = True,
        timeout: int = 120,
    ) -> dict[str, Any]:
        """Execute a shell command and return structured output.

        Parameters
        ----------
        cmd : list[str]
            Command and arguments.
        cwd : str | None
            Working directory.  Defaults to project root.
        capture : bool
            Whether to capture stdout/stderr.
        timeout : int
            Timeout in seconds.

        Returns
        -------
        dict with keys: success, returncode, stdout, stderr
        """
        work_dir = cwd or str(self._project_root)
        try:
            result = subprocess.run(
                cmd,
                capture_output=capture,
                text=True,
                cwd=work_dir,
                timeout=timeout,
            )
            return {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout.strip() if capture else "",
                "stderr": result.stderr.strip() if capture else "",
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "returncode": -1,
                "stdout": "",
                "stderr": f"Command timed out after {timeout}s",
            }
        except FileNotFoundError:
            return {
                "success": False,
                "returncode": -1,
                "stdout": "",
                "stderr": f"Command not found: {cmd[0]}",
            }

    def load_adapter_config(self) -> dict[str, Any]:
        """Load platform-adapters.json from .claude/ or config/ directory."""
        if self._config:
            return self._config

        root = self._project_root
        candidates = [
            root / ".claude" / ADAPTER_CONFIG_FILE,
            root / "config" / ADAPTER_CONFIG_FILE,
        ]
        for path in candidates:
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    self._config = data
                    return data
                except (json.JSONDecodeError, OSError):
                    pass

        self._config = {}
        return self._config

    def get_platform_settings(self) -> dict[str, Any]:
        """Return settings specific to this adapter's platform_id."""
        cfg = self.load_adapter_config()
        adapters = cfg.get("adapters", {})
        return adapters.get(self.platform_id, {})

    # ── Private helpers ─────────────────────────────────────────────────

    @staticmethod
    def _detect_project_root() -> Path:
        """Find project root via git or by walking up to find to-do.txt."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, check=True,
            )
            root = Path(result.stdout.strip())
            if (root / "to-do.txt").exists():
                return root
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        d = Path.cwd()
        while d != d.parent:
            if (d / "to-do.txt").exists():
                return d
            d = d.parent
        return Path.cwd()


# ── Platform Detection ──────────────────────────────────────────────────────

def detect_platform() -> str:
    """Detect which AI coding platform is running CTDF.

    Detection order:
    1. Explicit CTDF_PLATFORM environment variable
    2. Platform-specific environment markers
    3. Config file override
    4. Fallback to "claude-code" (the original platform)
    """
    # 1. Explicit override
    explicit = os.environ.get(PLATFORM_ENV_VAR, "").strip().lower()
    if explicit and explicit in ALL_PLATFORMS:
        return explicit

    # 2. Environment-based detection
    # Claude Code sets CLAUDE_CODE or runs inside its plugin system
    if os.environ.get("CLAUDE_CODE") or os.environ.get("CLAUDE_PLUGIN"):
        return PLATFORM_CLAUDE_CODE

    # OpenCode uses OPENCODE_HOME or has its own markers
    if os.environ.get("OPENCODE_HOME") or os.environ.get("OPENCODE"):
        return PLATFORM_OPENCODE

    # OpenClaw / ClawHub
    if os.environ.get("OPENCLAW") or os.environ.get("CLAWHUB"):
        return PLATFORM_OPENCLAW

    # Cursor sets CURSOR_* env vars
    if os.environ.get("CURSOR_SESSION") or os.environ.get("CURSOR"):
        return PLATFORM_CURSOR

    # Windsurf / Codeium
    if os.environ.get("WINDSURF") or os.environ.get("CODEIUM_SESSION"):
        return PLATFORM_WINDSURF

    # Continue.dev
    if os.environ.get("CONTINUE_SESSION") or os.environ.get("CONTINUE"):
        return PLATFORM_CONTINUE

    # GitHub Copilot in agent mode
    if os.environ.get("COPILOT_AGENT") or os.environ.get("GITHUB_COPILOT"):
        return PLATFORM_COPILOT

    # Aider
    if os.environ.get("AIDER") or os.environ.get("AIDER_SESSION"):
        return PLATFORM_AIDER

    # 3. Check config file for a forced platform
    try:
        root = PlatformAdapter._detect_project_root()
        for name in (ADAPTER_CONFIG_FILE,):
            for parent in (root / ".claude", root / "config"):
                cfg_path = parent / name
                if cfg_path.exists():
                    data = json.loads(cfg_path.read_text(encoding="utf-8"))
                    forced = data.get("default_platform", "").strip().lower()
                    if forced and forced in ALL_PLATFORMS:
                        return forced
    except (json.JSONDecodeError, OSError):
        pass

    # 4. Default: Claude Code (CTDF's original platform)
    return PLATFORM_CLAUDE_CODE


def get_adapter(platform: str | None = None, project_root: Path | None = None):
    """Factory: return the correct PlatformAdapter subclass instance.

    Parameters
    ----------
    platform : str | None
        Platform identifier.  Auto-detected when None.
    project_root : Path | None
        Project root.  Auto-detected when None.

    Returns
    -------
    PlatformAdapter
        A concrete adapter instance ready to use.
    """
    if platform is None:
        platform = detect_platform()

    # Lazy imports to avoid circular dependencies and keep startup fast
    if platform == PLATFORM_CLAUDE_CODE:
        from adapters.claude_code import ClaudeCodeAdapter
        return ClaudeCodeAdapter(project_root)

    if platform == PLATFORM_OPENCODE:
        from adapters.opencode import OpenCodeAdapter
        return OpenCodeAdapter(project_root)

    if platform == PLATFORM_OPENCLAW:
        from adapters.openclaw import OpenClawAdapter
        return OpenClawAdapter(project_root)

    # All other platforms use the generic adapter
    from adapters.generic import GenericAdapter
    return GenericAdapter(project_root, platform_id=platform)
