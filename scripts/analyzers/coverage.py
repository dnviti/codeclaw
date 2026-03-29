"""Persistent test-coverage tracking and regression detection.

Maintains JSON coverage manifests that map source files to their test
counterparts and track file hashes so regressions (source changed but
test did not) are surfaced automatically.  Follows the same staleness-
manifest pattern used by ``docs_manager.py``.

Zero external dependencies -- stdlib only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from . import (
    load_gitignore_patterns,
    read_file_safe,
    walk_source_files,
)
from .quality import SOURCE_EXTS, TEST_FILE_PATTERNS, FUNCTION_PATTERNS

# ── Constants ────────────────────────────────────────────────────────────────

COVERAGE_DIR_NAME = ".claude/coverage"
MANIFEST_NAME = "coverage-manifest.json"

TEST_RE = re.compile("|".join(TEST_FILE_PATTERNS), re.IGNORECASE)
FUNC_RE = re.compile("|".join(FUNCTION_PATTERNS), re.MULTILINE)

# Default minimum coverage threshold (percentage of files with tests)
DEFAULT_THRESHOLD = 0.0


# ── Helpers ──────────────────────────────────────────────────────────────────

def _hash_file(path: Path) -> str:
    """Compute SHA-256 of a file, returning '' on error."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def _is_test_file(rel_path: str) -> bool:
    return bool(TEST_RE.search(rel_path))


def _find_matching_test(source_rel: str, test_files: list[str]) -> str | None:
    """Find a test file that corresponds to *source_rel*."""
    src = Path(source_rel)
    stem = src.stem
    ext = src.suffix
    candidates = {
        f"test_{stem}{ext}",
        f"{stem}_test{ext}",
        f"{stem}.test{ext}",
        f"{stem}.spec{ext}",
    }
    for tf in test_files:
        tf_name = Path(tf).name
        if tf_name in candidates:
            return tf
        if f"__tests__/{src.name}" in tf:
            return tf
        if f"tests/{src.name}" in tf or f"test/{src.name}" in tf:
            return tf
    return None


def _ensure_coverage_dir(root: Path) -> Path:
    """Create .claude/coverage/ if it does not exist and return its path."""
    d = root / COVERAGE_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ── Manifest I/O ─────────────────────────────────────────────────────────────

def read_manifest(root: Path) -> dict:
    """Read the current coverage manifest, or return empty dict."""
    fp = root / COVERAGE_DIR_NAME / MANIFEST_NAME
    if not fp.exists():
        return {}
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def write_manifest(root: Path, manifest: dict) -> None:
    """Write the coverage manifest to .claude/coverage/."""
    d = _ensure_coverage_dir(root)
    fp = d / MANIFEST_NAME
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


# ── Core: snapshot ────────────────────────────────────────────────────────────

def take_snapshot(root: Path) -> dict:
    """Capture the current coverage state of the project.

    Returns a manifest dict with per-file entries containing:
    - source_hash, test_file, test_hash, functions, lines
    """
    root = root.resolve()
    gitignore = load_gitignore_patterns(root)

    test_files: list[str] = []
    source_files: list[str] = []

    for rel, fpath, ext, _size in walk_source_files(root, gitignore):
        if ext not in SOURCE_EXTS:
            continue
        if _is_test_file(rel):
            test_files.append(rel)
        else:
            source_files.append(rel)

    entries: list[dict] = []
    covered_count = 0

    for sf in source_files:
        sf_path = root / sf
        content = read_file_safe(sf_path)
        funcs = len(FUNC_RE.findall(content)) if content else 0
        lines = len(content.splitlines()) if content else 0
        source_hash = _hash_file(sf_path)

        matching = _find_matching_test(sf, test_files)
        test_hash = ""
        if matching:
            test_hash = _hash_file(root / matching)
            covered_count += 1

        entries.append({
            "source_file": sf,
            "source_hash": source_hash,
            "test_file": matching or "",
            "test_hash": test_hash,
            "functions": funcs,
            "lines": lines,
        })

    coverage_pct = round(covered_count / max(len(source_files), 1) * 100, 1)

    manifest = {
        "version": "1.0",
        "timestamp": _now_iso(),
        "root": str(root),
        "summary": {
            "total_source_files": len(source_files),
            "total_test_files": len(test_files),
            "covered_files": covered_count,
            "uncovered_files": len(source_files) - covered_count,
            "coverage_pct": coverage_pct,
        },
        "files": entries,
    }

    # Persist manifest
    write_manifest(root, manifest)

    # Also write timestamped snapshot for trend analysis
    _save_timestamped_snapshot(root, manifest)

    return manifest


def _save_timestamped_snapshot(root: Path, manifest: dict) -> None:
    """Write a copy with a timestamp name for historical tracking."""
    d = _ensure_coverage_dir(root)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    fp = d / f"snapshot-{ts}.json"
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


# ── Core: compare ─────────────────────────────────────────────────────────────

def compare_snapshots(old: dict, new: dict) -> dict:
    """Compare two snapshots and detect regressions.

    A regression is a source file whose hash changed while its
    corresponding test file hash did NOT change (or test is missing).
    """
    old_map: dict[str, dict] = {e["source_file"]: e for e in old.get("files", [])}
    new_map: dict[str, dict] = {e["source_file"]: e for e in new.get("files", [])}

    regressions: list[dict] = []
    improvements: list[dict] = []
    new_files: list[dict] = []
    removed_files: list[str] = []

    for sf, new_entry in new_map.items():
        old_entry = old_map.get(sf)
        if old_entry is None:
            new_files.append({"source_file": sf, "has_test": bool(new_entry["test_file"])})
            continue

        source_changed = new_entry["source_hash"] != old_entry["source_hash"]
        test_changed = new_entry["test_hash"] != old_entry["test_hash"]
        had_test = bool(old_entry["test_file"])
        has_test = bool(new_entry["test_file"])

        if source_changed and not test_changed and had_test:
            regressions.append({
                "source_file": sf,
                "test_file": new_entry["test_file"],
                "reason": "source changed but test unchanged",
            })
        elif source_changed and not has_test:
            regressions.append({
                "source_file": sf,
                "test_file": "",
                "reason": "source changed, no test file",
            })
        elif not had_test and has_test:
            improvements.append({
                "source_file": sf,
                "test_file": new_entry["test_file"],
            })

    for sf in old_map:
        if sf not in new_map:
            removed_files.append(sf)

    old_pct = old.get("summary", {}).get("coverage_pct", 0)
    new_pct = new.get("summary", {}).get("coverage_pct", 0)

    return {
        "old_timestamp": old.get("timestamp", "unknown"),
        "new_timestamp": new.get("timestamp", "unknown"),
        "coverage_change": round(new_pct - old_pct, 1),
        "old_coverage_pct": old_pct,
        "new_coverage_pct": new_pct,
        "regressions": regressions,
        "regression_count": len(regressions),
        "improvements": improvements,
        "improvement_count": len(improvements),
        "new_files": new_files,
        "removed_files": removed_files,
    }


# ── Core: report ──────────────────────────────────────────────────────────────

def generate_report(manifest: dict) -> str:
    """Generate a human-readable Markdown coverage report from a manifest.

    If the manifest contains a ``semantic_risks`` section (populated by
    heuristic semantic gap analysis), it is included as an additional section
    in the report highlighting high-risk untested code paths discovered via
    local code-pattern matching.
    """
    lines: list[str] = []
    summary = manifest.get("summary", {})
    ts = manifest.get("timestamp", "unknown")

    lines.append("# Test Coverage Report\n")
    lines.append(f"> Snapshot taken: {ts}\n")

    lines.append("## Summary\n")
    lines.append(f"- **Source files:** {summary.get('total_source_files', 0)}")
    lines.append(f"- **Test files:** {summary.get('total_test_files', 0)}")
    lines.append(f"- **Covered:** {summary.get('covered_files', 0)}")
    lines.append(f"- **Uncovered:** {summary.get('uncovered_files', 0)}")
    lines.append(f"- **Coverage:** {summary.get('coverage_pct', 0)}%")
    lines.append("")

    # Uncovered files table
    files = manifest.get("files", [])
    uncovered = [f for f in files if not f.get("test_file")]
    if uncovered:
        # Sort by functions descending (highest complexity first)
        uncovered.sort(key=lambda x: -(x.get("functions", 0) * x.get("lines", 0)))
        lines.append("## Uncovered Files\n")
        lines.append("| File | Lines | Functions |")
        lines.append("| --- | --- | --- |")
        for entry in uncovered[:30]:
            lines.append(
                f"| {entry['source_file']} "
                f"| {entry.get('lines', 0)} "
                f"| {entry.get('functions', 0)} |"
            )
        lines.append("")

    # Semantic risks section (from heuristic semantic gap analysis)
    semantic_risks = manifest.get("semantic_risks", [])
    if semantic_risks:
        lines.append("## Semantic Risk Analysis\n")
        lines.append(
            "> High-risk untested code paths discovered via local semantic heuristics. "
            "These are source code sections matching critical patterns "
            "(validation, auth, error handling, etc.) that have no "
            "corresponding test file.\n"
        )
        lines.append("| File | Symbol | Category | Lines |")
        lines.append("| --- | --- | --- | --- |")
        for risk in semantic_risks[:30]:
            lines.append(
                f"| {risk.get('file_path', '')} "
                f"| {risk.get('name', '')} "
                f"| {risk.get('category', '')} "
                f"| {risk.get('start_line', 0)}-{risk.get('end_line', 0)} |"
            )
        lines.append("")

        # Category summary
        categories: dict[str, int] = {}
        for risk in semantic_risks:
            cat = risk.get("category", "other")
            categories[cat] = categories.get(cat, 0) + 1
        if categories:
            lines.append("### Risk Categories\n")
            for cat, count in sorted(categories.items(),
                                     key=lambda x: -x[1]):
                lines.append(f"- **{cat}:** {count} untested path(s)")
            lines.append("")

    # Covered files table
    covered = [f for f in files if f.get("test_file")]
    if covered:
        lines.append("## Covered Files\n")
        lines.append("| Source File | Test File |")
        lines.append("| --- | --- |")
        for entry in covered[:30]:
            lines.append(f"| {entry['source_file']} | {entry['test_file']} |")
        lines.append("")

    return "\n".join(lines)


# ── Core: threshold-check ─────────────────────────────────────────────────────

def check_threshold(manifest: dict, min_coverage: float = DEFAULT_THRESHOLD) -> dict:
    """Check whether coverage meets a minimum threshold.

    Returns a dict with pass/fail and details.
    """
    summary = manifest.get("summary", {})
    actual = summary.get("coverage_pct", 0.0)
    passed = actual >= min_coverage

    return {
        "passed": passed,
        "actual_coverage_pct": actual,
        "required_coverage_pct": min_coverage,
        "covered_files": summary.get("covered_files", 0),
        "total_source_files": summary.get("total_source_files", 0),
        "deficit": round(max(min_coverage - actual, 0), 1),
    }


# ── Snapshot listing (for compare) ───────────────────────────────────────────

def list_snapshots(root: Path) -> list[dict]:
    """Return available timestamped snapshots sorted newest-first."""
    d = root / COVERAGE_DIR_NAME
    if not d.is_dir():
        return []
    snapshots = []
    for fp in sorted(d.glob("snapshot-*.json"), reverse=True):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            snapshots.append({
                "file": fp.name,
                "timestamp": data.get("timestamp", ""),
                "coverage_pct": data.get("summary", {}).get("coverage_pct", 0),
            })
        except (json.JSONDecodeError, OSError):
            continue
    return snapshots


def load_snapshot(root: Path, filename: str) -> dict:
    """Load a specific snapshot by filename."""
    fp = root / COVERAGE_DIR_NAME / filename
    if not fp.exists():
        return {}
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
