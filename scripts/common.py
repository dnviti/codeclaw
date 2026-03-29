#!/usr/bin/env python3
"""Shared utilities for CodeClaw scripts.

Centralises functions that were previously duplicated across multiple scripts:
find_project_root, get_main_repo_root, output_json, get_latest_tag, and
git_run.

Zero external dependencies — stdlib only.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────

# SKILL.md frontmatter parsing
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
YAML_KV_RE = re.compile(r'^(\w[\w-]*):\s*"?([^"]*?)"?\s*$', re.MULTILINE)


# ── Git Helpers ────────────────────────────────────────────────────────────

def git_run(*args: str, cwd: str | None = None) -> str | None:
    """Run a git command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True, check=True,
            cwd=cwd,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


# ── Project Root Detection ─────────────────────────────────────────────────

def find_project_root() -> Path:
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


def get_main_repo_root() -> Path:
    """Return the main repository root directory."""
    return find_project_root()


# ── Tag Helpers ────────────────────────────────────────────────────────────

def get_latest_tag(tag_prefix: str) -> str | None:
    """Get the latest git tag matching the prefix.

    Excludes environment-suffixed tags (e.g. -staging) so that only
    production tags are considered when determining the latest version.
    """
    try:
        result = subprocess.run(
            ["git", "tag", "-l", f"{tag_prefix}*", "--sort=-v:refname"],
            capture_output=True, text=True, check=True,
        )
        tags = [t for t in result.stdout.strip().splitlines()
                if not t.endswith("-staging")]
        return tags[0] if tags else None
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


# ── JSON Output ────────────────────────────────────────────────────────────

def output_json(data: dict) -> None:
    """Print JSON to stdout."""
    json.dump(data, sys.stdout, indent=2, default=str)
    print()


# ── SKILL.md Parser ───────────────────────────────────────────────────────

def parse_skill_md(skill_path: Path) -> dict | None:
    """Parse a SKILL.md file into structured data.

    Returns a dict with name, description, frontmatter, body, path, directory.
    """
    if not skill_path.exists():
        return None
    try:
        content = skill_path.read_text(encoding="utf-8")
    except OSError:
        return None

    frontmatter: dict[str, str] = {}
    body = content

    fm_match = FRONTMATTER_RE.match(content)
    if fm_match:
        fm_text = fm_match.group(1)
        for kv_match in YAML_KV_RE.finditer(fm_text):
            frontmatter[kv_match.group(1)] = kv_match.group(2).strip()
        body = content[fm_match.end():]

    return {
        "name": frontmatter.get("name", skill_path.parent.name),
        "description": frontmatter.get("description", ""),
        "frontmatter": frontmatter,
        "body": body.strip(),
        "path": str(skill_path),
        "directory": skill_path.parent.name,
    }


# ── Unified Config Loader ─────────────────────────────────────────────────

def load_config(root: Path | None = None) -> dict[str, str]:
    """Load project configuration from project-config.json.

    Config is checked at .claude/, config/, and the repository root.
    All keys are normalized to lowercase.
    """
    if root is None:
        root = get_main_repo_root()
    pc = load_project_config(root)

    # Flatten project-config.json top-level string values
    merged: dict[str, str] = {}
    for k, v in pc.items():
        if isinstance(v, str) and v:
            merged[k] = v

    return merged


# ── Project Config ────────────────────────────────────────────────────────

def load_project_config(root: Path | None = None) -> dict:
    """Load project-config.json from the repository root.

    Checks paths in order: .claude/project-config.json,
    config/project-config.json, project-config.json.
    """
    if root is None:
        root = get_main_repo_root()
    candidates = [
        root / ".claude" / "project-config.json",
        root / "config" / "project-config.json",
        root / "project-config.json",
    ]
    for config_path in candidates:
        if config_path.exists():
            try:
                return json.loads(config_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
    return {}
