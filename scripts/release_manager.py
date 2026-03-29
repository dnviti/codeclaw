#!/usr/bin/env python3
"""Release manager CLI for codeclaw.

Provides deterministic release operations for the /release skill:
- Version detection from manifest files
- Conventional commit parsing and classification
- Semantic version bump calculation
- Changelog generation in Keep a Changelog format

All output is JSON (default) or plain text.
Zero external dependencies — stdlib only.
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from common import find_project_root, get_main_repo_root, get_latest_tag, load_config  # noqa: E402

# ── Constants ───────────────────────────────────────────────────────────────

TASK_CODE_RE = re.compile(r"\(([A-Z]{3,5}-\d{4})\)\s*$")

CONVENTIONAL_RE = re.compile(
    r"^(?P<prefix>feat|fix|chore|docs|refactor|perf|test|ci|style|build|revert)"
    r"(?P<breaking>!)?"
    r":\s*(?P<description>.+)$"
)

# Mapping: conventional prefix → Keep a Changelog category (None = excluded)
PREFIX_TO_CATEGORY = {
    "feat": "Added",
    "fix": "Fixed",
    "refactor": "Changed",
    "perf": "Changed",
    "revert": "Removed",
    "docs": None,
    "chore": None,
    "ci": None,
    "test": None,
    "style": None,
    "build": None,
}

# For commits without conventional prefix, classify by first word
KEYWORD_TO_CATEGORY = {
    "add": "Added", "implement": "Added", "create": "Added", "introduce": "Added",
    "fix": "Fixed", "resolve": "Fixed", "correct": "Fixed", "patch": "Fixed",
    "remove": "Removed", "delete": "Removed", "drop": "Removed",
    "update": "Changed", "refactor": "Changed", "improve": "Changed",
    "optimize": "Changed", "change": "Changed",
}

CHANGELOG_ORDER = ["Added", "Changed", "Fixed", "Removed", "Security"]

SECURITY_KEYWORDS = {"security", "cve", "vulnerability", "auth hardening", "xss", "injection"}

VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:-beta)?")


# ── Version Detection ───────────────────────────────────────────────────────

def read_version_from_package_json(filepath: Path) -> str | None:
    """Read version from package.json."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("version")
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        return None


def read_version_from_pyproject(filepath: Path) -> str | None:
    """Read version from pyproject.toml."""
    try:
        # Python 3.11+ has tomllib
        import tomllib
        with open(filepath, "rb") as f:
            data = tomllib.load(f)
        return data.get("project", {}).get("version")
    except ImportError:
        pass
    # Fallback to regex
    try:
        content = filepath.read_text(encoding="utf-8")
        m = re.search(r'version\s*=\s*"([^"]+)"', content)
        return m.group(1) if m else None
    except (FileNotFoundError, OSError):
        return None


def read_version_from_cargo(filepath: Path) -> str | None:
    """Read version from Cargo.toml."""
    try:
        content = filepath.read_text(encoding="utf-8")
        # Match the first version in [package] section
        in_package = False
        for line in content.splitlines():
            if line.strip() == "[package]":
                in_package = True
                continue
            if in_package and line.strip().startswith("["):
                break
            if in_package:
                m = re.match(r'version\s*=\s*"([^"]+)"', line.strip())
                if m:
                    return m.group(1)
    except (FileNotFoundError, OSError):
        pass
    return None


def read_version_from_setup_py(filepath: Path) -> str | None:
    """Read version from setup.py."""
    try:
        content = filepath.read_text(encoding="utf-8")
        m = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
        return m.group(1) if m else None
    except (FileNotFoundError, OSError):
        return None


MANIFEST_READERS = [
    ("package.json", read_version_from_package_json),
    ("pyproject.toml", read_version_from_pyproject),
    ("Cargo.toml", read_version_from_cargo),
    ("setup.py", read_version_from_setup_py),
]


# ── Version Writers ────────────────────────────────────────────────────────

def write_version_to_package_json(filepath: Path, new_version: str) -> bool:
    """Update version in package.json, preserving formatting."""
    try:
        content = filepath.read_text(encoding="utf-8")
        data = json.loads(content)
        data["version"] = new_version
        # Detect indent from original file
        indent = 2
        for line in content.splitlines()[1:]:
            stripped = line.lstrip()
            if stripped:
                indent = len(line) - len(stripped)
                break
        filepath.write_text(
            json.dumps(data, indent=indent, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return True
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        return False


def write_version_to_pyproject(filepath: Path, new_version: str) -> bool:
    """Update version in pyproject.toml via regex replacement."""
    try:
        content = filepath.read_text(encoding="utf-8")
        escaped = re.escape(new_version)
        new_content = re.sub(
            r'(version\s*=\s*")[^"]+(")',
            rf"\g<1>{escaped}\2",
            content,
            count=1,
        )
        if new_content == content:
            return False
        filepath.write_text(new_content, encoding="utf-8")
        return True
    except (FileNotFoundError, OSError):
        return False


def write_version_to_cargo(filepath: Path, new_version: str) -> bool:
    """Update version in Cargo.toml [package] section."""
    try:
        content = filepath.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        in_package = False
        for i, line in enumerate(lines):
            if line.strip() == "[package]":
                in_package = True
                continue
            if in_package and line.strip().startswith("["):
                break
            if in_package and re.match(r'version\s*=\s*"[^"]+"', line.strip()):
                escaped = re.escape(new_version)
                lines[i] = re.sub(
                    r'(version\s*=\s*")[^"]+(")',
                    rf"\g<1>{escaped}\2",
                    line,
                )
                filepath.write_text("".join(lines), encoding="utf-8")
                return True
    except (FileNotFoundError, OSError):
        pass
    return False


def write_version_to_setup_py(filepath: Path, new_version: str) -> bool:
    """Update version in setup.py."""
    try:
        content = filepath.read_text(encoding="utf-8")
        escaped = re.escape(new_version)
        new_content = re.sub(
            r"""(version\s*=\s*['"])[^'"]+(['"])""",
            rf"\g<1>{escaped}\2",
            content,
            count=1,
        )
        if new_content == content:
            return False
        filepath.write_text(new_content, encoding="utf-8")
        return True
    except (FileNotFoundError, OSError):
        return False


def write_version_to_setup_cfg(filepath: Path, new_version: str) -> bool:
    """Update version in setup.cfg [metadata] section."""
    try:
        content = filepath.read_text(encoding="utf-8")
        escaped = re.escape(new_version)
        new_content = re.sub(
            r"(version\s*=\s*)\S+",
            rf"\g<1>{escaped}",
            content,
            count=1,
        )
        if new_content == content:
            return False
        filepath.write_text(new_content, encoding="utf-8")
        return True
    except (FileNotFoundError, OSError):
        return False


def write_version_to_pom_xml(filepath: Path, new_version: str) -> bool:
    """Update top-level <version> in pom.xml."""
    try:
        content = filepath.read_text(encoding="utf-8")
        # Match first <version> in the file (may not be the project version
        # if <parent> appears first — see review note)
        escaped = re.escape(new_version)
        new_content = re.sub(
            r"(<version>)[^<]+(</version>)",
            rf"\g<1>{escaped}\2",
            content,
            count=1,
        )
        if new_content == content:
            return False
        filepath.write_text(new_content, encoding="utf-8")
        return True
    except (FileNotFoundError, OSError):
        return False


def write_version_to_build_gradle(filepath: Path, new_version: str) -> bool:
    """Update version in build.gradle."""
    try:
        content = filepath.read_text(encoding="utf-8")
        escaped = re.escape(new_version)
        new_content = re.sub(
            r"""(version\s*=\s*['"])[^'"]+(['"])""",
            rf"\g<1>{escaped}\2",
            content,
            count=1,
        )
        if new_content == content:
            return False
        filepath.write_text(new_content, encoding="utf-8")
        return True
    except (FileNotFoundError, OSError):
        return False


MANIFEST_WRITERS = {
    "package.json": write_version_to_package_json,
    "pyproject.toml": write_version_to_pyproject,
    "Cargo.toml": write_version_to_cargo,
    "setup.py": write_version_to_setup_py,
    "setup.cfg": write_version_to_setup_cfg,
    "pom.xml": write_version_to_pom_xml,
    "build.gradle": write_version_to_build_gradle,
}

# Filenames to auto-discover when no explicit package_paths configured
AUTO_DISCOVER_MANIFESTS = [
    "package.json", "pyproject.toml", "setup.py", "setup.cfg",
    "Cargo.toml", "pom.xml", "build.gradle",
]


# ── Commit Parsing ──────────────────────────────────────────────────────────

def classify_non_conventional(message: str) -> str | None:
    """Classify a non-conventional commit by keyword analysis."""
    lower = message.lower().strip()
    # Check for security-related content
    if any(kw in lower for kw in SECURITY_KEYWORDS):
        return "Security"
    # Check first word
    first_word = lower.split()[0] if lower else ""
    return KEYWORD_TO_CATEGORY.get(first_word, "Changed")


def parse_single_commit(line: str) -> dict:
    """Parse a single oneline commit into structured data."""
    # Format: "hash message"
    parts = line.split(" ", 1)
    if len(parts) < 2:
        return {"hash": parts[0] if parts else "", "message": "", "skip": True}

    commit_hash = parts[0]
    message = parts[1].strip()

    # Extract task code from end of message
    task_code = None
    task_match = TASK_CODE_RE.search(message)
    if task_match:
        task_code = task_match.group(1)

    # Parse conventional commit
    conv_match = CONVENTIONAL_RE.match(message)

    if conv_match:
        prefix = conv_match.group("prefix")
        is_breaking = conv_match.group("breaking") == "!"
        description = conv_match.group("description").strip()
        category = PREFIX_TO_CATEGORY.get(prefix)

        # Security override
        if category and any(kw in description.lower() for kw in SECURITY_KEYWORDS):
            category = "Security"

        return {
            "hash": commit_hash,
            "message": message,
            "prefix": prefix,
            "is_breaking": is_breaking,
            "description": description,
            "task_code": task_code,
            "changelog_category": category,
            "skip": False,
        }
    else:
        category = classify_non_conventional(message)
        return {
            "hash": commit_hash,
            "message": message,
            "prefix": None,
            "is_breaking": False,
            "description": message,
            "task_code": task_code,
            "changelog_category": category,
            "skip": False,
        }


def check_breaking_in_bodies(since_tag: str | None) -> int:
    """Check for BREAKING CHANGE: in commit bodies."""
    try:
        cmd = ["git", "log", "--no-merges", "--format=%B"]
        if since_tag:
            cmd.insert(2, f"{since_tag}..HEAD")
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.count("BREAKING CHANGE")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 0


# ── Subcommand: current-version ────────────────────────────────────────────

def cmd_current_version(args):
    """Detect version from manifest files and git tags."""
    root = find_project_root()
    tag_prefix = args.tag_prefix

    all_sources = []
    primary_version = None
    primary_file = None

    for filename, reader in MANIFEST_READERS:
        filepath = root / filename
        if filepath.exists():
            version = reader(filepath)
            if version:
                all_sources.append({"file": filename, "version": version})
                if primary_version is None:
                    primary_version = version
                    primary_file = filename

    latest_tag = get_latest_tag(tag_prefix)

    if primary_version is None:
        primary_version = "0.0.0"
        primary_file = None

    is_beta = primary_version.endswith("-beta")
    base_version = primary_version.removesuffix("-beta")

    result = {
        "version": primary_version,
        "base_version": base_version,
        "is_beta": is_beta,
        "source_file": primary_file,
        "all_sources": all_sources,
        "latest_tag": latest_tag,
        "tag_prefix": tag_prefix,
    }
    print(json.dumps(result, indent=2))


# ── Subcommand: update-versions ───────────────────────────────────────────

def _discover_manifests(root: Path, package_paths: str | None) -> list[Path]:
    """Return list of manifest file paths to update."""
    if package_paths and package_paths.strip():
        return [root / p.strip() for p in package_paths.split() if p.strip()]
    # Auto-discover
    found = []
    for name in AUTO_DISCOVER_MANIFESTS:
        if name == "package.json":
            # Find all package.json excluding node_modules
            for pj in root.rglob("package.json"):
                if "node_modules" not in pj.parts:
                    found.append(pj)
        else:
            candidate = root / name
            if candidate.exists():
                found.append(candidate)
    return found


def cmd_update_versions(args):
    """Discover manifests, read old versions, write new version, report."""
    root = find_project_root()
    new_version = args.version
    package_paths = getattr(args, "package_paths", None)

    manifests = _discover_manifests(root, package_paths)

    updated = []
    skipped = []
    readers = dict(MANIFEST_READERS)

    for filepath in manifests:
        filename = filepath.name
        if not filepath.exists():
            skipped.append({"file": str(filepath.relative_to(root)), "reason": "file not found"})
            continue

        # Read current version
        reader = readers.get(filename)
        if not reader and filepath.suffix == ".json":
            reader = read_version_from_package_json
        if reader:
            old_version = reader(filepath)
        else:
            old_version = None

        # Get writer — fall back to JSON writer for any .json file
        writer = MANIFEST_WRITERS.get(filename)
        if not writer and filepath.suffix == ".json":
            writer = write_version_to_package_json
        if not writer:
            skipped.append({
                "file": str(filepath.relative_to(root)),
                "reason": f"no writer for {filename}",
            })
            continue

        if old_version == new_version:
            skipped.append({
                "file": str(filepath.relative_to(root)),
                "reason": "already at target version",
            })
            continue

        success = writer(filepath, new_version)
        if success:
            updated.append({
                "file": str(filepath.relative_to(root)),
                "old_version": old_version or "unknown",
                "new_version": new_version,
            })
        else:
            skipped.append({
                "file": str(filepath.relative_to(root)),
                "reason": "write failed or no version field found",
            })

    print(json.dumps({"updated": updated, "skipped": skipped}, indent=2))


# ── Subcommand: parse-commits ──────────────────────────────────────────────

def cmd_parse_commits(args):
    """Parse git log into structured commit data."""
    since_tag = args.since if args.since else None

    # Get oneline log
    cmd = ["git", "log", "--oneline", "--no-merges"]
    if since_tag:
        cmd.insert(2, f"{since_tag}..HEAD")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(json.dumps({"error": str(e), "commits": [], "summary": {}}))
        sys.exit(1)

    lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
    commits = [parse_single_commit(line) for line in lines]

    # Check for BREAKING CHANGE in bodies
    body_breaking_count = check_breaking_in_bodies(since_tag)

    # Build summary
    features = sum(1 for c in commits if c.get("prefix") == "feat")
    fixes = sum(1 for c in commits if c.get("prefix") == "fix")
    breaking = sum(1 for c in commits if c.get("is_breaking")) + body_breaking_count
    excluded = sum(1 for c in commits if c.get("changelog_category") is None)
    has_meaningful = any(c.get("changelog_category") is not None for c in commits)

    # Determine suggested bump
    if breaking > 0:
        suggested_bump = "major"
    elif features > 0:
        suggested_bump = "minor"
    else:
        suggested_bump = "patch"

    output = {
        "commits": commits,
        "summary": {
            "total": len(commits),
            "breaking": breaking,
            "features": features,
            "fixes": fixes,
            "other": len(commits) - features - fixes - excluded,
            "excluded": excluded,
            "has_meaningful_changes": has_meaningful,
        },
        "has_breaking_changes": breaking > 0,
        "suggested_bump": suggested_bump,
    }
    print(json.dumps(output, indent=2))


# ── Subcommand: suggest-bump ───────────────────────────────────────────────

def cmd_suggest_bump(args):
    """Calculate the new version based on bump type."""
    current = args.current_version
    is_beta = current.endswith("-beta")
    base = current.removesuffix("-beta")

    m = VERSION_RE.match(base)
    if not m:
        print(json.dumps({"error": f"Cannot parse version: {base}"}))
        sys.exit(1)

    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))

    bump = args.force if args.force else args.suggested_bump

    if bump == "major":
        new_version = f"{major + 1}.0.0-beta"
    elif bump == "minor":
        new_version = f"{major}.{minor + 1}.0"
    elif bump == "patch":
        new_version = f"{major}.{minor}.{patch + 1}"
    else:
        new_version = f"{major}.{minor}.{patch + 1}"

    result = {
        "current_version": current,
        "base_version": base,
        "is_current_beta": is_beta,
        "bump_type": bump,
        "new_version": new_version,
        "is_new_beta": new_version.endswith("-beta"),
        "is_forced": args.force is not None,
    }
    print(json.dumps(result, indent=2))


# ── Subcommand: generate-changelog ─────────────────────────────────────────

def cmd_generate_changelog(args):
    """Generate a changelog section from commits JSON (stdin)."""
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"Error reading commits JSON from stdin: {e}", file=sys.stderr)
        sys.exit(1)

    commits = data.get("commits", [])
    version = args.version
    release_date = args.date if args.date else date.today().isoformat()

    # Group by category
    groups: dict[str, list[str]] = {}
    for commit in commits:
        category = commit.get("changelog_category")
        if not category:
            continue
        description = commit.get("description", commit.get("message", ""))
        task_code = commit.get("task_code")
        entry = f"- {description}"
        if task_code:
            entry += f" ({task_code})"
        groups.setdefault(category, []).append(entry)

    # Build output
    lines = [f"## [{version}] - {release_date}", ""]

    for category in CHANGELOG_ORDER:
        entries = groups.get(category, [])
        if entries:
            lines.append(f"### {category}")
            lines.extend(entries)
            lines.append("")

    print("\n".join(lines).rstrip())


# ── Release Plan Helpers ────────────────────────────────────────────────────

def _uses_local_files() -> bool:
    """Return True when local file tracking is active (local-only or dual-sync).

    In platform-only mode (enabled=True, sync=False) local files like
    to-do.txt, progressing.txt, done.txt and releases.json are NOT used.
    """
    root = get_main_repo_root()
    for name in ("issues-tracker.json", "github-issues.json"):
        fp = root / ".claude" / name
        if fp.exists():
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                enabled = data.get("enabled", False)
                sync = data.get("sync", False)
                # platform-only → no local files
                if enabled and not sync:
                    return False
                return True
            except (json.JSONDecodeError, OSError):
                pass
    # No config found → local-only (default)
    return True


# ── Platform State Helpers ───────────────────────────────────────────────────

def _get_platform_config() -> dict:
    """Load platform config from .claude/issues-tracker.json or github-issues.json."""
    root = get_main_repo_root()
    for name in ("issues-tracker.json", "github-issues.json"):
        fp = root / ".claude" / name
        if fp.exists():
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
    return {}


def _platform_cli(cfg: dict) -> str:
    """Return 'gh' for GitHub or 'glab' for GitLab."""
    platform = cfg.get("platform", "github").lower()
    return "glab" if platform == "gitlab" else "gh"


_REPO_RE = re.compile(r"^[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+$")


def _validate_repo(repo: str) -> bool:
    """Return True if repo matches the expected owner/name format."""
    return bool(_REPO_RE.match(repo))


def _platform_state_issue_number(cli: str, repo: str) -> "int | None":
    """Find the claw-release-state issue number (any state), or None.

    Searches all issue states (open and closed) and returns the
    lowest-numbered issue to ensure a stable singleton.
    """
    try:
        result = subprocess.run(
            [cli, "issue", "list", "--label", "claw-release-state",
             "--state", "all", "--json", "number", "--limit", "100",
             "--repo", repo],
            capture_output=True, text=True, check=True, timeout=30,
        )
        issues = json.loads(result.stdout)
        if issues:
            # Use the lowest-numbered issue as the canonical singleton.
            return min(i["number"] for i in issues)
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError,
            KeyError, subprocess.TimeoutExpired):
        pass
    return None


def _platform_state_deduplicate(cli: str, repo: str) -> "int | None":
    """Find all claw-release-state issues and close duplicates.

    Keeps only the lowest-numbered issue. Removes ``claude-code``,
    ``task``, and ``status:todo`` labels from the surviving issue.
    Returns the canonical issue number, or None if none exist.
    """
    try:
        result = subprocess.run(
            [cli, "issue", "list", "--label", "claw-release-state",
             "--state", "all", "--json", "number,state", "--limit", "100",
             "--repo", repo],
            capture_output=True, text=True, check=True, timeout=30,
        )
        issues = json.loads(result.stdout)
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError,
            subprocess.TimeoutExpired):
        return None
    if not issues:
        return None

    sorted_issues = sorted(issues, key=lambda i: i["number"])
    canonical = sorted_issues[0]["number"]

    # Close all duplicates (issues other than the canonical one).
    for issue in sorted_issues[1:]:
        try:
            if issue.get("state", "").upper() != "CLOSED":
                subprocess.run(
                    [cli, "issue", "close", str(issue["number"]), "--repo", repo,
                     "--comment", f"Duplicate of #{canonical}. Auto-closed by CodeClaw."],
                    capture_output=True, text=True, timeout=30,
                )
        except (subprocess.CalledProcessError, FileNotFoundError,
                subprocess.TimeoutExpired):
            pass

    # Remove triage labels that should not be on the release state issue.
    # Use a single CLI call with comma-separated labels to avoid extra
    # subprocess spawns (OPT-2).
    try:
        subprocess.run(
            [cli, "issue", "edit", str(canonical), "--repo", repo,
             "--remove-label", "claude-code,task,status:todo"],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.CalledProcessError, FileNotFoundError,
            subprocess.TimeoutExpired):
        pass

    return canonical


def _platform_state_get() -> dict:
    """Fetch release state from the platform claw-release-state issue body.

    Returns an empty dict if no state issue exists or the body cannot be parsed.
    """
    cfg = _get_platform_config()
    cli = _platform_cli(cfg)
    repo = cfg.get("repo", "")
    if not repo or not _validate_repo(repo):
        return {}
    num = _platform_state_issue_number(cli, repo)
    if num is None:
        return {}
    try:
        result = subprocess.run(
            [cli, "issue", "view", str(num), "--repo", repo, "--json", "body"],
            capture_output=True, text=True, check=True, timeout=30,
        )
        body = json.loads(result.stdout).get("body", "")
        return json.loads(body)
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError,
            subprocess.TimeoutExpired):
        return {}


def _platform_state_set(state: dict) -> None:
    """Persist release state to the platform by creating or updating the state issue.

    If an existing issue is found (open or closed), it is reused: closed
    issues are reopened.  Before creating a new issue a second lookup is
    performed as a deduplication guard against race conditions.
    """
    cfg = _get_platform_config()
    cli = _platform_cli(cfg)
    repo = cfg.get("repo", "")
    if not repo or not _validate_repo(repo):
        return
    body = json.dumps(state, indent=2)

    # Deduplicate first — close extras and get the canonical issue.
    num = _platform_state_deduplicate(cli, repo)

    try:
        if num is not None:
            # Reopen if closed, then update the body.
            try:
                subprocess.run(
                    [cli, "issue", "reopen", str(num), "--repo", repo],
                    capture_output=True, text=True, timeout=30,
                )
            except (subprocess.CalledProcessError, FileNotFoundError,
                    subprocess.TimeoutExpired):
                pass  # Already open — that's fine.
            subprocess.run(
                [cli, "issue", "edit", str(num), "--repo", repo, "--body", body],
                capture_output=True, text=True, check=True, timeout=30,
            )
        else:
            # Race-condition guard: double-check before creating.
            num = _platform_state_issue_number(cli, repo)
            if num is not None:
                try:
                    subprocess.run(
                        [cli, "issue", "reopen", str(num), "--repo", repo],
                        capture_output=True, text=True, timeout=30,
                    )
                except (subprocess.CalledProcessError, FileNotFoundError,
                        subprocess.TimeoutExpired):
                    pass
                subprocess.run(
                    [cli, "issue", "edit", str(num), "--repo", repo, "--body", body],
                    capture_output=True, text=True, check=True, timeout=30,
                )
                return

            # Ensure the label exists before creating the issue; ignore errors
            # (label may already exist or caller may lack label-create permission).
            label_result = subprocess.run(
                [cli, "label", "create", "claw-release-state",
                 "--description", "CodeClaw platform release state", "--repo", repo],
                capture_output=True, text=True, timeout=30,
            )
            if label_result.returncode not in (0, 1):
                # returncode 1 typically means the label already exists — OK.
                # Any other non-zero value is unexpected; log to stderr.
                print(
                    f"[claw] warning: label create exited {label_result.returncode}: "
                    f"{label_result.stderr.strip()}",
                    file=sys.stderr,
                )
            subprocess.run(
                [cli, "issue", "create", "--repo", repo,
                 "--label", "claw-release-state",
                 "--title", "CodeClaw Release State",
                 "--body", body],
                capture_output=True, text=True, check=True, timeout=30,
            )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass


def _platform_state_clear() -> None:
    """Clear the claw-release-state issue body without closing it.

    The issue remains open with an empty JSON body (``{}``) so that
    subsequent release cycles reuse the same issue instead of creating
    a new one.
    """
    cfg = _get_platform_config()
    cli = _platform_cli(cfg)
    repo = cfg.get("repo", "")
    if not repo or not _validate_repo(repo):
        return
    num = _platform_state_issue_number(cli, repo)
    if num is None:
        return
    try:
        subprocess.run(
            [cli, "issue", "edit", str(num), "--repo", repo, "--body", "{}"],
            capture_output=True, text=True, check=True, timeout=30,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        pass


def _releases_path() -> Path:
    """Return path to releases.json at project root."""
    return get_main_repo_root() / "releases.json"


def _read_releases() -> list[dict]:
    """Read releases from releases.json. Returns empty list if missing."""
    fp = _releases_path()
    if not fp.exists():
        return []
    try:
        with open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("releases", [])
    except (json.JSONDecodeError, OSError):
        return []


def _write_releases(releases: list[dict]) -> None:
    """Write releases list to releases.json."""
    fp = _releases_path()
    with open(fp, "w", encoding="utf-8") as f:
        json.dump({"releases": releases}, f, indent=2)
        f.write("\n")


def _version_tuple(v: str) -> tuple[int, ...]:
    """Parse a semver string into a comparable tuple."""
    m = VERSION_RE.match(v)
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _sort_releases(releases: list[dict]) -> list[dict]:
    """Sort releases by semver version."""
    return sorted(releases, key=lambda r: _version_tuple(r.get("version", "0.0.0")))


# ── Subcommand: release-plan-list ──────────────────────────────────────────

def cmd_release_plan_list(args):
    """List all releases with cross-referenced task statuses."""
    if not _uses_local_files():
        print(json.dumps({"releases": [], "next_release": None,
                           "note": "releases.json is not used in platform-only mode"}))
        return
    releases = _read_releases()
    if not releases:
        print(json.dumps({"releases": [], "next_release": None}))
        return

    # Try to cross-reference task statuses from local files
    root = get_main_repo_root()
    task_statuses = {}

    # Import task_manager functions by reading task files directly
    for fname, status in [("to-do.txt", "todo"), ("progressing.txt", "progressing"), ("done.txt", "done")]:
        fp = root / fname
        if not fp.exists():
            continue
        try:
            content = fp.read_text(encoding="utf-8")
            # Simple regex to find task codes and their status
            for line in content.splitlines():
                line_stripped = line.strip()
                task_match = re.match(r"^\[(.)\]\s+([A-Z]{3,5}-\d{4})\s+—", line_stripped)
                if task_match:
                    task_statuses[task_match.group(2)] = status
        except OSError:
            pass

    sorted_releases = _sort_releases(releases)
    next_release = None
    enriched = []

    for rel in sorted_releases:
        tasks = rel.get("tasks", [])
        done_count = sum(1 for t in tasks if task_statuses.get(t) == "done")
        total = len(tasks)
        progress = round((done_count / total * 100) if total > 0 else 0)

        entry = {
            "version": rel["version"],
            "status": rel["status"],
            "theme": rel.get("theme", ""),
            "target_date": rel.get("target_date"),
            "tasks": tasks,
            "task_count": total,
            "done_count": done_count,
            "progress_percent": progress,
            "created_at": rel.get("created_at"),
            "released_at": rel.get("released_at"),
        }
        enriched.append(entry)

        if next_release is None and rel["status"] in ("planned", "in-progress"):
            next_release = rel["version"]

    print(json.dumps({"releases": enriched, "next_release": next_release}, indent=2))


# ── Subcommand: release-plan-create ────────────────────────────────────────

def cmd_release_plan_create(args):
    """Create a new release entry in releases.json."""
    if not _uses_local_files():
        print(json.dumps({"error": "releases.json is not used in platform-only mode. Use platform milestones instead."}))
        sys.exit(1)
    releases = _read_releases()
    version = args.version.lstrip("v")

    # Check for duplicates
    for rel in releases:
        if rel["version"] == version:
            print(json.dumps({"error": f"Release {version} already exists"}))
            sys.exit(1)

    new_release = {
        "version": version,
        "status": "planned",
        "target_date": args.target_date,
        "theme": args.theme or "",
        "tasks": [],
        "created_at": date.today().isoformat(),
        "released_at": None,
    }
    releases.append(new_release)
    _write_releases(_sort_releases(releases))

    print(json.dumps({"success": True, "release": new_release}, indent=2))


# ── Subcommand: release-plan-add-task ──────────────────────────────────────

def cmd_release_plan_add_task(args):
    """Add a task to a release's tasks array."""
    if not _uses_local_files():
        print(json.dumps({"error": "releases.json is not used in platform-only mode. Use platform milestones instead."}))
        sys.exit(1)
    releases = _read_releases()
    version = args.version.lstrip("v")
    task_code = args.task.upper()

    target = None
    for rel in releases:
        if rel["version"] == version:
            target = rel
            break

    if target is None:
        print(json.dumps({"error": f"Release {version} not found"}))
        sys.exit(1)

    if task_code in target["tasks"]:
        print(json.dumps({"error": f"Task {task_code} is already in release {version}"}))
        sys.exit(1)

    target["tasks"].append(task_code)
    _write_releases(releases)

    print(json.dumps({"success": True, "version": version, "task": task_code}))


# ── Subcommand: release-plan-remove-task ───────────────────────────────────

def cmd_release_plan_remove_task(args):
    """Remove a task from a release's tasks array."""
    if not _uses_local_files():
        print(json.dumps({"error": "releases.json is not used in platform-only mode. Use platform milestones instead."}))
        sys.exit(1)
    releases = _read_releases()
    version = args.version.lstrip("v")
    task_code = args.task.upper()

    target = None
    for rel in releases:
        if rel["version"] == version:
            target = rel
            break

    if target is None:
        print(json.dumps({"error": f"Release {version} not found"}))
        sys.exit(1)

    if task_code not in target["tasks"]:
        print(json.dumps({"error": f"Task {task_code} is not in release {version}"}))
        sys.exit(1)

    target["tasks"].remove(task_code)
    _write_releases(releases)

    print(json.dumps({"success": True, "version": version, "task": task_code}))


# ── Subcommand: release-plan-next ──────────────────────────────────────────

def cmd_release_plan_next(args):
    """Return the next planned or in-progress release."""
    if not _uses_local_files():
        print(json.dumps({"next_release": None,
                           "note": "releases.json is not used in platform-only mode"}))
        return
    releases = _read_releases()
    sorted_rels = _sort_releases(releases)

    for rel in sorted_rels:
        if rel["status"] in ("planned", "in-progress"):
            print(json.dumps(rel, indent=2))
            return

    print(json.dumps({"next_release": None}))


# ── Subcommand: release-plan-mark-released ─────────────────────────────────

def cmd_release_plan_mark_released(args):
    """Mark a release as released."""
    if not _uses_local_files():
        print(json.dumps({"error": "releases.json is not used in platform-only mode. Use platform milestones instead."}))
        sys.exit(1)
    releases = _read_releases()
    version = args.version.lstrip("v")

    target = None
    for rel in releases:
        if rel["version"] == version:
            target = rel
            break

    if target is None:
        print(json.dumps({"error": f"Release {version} not found"}))
        sys.exit(1)

    target["status"] = "released"
    target["released_at"] = date.today().isoformat()
    _write_releases(releases)

    print(json.dumps({"success": True, "version": version, "released_at": target["released_at"]}))


# ── Subcommand: release-generate ───────────────────────────────────────────

def cmd_release_generate(args):
    """Analyze non-done tasks and return grouped data for roadmap generation."""
    if not _uses_local_files():
        print(json.dumps({"error": "releases.json is not used in platform-only mode."}))
        sys.exit(1)

    root = get_main_repo_root()

    # Collect all non-done tasks from to-do.txt and progressing.txt
    all_tasks = []
    for fname, status_key in [("to-do.txt", "todo"), ("progressing.txt", "progressing")]:
        fp = root / fname
        if not fp.exists():
            continue
        content = fp.read_text(encoding="utf-8")
        current_code = None
        current_title = None
        current_priority = ""
        current_deps = "None"
        current_release = None
        for line in content.splitlines():
            stripped = line.strip()
            m = re.match(
                r"^\[.\]\s+([A-Z]{3,5}-\d{4})\s+\u2014\s+(.+)$", stripped
            )
            if m:
                if current_code:
                    all_tasks.append({
                        "code": current_code, "title": current_title,
                        "status": status_key, "prefix": current_code.split("-")[0],
                        "priority": current_priority, "dependencies": current_deps,
                        "release": current_release,
                    })
                current_code = m.group(1)
                current_title = m.group(2).strip()
                current_priority = ""
                current_deps = "None"
                current_release = None
            elif current_code:
                if stripped.startswith("Priority:"):
                    current_priority = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("Dependencies:"):
                    current_deps = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("Release:"):
                    current_release = stripped.split(":", 1)[1].strip()
        if current_code:
            all_tasks.append({
                "code": current_code, "title": current_title,
                "status": status_key, "prefix": current_code.split("-")[0],
                "priority": current_priority, "dependencies": current_deps,
                "release": current_release,
            })

    # Group by prefix
    groups = {}
    for t in all_tasks:
        groups.setdefault(t["prefix"], []).append(t)

    # Unassigned tasks (no release set)
    unassigned = [t for t in all_tasks if not t["release"] or t["release"] == "None"]

    # Existing releases
    existing = _read_releases()

    print(json.dumps({
        "pending_tasks": all_tasks,
        "task_count": len(all_tasks),
        "unassigned_count": len(unassigned),
        "unassigned": [t["code"] for t in unassigned],
        "groups": {k: [t["code"] for t in v] for k, v in groups.items()},
        "existing_releases": [{"version": r["version"], "status": r["status"],
                               "task_count": len(r.get("tasks", []))}
                              for r in existing],
    }, indent=2))


# ── Subcommand: release-close ──────────────────────────────────────────────

def cmd_release_close(args):
    """Check release readiness and return status summary for closing."""
    if not _uses_local_files():
        print(json.dumps({"error": "releases.json is not used in platform-only mode."}))
        sys.exit(1)

    releases = _read_releases()
    version = args.version.lstrip("v")

    target = None
    for rel in releases:
        if rel["version"] == version:
            target = rel
            break
    if target is None:
        print(json.dumps({"error": f"Release {version} not found"}))
        sys.exit(1)

    # Cross-reference task statuses
    root = get_main_repo_root()
    task_statuses = {}
    for fname, status in [("to-do.txt", "todo"), ("progressing.txt", "progressing"),
                          ("done.txt", "done")]:
        fp = root / fname
        if not fp.exists():
            continue
        content = fp.read_text(encoding="utf-8")
        for line in content.splitlines():
            m = re.match(r"^\[.\]\s+([A-Z]{3,5}-\d{4})\s+\u2014", line.strip())
            if m:
                task_statuses[m.group(1)] = status

    tasks = target.get("tasks", [])
    pending = []
    for t in tasks:
        st = task_statuses.get(t, "not-found")
        if st != "done":
            pending.append({"code": t, "status": st})

    print(json.dumps({
        "version": version,
        "release_status": target["status"],
        "all_tasks_done": len(pending) == 0,
        "total_tasks": len(tasks),
        "done_tasks": len(tasks) - len(pending),
        "pending_tasks": pending,
    }, indent=2))


# ── Subcommand: release-state-get ──────────────────────────────────────────

def cmd_release_state_get(args):
    """Read and print .claude/release-state.json (or platform issue in platform-only mode)."""
    if not _uses_local_files():
        state = _platform_state_get()
        if not state:
            print(json.dumps({"error": "No release state found"}))
        else:
            print(json.dumps(state, indent=2))
        return
    root = get_main_repo_root()
    state_file = root / ".claude" / "release-state.json"
    if not state_file.exists():
        print(json.dumps({"error": "No release state found"}))
        return
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(json.dumps(data, indent=2))
    except (json.JSONDecodeError, OSError) as e:
        print(json.dumps({"error": str(e)}))


# ── Subcommand: release-state-set ──────────────────────────────────────────

def cmd_release_state_set(args):
    """Update release state fields (local file or platform issue in platform-only mode)."""
    platform_only = not _uses_local_files()
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Read existing state from the appropriate source
    if platform_only:
        state = _platform_state_get()
    else:
        root = get_main_repo_root()
        state_file = root / ".claude" / "release-state.json"
        state = {}
        if state_file.exists():
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
            except (json.JSONDecodeError, OSError):
                state = {}

    # Create default state if none exists
    if not state:
        state = {
            "version": args.version,
            "branch": "",
            "current_stage": 1,
            "stage_name": "start",
            "started_at": now,
            "updated_at": now,
            "loop_count": 0,
            "stages_completed": [],
            "tasks_completed": [],
            "tasks_pending": [],
            "issues_found": [],
            "gate_approvals": {},
        }

    # Update version (always required)
    state["version"] = args.version

    # Update branch if provided
    if args.branch is not None:
        state["branch"] = args.branch

    # Update stage if provided
    if args.stage is not None:
        # Append previous stage to stages_completed
        prev_stage = state.get("current_stage", 0)
        if prev_stage > 0:
            completed = state.setdefault("stages_completed", [])
            if prev_stage not in completed:
                completed.append(prev_stage)
        state["current_stage"] = args.stage

    # Update stage name if provided
    if args.stage_name is not None:
        state["stage_name"] = args.stage_name

    # Append completed task
    if args.add_completed_task is not None:
        completed_tasks = state.setdefault("tasks_completed", [])
        if args.add_completed_task not in completed_tasks:
            completed_tasks.append(args.add_completed_task)

    # Append issue
    if args.add_issue is not None:
        try:
            issue = json.loads(args.add_issue)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON for --add-issue: {e}"}))
            sys.exit(1)
        state.setdefault("issues_found", []).append(issue)

    # Increment loop count
    if args.increment_loop:
        state["loop_count"] = state.get("loop_count", 0) + 1

    # Mark gate approved
    if args.mark_gate_approved is not None:
        approvals = state.setdefault("gate_approvals", {})
        approvals[str(args.mark_gate_approved)] = True

    # Always update timestamp
    state["updated_at"] = now

    if platform_only:
        _platform_state_set(state)
        print(json.dumps(state, indent=2))
        return

    # Ensure .claude directory exists
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        f.write("\n")

    print(json.dumps(state, indent=2))


# ── Subcommand: release-state-clear ────────────────────────────────────────

def cmd_release_state_clear(args):
    """Delete .claude/release-state.json (or close platform issue in platform-only mode)."""
    if not _uses_local_files():
        _platform_state_clear()
        print(json.dumps({"success": True}))
        return
    root = get_main_repo_root()
    state_file = root / ".claude" / "release-state.json"
    if state_file.exists():
        state_file.unlink()
    print(json.dumps({"success": True}))


# ── Subcommand: release-plan-set-status ────────────────────────────────────

def cmd_release_plan_set_status(args):
    """Set a release's status in releases.json."""
    if not _uses_local_files():
        print(json.dumps({"error": "releases.json is not used in platform-only mode. Use platform milestones instead."}))
        sys.exit(1)
    releases = _read_releases()
    version = args.version.lstrip("v")

    target = None
    for rel in releases:
        if rel["version"] == version:
            target = rel
            break

    if target is None:
        print(json.dumps({"error": f"Release {version} not found"}))
        sys.exit(1)

    target["status"] = args.status
    if args.status == "released":
        target["released_at"] = date.today().isoformat()

    _write_releases(releases)

    result = {"success": True, "version": version, "status": args.status}
    if args.status == "released":
        result["released_at"] = target["released_at"]
    print(json.dumps(result, indent=2))


# ── Subcommand: merge-check ───────────────────────────────────────────────

def cmd_merge_check(args):
    """Dry-run a git merge and report conflicts."""
    source = args.source
    target = args.target

    # Save current branch
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, check=True,
        )
        original_branch = result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(json.dumps({"error": f"Failed to get current branch: {e}"}))
        sys.exit(1)

    # Checkout target branch
    try:
        subprocess.run(
            ["git", "checkout", target],
            capture_output=True, text=True, check=True,
        )
    except subprocess.CalledProcessError as e:
        print(json.dumps({
            "error": f"Failed to checkout target branch '{target}': {e.stderr.strip()}",
            "has_conflicts": False,
            "conflicting_files": [],
            "merge_possible": False,
        }))
        sys.exit(1)

    # Try the merge
    has_conflicts = False
    conflicting_files = []
    merge_possible = True

    try:
        merge_result = subprocess.run(
            ["git", "merge", "--no-commit", "--no-ff", source],
            capture_output=True, text=True,
        )
        if merge_result.returncode != 0:
            has_conflicts = True
            merge_possible = False
            # Parse conflicting files from stderr and stdout
            for line in (merge_result.stdout + merge_result.stderr).splitlines():
                # "CONFLICT (content): Merge conflict in <file>"
                conflict_match = re.search(r"Merge conflict in (.+)$", line)
                if conflict_match:
                    conflicting_files.append(conflict_match.group(1).strip())
                # "CONFLICT (modify/delete): <file> deleted in ..."
                modify_delete = re.search(r"^CONFLICT \([^)]+\):\s+(\S+)", line)
                if modify_delete and not conflict_match:
                    conflicting_files.append(modify_delete.group(1).strip())
            # Abort the failed merge
            subprocess.run(
                ["git", "merge", "--abort"],
                capture_output=True, text=True,
            )
        else:
            # Merge succeeded — undo the uncommitted merge
            subprocess.run(
                ["git", "reset", "--merge"],
                capture_output=True, text=True,
            )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        has_conflicts = True
        merge_possible = False
        # Try to abort on error
        subprocess.run(
            ["git", "merge", "--abort"],
            capture_output=True, text=True,
        )

    # Restore original branch
    subprocess.run(
        ["git", "checkout", original_branch],
        capture_output=True, text=True,
    )

    # Deduplicate conflicting files
    seen = set()
    unique_files = []
    for f in conflicting_files:
        if f not in seen:
            seen.add(f)
            unique_files.append(f)

    print(json.dumps({
        "has_conflicts": has_conflicts,
        "conflicting_files": unique_files,
        "merge_possible": not has_conflicts,
    }, indent=2))


# ── Subcommand: full-context ────────────────────────────────────────────────

def cmd_full_context(args):
    """Return all release-related context in a single call."""
    root = find_project_root()
    main_root = get_main_repo_root()
    tag_prefix = args.tag_prefix

    # 1. Detect current version from manifest files (reuse existing logic)
    all_sources = []
    primary_version = None
    primary_file = None

    for filename, reader in MANIFEST_READERS:
        filepath = root / filename
        if filepath.exists():
            version = reader(filepath)
            if version:
                all_sources.append({"file": filename, "version": version})
                if primary_version is None:
                    primary_version = version
                    primary_file = filename

    if primary_version is None:
        primary_version = "0.0.0"
        primary_file = None

    is_beta = primary_version.endswith("-beta")
    base_version = primary_version.removesuffix("-beta")

    # 2. Get latest git tag
    latest_tag = get_latest_tag(tag_prefix)

    # 3. Get current branch
    current_branch = None
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, check=True,
        )
        current_branch = result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # 4. Get working tree status
    dirty_files_count = 0
    is_clean = True
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, check=True,
        )
        dirty_lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
        dirty_files_count = len(dirty_lines)
        is_clean = dirty_files_count == 0
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    # 5. Read project config
    project_cfg = load_config(root)

    # 6. Auto-detect missing values
    # Tag prefix: use --tag-prefix arg first, then config, then auto-detect from existing tags
    if args.tag_prefix == "auto":
        configured_prefix = project_cfg.get("tag_prefix", "")
        if configured_prefix:
            tag_prefix = configured_prefix
        else:
            # Try to detect from existing tags
            try:
                result = subprocess.run(
                    ["git", "tag", "-l", "--sort=-v:refname"],
                    capture_output=True, text=True, check=True,
                )
                tags = result.stdout.strip().splitlines()
                if tags:
                    first_tag = tags[0]
                    m = re.match(r"^([a-zA-Z]*)\d", first_tag)
                    tag_prefix = m.group(1) if m else "v"
                else:
                    tag_prefix = "v"
            except (subprocess.CalledProcessError, FileNotFoundError):
                tag_prefix = "v"
        # Re-fetch latest tag with detected prefix
        latest_tag = get_latest_tag(tag_prefix)

    # Release branch: from config or auto-detect
    development_branch = project_cfg.get("development_branch", "") or ""
    staging_branch = project_cfg.get("staging_branch", "") or "staging"
    production_branch = project_cfg.get("production_branch", "") or "main"
    release_branch_legacy = project_cfg.get("release_branch", "")

    # Auto-detect development branch if not configured
    if not development_branch and not release_branch_legacy:
        try:
            result = subprocess.run(
                ["git", "branch", "--list", "develop"],
                capture_output=True, text=True, check=True,
            )
            if result.stdout.strip():
                development_branch = "develop"
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    # Changelog
    changelog_file = project_cfg.get("changelog_file", "")
    changelog_exists = False
    if changelog_file:
        changelog_exists = (root / changelog_file).exists()

    # Repo URL and verify command
    repo_url = project_cfg.get("github_repo_url", "")
    verify_command = project_cfg.get("verify_command", "")
    package_paths = project_cfg.get("package_json_paths", "")

    # 7. Check releases.json for next planned release (only when using local files)
    release_plan = {
        "has_plan": False,
        "next_version": None,
        "next_status": None,
        "next_theme": None,
        "next_task_count": 0,
    }
    if _uses_local_files():
        releases = _read_releases()
        sorted_rels = _sort_releases(releases)
        for rel in sorted_rels:
            if rel["status"] in ("planned", "in-progress"):
                release_plan = {
                    "has_plan": True,
                    "next_version": rel["version"],
                    "next_status": rel["status"],
                    "next_theme": rel.get("theme", ""),
                    "next_task_count": len(rel.get("tasks", [])),
                }
                break

    # 8. Check if release-state.json exists (resume detection)
    state_file = main_root / ".claude" / "release-state.json"
    release_state = {
        "has_active": False,
        "version": None,
        "stage": None,
        "stage_name": None,
    }
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)
            release_state = {
                "has_active": True,
                "version": state_data.get("version"),
                "stage": state_data.get("current_stage"),
                "stage_name": state_data.get("stage_name"),
            }
        except (json.JSONDecodeError, OSError):
            pass

    # 9. Load platform config from issues-tracker.json
    platform_info = {
        "enabled": False,
        "platform": None,
        "repo": None,
    }
    branch_protection = {}
    for candidate in ["issues-tracker.json", "github-issues.json"]:
        fp = main_root / ".claude" / candidate
        if fp.exists():
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    pt_data = json.load(f)
                platform_info = {
                    "enabled": pt_data.get("enabled", False),
                    "platform": pt_data.get("platform", "github"),
                    "repo": pt_data.get("repo", None),
                }
                # Read cached branch protection settings
                cached_branches = pt_data.get("branches", {})
                for bname, binfo in cached_branches.items():
                    if isinstance(binfo, dict):
                        branch_protection[bname] = {
                            "role": binfo.get("role", ""),
                            "protected": binfo.get("protected", False),
                            "merge_strategy": binfo.get("merge_strategy", ""),
                            "require_reviews": binfo.get("require_reviews", 0),
                        }
            except (json.JSONDecodeError, OSError):
                pass
            break

    # Build output
    output = {
        "version": {
            "current": primary_version,
            "base": base_version,
            "is_beta": is_beta,
            "source_file": primary_file,
            "all_sources": all_sources,
        },
        "tags": {
            "prefix": tag_prefix,
            "latest": latest_tag,
        },
        "git": {
            "current_branch": current_branch,
            "is_clean": is_clean,
            "dirty_files_count": dirty_files_count,
        },
        "config": {
            "development_branch": development_branch or "develop",
            "staging_branch": staging_branch or "staging",
            "production_branch": production_branch or "main",
            "changelog_file": changelog_file,
            "changelog_exists": changelog_exists,
            "repo_url": repo_url,
            "verify_command": verify_command,
            "package_paths": package_paths,
        },
        "platform": platform_info,
        "branch_protection": branch_protection,
        "release_plan": release_plan,
        "release_state": release_state,
    }
    print(json.dumps(output, indent=2))


# ── Subcommand: coverage-gate ───────────────────────────────────────────────

def cmd_coverage_gate(args):
    """Run coverage threshold check as a release gate.

    Imports from the coverage analyzer to take a snapshot and evaluate
    against the configured minimum threshold.  Designed to be invoked
    during Stage 6 (Integration Tests) of the release pipeline.
    """
    root = get_main_repo_root()

    # Lazy import to avoid circular dependency at module level
    scripts_dir = Path(__file__).resolve().parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))

    from analyzers.coverage import (  # noqa: E402
        take_snapshot,
        check_threshold,
        read_manifest,
    )

    min_cov = getattr(args, "min_coverage", 0.0)

    # Take a fresh snapshot (also persists it)
    manifest = take_snapshot(root)
    result = check_threshold(manifest, min_cov)

    # Augment with release-gate framing
    result["gate"] = "coverage"
    result["gate_status"] = "passed" if result["passed"] else "failed"

    print(json.dumps(result, indent=2))
    if not result["passed"]:
        sys.exit(1)


# ── CLI Setup ───────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Release manager CLI for codeclaw",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # current-version
    p = sub.add_parser("current-version", help="Detect version from manifest files")
    p.add_argument("--tag-prefix", default="v", help="Git tag prefix (default: v)")
    p.set_defaults(func=cmd_current_version)

    # update-versions
    p = sub.add_parser("update-versions", help="Bump version in all manifest files")
    p.add_argument("--version", required=True, help="New version to set (e.g., 1.2.3)")
    p.add_argument("--package-paths", default=None,
                    help="Space-separated manifest paths (uses auto-discovery if omitted)")
    p.set_defaults(func=cmd_update_versions)

    # parse-commits
    p = sub.add_parser("parse-commits", help="Parse git log into structured data")
    p.add_argument("--since", default=None, help="Git tag to use as base (commits since this tag)")
    p.set_defaults(func=cmd_parse_commits)

    # suggest-bump
    p = sub.add_parser("suggest-bump", help="Calculate new version from bump type")
    p.add_argument("--current-version", required=True, help="Current version string")
    p.add_argument("--suggested-bump", choices=["major", "minor", "patch"], default="patch",
                    help="Suggested bump from parse-commits")
    p.add_argument("--force", choices=["major", "minor", "patch"], default=None,
                    help="Force a specific bump type (overrides suggested)")
    p.set_defaults(func=cmd_suggest_bump)

    # generate-changelog
    p = sub.add_parser("generate-changelog", help="Generate changelog section from commits JSON (stdin)")
    p.add_argument("--version", required=True, help="Version string for the header")
    p.add_argument("--date", default=None, help="Release date (YYYY-MM-DD, default: today)")
    p.set_defaults(func=cmd_generate_changelog)

    # release-plan-list
    p = sub.add_parser("release-plan-list", help="List all planned releases with stats")
    p.set_defaults(func=cmd_release_plan_list)

    # release-plan-create
    p = sub.add_parser("release-plan-create", help="Create a new release plan entry")
    p.add_argument("--version", required=True, help="Semver version (e.g., 1.1.0)")
    p.add_argument("--theme", default=None, help="Release theme/goal description")
    p.add_argument("--target-date", default=None, help="Target date (YYYY-MM-DD)")
    p.set_defaults(func=cmd_release_plan_create)

    # release-plan-add-task
    p = sub.add_parser("release-plan-add-task", help="Add a task to a release")
    p.add_argument("--version", required=True, help="Release version")
    p.add_argument("--task", required=True, help="Task code (e.g., AUTH-0001)")
    p.set_defaults(func=cmd_release_plan_add_task)

    # release-plan-remove-task
    p = sub.add_parser("release-plan-remove-task", help="Remove a task from a release")
    p.add_argument("--version", required=True, help="Release version")
    p.add_argument("--task", required=True, help="Task code (e.g., AUTH-0001)")
    p.set_defaults(func=cmd_release_plan_remove_task)

    # release-plan-next
    p = sub.add_parser("release-plan-next", help="Get the next planned/in-progress release")
    p.set_defaults(func=cmd_release_plan_next)

    # release-plan-mark-released
    p = sub.add_parser("release-plan-mark-released", help="Mark a release as released")
    p.add_argument("--version", required=True, help="Release version to mark as released")
    p.set_defaults(func=cmd_release_plan_mark_released)

    # release-state-get
    p = sub.add_parser("release-state-get", help="Read release state from .claude/release-state.json")
    p.set_defaults(func=cmd_release_state_get)

    # release-state-set
    p = sub.add_parser("release-state-set", help="Update release state in .claude/release-state.json")
    p.add_argument("--version", required=True, help="Release version")
    p.add_argument("--branch", default=None, help="Release branch name (e.g., release/1.2.0)")
    p.add_argument("--stage", type=int, default=None, help="Current stage number (1-10)")
    p.add_argument("--stage-name", default=None, help="Current stage name")
    p.add_argument("--add-completed-task", default=None, help="Task code to append to tasks_completed")
    p.add_argument("--add-issue", default=None, help="JSON string of issue to append to issues_found")
    p.add_argument("--increment-loop", action="store_true", help="Increment loop_count by 1")
    p.add_argument("--mark-gate-approved", type=int, default=None, help="Stage number to mark as approved")
    p.set_defaults(func=cmd_release_state_set)

    # release-generate
    p = sub.add_parser("release-generate", help="Analyze non-done tasks and return grouped data for roadmap generation")
    p.set_defaults(func=cmd_release_generate)

    # release-close
    p = sub.add_parser("release-close", help="Check release readiness and return status summary for closing")
    p.add_argument("--version", required=True, help="Release version to check")
    p.set_defaults(func=cmd_release_close)

    # release-state-clear
    p = sub.add_parser("release-state-clear", help="Delete .claude/release-state.json")
    p.set_defaults(func=cmd_release_state_clear)

    # release-plan-set-status
    p = sub.add_parser("release-plan-set-status", help="Set a release status in releases.json")
    p.add_argument("--version", required=True, help="Release version")
    p.add_argument("--status", required=True, choices=["planned", "in-progress", "released"],
                    help="New status for the release")
    p.set_defaults(func=cmd_release_plan_set_status)

    # merge-check
    p = sub.add_parser("merge-check", help="Dry-run git merge and report conflicts")
    p.add_argument("--source", required=True, help="Source branch to merge from")
    p.add_argument("--target", required=True, help="Target branch to merge into")
    p.set_defaults(func=cmd_merge_check)

    # full-context
    p = sub.add_parser("full-context", help="Return all release-related context in a single call")
    p.add_argument("--tag-prefix", default="auto",
                    help="Git tag prefix (default: auto-detect from project config or existing tags)")
    p.set_defaults(func=cmd_full_context)

    # coverage-gate
    p = sub.add_parser("coverage-gate",
                        help="Run coverage threshold check as a release gate")
    p.add_argument("--min-coverage", type=float, default=0.0,
                    help="Minimum coverage percentage to pass (default: 0)")
    p.set_defaults(func=cmd_coverage_gate)

    return parser


def main():
    parser = build_parser()
    try:
        args = parser.parse_args()
        args.func(args)
    except Exception as e:
        print(json.dumps({"error": str(e), "type": type(e).__name__}))
        sys.exit(1)


if __name__ == "__main__":
    main()
