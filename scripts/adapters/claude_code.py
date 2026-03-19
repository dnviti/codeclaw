#!/usr/bin/env python3
"""Claude Code platform adapter for CodeClaw.

Wraps the existing Claude Code plugin system behavior.  This is the
"native" adapter -- CodeClaw was originally built for Claude Code, so this
adapter delegates directly to the skill_helper and plugin.json machinery
that already exists.

Zero external dependencies -- stdlib only.
"""

import json
import sys
from pathlib import Path
from typing import Any

# Add parent directory to path so platform_adapter can be found
_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from platform_adapter import PlatformAdapter, PLATFORM_CLAUDE_CODE


class ClaudeCodeAdapter(PlatformAdapter):
    """Adapter for Claude Code's native plugin system.

    Claude Code discovers skills via the ``skills/`` directory structure
    where each skill has a ``SKILL.md`` file.  Tool invocation goes
    through the Claude Code tool-use protocol; user interaction is
    handled by Claude Code's built-in ask_user mechanism.
    """

    platform_id: str = PLATFORM_CLAUDE_CODE

    def __init__(self, project_root: Path | None = None) -> None:
        super().__init__(project_root)
        self._plugin_json: dict[str, Any] | None = None

    # ── Skill Discovery ─────────────────────────────────────────────────

    def discover_skills(self) -> list[dict[str, Any]]:
        """Discover skills from the skills/ directory structure.

        Claude Code expects each skill to live in ``skills/<name>/SKILL.md``.
        The plugin.json ``skills`` field points to the skills directory.
        """
        root = self.get_project_root()
        plugin = self._load_plugin_json()
        skills_dir = root / (plugin.get("skills", "skills") or "skills").strip("./")

        skills: list[dict[str, Any]] = []
        if not skills_dir.is_dir():
            return skills

        for entry in sorted(skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if skill_md.exists():
                skills.append({
                    "name": entry.name,
                    "path": str(skill_md),
                    "metadata": {
                        "format": "claude-code-skill-md",
                        "directory": str(entry),
                    },
                })
        return skills

    # ── Tool Invocation ─────────────────────────────────────────────────

    def invoke_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke a tool through Claude Code's protocol.

        In Claude Code, tool invocation is handled by the LLM runtime
        itself -- the adapter's role is to prepare the call and delegate
        to the skill_helper when the tool is a CodeClaw subcommand.
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
        """Prompt via Claude Code's native ask_user mechanism.

        In the plugin runtime, Claude Code handles user prompts through
        its built-in UI.  When running outside that context (e.g. direct
        CLI invocation), fall back to stdin.
        """
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
        """Return merged Claude Code configuration.

        Combines plugin.json metadata with platform-adapters.json settings.
        """
        plugin = self._load_plugin_json()
        adapter_settings = self.get_platform_settings()
        return {
            "platform": self.platform_id,
            "plugin": plugin,
            "adapter_settings": adapter_settings,
        }

    # ── Private ─────────────────────────────────────────────────────────

    def _load_plugin_json(self) -> dict[str, Any]:
        """Load and cache .claude-plugin/plugin.json."""
        if self._plugin_json is not None:
            return self._plugin_json

        path = self.get_project_root() / ".claude-plugin" / "plugin.json"
        if path.exists():
            try:
                self._plugin_json = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._plugin_json = {}
        else:
            self._plugin_json = {}
        return self._plugin_json
