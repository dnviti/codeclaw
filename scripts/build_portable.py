#!/usr/bin/env python3
"""Build a portable ZIP distribution of CodeClaw.

Assembles a self-contained .zip archive that users can download and extract
into any project directory without Claude Code or any package manager.

The archive contains:
  - All Python scripts (scripts/, scripts/adapters/, scripts/analyzers/)
  - Platform-neutral skill definitions (skills/)
  - Configuration templates (config/)
  - Bootstrap installers (install.sh, install.ps1)
  - manifest.json with version, file list, and checksums
  - CLAUDE.md template, .claude-plugin metadata
  - docs/ directory for reference

Usage:
    python3 scripts/build_portable.py [--version VERSION] [--output DIR]
    python3 scripts/build_portable.py --help

Zero external dependencies -- stdlib only.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# ── Constants ───────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

# Directories to include in the archive (relative to repo root)
INCLUDE_DIRS = [
    "scripts",
    "skills",
    "config",
    "docs",
    "hooks",
    "templates",
    ".claude-plugin",
]

# Individual files to include at the archive root
INCLUDE_FILES = [
    "CHANGELOG.md",
    "README.md",
    ".gitignore",
]

# Patterns to exclude from the archive (matched against relative paths)
EXCLUDE_PATTERNS = [
    r"^\.git(/|$)",
    r"^\.github(/|$)",
    r"^\.claude(/|$)",
    r"^tests(/|$)",
    r"__pycache__(/|$)",
    r"\.pyc$",
    r"\.pyo$",
    r"\.egg-info(/|$)",
    r"^\.env",
    r"^node_modules(/|$)",
    r"^\.DS_Store$",
    r"^Thumbs\.db$",
]

# Compiled exclude regexes
_EXCLUDE_RE = [re.compile(p) for p in EXCLUDE_PATTERNS]

# Default output directory
DEFAULT_OUTPUT_DIR = REPO_ROOT / "dist"

# Archive name template
ARCHIVE_NAME_TEMPLATE = "claw-{version}-portable.zip"

# Supported platform targets for the manifest
PLATFORM_TARGETS = [
    "claude-code",
    "opencode",
    "openclaw",
    "cursor",
    "windsurf",
    "continue",
    "copilot",
    "aider",
    "generic",
]

# Version detection regex
VERSION_RE = re.compile(r'"version"\s*:\s*"([^"]+)"')

# Allowed version string pattern (semver with optional pre-release/build metadata)
SAFE_VERSION_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z.\-+]{0,63}$")


# ── Helpers ─────────────────────────────────────────────────────────────────

def validate_version(version: str) -> str:
    """Validate that a version string is safe for use in file paths and ZIP entries.

    Raises ValueError if the version contains path-traversal sequences or
    characters that could be problematic in archive entry names.
    """
    if not version:
        raise ValueError("Version string must not be empty")
    if ".." in version or "/" in version or "\\" in version:
        raise ValueError(
            f"Version string contains path-traversal characters: {version!r}"
        )
    if not SAFE_VERSION_RE.match(version):
        raise ValueError(
            f"Version string contains disallowed characters: {version!r}. "
            "Only alphanumeric, dots, hyphens, and plus signs are allowed."
        )
    return version


def detect_version() -> str:
    """Detect the current version from plugin.json or CHANGELOG.md."""
    plugin_json = REPO_ROOT / ".claude-plugin" / "plugin.json"
    if plugin_json.exists():
        try:
            data = json.loads(plugin_json.read_text(encoding="utf-8"))
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


def is_excluded(rel_path: str) -> bool:
    """Check whether a relative path should be excluded from the archive."""
    normalized = rel_path.replace(os.sep, "/")
    for pattern in _EXCLUDE_RE:
        if pattern.search(normalized):
            return True
    return False


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(131072)  # 128 KB for fewer syscalls
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def collect_files(root: Path) -> list[tuple[Path, str]]:
    """Collect all files to include in the archive.

    Returns a list of (absolute_path, archive_relative_path) tuples.
    """
    files: list[tuple[Path, str]] = []

    # Collect from included directories
    for dir_name in INCLUDE_DIRS:
        dir_path = root / dir_name
        if not dir_path.is_dir():
            continue
        for file_path in sorted(dir_path.rglob("*")):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(root)
            rel_str = str(rel).replace(os.sep, "/")
            if not is_excluded(rel_str):
                files.append((file_path, rel_str))

    # Collect individual root-level files
    for file_name in INCLUDE_FILES:
        file_path = root / file_name
        if file_path.is_file():
            files.append((file_path, file_name))

    return files


def build_manifest(
    version: str,
    files: list[tuple[Path, str]],
    manifest_template: Path | None = None,
) -> dict:
    """Build the manifest.json content for the archive.

    Parameters
    ----------
    version : str
        The version string for this distribution.
    files : list
        List of (absolute_path, archive_relative_path) tuples.
    manifest_template : Path | None
        Optional template file to merge with generated data.

    Returns
    -------
    dict
        The complete manifest data.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    file_entries = []
    for abs_path, rel_path in files:
        entry = {
            "path": rel_path,
            "sha256": compute_sha256(abs_path),
            "size": abs_path.stat().st_size,
        }
        file_entries.append(entry)

    manifest = {
        "name": "claw",
        "version": version,
        "description": "CodeClaw - Portable Distribution",
        "build_date": now,
        "platform_targets": PLATFORM_TARGETS,
        "archive_format": "zip",
        "installer": {
            "posix": "install.sh",
            "windows": "install.ps1",
        },
        "files": file_entries,
        "file_count": len(file_entries),
    }

    # Merge with template if provided
    if manifest_template and manifest_template.exists():
        try:
            template_data = json.loads(manifest_template.read_text(encoding="utf-8"))
            # Template fields that are not auto-generated take precedence
            for key in ("license", "repository", "author", "keywords"):
                if key in template_data:
                    manifest[key] = template_data[key]
        except (json.JSONDecodeError, OSError):
            pass

    return manifest


def build_archive(
    version: str,
    output_dir: Path,
    verbose: bool = False,
) -> Path:
    """Build the portable ZIP archive.

    Parameters
    ----------
    version : str
        Version string for the archive.
    output_dir : Path
        Directory to write the .zip file.
    verbose : bool
        Print progress messages.

    Returns
    -------
    Path
        Path to the created .zip file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_name = ARCHIVE_NAME_TEMPLATE.format(version=version)
    archive_path = output_dir / archive_name

    if verbose:
        print(f"[build] Collecting files from {REPO_ROOT}")

    files = collect_files(REPO_ROOT)
    if verbose:
        print(f"[build] Found {len(files)} files to include")

    # Build manifest
    manifest_template = REPO_ROOT / "templates" / "portable-manifest.json"
    manifest_data = build_manifest(version, files, manifest_template)

    # Locate bootstrap installers
    install_sh = REPO_ROOT / "templates" / "install.sh"
    install_ps1 = REPO_ROOT / "templates" / "install.ps1"

    # Write the archive
    if verbose:
        print(f"[build] Creating archive: {archive_path}")

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add all collected files under a claw-{version}/ prefix
        prefix = f"claw-{version}"

        for abs_path, rel_path in files:
            arcname = f"{prefix}/{rel_path}"
            zf.write(abs_path, arcname)
            if verbose:
                print(f"  + {rel_path}")

        # Add bootstrap installers at the archive root (for easy access).
        # These are already included under templates/ via INCLUDE_DIRS, so
        # we use writestr with the file content to place a copy at the root
        # without storing the same bytes twice (ZIP deduplication is not
        # guaranteed, but having them at the root is needed for usability).
        if install_sh.exists():
            # Only add root-level copy if not already present via templates/
            root_sh = f"{prefix}/install.sh"
            if root_sh not in zf.namelist():
                zf.write(install_sh, root_sh)
                if verbose:
                    print("  + install.sh")
            elif verbose:
                print("  ~ install.sh (already included via templates/)")
        else:
            print("[warn] templates/install.sh not found, skipping", file=sys.stderr)

        if install_ps1.exists():
            root_ps1 = f"{prefix}/install.ps1"
            if root_ps1 not in zf.namelist():
                zf.write(install_ps1, root_ps1)
                if verbose:
                    print("  + install.ps1")
            elif verbose:
                print("  ~ install.ps1 (already included via templates/)")
        else:
            print("[warn] templates/install.ps1 not found, skipping", file=sys.stderr)

        # Add manifest.json
        manifest_json = json.dumps(manifest_data, indent=2, ensure_ascii=False)
        zf.writestr(f"{prefix}/manifest.json", manifest_json)
        if verbose:
            print("  + manifest.json")

    # Print summary
    archive_size = archive_path.stat().st_size
    if verbose:
        size_kb = archive_size / 1024
        print(f"[build] Archive created: {archive_path} ({size_kb:.1f} KB)")
        print(f"[build] Version: {version}")
        print(f"[build] Files: {manifest_data['file_count']} + installers + manifest")

    return archive_path


# ── CLI ─────────────────────────────────────────────────────────────────────

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Build a portable ZIP distribution of CodeClaw.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python3 scripts/build_portable.py
  python3 scripts/build_portable.py --version 3.5.0
  python3 scripts/build_portable.py --output /tmp/release --verbose
  python3 scripts/build_portable.py --json
""",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Version string for the archive (default: auto-detect from plugin.json)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=f"Output directory for the .zip file (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print progress messages during build",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output result as JSON (for CI integration)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Main entry point."""
    args = parse_args(argv)

    version = args.version or detect_version()
    try:
        version = validate_version(version)
    except ValueError as exc:
        if args.json_output:
            print(json.dumps({"success": False, "error": str(exc)}))
        else:
            print(f"[error] {exc}", file=sys.stderr)
        return 1

    output_dir = Path(args.output) if args.output else DEFAULT_OUTPUT_DIR

    if not args.json_output:
        print(f"Building CodeClaw portable distribution v{version}...")

    try:
        archive_path = build_archive(
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

    if args.json_output:
        result = {
            "success": True,
            "archive": str(archive_path),
            "version": version,
            "size": archive_path.stat().st_size,
        }
        print(json.dumps(result))
    else:
        print(f"Done. Archive: {archive_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
