#!/usr/bin/env python3
"""Social media announcement CLI for CodeClaw releases.

Generates platform-specific release announcements and posts them to
configured social media platforms. Supports direct posting (Bluesky,
Mastodon, Discord, Slack) and clipboard copy for manual posting
(Twitter/X, LinkedIn, Reddit, Hacker News).

Subcommands:
    generate  -- Generate platform-specific announcements from changelog
    post      -- Post to a single platform
    preview   -- Show all generated announcements for configured platforms
    platforms -- List configured platforms and credential status

All output is JSON. Zero external dependencies -- stdlib only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

# ── Imports from sibling modules ─────────────────────────────────────────

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from common import get_main_repo_root, load_project_config  # noqa: E402
from social_platforms import get_platform, list_platforms  # noqa: E402



def _get_social_config() -> dict[str, Any]:
    """Extract the social_announce section from project config."""
    config = load_project_config()
    return config.get("social_announce", {})


def _load_project_description() -> str:
    """Load project description from CLAUDE.md or project-config.json."""
    root = get_main_repo_root()
    # Try project_context from config
    config = load_project_config()
    desc = config.get("project_context", "")
    if desc:
        return desc

    # Try CLAUDE.md
    claude_md = root / "CLAUDE.md"
    if claude_md.exists():
        try:
            text = claude_md.read_text(encoding="utf-8")
            # Extract first paragraph after first heading
            lines = text.split("\n")
            in_content = False
            paragraphs = []
            for line in lines:
                if line.startswith("# "):
                    in_content = True
                    continue
                if in_content and line.strip():
                    paragraphs.append(line.strip())
                elif in_content and paragraphs:
                    break
            if paragraphs:
                return " ".join(paragraphs)
        except OSError:
            pass

    return ""


# ── Changelog parsing ────────────────────────────────────────────────────

def _parse_latest_changelog(changelog_path: str, version: str) -> dict[str, list[str]]:
    """Parse the latest version section from a Keep a Changelog file.

    Returns a dict mapping categories (Added, Changed, Fixed, etc.)
    to lists of change descriptions.
    """
    path = Path(changelog_path)
    if not path.exists():
        return {}

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    # Find the section for this version
    version_escaped = re.escape(version)
    section_re = re.compile(
        rf"^##\s+\[?{version_escaped}\]?.*?$",
        re.MULTILINE,
    )
    match = section_re.search(text)
    if not match:
        return {}

    # Extract content until next version heading or end of file
    start = match.end()
    next_heading = re.search(r"^##\s+\[", text[start:], re.MULTILINE)
    if next_heading:
        section = text[start:start + next_heading.start()]
    else:
        section = text[start:]

    # Parse categories
    categories: dict[str, list[str]] = {}
    current_cat = ""
    for line in section.split("\n"):
        cat_match = re.match(r"^###\s+(.+)$", line)
        if cat_match:
            current_cat = cat_match.group(1).strip()
            categories[current_cat] = []
        elif current_cat and line.strip().startswith("- "):
            categories[current_cat].append(line.strip()[2:].strip())

    return categories


def _summarize_changes(changes: dict[str, list[str]], max_items: int = 3) -> str:
    """Create a human-readable summary of changes."""
    parts = []
    for category in ["Added", "Changed", "Fixed", "Removed", "Security"]:
        items = changes.get(category, [])
        if items:
            shown = items[:max_items]
            if len(items) > max_items:
                parts.append(f"{category}: {', '.join(shown)} (+{len(items) - max_items} more)")
            else:
                parts.append(f"{category}: {', '.join(shown)}")
    return "; ".join(parts) if parts else "Various improvements and fixes."


# ── Announcement generation ─────────────────────────────────────────────

def _generate_short(version: str, repo_url: str, changes: dict[str, list[str]],
                     project_desc: str) -> str:
    """Generate a short announcement (~280 chars) for Bluesky/Twitter."""
    # Count total changes
    total = sum(len(v) for v in changes.values())
    highlights = []
    for cat in ["Added", "Fixed", "Changed"]:
        items = changes.get(cat, [])
        if items:
            highlights.append(items[0])
            if len(highlights) >= 2:
                break

    highlight_text = " | ".join(highlights) if highlights else "Various improvements"
    text = f"v{version} released! {highlight_text}. {repo_url}"

    if len(text) > 280:
        text = f"v{version} released! {total} changes. {repo_url}"
    return text


def _generate_medium(version: str, repo_url: str, changes: dict[str, list[str]],
                      project_desc: str) -> str:
    """Generate a medium announcement (~500 chars) for Mastodon/Reddit."""
    summary = _summarize_changes(changes, max_items=2)
    desc_part = f"{project_desc}\n\n" if project_desc else ""
    text = (
        f"{desc_part}"
        f"v{version} is out!\n\n"
        f"{summary}\n\n"
        f"Full changelog and downloads: {repo_url}/releases/tag/v{version}\n\n"
        f"#opensource #release"
    )
    return text[:500]


def _generate_full(version: str, repo_url: str, changes: dict[str, list[str]],
                    project_desc: str) -> str:
    """Generate a full announcement for Discord/Slack with rich formatting."""
    lines = []
    if project_desc:
        lines.append(f"*{project_desc}*")
        lines.append("")

    lines.append(f"**Release v{version}**")
    lines.append("")

    for category in ["Added", "Changed", "Fixed", "Removed", "Security"]:
        items = changes.get(category, [])
        if items:
            lines.append(f"**{category}:**")
            for item in items[:5]:
                lines.append(f"  - {item}")
            if len(items) > 5:
                lines.append(f"  - ... and {len(items) - 5} more")
            lines.append("")

    lines.append(f"Full changelog: {repo_url}/releases/tag/v{version}")
    return "\n".join(lines)


def generate_announcements(version: str, changelog_file: str, repo_url: str) -> dict[str, Any]:
    """Generate all announcement variants from changelog.

    Returns JSON with short, medium, and full announcement texts
    plus parsed changelog data.
    """
    changes = _parse_latest_changelog(changelog_file, version)
    project_desc = _load_project_description()

    # Clean repo_url trailing slash
    repo_url = repo_url.rstrip("/")

    short = _generate_short(version, repo_url, changes, project_desc)
    medium = _generate_medium(version, repo_url, changes, project_desc)
    full = _generate_full(version, repo_url, changes, project_desc)

    return {
        "version": version,
        "repo_url": repo_url,
        "changes_found": bool(changes),
        "change_categories": {k: len(v) for k, v in changes.items()},
        "announcements": {
            "short": {"text": short, "length": len(short), "platforms": ["bluesky", "clipboard"]},
            "medium": {"text": medium, "length": len(medium), "platforms": ["mastodon", "clipboard"]},
            "full": {"text": full, "length": len(full), "platforms": ["discord", "slack"]},
        },
    }


# ── Platform posting ────────────────────────────────────────────────────

PLATFORM_FORMAT_MAP = {
    "bluesky": "short",
    "mastodon": "medium",
    "discord": "full",
    "slack": "full",
    "clipboard": "medium",
}


def post_to_platform(platform_name: str, message: str) -> dict[str, Any]:
    """Post a message to a single platform."""
    try:
        p = get_platform(platform_name)
    except ValueError as e:
        return {"success": False, "platform": platform_name, "error": str(e)}

    return p.post(message)


# ── CLI ──────────────────────────────────────────────────────────────────

def cmd_generate(args: argparse.Namespace) -> None:
    """Handle the 'generate' subcommand."""
    result = generate_announcements(args.version, args.changelog_file, args.repo_url)
    print(json.dumps(result, indent=2))


def cmd_post(args: argparse.Namespace) -> None:
    """Handle the 'post' subcommand."""
    result = post_to_platform(args.platform, args.message)
    print(json.dumps(result, indent=2))


def cmd_preview(args: argparse.Namespace) -> None:
    """Handle the 'preview' subcommand."""
    config = load_project_config()
    social_config = config.get("social_announce", {})
    enabled_platforms = social_config.get("platforms", {})

    # Determine changelog file and repo URL from config
    changelog_file = args.changelog_file or config.get("changelog_file", "CHANGELOG.md")
    repo_url = args.repo_url or config.get("github_repo_url", "")

    announcements = generate_announcements(args.version, changelog_file, repo_url)

    # Build preview for each configured platform
    previews = []
    for pname, pconfig in enabled_platforms.items():
        if not pconfig.get("enabled", False):
            continue
        fmt = PLATFORM_FORMAT_MAP.get(pname, "medium")
        ann = announcements["announcements"].get(fmt, {})
        try:
            p = get_platform(pname)
            configured = p.is_configured()
        except ValueError:
            configured = False

        previews.append({
            "platform": pname,
            "format": fmt,
            "configured": configured,
            "announcement": ann.get("text", ""),
            "length": ann.get("length", 0),
        })

    # Include clipboard platforms
    clipboard_platforms = social_config.get("clipboard_platforms", [])
    for cp in clipboard_platforms:
        name = cp.get("name", "")
        fmt = "short" if cp.get("max_length", 500) <= 300 else "medium"
        ann = announcements["announcements"].get(fmt, {})
        previews.append({
            "platform": f"{name} (clipboard)",
            "format": fmt,
            "configured": True,
            "announcement": ann.get("text", ""),
            "length": ann.get("length", 0),
            "post_url": cp.get("post_url", ""),
        })

    result = {
        "version": args.version,
        "platforms": previews,
        "total_platforms": len(previews),
    }
    print(json.dumps(result, indent=2))


def cmd_platforms(args: argparse.Namespace) -> None:
    """Handle the 'platforms' subcommand."""
    social_config = _get_social_config()
    all_platforms = list_platforms()

    # Merge with project config
    enabled_in_config = social_config.get("platforms", {})
    for p in all_platforms:
        p["enabled_in_config"] = p["name"] in enabled_in_config and enabled_in_config[p["name"]].get("enabled", False)

    # Add clipboard platforms info
    clipboard_platforms = social_config.get("clipboard_platforms", [])

    result = {
        "platforms": all_platforms,
        "clipboard_platforms": clipboard_platforms,
        "config_section": "social_announce",
    }
    print(json.dumps(result, indent=2))


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Social media announcement manager for CodeClaw releases.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # generate
    gen_p = sub.add_parser("generate", help="Generate platform-specific announcements")
    gen_p.add_argument("--version", required=True, help="Release version (e.g. 1.2.0)")
    gen_p.add_argument("--changelog-file", required=True, help="Path to CHANGELOG.md")
    gen_p.add_argument("--repo-url", required=True, help="Repository URL")

    # post
    post_p = sub.add_parser("post", help="Post to a single platform")
    post_p.add_argument("--platform", required=True,
                        choices=["bluesky", "mastodon", "discord", "slack", "clipboard"],
                        help="Target platform")
    post_p.add_argument("--message", required=True, help="Message to post")

    # preview
    prev_p = sub.add_parser("preview", help="Preview announcements for configured platforms")
    prev_p.add_argument("--version", required=True, help="Release version")
    prev_p.add_argument("--changelog-file", default="", help="Path to CHANGELOG.md")
    prev_p.add_argument("--repo-url", default="", help="Repository URL")

    # platforms
    sub.add_parser("platforms", help="List configured platforms and credential status")

    args = parser.parse_args()
    dispatch = {
        "generate": cmd_generate,
        "post": cmd_post,
        "preview": cmd_preview,
        "platforms": cmd_platforms,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
