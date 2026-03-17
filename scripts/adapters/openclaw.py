#!/usr/bin/env python3
"""OpenClaw platform adapter for CTDF.

OpenClaw uses a SKILL.md-based format for skill definitions and
integrates with ClawHub for skill sharing and discovery.  This adapter
maps CTDF's skill directory structure onto OpenClaw's expectations.

Zero external dependencies -- stdlib only.
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from platform_adapter import PlatformAdapter, PLATFORM_OPENCLAW


class OpenClawAdapter(PlatformAdapter):
    """Adapter for the OpenClaw / ClawHub platform.

    OpenClaw discovers skills through SKILL.md files and can register
    them with ClawHub for cross-project sharing.  Each skill's SKILL.md
    is parsed for metadata directives that OpenClaw uses to build its
    skill registry.
    """

    platform_id: str = PLATFORM_OPENCLAW

    # Regex to extract metadata from SKILL.md front-matter comments
    _METADATA_RE = re.compile(
        r"^<!--\s*(\w+):\s*(.+?)\s*-->$", re.MULTILINE
    )

    def __init__(self, project_root: Path | None = None) -> None:
        super().__init__(project_root)

    # ── Skill Discovery ─────────────────────────────────────────────────

    def discover_skills(self) -> list[dict[str, Any]]:
        """Discover skills in OpenClaw's SKILL.md format.

        OpenClaw supports two discovery modes:
        1. Local: scan skills/ directory for SKILL.md files
        2. ClawHub: fetch registered skills from the hub (not yet implemented)

        Each SKILL.md may contain HTML comment metadata directives:
            <!-- clawhub-id: ctdf/task -->
            <!-- clawhub-version: 1.0.0 -->
        """
        root = self.get_project_root()
        skills_dir = root / "skills"
        skills: list[dict[str, Any]] = []

        if not skills_dir.is_dir():
            return skills

        for entry in sorted(skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.exists():
                continue

            # Parse SKILL.md for OpenClaw metadata
            metadata = self._parse_skill_metadata(skill_md)
            metadata["format"] = "openclaw-skill"
            metadata["directory"] = str(entry)

            skills.append({
                "name": entry.name,
                "path": str(skill_md),
                "metadata": metadata,
            })
        return skills

    # ── Tool Invocation ─────────────────────────────────────────────────

    def invoke_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke a tool through OpenClaw's execution layer.

        OpenClaw routes tool calls through its own dispatcher.  When
        running outside the OpenClaw runtime (e.g. direct invocation),
        this falls back to calling skill_helper.py directly.
        """
        root = self.get_project_root()

        try:
            safe_args = self.validate_tool_arguments(arguments)
        except ValueError as exc:
            return {"success": False, "output": "", "error": str(exc)}

        # Check if OpenClaw's native dispatcher is available
        openclaw_bin = os.environ.get("OPENCLAW_BIN", "")
        if openclaw_bin and Path(openclaw_bin).exists():
            cmd = [openclaw_bin, "invoke", tool_name]
            for key, value in safe_args.items():
                cmd.extend([f"--{key}", value])
            result = self.run_command(cmd)
        else:
            # Fallback: direct Python invocation
            helper = root / "scripts" / "skill_helper.py"
            if not helper.exists():
                return {
                    "success": False,
                    "output": "",
                    "error": f"skill_helper.py not found at {helper}",
                }
            cmd = [sys.executable, str(helper), tool_name]
            for key, value in safe_args.items():
                cmd.extend([f"--{key}", value])
            result = self.run_command(cmd)

        if result["success"]:
            try:
                parsed = json.loads(result["stdout"])
                return {"success": True, "output": parsed, "error": ""}
            except json.JSONDecodeError:
                return {"success": True, "output": result["stdout"], "error": ""}
        return {
            "success": False,
            "output": result["stdout"],
            "error": result["stderr"],
        }

    # ── User Interaction ────────────────────────────────────────────────

    def ask_user(self, prompt: str, choices: list[str] | None = None) -> str:
        """Prompt the user through OpenClaw's interface.

        OpenClaw may provide a structured prompt mechanism via its
        runtime.  Outside that context, use stdin.
        """
        if choices:
            numbered = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(choices))
            display = f"{prompt}\n{numbered}\nChoice: "
        else:
            display = f"{prompt}: "

        try:
            return input(display).strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    # ── Configuration ───────────────────────────────────────────────────

    def get_config(self) -> dict[str, Any]:
        """Return merged OpenClaw configuration."""
        adapter_settings = self.get_platform_settings()

        # OpenClaw may store config in .openclaw/config.json
        openclaw_config: dict[str, Any] = {}
        oc_path = self.get_project_root() / ".openclaw" / "config.json"
        if oc_path.exists():
            try:
                openclaw_config = json.loads(oc_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        return {
            "platform": self.platform_id,
            "openclaw_config": openclaw_config,
            "adapter_settings": adapter_settings,
            "clawhub_enabled": bool(os.environ.get("CLAWHUB")),
        }

    # ── Private ─────────────────────────────────────────────────────────

    def _parse_skill_metadata(self, skill_md: Path) -> dict[str, str]:
        """Extract metadata directives from SKILL.md HTML comments."""
        metadata: dict[str, str] = {}
        try:
            content = skill_md.read_text(encoding="utf-8")
            for match in self._METADATA_RE.finditer(content):
                key = match.group(1).strip().lower().replace("-", "_")
                metadata[key] = match.group(2).strip()
        except OSError:
            pass
        return metadata
