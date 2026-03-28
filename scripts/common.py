#!/usr/bin/env python3
"""Shared utilities for CodeClaw scripts.

Centralises functions that were previously duplicated across multiple scripts:
find_project_root, get_main_repo_root, parse_claude_md, output_json,
get_latest_tag, and git_run.

Zero external dependencies — stdlib only.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

# ── Constants ──────────────────────────────────────────────────────────────

CLAUDE_MD_VAR_RE = re.compile(r'^([A-Z_]+)\s*=\s*"?([^"#]*)"?\s*(?:#.*)?$')

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


# ── CLAUDE.md Parser ───────────────────────────────────────────────────────

def parse_claude_md(root: Path) -> dict[str, str]:
    """Extract key=value pairs from the bash code block in CLAUDE.md."""
    claude_md = root / "CLAUDE.md"
    if not claude_md.exists():
        return {}
    content = claude_md.read_text(encoding="utf-8")
    # Find the first ```bash ... ``` block
    m = re.search(r"```bash\n(.*?)```", content, re.DOTALL)
    if not m:
        return {}
    pairs: dict[str, str] = {}
    for line in m.group(1).splitlines():
        vm = CLAUDE_MD_VAR_RE.match(line)
        if vm:
            val = vm.group(2).strip().strip('"')
            if val:
                pairs[vm.group(1)] = val
    return pairs


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

_CLAUDE_MD_WARNED: set[str] = set()


def load_config(root: Path | None = None) -> dict[str, str]:
    """Load project configuration, merging project-config.json with CLAUDE.md fallback.

    Primary source: project-config.json (checked at .claude/, config/, root).
    Fallback: CLAUDE.md bash block key=value pairs (deprecated).
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

    # Fallback to CLAUDE.md bash block for any missing keys
    md_vars = parse_claude_md(root)
    for k_upper, v in md_vars.items():
        k_lower = k_upper.lower()
        if k_lower not in merged and v:
            if k_lower not in _CLAUDE_MD_WARNED:
                print(
                    f"[codeclaw] Config key '{k_lower}' read from CLAUDE.md"
                    " — migrate to project-config.json",
                    file=sys.stderr,
                )
                _CLAUDE_MD_WARNED.add(k_lower)
            merged[k_lower] = v

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
