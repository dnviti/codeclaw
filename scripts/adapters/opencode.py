#!/usr/bin/env python3
"""OpenCode platform adapter for CodeClaw.

OpenCode is a JS-based AI coding assistant.  This adapter bridges its
JavaScript wrapper layer to CodeClaw's Python skill infrastructure by:

1. Discovering skills via the same skills/ directory
2. Invoking tools through Python subprocess calls (since OpenCode
   executes Python scripts as external processes)
3. Using stdin/stdout for user interaction when OpenCode does not
   provide a native prompt mechanism

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

from platform_adapter import PlatformAdapter, PLATFORM_OPENCODE


class OpenCodeAdapter(PlatformAdapter):
    """Adapter for the OpenCode AI coding platform.

    OpenCode discovers tools through a JS configuration layer.  This
    adapter presents CodeClaw skills as external Python scripts that
    OpenCode can call via its tool-execution pipeline.
    """

    platform_id: str = PLATFORM_OPENCODE

    def __init__(self, project_root: Path | None = None) -> None:
        super().__init__(project_root)

    # ── Skill Discovery ─────────────────────────────────────────────────

    def discover_skills(self) -> list[dict[str, Any]]:
        """Discover skills and present them in OpenCode-compatible format.

        OpenCode expects tool definitions to be described in a JSON schema.
        This method scans the skills/ directory and builds descriptors
        that the OpenCode JS wrapper can consume.
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

            # Extract the first line as a description
            description = ""
            try:
                first_lines = skill_md.read_text(encoding="utf-8").splitlines()[:5]
                for line in first_lines:
                    stripped = line.strip().lstrip("#").strip()
                    if stripped:
                        description = stripped
                        break
            except OSError:
                pass

            skills.append({
                "name": entry.name,
                "path": str(skill_md),
                "metadata": {
                    "format": "opencode-tool",
                    "description": description,
                    "invoke_cmd": f"python3 scripts/skill_helper.py dispatch --skill {entry.name}",
                    "directory": str(entry),
                },
            })
        return skills

    # ── Tool Invocation ─────────────────────────────────────────────────

    def invoke_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke a CodeClaw tool via subprocess.

        OpenCode calls Python scripts as external processes.  This method
        builds the appropriate command line and captures output as JSON.
        """
        root = self.get_project_root()
        helper = root / "scripts" / "skill_helper.py"

        if not helper.exists():
            return {
                "success": False,
                "output": "",
                "error": f"skill_helper.py not found at {helper}",
            }

        try:
            safe_args = self.validate_tool_arguments(arguments)
        except ValueError as exc:
            return {"success": False, "output": "", "error": str(exc)}

        cmd = [sys.executable, str(helper), tool_name]
        for key, value in safe_args.items():
            cmd.extend([f"--{key}", value])

        # OpenCode may set a custom working directory
        work_dir = os.environ.get("OPENCODE_WORKDIR", str(root))
        result = self.run_command(cmd, cwd=work_dir)

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
        """Prompt via stdout/stdin for OpenCode's terminal interface.

        OpenCode processes run in a terminal context where stdin is
        available for simple prompts.
        """
        if choices:
            display = f"{prompt}\nOptions: {', '.join(choices)}\n> "
        else:
            display = f"{prompt}\n> "

        try:
            return input(display).strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    # ── Configuration ───────────────────────────────────────────────────

    def get_config(self) -> dict[str, Any]:
        """Return merged OpenCode configuration."""
        adapter_settings = self.get_platform_settings()

        # OpenCode may have its own config at .opencode/config.json
        opencode_config: dict[str, Any] = {}
        oc_path = self.get_project_root() / ".opencode" / "config.json"
        if oc_path.exists():
            try:
                opencode_config = json.loads(oc_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        return {
            "platform": self.platform_id,
            "opencode_config": opencode_config,
            "adapter_settings": adapter_settings,
        }
