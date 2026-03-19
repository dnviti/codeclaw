#!/usr/bin/env python3
"""Documentation manager CLI for CodeClaw.

Provides deterministic operations for documentation lifecycle:
discover codebase structure, track staleness via manifest hashes,
detect static site generators, and clean generated docs.

All output is JSON. Zero external dependencies (stdlib only).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Imports from sibling modules ───────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from analyzers import (  # noqa: E402
    classify_all_files,
    detect_frameworks,
    detect_languages,
    load_gitignore_patterns,
    walk_source_files,
)


# ── Helpers ────────────────────────────────────────────────────────────────

def get_main_repo_root() -> Path:
    """Return the main git repo root (not a worktree)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        top = Path(result.stdout.strip())
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, check=True, cwd=top,
        )
        common_dir = Path(common.stdout.strip())
        if common_dir.is_absolute():
            return common_dir.parent
        return (top / common_dir).resolve().parent
    except (subprocess.CalledProcessError, OSError):
        return Path.cwd()


DOCS_DIR_NAME = "docs"
MANIFEST_NAME = ".docs-manifest.json"
VISUAL_RICHNESS_LEVELS = ("zero", "tiny", "moderate", "large")
VISUAL_RICHNESS_DEFAULT = "tiny"

# Standard documentation sections
SECTIONS = [
    {"name": "index", "file": "index.md", "title": "Documentation Index",
     "description": "Landing page, table of contents, project summary"},
    {"name": "architecture", "file": "architecture.md", "title": "Architecture",
     "description": "System architecture, components, data flow (Mermaid diagrams)"},
    {"name": "getting-started", "file": "getting-started.md", "title": "Getting Started",
     "description": "Installation, prerequisites, first run"},
    {"name": "configuration", "file": "configuration.md", "title": "Configuration",
     "description": "Environment variables, config files, feature flags"},
    {"name": "api-reference", "file": "api-reference.md", "title": "API Reference",
     "description": "Endpoints, functions, CLI commands"},
    {"name": "deployment", "file": "deployment.md", "title": "Deployment",
     "description": "Build, Docker, CI/CD, production setup"},
    {"name": "development", "file": "development.md", "title": "Development",
     "description": "Contributing, local dev, testing, branch strategy"},
    {"name": "troubleshooting", "file": "troubleshooting.md", "title": "Troubleshooting",
     "description": "Common errors, debugging, FAQ"},
    {"name": "llm-context", "file": "llm-context.md", "title": "LLM Context",
     "description": "Consolidated single-file for LLM/bot consumption"},
]


def _hash_file(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _read_manifest(root: Path) -> dict:
    """Read .docs-manifest.json from the docs directory."""
    fp = root / DOCS_DIR_NAME / MANIFEST_NAME
    if not fp.exists():
        return {}
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_manifest(root: Path, manifest: dict) -> None:
    """Write .docs-manifest.json to the docs directory."""
    docs_dir = root / DOCS_DIR_NAME
    docs_dir.mkdir(parents=True, exist_ok=True)
    fp = docs_dir / MANIFEST_NAME
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


# ── Subcommand: discover ───────────────────────────────────────────────────

def cmd_discover(args):
    """Scan the codebase and return structured JSON of what exists."""
    root = get_main_repo_root()
    gitignore = load_gitignore_patterns(root)

    languages = detect_languages(root, gitignore)
    frameworks = detect_frameworks(root)
    file_roles = classify_all_files(root, gitignore)

    # Count files per role
    role_counts = {role: len(files) for role, files in file_roles.items()}

    # Detect entry points
    entry_points = []
    for role in ("entry_point", "main", "server", "app"):
        entry_points.extend(file_roles.get(role, []))

    # Detect config files
    config_files = file_roles.get("config", [])

    # Detect test files
    test_files = file_roles.get("test", [])

    # Check for existing docs
    docs_dir = root / DOCS_DIR_NAME
    docs_exist = docs_dir.is_dir()
    existing_sections = []
    if docs_exist:
        for section in SECTIONS:
            fp = docs_dir / section["file"]
            if fp.exists():
                existing_sections.append(section["name"])

    # Read manifest if present
    manifest = _read_manifest(root)

    # Read CLAUDE.md if present
    claude_md = root / "CLAUDE.md"
    has_claude_md = claude_md.exists()

    # Detect README
    readme = None
    for name in ("README.md", "readme.md", "README.rst", "README.txt"):
        if (root / name).exists():
            readme = name
            break

    print(json.dumps({
        "root": str(root),
        "languages": languages,
        "frameworks": frameworks,
        "role_counts": role_counts,
        "total_files": sum(role_counts.values()),
        "entry_points": entry_points[:20],
        "config_files": config_files[:20],
        "test_files_count": len(test_files),
        "docs_exist": docs_exist,
        "existing_sections": existing_sections,
        "has_manifest": bool(manifest),
        "has_claude_md": has_claude_md,
        "readme": readme,
        "standard_sections": SECTIONS,
    }, indent=2))


# ── Subcommand: check-staleness ────────────────────────────────────────────

def cmd_check_staleness(args):
    """Compare current source file hashes against .docs-manifest.json."""
    root = get_main_repo_root()
    manifest = _read_manifest(root)

    if not manifest:
        print(json.dumps({
            "has_manifest": False,
            "sections": [],
            "message": "No manifest found. Run /docs generate first.",
        }))
        return

    sections_status = []
    for section_entry in manifest.get("sections", []):
        name = section_entry["name"]
        doc_file = root / DOCS_DIR_NAME / section_entry["file"]
        doc_exists = doc_file.exists()

        changed_sources = []
        for src in section_entry.get("source_files", []):
            src_path = root / src["path"]
            current_hash = _hash_file(src_path) if src_path.exists() else ""
            if current_hash != src.get("hash", ""):
                changed_sources.append({
                    "path": src["path"],
                    "old_hash": src.get("hash", ""),
                    "current_hash": current_hash,
                    "missing": not src_path.exists(),
                })

        if not doc_exists:
            status = "missing"
        elif changed_sources:
            status = "stale"
        else:
            status = "current"

        sections_status.append({
            "name": name,
            "file": section_entry["file"],
            "status": status,
            "changed_sources": changed_sources,
        })

    stale_count = sum(1 for s in sections_status if s["status"] == "stale")
    missing_count = sum(1 for s in sections_status if s["status"] == "missing")

    print(json.dumps({
        "has_manifest": True,
        "sections": sections_status,
        "stale_count": stale_count,
        "missing_count": missing_count,
        "current_count": len(sections_status) - stale_count - missing_count,
    }, indent=2))


# ── Subcommand: list-sections ──────────────────────────────────────────────

def cmd_list_sections(args):
    """Return the list of doc sections with their status."""
    root = get_main_repo_root()
    docs_dir = root / DOCS_DIR_NAME
    manifest = _read_manifest(root)

    sections = []
    for section in SECTIONS:
        fp = docs_dir / section["file"]
        exists = fp.exists()
        size = fp.stat().st_size if exists else 0
        in_manifest = any(
            s["name"] == section["name"]
            for s in manifest.get("sections", [])
        )
        sections.append({
            **section,
            "exists": exists,
            "size": size,
            "tracked": in_manifest,
        })

    print(json.dumps({
        "docs_dir": str(docs_dir),
        "docs_exist": docs_dir.is_dir(),
        "sections": sections,
    }, indent=2))


# ── Subcommand: init-manifest ─────────────────────────────────────────────

def cmd_init_manifest(args):
    """Create or update .docs-manifest.json after generation."""
    root = get_main_repo_root()

    # Parse sections-json: [{"name": "...", "file": "...", "source_files": ["path1", ...]}]
    try:
        sections_data = json.loads(args.sections_json)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid sections JSON: {e}"}))
        sys.exit(1)

    manifest_sections = []
    for section in sections_data:
        source_entries = []
        for src_path in section.get("source_files", []):
            fp = root / src_path
            source_entries.append({
                "path": src_path,
                "hash": _hash_file(fp),
            })
        manifest_sections.append({
            "name": section["name"],
            "file": section["file"],
            "source_files": source_entries,
            "generated_at": datetime.now(timezone.utc).isoformat()
                .replace("+00:00", "Z"),
        })

    # Visual richness tier
    vr = getattr(args, "visual_richness", None)
    if vr is None or vr not in VISUAL_RICHNESS_LEVELS:
        vr = VISUAL_RICHNESS_DEFAULT

    manifest = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat()
            .replace("+00:00", "Z"),
        "visual_richness": vr,
        "sections": manifest_sections,
    }

    _write_manifest(root, manifest)
    print(json.dumps({
        "success": True,
        "sections_count": len(manifest_sections),
        "visual_richness": vr,
    }))


# ── Subcommand: clean ──────────────────────────────────────────────────────

def cmd_clean(args):
    """Remove all generated documentation files tracked in the manifest."""
    root = get_main_repo_root()
    docs_dir = root / DOCS_DIR_NAME
    manifest = _read_manifest(root)

    deleted = []

    if manifest:
        # Delete only tracked files
        for section in manifest.get("sections", []):
            fp = docs_dir / section["file"]
            if fp.exists():
                fp.unlink()
                deleted.append(section["file"])
        # Delete manifest itself
        manifest_fp = docs_dir / MANIFEST_NAME
        if manifest_fp.exists():
            manifest_fp.unlink()
            deleted.append(MANIFEST_NAME)
    else:
        # No manifest: delete all known section files
        for section in SECTIONS:
            fp = docs_dir / section["file"]
            if fp.exists():
                fp.unlink()
                deleted.append(section["file"])

    # Remove docs dir if empty
    if docs_dir.is_dir() and not any(docs_dir.iterdir()):
        docs_dir.rmdir()
        deleted.append(DOCS_DIR_NAME + "/")

    print(json.dumps({
        "success": True,
        "deleted": deleted,
        "count": len(deleted),
    }, indent=2))


# ── Subcommand: get-visual-richness ────────────────────────────────────────

def cmd_get_visual_richness(args):
    """Return the visual richness tier stored in the docs manifest."""
    root = get_main_repo_root()
    manifest = _read_manifest(root)

    if not manifest:
        print(json.dumps({
            "visual_richness": VISUAL_RICHNESS_DEFAULT,
            "source": "default",
            "message": "No manifest found. Using default tier.",
        }))
        return

    vr = manifest.get("visual_richness", VISUAL_RICHNESS_DEFAULT)
    if vr not in VISUAL_RICHNESS_LEVELS:
        vr = VISUAL_RICHNESS_DEFAULT

    print(json.dumps({
        "visual_richness": vr,
        "source": "manifest",
    }))


# ── Subcommand: detect-site-generator ──────────────────────────────────────

SITE_GENERATORS = [
    {"name": "MkDocs", "config": "mkdocs.yml",
     "build": "mkdocs build", "serve": "mkdocs serve",
     "ecosystem": "python"},
    {"name": "Docusaurus", "config": "docusaurus.config.js",
     "build": "npm run build", "serve": "npm run start",
     "ecosystem": "node"},
    {"name": "Docusaurus", "config": "docusaurus.config.ts",
     "build": "npm run build", "serve": "npm run start",
     "ecosystem": "node"},
    {"name": "VitePress", "config": ".vitepress/config.ts",
     "build": "npx vitepress build docs", "serve": "npx vitepress dev docs",
     "ecosystem": "node"},
    {"name": "VitePress", "config": ".vitepress/config.js",
     "build": "npx vitepress build docs", "serve": "npx vitepress dev docs",
     "ecosystem": "node"},
    {"name": "Jekyll", "config": "_config.yml",
     "build": "bundle exec jekyll build", "serve": "bundle exec jekyll serve",
     "ecosystem": "ruby"},
    {"name": "mdBook", "config": "book.toml",
     "build": "mdbook build", "serve": "mdbook serve",
     "ecosystem": "rust"},
    {"name": "Sphinx", "config": "conf.py",
     "build": "make html", "serve": "python -m http.server -d _build/html",
     "ecosystem": "python"},
]

RECOMMENDATIONS = {
    "node": {"name": "VitePress", "install": "npm add -D vitepress",
             "reason": "Native Markdown + Mermaid support, fast, Node ecosystem"},
    "python": {"name": "MkDocs Material", "install": "pip install mkdocs-material",
               "reason": "Rich Markdown + Mermaid support, Python ecosystem"},
    "rust": {"name": "mdBook", "install": "cargo install mdbook",
             "reason": "Lightweight, Rust ecosystem native"},
    "default": {"name": "MkDocs Material", "install": "pip install mkdocs-material",
                "reason": "Universal Markdown support, Mermaid, search, rich theming"},
}


def cmd_detect_site_generator(args):
    """Check for static site generators and return recommendations."""
    root = get_main_repo_root()

    detected = None
    for gen in SITE_GENERATORS:
        config_path = root / gen["config"]
        if config_path.exists():
            detected = {
                "name": gen["name"],
                "config_file": gen["config"],
                "build_command": gen["build"],
                "serve_command": gen["serve"],
            }
            break

    # Determine ecosystem for recommendations
    languages = detect_languages(root)
    primary_eco = "default"
    if languages:
        top_lang = next(iter(languages))
        eco_map = {
            "JavaScript": "node", "TypeScript": "node",
            "Python": "python", "Rust": "rust",
        }
        primary_eco = eco_map.get(top_lang, "default")

    rec = RECOMMENDATIONS.get(primary_eco, RECOMMENDATIONS["default"])

    print(json.dumps({
        "detected": detected,
        "has_generator": detected is not None,
        "recommended": rec,
        "primary_ecosystem": primary_eco,
    }, indent=2))


# ── Subcommand: diff-since-tag ─────────────────────────────────────────────

def cmd_diff_since_tag(args):
    """Return changed files since a given git tag."""
    root = get_main_repo_root()
    tag = args.tag

    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{tag}..HEAD"],
            capture_output=True, text=True, check=True, cwd=root,
        )
        changed_files = [f for f in result.stdout.strip().splitlines() if f]
    except subprocess.CalledProcessError:
        changed_files = []

    # Cross-reference with manifest to find affected sections
    manifest = _read_manifest(root)
    affected_sections = set()
    if manifest:
        for section in manifest.get("sections", []):
            tracked_paths = {s["path"] for s in section.get("source_files", [])}
            if tracked_paths & set(changed_files):
                affected_sections.add(section["name"])

    print(json.dumps({
        "tag": tag,
        "changed_files": changed_files,
        "changed_count": len(changed_files),
        "affected_sections": sorted(affected_sections),
    }, indent=2))


# ── Subcommand: semantic-discover ──────────────────────────────────────────

# Section topic keywords used as semantic queries
SECTION_TOPICS = {
    "architecture": "system architecture component design patterns middleware routing",
    "getting-started": "installation setup prerequisites quickstart first run",
    "configuration": "configuration environment variables config files feature flags settings",
    "api-reference": "API endpoints routes controllers handlers functions CLI commands",
    "deployment": "deployment CI CD Docker build pipeline infrastructure production",
    "development": "development contributing testing local dev branch strategy linting",
    "troubleshooting": "error handling logging debugging troubleshooting health check FAQ",
}


def cmd_semantic_discover(args):
    """Use vector memory semantic search to find cross-cutting source files.

    For a given documentation section, performs a semantic search with the
    section topic as the query and returns related source files that are
    not already in the section's tracked source list. This discovers
    cross-cutting concerns (logging, error handling, middleware, utilities)
    that don't fit neatly into a single role classification but are
    essential to the documentation.
    """
    root = get_main_repo_root()
    section = args.section
    top_k = min(args.top_k, 100)  # Cap to prevent excessive vector queries

    # Get existing tracked source files from the manifest
    manifest = _read_manifest(root)
    existing_sources: set[str] = set()
    if manifest:
        for sec in manifest.get("sections", []):
            if sec["name"] == section:
                existing_sources = {
                    s["path"] for s in sec.get("source_files", [])
                }
                break

    # Also accept explicit exclude list (must be a JSON array of strings)
    if args.exclude:
        try:
            exclude_list = json.loads(args.exclude)
            if isinstance(exclude_list, list):
                existing_sources.update(
                    str(p) for p in exclude_list if isinstance(p, str)
                )
        except (json.JSONDecodeError, TypeError):
            pass

    # Determine the semantic query for this section
    topic = args.topic if args.topic else SECTION_TOPICS.get(section, section)

    # Call vector_memory.py search with JSON output
    vm_script = Path(__file__).resolve().parent / "vector_memory.py"
    try:
        result = subprocess.run(
            [
                sys.executable, str(vm_script), "search", topic,
                "--root", str(root),
                "--top-k", str(top_k * 2),  # Fetch extra to filter
                "--json",
            ],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            print(json.dumps({
                "section": section,
                "topic": topic,
                "discovered_files": [],
                "error": result.stderr.strip() or "Search failed",
            }))
            return
    except (subprocess.TimeoutExpired, OSError) as e:
        print(json.dumps({
            "section": section,
            "topic": topic,
            "discovered_files": [],
            "error": str(e),
        }))
        return

    # Parse search results
    try:
        search_results = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(json.dumps({
            "section": section,
            "topic": topic,
            "discovered_files": [],
            "error": "Failed to parse search results",
        }))
        return

    # Collect unique file paths not already tracked, preserving relevance order
    discovered: list[dict] = []
    seen_paths: set[str] = set()
    for hit in search_results:
        fp = hit.get("file_path", "")
        if not fp or fp in existing_sources or fp in seen_paths:
            continue
        # Skip documentation files themselves to avoid circular references
        if fp.startswith("docs/") and fp.endswith(".md"):
            continue
        seen_paths.add(fp)
        discovered.append({
            "path": fp,
            "score": hit.get("score", 0.0),
            "chunk_type": hit.get("chunk_type", ""),
            "name": hit.get("name", ""),
        })
        if len(discovered) >= top_k:
            break

    print(json.dumps({
        "section": section,
        "topic": topic,
        "discovered_files": discovered,
        "count": len(discovered),
        "existing_source_count": len(existing_sources),
    }, indent=2))


# ── Subcommand: reindex-docs ───────────────────────────────────────────────

def cmd_reindex_docs(args):
    """Trigger incremental re-index of the docs/ directory.

    After documentation generation or sync, call this to ensure the
    vector index includes the latest documentation content. Uses
    vector_memory.py hook-batch for efficient batch processing.
    """
    root = get_main_repo_root()
    docs_dir = root / DOCS_DIR_NAME

    if not docs_dir.is_dir():
        print(json.dumps({
            "success": False,
            "error": "No docs/ directory found",
            "indexed_files": [],
        }))
        return

    # Collect all markdown files in docs/
    doc_files: list[str] = []
    for md_file in sorted(docs_dir.glob("*.md")):
        doc_files.append(str(md_file))

    if not doc_files:
        print(json.dumps({
            "success": True,
            "indexed_files": [],
            "message": "No documentation files to index",
        }))
        return

    # Call vector_memory.py hook-batch
    vm_script = Path(__file__).resolve().parent / "vector_memory.py"
    try:
        result = subprocess.run(
            [sys.executable, str(vm_script), "hook-batch"] + doc_files,
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            print(json.dumps({
                "success": False,
                "error": result.stderr.strip() or "Re-index failed",
                "indexed_files": [
                    os.path.basename(f) for f in doc_files
                ],
            }))
            return
    except (subprocess.TimeoutExpired, OSError) as e:
        print(json.dumps({
            "success": False,
            "error": str(e),
            "indexed_files": [],
        }))
        return

    # Parse batch result
    batch_result = {}
    try:
        batch_result = json.loads(result.stdout)
    except json.JSONDecodeError:
        pass

    print(json.dumps({
        "success": True,
        "indexed_files": [os.path.basename(f) for f in doc_files],
        "count": len(doc_files),
        "batch_result": batch_result,
    }, indent=2))


# ── Subcommand: semantic-staleness ─────────────────────────────────────────

def cmd_semantic_staleness(args):
    """Supplement hash-based staleness with semantic similarity.

    For each changed file, perform a semantic search against existing
    documentation sections to detect if a utility/cross-cutting change
    affects a section even if the file is not in that section's tracked
    source list.
    """
    root = get_main_repo_root()
    manifest = _read_manifest(root)

    if not manifest:
        print(json.dumps({
            "has_manifest": False,
            "affected_sections": [],
            "message": "No manifest found.",
        }))
        return

    # Parse changed files list (must be a JSON array of strings)
    try:
        changed_files = json.loads(args.changed_files)
    except json.JSONDecodeError:
        print(json.dumps({
            "error": "Invalid changed_files JSON",
            "affected_sections": [],
        }))
        return

    if not isinstance(changed_files, list):
        print(json.dumps({
            "error": "changed_files must be a JSON array",
            "affected_sections": [],
        }))
        return

    if not changed_files:
        print(json.dumps({
            "affected_sections": [],
            "message": "No changed files provided",
        }))
        return

    # For each changed file, read its content and search for semantic
    # similarity against doc sections
    vm_script = Path(__file__).resolve().parent / "vector_memory.py"
    affected_sections: dict[str, list[str]] = {}

    for changed_file in changed_files:
        if not isinstance(changed_file, str):
            continue
        # Validate path stays within project root (prevent traversal)
        fp = (root / changed_file).resolve()
        try:
            fp.relative_to(root)
        except ValueError:
            continue  # Path escapes project root
        if not fp.exists():
            continue

        # Read first 500 chars of the file to build a semantic query
        try:
            content = fp.read_text(encoding="utf-8", errors="replace")[:500]
        except OSError:
            continue

        # Use file name and content snippet as query
        query = f"{changed_file} {content}"

        try:
            result = subprocess.run(
                [
                    sys.executable, str(vm_script), "search", query,
                    "--root", str(root),
                    "--top-k", "5",
                    "--file-filter", "docs/",
                    "--json",
                ],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                continue
        except (subprocess.TimeoutExpired, OSError):
            continue

        try:
            hits = json.loads(result.stdout)
        except json.JSONDecodeError:
            continue

        # Map doc file hits back to section names
        for hit in hits:
            hit_path = hit.get("file_path", "")
            if not hit_path.startswith("docs/"):
                continue
            # Find matching section
            for sec_info in SECTIONS:
                if hit_path == f"docs/{sec_info['file']}":
                    sec_name = sec_info["name"]
                    if sec_name not in affected_sections:
                        affected_sections[sec_name] = []
                    if changed_file not in affected_sections[sec_name]:
                        affected_sections[sec_name].append(changed_file)
                    break

    print(json.dumps({
        "affected_sections": [
            {"name": name, "related_changes": files}
            for name, files in sorted(affected_sections.items())
        ],
        "count": len(affected_sections),
    }, indent=2))


# ── CLI ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="CodeClaw Documentation Manager",
    )
    sub = parser.add_subparsers(dest="command")

    # discover
    sub.add_parser("discover", help="Scan codebase and return structured data")

    # check-staleness
    sub.add_parser("check-staleness",
                   help="Compare source hashes against manifest")

    # list-sections
    sub.add_parser("list-sections", help="List doc sections with status")

    # init-manifest
    p = sub.add_parser("init-manifest",
                       help="Create/update .docs-manifest.json")
    p.add_argument("--sections-json", required=True,
                   help="JSON array of section data")
    p.add_argument("--visual-richness", default=VISUAL_RICHNESS_DEFAULT,
                   choices=VISUAL_RICHNESS_LEVELS,
                   help="Visual richness tier (default: tiny)")

    # clean
    sub.add_parser("clean", help="Remove all generated doc files")

    # get-visual-richness
    sub.add_parser("get-visual-richness",
                   help="Return the visual richness tier from manifest")

    # detect-site-generator
    sub.add_parser("detect-site-generator",
                   help="Check for static site generators")

    # diff-since-tag
    p = sub.add_parser("diff-since-tag",
                       help="Return changed files since a git tag")
    p.add_argument("--tag", required=True, help="Git tag to diff from")

    # semantic-discover
    p = sub.add_parser("semantic-discover",
                       help="Find cross-cutting source files via semantic search")
    p.add_argument("--section", required=True,
                   help="Documentation section name")
    p.add_argument("--topic", default="",
                   help="Custom search topic (default: section keywords)")
    p.add_argument("--top-k", type=int, default=10,
                   help="Max files to return (default: 10)")
    p.add_argument("--exclude", default="",
                   help="JSON array of file paths to exclude")

    # reindex-docs
    sub.add_parser("reindex-docs",
                   help="Re-index docs/ directory into vector memory")

    # semantic-staleness
    p = sub.add_parser("semantic-staleness",
                       help="Semantic similarity check for staleness detection")
    p.add_argument("--changed-files", required=True,
                   help="JSON array of changed file paths")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmd_map = {
        "discover": cmd_discover,
        "check-staleness": cmd_check_staleness,
        "list-sections": cmd_list_sections,
        "init-manifest": cmd_init_manifest,
        "clean": cmd_clean,
        "get-visual-richness": cmd_get_visual_richness,
        "detect-site-generator": cmd_detect_site_generator,
        "diff-since-tag": cmd_diff_since_tag,
        "semantic-discover": cmd_semantic_discover,
        "reindex-docs": cmd_reindex_docs,
        "semantic-staleness": cmd_semantic_staleness,
    }

    cmd_map[args.command](args)


if __name__ == "__main__":
    main()
