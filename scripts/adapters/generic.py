#!/usr/bin/env python3
"""Generic / fallback platform adapter for CTDF.

Handles Cursor, Windsurf, Continue, Copilot, Aider, and any other
AI coding tool that reads AGENTS.md or .github/copilot-instructions.md
for project context.  This adapter provides a common baseline that
works with any platform capable of running Python scripts.

Zero external dependencies -- stdlib only.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from platform_adapter import (
    PlatformAdapter,
    PLATFORM_GENERIC,
    PLATFORM_CURSOR,
    PLATFORM_WINDSURF,
    PLATFORM_CONTINUE,
    PLATFORM_COPILOT,
    PLATFORM_AIDER,
)

# Mapping from platform_id to typical instruction file paths
_INSTRUCTION_FILES: dict[str, list[str]] = {
    PLATFORM_CURSOR: [".cursor/rules", ".cursorrules"],
    PLATFORM_WINDSURF: [".windsurf/rules", ".windsurfrules"],
    PLATFORM_CONTINUE: [".continue/config.json"],
    PLATFORM_COPILOT: [".github/copilot-instructions.md"],
    PLATFORM_AIDER: [".aider.conf.yml", ".aiderignore"],
    PLATFORM_GENERIC: ["AGENTS.md"],
}


class GenericAdapter(PlatformAdapter):
    """Fallback adapter for platforms without a dedicated integration.

    Works with Cursor, Windsurf, Continue, Copilot, Aider, and any
    other tool that can execute Python scripts and read Markdown
    instruction files.

    The adapter discovers skills from the standard skills/ directory
    and invokes tools through direct Python subprocess calls.
    """

    platform_id: str = PLATFORM_GENERIC

    def __init__(
        self,
        project_root: Path | None = None,
        platform_id: str | None = None,
    ) -> None:
        if platform_id:
            self.platform_id = platform_id
        super().__init__(project_root)

    # ── Skill Discovery ─────────────────────────────────────────────────

    def discover_skills(self) -> list[dict[str, Any]]:
        """Discover skills from the skills/ directory.

        Generic platforms read skill definitions from SKILL.md files.
        The adapter also checks for platform-specific instruction files
        (e.g. AGENTS.md, .cursorrules) that may reference skills.
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

            # Extract description from first meaningful line
            description = ""
            try:
                for line in skill_md.read_text(encoding="utf-8").splitlines()[:10]:
                    stripped = line.strip().lstrip("#").strip()
                    if stripped and not stripped.startswith("<!--"):
                        description = stripped
                        break
            except OSError:
                pass

            skills.append({
                "name": entry.name,
                "path": str(skill_md),
                "metadata": {
                    "format": "generic-skill-md",
                    "description": description,
                    "directory": str(entry),
                    "platform": self.platform_id,
                },
            })
        return skills

    # ── Tool Invocation ─────────────────────────────────────────────────

    def invoke_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke a tool through direct subprocess execution.

        All generic platforms use the same mechanism: run skill_helper.py
        as a Python subprocess and capture its JSON output.
        """
        root = self.get_project_root()
        helper = root / "scripts" / "skill_helper.py"

        if not helper.exists():
            return {
                "success": False,
                "output": "",
                "error": f"skill_helper.py not found at {helper}",
            }

        cmd = [sys.executable, str(helper), tool_name]
        for key, value in arguments.items():
            cmd.extend([f"--{key}", str(value)])

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
        """Prompt via stdin/stdout.

        Most generic platforms operate in a terminal or editor context
        where direct stdin prompting may not be available.  In that case,
        return an empty string (the caller should handle non-interactive
        mode gracefully).
        """
        # Check if stdin is a terminal (interactive mode)
        if not sys.stdin.isatty():
            return ""

        if choices:
            display = f"{prompt} [{'/'.join(choices)}]: "
        else:
            display = f"{prompt}: "

        try:
            return input(display).strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    # ── Configuration ───────────────────────────────────────────────────

    def get_config(self) -> dict[str, Any]:
        """Return merged configuration for this generic platform."""
        adapter_settings = self.get_platform_settings()
        instruction_files = self._find_instruction_files()

        return {
            "platform": self.platform_id,
            "instruction_files": instruction_files,
            "adapter_settings": adapter_settings,
            "interactive": sys.stdin.isatty(),
        }

    # ── Platform-Specific Helpers ───────────────────────────────────────

    def get_instruction_file_paths(self) -> list[str]:
        """Return the list of instruction file paths for this platform."""
        return _INSTRUCTION_FILES.get(self.platform_id, ["AGENTS.md"])

    def _find_instruction_files(self) -> list[str]:
        """Find which platform instruction files exist in the project."""
        root = self.get_project_root()
        candidates = self.get_instruction_file_paths()
        found: list[str] = []
        for rel_path in candidates:
            if (root / rel_path).exists():
                found.append(rel_path)
        return found
