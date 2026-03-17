"""Platform adapters for CTDF multi-agent compatibility.

Each module provides a concrete PlatformAdapter subclass that translates
CTDF skill operations into the native mechanisms of a specific AI coding
platform.

Available adapters:
    claude_code -- Claude Code plugin system (default / original)
    opencode    -- OpenCode JS wrapper -> Python bridge
    openclaw    -- OpenClaw / ClawHub SKILL.md format
    generic     -- Fallback for Cursor, Windsurf, Continue, Copilot, Aider

Zero external dependencies -- stdlib only.
"""
