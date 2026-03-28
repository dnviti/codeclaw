#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# CodeClaw Skills Installer
# ──────────────────────────────────────────────────────────────────────────────
#
# Installs the CodeClaw skillset into any AI coding platform project.
# Auto-detects the platform or accepts --platform to force one.
#
# Usage:
#   ./skills.sh [OPTIONS]
#   curl -sL <raw-url>/skills.sh | bash
#
# Options:
#   --platform PLATFORM   Force a specific platform (skip auto-detection)
#                         Platforms: claude-code, opencode, openclaw, cursor,
#                         windsurf, continue, copilot, aider, generic
#   --target DIR          Target project directory (default: current directory)
#   --link                Use symlinks instead of copies
#   --dry-run             Show what would be done without making changes
#   --help                Show this help message
#
# ──────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Delegate to the full installer
exec "$SCRIPT_DIR/templates/install.sh" "$@"
