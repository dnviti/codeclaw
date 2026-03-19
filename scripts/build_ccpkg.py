#!/usr/bin/env python3
"""Build a .ccpkg archive for standardized cross-tool distribution.

Assembles a ccpkg-format archive following the ccpkg open packaging
specification. The archive contains all Python scripts, skill definitions,
templates, and hooks -- fully vendored with no network dependencies.

The build process:
  1. Reads plugin.json for package metadata
  2. Discovers skills, hooks, and agent components
  3. Generates ccpkg-manifest.json with typed config schema
  4. Computes SHA-256 checksums for every bundled file
  5. Creates multi-target instruction mappings (reusing platform_exporter patterns)
  6. Writes the .ccpkg archive (ZIP-based) with all assets

The .ccpkg supports both global and project-scoped installation:
  Global:   ~/.claude/packages/   ~/.opencode/packages/
  Project:  ./.ccpkg/packages/

Usage:
    python3 scripts/build_ccpkg.py [--version VERSION] [--output DIR]
    python3 scripts/build_ccpkg.py --json
    python3 scripts/build_ccpkg.py --help

Zero external dependencies -- stdlib only.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import textwrap
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Constants ───────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

PLUGIN_JSON = REPO_ROOT / ".claude-plugin" / "plugin.json"
SKILLS_DIR = REPO_ROOT / "skills"
HOOKS_DIR = REPO_ROOT / "hooks"
SCRIPTS_DIR = REPO_ROOT / "scripts"
CONFIG_DIR = REPO_ROOT / "config"
TEMPLATES_DIR = REPO_ROOT / "templates"

# Directories to bundle into the archive (relative to repo root)
BUNDLE_DIRS = [
    "scripts",
    "skills",
    "config",
    "hooks",
    "templates",
    ".claude-plugin",
]

# Individual root-level files to bundle
BUNDLE_FILES = [
    "CHANGELOG.md",
    "README.md",
]

# File patterns to exclude
EXCLUDE_PATTERNS = [
    r"__pycache__(/|$)",
    r"\.pyc$",
    r"\.pyo$",
    r"\.egg-info(/|$)",
    r"\.DS_Store$",
    r"Thumbs\.db$",
    r"\.env$",
]

_EXCLUDE_RE = [re.compile(p) for p in EXCLUDE_PATTERNS]

# ccpkg archive extension and naming
CCPKG_EXTENSION = ".ccpkg"
ARCHIVE_NAME_TEMPLATE = "claw-{version}{ext}"

# Default output directory
DEFAULT_OUTPUT_DIR = REPO_ROOT / "dist"

# Frontmatter regex for SKILL.md parsing
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
YAML_KV_RE = re.compile(r'^(\w[\w-]*):\s*"?([^"]*?)"?\s*$', re.MULTILINE)

# Supported installation targets (mirrors platform_exporter.py targets)
INSTALL_TARGETS = [
    "claude-code",
    "opencode",
    "openclaw",
    "cursor",
    "windsurf",
    "continue",
    "copilot",
    "aider",
    "agents_md",
    "generic",
]

# Global installation paths by target
GLOBAL_INSTALL_PATHS = {
    "claude-code": "~/.claude/packages/",
    "opencode": "~/.opencode/packages/",
    "generic": "~/.config/ccpkg/packages/",
}

# Version detection regex
VERSION_RE = re.compile(r'"version"\s*:\s*"([^"]+)"')


# ── Helpers ─────────────────────────────────────────────────────────────────


def detect_version() -> str:
    """Detect the current version from plugin.json or CHANGELOG.md."""
    if PLUGIN_JSON.exists():
        try:
            data = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
            version = data.get("version", "")
            if version:
                return version
        except (json.JSONDecodeError, OSError):
            pass

    changelog = REPO_ROOT / "CHANGELOG.md"
    if changelog.exists():
        try:
            text = changelog.read_text(encoding="utf-8")
            match = re.search(r"##\s*\[?v?(\d+\.\d+\.\d+)", text)
            if match:
                return match.group(1)
        except OSError:
            pass

    return "0.0.0"


def load_plugin_metadata() -> dict[str, Any]:
    """Load metadata from .claude-plugin/plugin.json."""
    if not PLUGIN_JSON.exists():
        return {}
    try:
        return json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def is_excluded(rel_path: str) -> bool:
    """Check whether a relative path should be excluded from the archive."""
    normalized = rel_path.replace(os.sep, "/")
    for pattern in _EXCLUDE_RE:
        if pattern.search(normalized):
            return True
    return False


# ── Skill Discovery ────────────────────────────────────────────────────────
# Reuses the same parsing approach as platform_exporter.py


def parse_skill_md(skill_path: Path) -> dict[str, Any] | None:
    """Parse a SKILL.md file into structured component data.

    Mirrors the parsing logic from platform_exporter.py for consistency
    across the CodeClaw toolchain.
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
        body = content[fm_match.end() :]

    return {
        "name": frontmatter.get("name", skill_path.parent.name),
        "description": frontmatter.get("description", ""),
        "frontmatter": frontmatter,
        "body": body.strip(),
        "path": str(skill_path),
        "directory": skill_path.parent.name,
    }


def discover_skills() -> list[dict[str, Any]]:
    """Discover all skills in the skills/ directory."""
    skills: list[dict[str, Any]] = []
    if not SKILLS_DIR.is_dir():
        return skills
    for entry in sorted(SKILLS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        parsed = parse_skill_md(skill_md)
        if parsed:
            skills.append(parsed)
    return skills


def discover_hooks() -> list[dict[str, Any]]:
    """Discover hooks from hooks/hooks.json."""
    hooks_json = HOOKS_DIR / "hooks.json"
    if not hooks_json.exists():
        return []
    try:
        data = json.loads(hooks_json.read_text(encoding="utf-8"))
        hooks_config = data.get("hooks", {})
        result = []
        for event_name, hook_list in hooks_config.items():
            for hook_entry in hook_list:
                hook_defs = hook_entry.get("hooks", [])
                first_hook = hook_defs[0] if hook_defs else {}
                result.append({
                    "event": event_name,
                    "matcher": hook_entry.get("matcher", "*"),
                    "type": first_hook.get("type", "command"),
                    "command": first_hook.get("command", ""),
                })
        return result
    except (json.JSONDecodeError, OSError):
        return []


# ── File Collection ─────────────────────────────────────────────────────────


def collect_files() -> list[tuple[Path, str]]:
    """Collect all files to bundle in the .ccpkg archive.

    Returns a list of (absolute_path, archive_relative_path) tuples.
    """
    files: list[tuple[Path, str]] = []

    for dir_name in BUNDLE_DIRS:
        dir_path = REPO_ROOT / dir_name
        if not dir_path.is_dir():
            continue
        for file_path in sorted(dir_path.rglob("*")):
            if not file_path.is_file():
                continue
            # Guard against symlinks pointing outside the repo root
            try:
                resolved = file_path.resolve()
                if not str(resolved).startswith(str(REPO_ROOT.resolve())):
                    continue
                rel = file_path.relative_to(REPO_ROOT)
            except (ValueError, OSError):
                continue
            rel_str = str(rel).replace(os.sep, "/")
            if not is_excluded(rel_str):
                files.append((file_path, rel_str))

    for file_name in BUNDLE_FILES:
        file_path = REPO_ROOT / file_name
        if file_path.is_file():
            files.append((file_path, file_name))

    return files


# ── Manifest Generation ────────────────────────────────────────────────────


def build_components(skills: list[dict[str, Any]], hooks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build the components array for the ccpkg manifest.

    Components include skills, hooks, and agent runner entries.
    """
    components: list[dict[str, Any]] = []

    # Skills
    for skill in skills:
        component = {
            "type": "skill",
            "name": skill["name"],
            "description": skill["description"],
            "entry_point": f"skills/{skill['directory']}/SKILL.md",
            "slash_command": f"/{skill['name']}",
        }
        if skill["frontmatter"].get("argument-hint"):
            component["argument_hint"] = skill["frontmatter"]["argument-hint"]
        components.append(component)

    # Hooks
    for hook in hooks:
        components.append({
            "type": "hook",
            "event": hook["event"],
            "matcher": hook["matcher"],
            "handler_type": hook["type"],
            "command": hook["command"],
        })

    # Agent runner (scripts/agent_runner.py)
    agent_runner = SCRIPTS_DIR / "agent_runner.py"
    if agent_runner.exists():
        components.append({
            "type": "agent",
            "name": "agent_runner",
            "description": "Subagent orchestrator for parallel task execution",
            "entry_point": "scripts/agent_runner.py",
            "runtime": "python3",
        })

    return components


def build_config_schema() -> dict[str, Any]:
    """Build a typed configuration schema from project-config.example.json.

    Maps each configuration key to a typed schema entry.
    """
    config_example = CONFIG_DIR / "project-config.example.json"
    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    if not config_example.exists():
        return schema

    try:
        data = json.loads(config_example.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return schema

    type_map = {
        str: "string",
        bool: "boolean",
        int: "integer",
        float: "number",
        list: "array",
        dict: "object",
    }

    for key, value in data.items():
        py_type = type(value)
        json_type = type_map.get(py_type, "string")
        prop: dict[str, Any] = {"type": json_type}

        # Add descriptions for known keys
        descriptions = {
            "dev_ports": "Port(s) the dev server listens on",
            "start_command": "Command to start the dev server",
            "predev_command": "Optional pre-start setup command",
            "verify_command": "Quality gate command (lint + test + build)",
            "test_framework": "Testing framework name (e.g., pytest, vitest)",
            "test_command": "Command to run the test suite",
            "test_file_pattern": "Glob pattern for test files",
            "ci_runtime_setup": "GitHub Actions setup step YAML",
            "tech_detail_layers": "Technical detail layers for task specs",
            "idea_categories": "Custom idea categories",
            "doc_categories": "Custom documentation categories",
            "project_context": "Free-form project context for agents",
            "scout_categories": "Custom scout/analysis categories",
            "package_json_paths": "Space-separated manifest file paths",
            "changelog_file": "Path to the changelog file",
            "tag_prefix": "Git tag prefix (e.g., v)",
            "github_repo_url": "HTTPS repository URL",
            "release_branch": "Release branch name",
            "show_generated_footer": "Show generated-by footer in outputs",
        }

        if key in descriptions:
            prop["description"] = descriptions[key]

        if isinstance(value, str):
            prop["default"] = value
        elif isinstance(value, bool):
            prop["default"] = value

        schema["properties"][key] = prop

    return schema


def build_target_mappings(skills: list[dict[str, Any]]) -> dict[str, Any]:
    """Build multi-target instruction file mappings.

    Mirrors the target structure from platform_exporter.py, indicating
    which files map to which platform-specific config locations.
    """
    mappings: dict[str, Any] = {}

    for target in INSTALL_TARGETS:
        target_info: dict[str, Any] = {
            "supported": True,
            "instruction_format": _target_format(target),
            "skill_mappings": [],
        }

        if target in GLOBAL_INSTALL_PATHS:
            target_info["global_install_path"] = GLOBAL_INSTALL_PATHS[target]

        for skill in skills:
            mapping = {
                "skill": skill["name"],
                "source": f"skills/{skill['directory']}/SKILL.md",
                "destination": _target_destination(target, skill["name"]),
            }
            target_info["skill_mappings"].append(mapping)

        mappings[target] = target_info

    return mappings


def _target_format(target: str) -> str:
    """Return the instruction file format for a given target."""
    formats = {
        "claude-code": "markdown",
        "opencode": "json+js",
        "openclaw": "markdown",
        "cursor": "mdc",
        "windsurf": "markdown",
        "continue": "json",
        "copilot": "markdown",
        "aider": "markdown",
        "agents_md": "markdown",
        "generic": "markdown",
    }
    return formats.get(target, "markdown")


def _target_destination(target: str, skill_name: str) -> str:
    """Return the expected destination path for a skill on a given target."""
    destinations = {
        "claude-code": f".claude/skills/{skill_name}/SKILL.md",
        "opencode": f".opencode/plugins/{skill_name}.js",
        "openclaw": f".openclaw/skills/{skill_name}/SKILL.md",
        "cursor": f".cursor/rules/claw-{skill_name}.mdc",
        "windsurf": f".windsurf/rules/claw-{skill_name}.md",
        "continue": f".continue/assistants/claw-{skill_name}.json",
        "copilot": ".github/copilot-instructions.md",
        "aider": ".aider/instructions.md",
        "agents_md": "AGENTS.md",
        "generic": f"skills/{skill_name}/SKILL.md",
    }
    return destinations.get(target, f"skills/{skill_name}/SKILL.md")


def build_manifest(
    version: str,
    files: list[tuple[Path, str]],
    skills: list[dict[str, Any]],
    hooks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the complete ccpkg manifest.

    Parameters
    ----------
    version : str
        Package version string.
    files : list
        List of (absolute_path, archive_relative_path) tuples.
    skills : list
        Discovered skill components.
    hooks : list
        Discovered hook components.

    Returns
    -------
    dict
        The complete ccpkg manifest data.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    plugin_meta = load_plugin_metadata()

    # Build file entries with checksums
    file_entries = []
    for abs_path, rel_path in files:
        entry = {
            "path": rel_path,
            "sha256": compute_sha256(abs_path),
            "size": abs_path.stat().st_size,
        }
        file_entries.append(entry)

    manifest = {
        "ccpkg_version": "1.0.0",
        "name": plugin_meta.get("name", "claw"),
        "version": version,
        "description": plugin_meta.get(
            "description",
            "CodeClaw",
        ),
        "author": plugin_meta.get("author", {"name": "dnviti"}),
        "repository": plugin_meta.get(
            "repository",
            "https://github.com/dnviti/codeclaw",
        ),
        "license": plugin_meta.get("license", "MIT"),
        "keywords": plugin_meta.get("keywords", []),
        "build_date": now,
        "components": build_components(skills, hooks),
        "config_schema": build_config_schema(),
        "targets": build_target_mappings(skills),
        "install": {
            "global_paths": GLOBAL_INSTALL_PATHS,
            "project_path": ".ccpkg/packages/",
            "post_install": None,
            "network_required": False,
        },
        "files": file_entries,
        "file_count": len(file_entries),
        "checksums": {
            "algorithm": "sha256",
            "manifest_version": "1.0.0",
        },
    }

    return manifest


def build_lock_data(version: str, archive_path: Path) -> dict[str, Any]:
    """Build ccpkg-lock.json data for reproducible installs."""
    archive_hash = compute_sha256(archive_path) if archive_path.exists() else ""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "ccpkg_lock_version": "1.0.0",
        "locked_at": now,
        "packages": {
            "claw": {
                "version": version,
                "resolved": f"claw-{version}.ccpkg",
                "integrity": f"sha256-{archive_hash}",
                "requires_python": ">=3.10",
                "network_required": False,
            }
        },
    }


# ── Archive Builder ─────────────────────────────────────────────────────────


def build_ccpkg(
    version: str,
    output_dir: Path,
    verbose: bool = False,
) -> Path:
    """Build the .ccpkg archive.

    Parameters
    ----------
    version : str
        Version string for the package.
    output_dir : Path
        Directory to write the .ccpkg file.
    verbose : bool
        Print progress messages.

    Returns
    -------
    Path
        Path to the created .ccpkg file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    archive_name = ARCHIVE_NAME_TEMPLATE.format(version=version, ext=CCPKG_EXTENSION)
    archive_path = output_dir / archive_name

    if verbose:
        print(f"[ccpkg] Collecting files from {REPO_ROOT}")

    files = collect_files()
    if verbose:
        print(f"[ccpkg] Found {len(files)} files to bundle")

    # Discover components
    if verbose:
        print("[ccpkg] Discovering skills...")
    skills = discover_skills()
    if verbose:
        print(f"[ccpkg] Found {len(skills)} skills: {', '.join(s['name'] for s in skills)}")

    if verbose:
        print("[ccpkg] Discovering hooks...")
    hooks = discover_hooks()
    if verbose:
        print(f"[ccpkg] Found {len(hooks)} hook(s)")

    # Build manifest
    if verbose:
        print("[ccpkg] Generating ccpkg manifest...")
    manifest_data = build_manifest(version, files, skills, hooks)

    # Write the archive (ZIP-based, .ccpkg extension)
    if verbose:
        print(f"[ccpkg] Creating archive: {archive_path}")

    prefix = f"claw-{version}"

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Bundle all collected files
        for abs_path, rel_path in files:
            arcname = f"{prefix}/{rel_path}"
            zf.write(abs_path, arcname)
            if verbose:
                print(f"  + {rel_path}")

        # Write manifest into archive root
        manifest_json = json.dumps(manifest_data, indent=2, ensure_ascii=False)
        zf.writestr(f"{prefix}/ccpkg-manifest.json", manifest_json)
        if verbose:
            print("  + ccpkg-manifest.json")

    # Print summary
    archive_size = archive_path.stat().st_size
    size_kb = archive_size / 1024

    if verbose:
        print(f"[ccpkg] Archive created: {archive_path} ({size_kb:.1f} KB)")
        print(f"[ccpkg] Version: {version}")
        print(f"[ccpkg] Components: {len(skills)} skills, {len(hooks)} hooks")
        print(f"[ccpkg] Files: {manifest_data['file_count']} + manifest")
        print(f"[ccpkg] Targets: {', '.join(INSTALL_TARGETS)}")

    return archive_path


# ── CLI ─────────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Build a .ccpkg archive for CodeClaw cross-tool distribution.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python3 scripts/build_ccpkg.py
              python3 scripts/build_ccpkg.py --version 3.5.0
              python3 scripts/build_ccpkg.py --output /tmp/release --verbose
              python3 scripts/build_ccpkg.py --json
              python3 scripts/build_ccpkg.py --lock
        """),
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Version string (default: auto-detect from plugin.json)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=f"Output directory for the .ccpkg file (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print progress messages during build",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output result as JSON (for CI integration)",
    )
    parser.add_argument(
        "--lock",
        action="store_true",
        help="Also generate a ccpkg-lock.json file alongside the archive",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    args = parse_args(argv)

    version = args.version or detect_version()
    output_dir = Path(args.output) if args.output else DEFAULT_OUTPUT_DIR

    if not args.json_output:
        print(f"Building CodeClaw .ccpkg package v{version}...")

    try:
        archive_path = build_ccpkg(
            version=version,
            output_dir=output_dir,
            verbose=args.verbose and not args.json_output,
        )
    except Exception as exc:
        if args.json_output:
            print(json.dumps({"success": False, "error": str(exc)}))
        else:
            print(f"[error] Build failed: {exc}", file=sys.stderr)
        return 1

    # Generate lock file if requested
    lock_path = None
    if args.lock:
        lock_data = build_lock_data(version, archive_path)
        lock_path = output_dir / "ccpkg-lock.json"
        lock_path.write_text(
            json.dumps(lock_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        if not args.json_output:
            print(f"Lock file: {lock_path}")

    if args.json_output:
        result: dict[str, Any] = {
            "success": True,
            "archive": str(archive_path),
            "version": version,
            "size": archive_path.stat().st_size,
            "format": "ccpkg",
        }
        if lock_path:
            result["lock_file"] = str(lock_path)
        print(json.dumps(result))
    else:
        print(f"Done. Package: {archive_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
