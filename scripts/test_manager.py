#!/usr/bin/env python3
"""Test manager for the CodeClaw /tests skill.

Provides test discovery, gap analysis, suggestion, execution,
persistent coverage tracking with regression detection, heuristic
semantic gap analysis, and test pattern discovery.
All output is JSON. Zero external dependencies — stdlib only.

Usage:
    python3 test_manager.py discover --root /path/to/project
    python3 test_manager.py analyze-gaps --root /path/to/project [--target file]
    python3 test_manager.py suggest --root /path/to/project
    python3 test_manager.py run --root /path/to/project [--target file]
    python3 test_manager.py semantic-gaps --root /path/to/project
    python3 test_manager.py similar-tests --root /path/to/project --target file
    python3 test_manager.py coverage snapshot --root /path/to/project
    python3 test_manager.py coverage compare --root /path/to/project [--old FILE --new FILE]
    python3 test_manager.py coverage report --root /path/to/project
    python3 test_manager.py coverage threshold-check --root /path/to/project [--min-coverage N]
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Add parent directory to path so analyzers package can be found
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from analyzers import (
    load_gitignore_patterns,
    walk_source_files,
    read_file_safe,
    classify_file_role,
)
from analyzers.quality import (
    SOURCE_EXTS,
    TEST_FILE_PATTERNS,
    FUNCTION_PATTERNS,
    analyze_test_coverage,
)
from analyzers.coverage import (
    take_snapshot,
    compare_snapshots,
    generate_report as generate_coverage_report,
    check_threshold,
    list_snapshots,
    load_snapshot,
    read_manifest as read_coverage_manifest,
)
from common import load_config, output_json

# ── Constants ───────────────────────────────────────────────────────────────

TEST_EXECUTION_TIMEOUT_SECONDS = 300
MAX_STDOUT_TAIL_CHARS = 5000
MAX_STDERR_TAIL_CHARS = 2000

TEST_RE = re.compile("|".join(TEST_FILE_PATTERNS), re.IGNORECASE)
FUNC_RE = re.compile("|".join(FUNCTION_PATTERNS), re.MULTILINE)

# ── Helpers ─────────────────────────────────────────────────────────────────

def get_test_config(root: Path) -> dict:
    """Read test configuration from project config."""
    cfg = load_config(root)
    return {
        "framework": cfg.get("test_framework", ""),
        "command": cfg.get("test_command", ""),
        "file_pattern": cfg.get("test_file_pattern", ""),
    }


def is_test_file(rel_path: str) -> bool:
    """Check if a relative path matches test file patterns."""
    return bool(TEST_RE.search(rel_path))


def find_matching_test(source_rel: str, test_files: list[str]) -> str | None:
    """Find a test file that corresponds to a source file.

    Matches by stem name with common test conventions:
      foo.py -> test_foo.py, foo_test.py, foo.test.py, foo.spec.py
      foo.ts -> foo.test.ts, foo.spec.ts, __tests__/foo.ts
    """
    source_path = Path(source_rel)
    stem = source_path.stem
    ext = source_path.suffix

    # Possible test file name patterns
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
        # Also check if test file is in __tests__/ with same name
        if f"__tests__/{source_path.name}" in tf:
            return tf
        # Check if test file is in tests/ directory with same name
        if f"tests/{source_path.name}" in tf or f"test/{source_path.name}" in tf:
            return tf

    return None


def find_matching_source(test_rel: str, source_files: list[str]) -> str | None:
    """Find the source file that a test file corresponds to."""
    test_path = Path(test_rel)
    name = test_path.stem

    # Strip test prefixes/suffixes
    clean = name
    for pattern in [r"^test_", r"_test$", r"\.test$", r"\.spec$"]:
        clean = re.sub(pattern, "", clean)

    if not clean:
        return None

    for sf in source_files:
        sf_stem = Path(sf).stem
        if sf_stem == clean:
            return sf

    return None


def count_functions(content: str) -> int:
    """Count function/method definitions in source content."""
    return len(FUNC_RE.findall(content))


# ── Subcommand: discover ────────────────────────────────────────────────────

def cmd_discover(args) -> dict:
    """Find all test files in the project."""
    root = Path(args.root).resolve()
    gitignore = load_gitignore_patterns(root)
    config = get_test_config(root)

    test_files: list[dict] = []
    source_files: list[str] = []

    for rel, fpath, ext, size in walk_source_files(root, gitignore):
        if ext not in SOURCE_EXTS:
            continue
        if is_test_file(rel):
            content = read_file_safe(fpath)
            line_count = len(content.splitlines()) if content else 0
            test_files.append({
                "path": rel,
                "lines": line_count,
                "size": size,
            })
        else:
            source_files.append(rel)

    return {
        "test_config": config,
        "test_files": test_files,
        "test_file_count": len(test_files),
        "source_file_count": len(source_files),
    }


# ── Subcommand: analyze-gaps ───────────────────────────────────────────────

def cmd_analyze_gaps(args) -> dict:
    """Compare source files vs test files to find coverage gaps.

    Returns per-file coverage mapping showing which source files
    have tests and which do not.
    """
    root = Path(args.root).resolve()
    gitignore = load_gitignore_patterns(root)
    target = getattr(args, "target", None)

    test_files: list[str] = []
    source_files: list[str] = []
    source_details: dict[str, dict] = {}

    for rel, fpath, ext, size in walk_source_files(root, gitignore):
        if ext not in SOURCE_EXTS:
            continue
        if is_test_file(rel):
            test_files.append(rel)
        else:
            content = read_file_safe(fpath)
            lines = len(content.splitlines()) if content else 0
            funcs = count_functions(content) if content else 0
            role = classify_file_role(rel)
            source_files.append(rel)
            source_details[rel] = {
                "lines": lines,
                "functions": funcs,
                "role": role,
                "size": size,
            }

    # If target specified, filter to just that file
    if target:
        target_norm = target.replace("\\", "/")
        source_files = [s for s in source_files if target_norm in s]

    # Build per-file coverage map
    covered: list[dict] = []
    uncovered: list[dict] = []

    for sf in source_files:
        matching_test = find_matching_test(sf, test_files)
        detail = source_details.get(sf, {})
        entry = {
            "source_file": sf,
            "lines": detail.get("lines", 0),
            "functions": detail.get("functions", 0),
            "role": detail.get("role", "other"),
        }
        if matching_test:
            entry["test_file"] = matching_test
            covered.append(entry)
        else:
            uncovered.append(entry)

    # Sort uncovered by complexity (functions * lines)
    uncovered.sort(key=lambda x: -(x["functions"] * x["lines"]))

    # Also use the existing directory-level analysis
    dir_coverage = analyze_test_coverage(root, gitignore)

    return {
        "total_source_files": len(source_files),
        "covered_files": len(covered),
        "uncovered_files": len(uncovered),
        "coverage_pct": round(len(covered) / max(len(source_files), 1) * 100, 1),
        "covered": covered,
        "uncovered": uncovered,
        "by_directory": dir_coverage.get("by_directory", {}),
        "frameworks": dir_coverage.get("frameworks", []),
    }


# ── Subcommand: suggest ────────────────────────────────────────────────────

def cmd_suggest(args) -> dict:
    """Recommend test targets based on complexity, role, and missing coverage."""
    root = Path(args.root).resolve()
    gitignore = load_gitignore_patterns(root)

    test_files: list[str] = []
    source_files: list[str] = []
    source_details: dict[str, dict] = {}

    for rel, fpath, ext, size in walk_source_files(root, gitignore):
        if ext not in SOURCE_EXTS:
            continue
        if is_test_file(rel):
            test_files.append(rel)
        else:
            content = read_file_safe(fpath)
            lines = len(content.splitlines()) if content else 0
            funcs = count_functions(content) if content else 0
            role = classify_file_role(rel)
            source_files.append(rel)
            source_details[rel] = {
                "lines": lines,
                "functions": funcs,
                "role": role,
            }

    # Find recently changed files via git
    recent_changes: list[str] = []
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--name-only", "-20"],
            capture_output=True, text=True, check=True,
            cwd=str(root),
        )
        for line in result.stdout.splitlines():
            line = line.strip()
            if line and not line[0].isdigit() and not line.startswith("*"):
                # It's a file path
                if any(line.endswith(e) for e in SOURCE_EXTS):
                    if not is_test_file(line):
                        recent_changes.append(line)
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    recent_set = set(recent_changes)

    # Score each uncovered source file
    suggestions: list[dict] = []

    for sf in source_files:
        if find_matching_test(sf, test_files):
            continue  # already has tests

        detail = source_details.get(sf, {})
        funcs = detail.get("functions", 0)
        lines = detail.get("lines", 0)
        role = detail.get("role", "other")

        # Score: higher = more important to test
        score = 0
        reasons: list[str] = []

        # Complexity score
        if funcs > 10:
            score += 30
            reasons.append(f"high complexity ({funcs} functions)")
        elif funcs > 5:
            score += 20
            reasons.append(f"moderate complexity ({funcs} functions)")
        elif funcs > 0:
            score += 10

        # Size score
        if lines > 200:
            score += 20
            reasons.append(f"large file ({lines} lines)")
        elif lines > 100:
            score += 10

        # Role score: services and controllers are critical
        role_scores = {
            "service": 25, "controller": 25, "handler": 20,
            "route": 15, "utility": 15, "middleware": 15,
            "model": 10, "store": 10, "hook": 10,
        }
        role_bonus = role_scores.get(role, 0)
        if role_bonus:
            score += role_bonus
            reasons.append(f"critical role ({role})")

        # Recently changed bonus
        if sf in recent_set:
            score += 20
            reasons.append("recently modified")

        if score > 0 and funcs > 0:
            suggestions.append({
                "file": sf,
                "score": score,
                "functions": funcs,
                "lines": lines,
                "role": role,
                "recently_changed": sf in recent_set,
                "reasons": reasons,
            })

    suggestions.sort(key=lambda x: -x["score"])

    return {
        "suggestions": suggestions[:20],
        "total_uncovered": len(suggestions),
        "recently_changed_without_tests": [
            s for s in suggestions if s["recently_changed"]
        ][:10],
    }


# ── Subcommand: run ─────────────────────────────────────────────────────────

def cmd_run(args) -> dict:
    """Execute tests via the configured test framework."""
    root = Path(args.root).resolve()
    config = get_test_config(root)
    target = getattr(args, "target", None)

    test_command = config.get("command", "")

    if not test_command:
        # Auto-detect test command
        if (root / "package.json").exists():
            content = read_file_safe(root / "package.json")
            if "vitest" in content.lower():
                test_command = "npx vitest run"
            elif "jest" in content.lower():
                test_command = "npx jest"
            elif "mocha" in content.lower():
                test_command = "npx mocha"
        elif (root / "pytest.ini").exists() or (root / "conftest.py").exists():
            test_command = "python3 -m pytest"
        elif (root / "pyproject.toml").exists():
            content = read_file_safe(root / "pyproject.toml")
            if "pytest" in content.lower():
                test_command = "python3 -m pytest"
        elif (root / "Cargo.toml").exists():
            test_command = "cargo test"
        elif (root / "go.mod").exists():
            test_command = "go test ./..."

    if not test_command:
        return {
            "success": False,
            "error": "No test command configured. Set TEST_COMMAND in project-config.json.",
            "output": "",
        }

    # Append target if provided
    cmd = test_command
    if target:
        cmd = f"{cmd} {target}"

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=TEST_EXECUTION_TIMEOUT_SECONDS,
        )
        return {
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "command": cmd,
            "output": result.stdout[-MAX_STDOUT_TAIL_CHARS:] if len(result.stdout) > MAX_STDOUT_TAIL_CHARS else result.stdout,
            "errors": result.stderr[-MAX_STDERR_TAIL_CHARS:] if len(result.stderr) > MAX_STDERR_TAIL_CHARS else result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Test execution timed out after {TEST_EXECUTION_TIMEOUT_SECONDS} seconds.",
            "command": cmd,
            "output": "",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "command": cmd,
            "output": "",
        }


# ── Subcommand: coverage ─────────────────────────────────────────────────────

def cmd_coverage(args) -> dict:
    """Dispatch coverage sub-commands: snapshot, compare, report, threshold-check."""
    root = Path(args.root).resolve()
    sub = args.coverage_command

    if sub == "snapshot":
        return take_snapshot(root)

    elif sub == "compare":
        old_file = getattr(args, "old", None)
        new_file = getattr(args, "new", None)

        if old_file and new_file:
            old_data = load_snapshot(root, old_file)
            new_data = load_snapshot(root, new_file)
        else:
            # Compare current manifest against latest timestamped snapshot
            snapshots = list_snapshots(root)
            if len(snapshots) < 2:
                # Not enough history — take a fresh snapshot and compare
                # against the existing manifest
                current_manifest = read_coverage_manifest(root)
                if not current_manifest:
                    return {
                        "error": "No previous snapshot found. "
                                 "Run 'coverage snapshot' first."
                    }
                new_data = take_snapshot(root)
                old_data = current_manifest
            else:
                new_data = load_snapshot(root, snapshots[0]["file"])
                old_data = load_snapshot(root, snapshots[1]["file"])

        if not old_data or not new_data:
            return {"error": "Could not load one or both snapshots."}

        return compare_snapshots(old_data, new_data)

    elif sub == "report":
        manifest = read_coverage_manifest(root)
        if not manifest:
            return {"error": "No coverage manifest. Run 'coverage snapshot' first."}
        return {"report": generate_coverage_report(manifest)}

    elif sub == "threshold-check":
        min_cov = getattr(args, "min_coverage", 0.0)
        manifest = read_coverage_manifest(root)
        if not manifest:
            # Take a fresh snapshot
            manifest = take_snapshot(root)
        return check_threshold(manifest, min_cov)

    elif sub == "list-snapshots":
        return {"snapshots": list_snapshots(root)}

    else:
        return {"error": f"Unknown coverage sub-command: {sub}"}


# ── Semantic Gap Analysis ────────────────────────────────────────────────────

SEMANTIC_RISK_PATTERNS: list[dict[str, str]] = [
    {"query": "input validation sanitize", "category": "validation"},
    {"query": "authentication authorization login token", "category": "auth"},
    {"query": "error handling exception catch raise", "category": "error_handling"},
    {"query": "payment billing charge transaction", "category": "payment"},
    {"query": "password hash encrypt decrypt secret", "category": "security"},
    {"query": "file upload download write delete", "category": "file_io"},
    {"query": "database query insert update delete SQL", "category": "database"},
    {"query": "rate limit throttle retry backoff", "category": "rate_limiting"},
    {"query": "permission role access control", "category": "access_control"},
    {"query": "parse deserialize decode unmarshal", "category": "parsing"},
]

COMMON_STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "into", "your",
    "using", "use", "code", "file", "files", "test", "tests", "line",
    "project", "source", "target", "data", "value", "values", "create",
    "update", "get", "set", "run", "all", "any", "one", "two", "three",
    "not", "only", "new", "old", "by", "or", "of", "in", "on", "to",
}


def _tokenize_for_similarity(text: str) -> set[str]:
    """Return a lower-cased token set for similarity scoring."""
    tokens = set()
    for raw in re.findall(r"[A-Za-z][A-Za-z0-9_]+", text.lower()):
        token = raw.strip("_")
        if len(token) < 3 or token in COMMON_STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def _path_tokens(rel_path: str) -> set[str]:
    """Tokenize a relative path for path-similarity scoring."""
    tokens = set()
    for part in Path(rel_path).parts:
        if part in {".", ".."}:
            continue
        tokens.update(_tokenize_for_similarity(part))
    return tokens


def _extract_import_tokens(content: str) -> set[str]:
    """Extract import-related tokens from source text."""
    tokens = set()
    for line in content.splitlines():
        s = line.strip()
        if not s:
            continue
        if not any(marker in s for marker in ("import ", "from ", "require(", "using ", "include ")):
            continue
        for raw in re.findall(r"[A-Za-z][A-Za-z0-9_./:-]+", s):
            token = raw.lower().strip("._-/")
            if not token or token in COMMON_STOPWORDS or token in {"import", "from", "require", "using", "include", "export", "const", "let", "var"}:
                continue
            tokens.update(part for part in re.split(r"[./_-]+", token) if part and part not in COMMON_STOPWORDS)
    return tokens


def _extract_symbol_tokens(content: str) -> set[str]:
    """Extract function/class-ish symbol names from source text."""
    tokens = set()
    symbol_patterns = [
        r"^\s*def\s+(\w+)",
        r"^\s*function\s+(\w+)",
        r"^\s*export\s+function\s+(\w+)",
        r"^\s*(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(",
        r"^\s*fn\s+(\w+)",
        r"^\s*func\s+(?:\(.*\)\s*)?(\w+)",
    ]
    for pattern in symbol_patterns:
        for match in re.finditer(pattern, content, re.MULTILINE | re.IGNORECASE):
            tokens.add(match.group(1).lower())
    return tokens


def _jaccard_score(left: set[str], right: set[str]) -> float:
    """Return a basic Jaccard similarity score."""
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    union = len(left | right)
    return overlap / union if union else 0.0


def _test_framework_hints(content: str) -> set[str]:
    """Infer test framework hints from file content."""
    content_lower = content.lower()
    hints = set()
    if "pytest" in content_lower or "@pytest" in content_lower:
        hints.add("pytest")
    if "unittest" in content_lower:
        hints.add("unittest")
    if "expect(" in content_lower or "jest." in content_lower:
        hints.add("jest")
    if "describe(" in content_lower or "it(" in content_lower:
        hints.add("bdd")
    if "vitest" in content_lower:
        hints.add("vitest")
    return hints


def _add_unique(lst: list[str], item: str) -> None:
    """Append item to list only if not already present."""
    if item not in lst:
        lst.append(item)


def _test_pattern_summary(test_content: str) -> dict:
    """Summarize test style conventions from file content."""
    patterns: dict[str, list[str]] = {
        "frameworks": [],
        "assertion_styles": [],
        "mocking_libraries": [],
        "naming_conventions": [],
    }

    if "assert " in test_content:
        _add_unique(patterns["assertion_styles"], "plain assert")
    if "assertEqual" in test_content or "self.assert" in test_content:
        _add_unique(patterns["assertion_styles"], "unittest assert methods")
    if "expect(" in test_content:
        _add_unique(patterns["assertion_styles"], "expect()")
    if "should." in test_content or "should(" in test_content:
        _add_unique(patterns["assertion_styles"], "should-style")

    if "unittest.mock" in test_content or "from mock" in test_content:
        _add_unique(patterns["mocking_libraries"], "unittest.mock")
    if "pytest-mock" in test_content or "mocker" in test_content:
        _add_unique(patterns["mocking_libraries"], "pytest-mock")
    if "jest.mock" in test_content or "jest.fn" in test_content:
        _add_unique(patterns["mocking_libraries"], "jest")
    if "sinon" in test_content:
        _add_unique(patterns["mocking_libraries"], "sinon")
    if "@patch" in test_content:
        _add_unique(patterns["mocking_libraries"], "unittest.mock @patch")

    if "import pytest" in test_content or "@pytest" in test_content:
        _add_unique(patterns["frameworks"], "pytest")
    if "import unittest" in test_content:
        _add_unique(patterns["frameworks"], "unittest")
    if "describe(" in test_content:
        _add_unique(patterns["frameworks"], "describe/it (BDD)")
    if "import { test" in test_content or "import { it" in test_content:
        _add_unique(patterns["frameworks"], "vitest/jest")

    return patterns


def _score_test_candidate(target_rel: str, target_content: str, test_rel: str, test_content: str) -> tuple[float, dict]:
    """Score how similar a test file is to the target source file."""
    target_name_tokens = _tokenize_for_similarity(Path(target_rel).stem)
    test_name_tokens = _tokenize_for_similarity(Path(test_rel).stem)
    target_path_tokens = _path_tokens(target_rel)
    test_path_tokens = _path_tokens(test_rel)
    target_text_tokens = _tokenize_for_similarity(target_content)
    test_text_tokens = _tokenize_for_similarity(test_content)
    target_import_tokens = _extract_import_tokens(target_content)
    test_import_tokens = _extract_import_tokens(test_content)
    target_symbol_tokens = _extract_symbol_tokens(target_content)
    test_symbol_tokens = _extract_symbol_tokens(test_content)

    score = 0.0
    reasons: list[str] = []

    if find_matching_source(test_rel, [target_rel]) is not None:
        score += 6.0
        reasons.append("matching source/test naming")

    stem_similarity = _jaccard_score(target_name_tokens, test_name_tokens)
    if stem_similarity:
        score += stem_similarity * 4.0
        reasons.append("stem overlap")

    path_similarity = _jaccard_score(target_path_tokens, test_path_tokens)
    if path_similarity:
        score += path_similarity * 2.0
        reasons.append("path overlap")

    keyword_similarity = _jaccard_score(target_text_tokens, test_text_tokens)
    if keyword_similarity:
        score += keyword_similarity * 4.0
        reasons.append("keyword overlap")

    import_similarity = _jaccard_score(target_import_tokens, test_import_tokens)
    if import_similarity:
        score += import_similarity * 3.0
        reasons.append("import overlap")

    symbol_similarity = _jaccard_score(target_symbol_tokens, test_symbol_tokens)
    if symbol_similarity:
        score += symbol_similarity * 3.0
        reasons.append("symbol overlap")

    target_frameworks = _test_framework_hints(target_content)
    test_frameworks = _test_framework_hints(test_content)
    if target_frameworks & test_frameworks:
        score += 1.5
        reasons.append("framework overlap")

    if "tests" in Path(test_rel).parts:
        score += 0.5

    return score, {
        "reasons": reasons,
        "frameworks": sorted(test_frameworks),
        "keywords": sorted((target_text_tokens | target_symbol_tokens | target_import_tokens) & (test_text_tokens | test_symbol_tokens | test_import_tokens))[:12],
    }


def semantic_gap_analysis(root: Path) -> dict:
    """Heuristically find high-risk source files that lack test coverage."""
    root = root.resolve()
    gitignore = load_gitignore_patterns(root)

    coverage = analyze_test_coverage(root, gitignore)
    covered_sources = {
        entry["source"]
        for entry in coverage.get("per_file", [])
        if entry.get("has_test")
    }

    source_details: list[dict] = []
    for rel, fpath, ext, size in walk_source_files(root, gitignore):
        if ext not in SOURCE_EXTS or is_test_file(rel):
            continue
        content = read_file_safe(fpath)
        if not content:
            continue
        source_details.append({
            "path": rel,
            "content": content,
            "role": classify_file_role(rel),
            "lines": len(content.splitlines()),
            "size": size,
        })

    risks: list[dict] = []
    categories_found: dict[str, int] = {}

    for source in source_details:
        if source["path"] in covered_sources:
            continue

        text = f"{source['path']}\n{source['content']}".lower()
        text_tokens = _tokenize_for_similarity(text)
        path_tokens = _path_tokens(source["path"])
        content_tokens = _tokenize_for_similarity(source["content"])
        role = source["role"]
        role_boost = 1.0 if role in {"server", "app", "api", "controller", "middleware", "service", "router"} else 0.0

        for pattern_info in SEMANTIC_RISK_PATTERNS:
            query_tokens = _tokenize_for_similarity(pattern_info["query"])
            matched_terms = sorted(query_tokens & (text_tokens | path_tokens | content_tokens))
            if not matched_terms:
                continue

            score = len(matched_terms) + role_boost
            risks.append({
                "file_path": source["path"],
                "category": pattern_info["category"],
                "role": role,
                "matched_terms": matched_terms,
                "line_count": source["lines"],
                "size": source["size"],
                "score": round(score, 2),
                "reason": (
                    f"Uncovered {role or 'source'} file matches "
                    f"{pattern_info['category']} heuristics: {', '.join(matched_terms)}"
                ),
                "content_preview": source["content"][:200],
            })
            categories_found[pattern_info["category"]] = categories_found.get(pattern_info["category"], 0) + 1

    unique_risks: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for risk in sorted(risks, key=lambda r: (-r["score"], r["file_path"], r["category"])):
        key = (risk["file_path"], risk["category"])
        if key in seen:
            continue
        seen.add(key)
        unique_risks.append(risk)

    return {
        "semantic_risks": unique_risks,
        "total_risks": len(unique_risks),
        "categories": categories_found,
        "patterns_searched": len(SEMANTIC_RISK_PATTERNS),
        "heuristic_analysis_available": True,
    }


def find_similar_tests(target_file: str, root: Path) -> dict:
    """Find tests that are heuristically similar to a source file."""
    root = root.resolve()

    target_path = root / target_file
    content = read_file_safe(target_path)
    if not content:
        return {
            "similar_tests": [],
            "patterns": {},
            "error": f"Could not read target file: {target_file}",
        }

    gitignore = load_gitignore_patterns(root)
    test_files: list[dict] = []
    for rel, fpath, ext, _size in walk_source_files(root, gitignore):
        if ext not in SOURCE_EXTS or not is_test_file(rel):
            continue
        test_content = read_file_safe(fpath)
        if not test_content:
            continue
        score, meta = _score_test_candidate(target_file, content, rel, test_content)
        test_files.append({
            "test_file": rel,
            "name": Path(rel).name,
            "score": round(score, 4),
            "content_preview": test_content[:300],
            "frameworks": meta["frameworks"],
            "keywords": meta["keywords"],
        })

    similar_tests = sorted(test_files, key=lambda item: (-item["score"], item["test_file"]))[:10]

    patterns: dict[str, list[str]] = {
        "frameworks": [],
        "assertion_styles": [],
        "mocking_libraries": [],
        "naming_conventions": [],
    }
    for test_info in similar_tests[:5]:
        test_path = root / test_info["test_file"]
        test_content = read_file_safe(test_path)
        if not test_content:
            continue
        summary = _test_pattern_summary(test_content)
        for key in patterns:
            for item in summary[key]:
                _add_unique(patterns[key], item)

    query_used = " ".join(sorted((_tokenize_for_similarity(content) | _path_tokens(target_file)))[:20])
    return {
        "similar_tests": similar_tests,
        "patterns": patterns,
        "target_file": target_file,
        "query_used": query_used,
        "heuristic_similarity_available": True,
    }


# ── Subcommand wrappers for heuristic features ─────────────────────────────

def cmd_semantic_gaps(args) -> dict:
    """CLI wrapper for semantic_gap_analysis."""
    root = Path(args.root).resolve()
    return semantic_gap_analysis(root)


def cmd_similar_tests(args) -> dict:
    """CLI wrapper for find_similar_tests."""
    root = Path(args.root).resolve()
    target = args.target
    if not target:
        return {"error": "No target file specified. Use --target <file>."}
    return find_similar_tests(target, root)


# ── CLI Entrypoint ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Test manager for CodeClaw /tests skill",
    )
    sub = parser.add_subparsers(dest="command")

    # discover
    p_discover = sub.add_parser("discover", help="Find all test files in the project")
    p_discover.add_argument("--root", default=".", help="Project root directory")

    # analyze-gaps
    p_gaps = sub.add_parser("analyze-gaps", help="Compare source vs test coverage per file")
    p_gaps.add_argument("--root", default=".", help="Project root directory")
    p_gaps.add_argument("--target", default=None, help="Filter to a specific source file")

    # suggest
    p_suggest = sub.add_parser("suggest", help="Recommend test targets")
    p_suggest.add_argument("--root", default=".", help="Project root directory")

    # run
    p_run = sub.add_parser("run", help="Execute tests via configured framework")
    p_run.add_argument("--root", default=".", help="Project root directory")
    p_run.add_argument("--target", default=None, help="Specific test file or pattern to run")

    # semantic-gaps
    p_sgaps = sub.add_parser("semantic-gaps",
                             help="Heuristic gap analysis over source and test files")
    p_sgaps.add_argument("--root", default=".", help="Project root directory")

    # similar-tests
    p_sim = sub.add_parser("similar-tests",
                           help="Find test files similar to a target source file")
    p_sim.add_argument("--root", default=".", help="Project root directory")
    p_sim.add_argument("--target", required=True,
                       help="Source file to find similar tests for")

    # coverage (with sub-commands)
    # Note: --root is added to each sub-sub-parser so argparse handles it
    p_cov = sub.add_parser("coverage", help="Persistent coverage tracking")
    p_cov_sub = p_cov.add_subparsers(dest="coverage_command")

    p_snap = p_cov_sub.add_parser("snapshot", help="Capture current coverage state")
    p_snap.add_argument("--root", default=".", help="Project root directory")

    p_cmp = p_cov_sub.add_parser("compare", help="Diff two snapshots for regressions")
    p_cmp.add_argument("--root", default=".", help="Project root directory")
    p_cmp.add_argument("--old", default=None, help="Older snapshot filename")
    p_cmp.add_argument("--new", default=None, help="Newer snapshot filename")

    p_rpt = p_cov_sub.add_parser("report", help="Generate human-readable coverage report")
    p_rpt.add_argument("--root", default=".", help="Project root directory")

    p_thr = p_cov_sub.add_parser("threshold-check", help="Pass/fail against minimum coverage")
    p_thr.add_argument("--root", default=".", help="Project root directory")
    p_thr.add_argument("--min-coverage", type=float, default=0.0,
                        help="Minimum coverage percentage (default: 0)")

    p_ls = p_cov_sub.add_parser("list-snapshots", help="List available coverage snapshots")
    p_ls.add_argument("--root", default=".", help="Project root directory")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # coverage requires a sub-command
    if args.command == "coverage" and not getattr(args, "coverage_command", None):
        p_cov.print_help()
        sys.exit(1)

    handlers = {
        "discover": cmd_discover,
        "analyze-gaps": cmd_analyze_gaps,
        "suggest": cmd_suggest,
        "run": cmd_run,
        "semantic-gaps": cmd_semantic_gaps,
        "similar-tests": cmd_similar_tests,
        "coverage": cmd_coverage,
    }

    handler = handlers.get(args.command)
    if not handler:
        output_json({"error": f"Unknown command: {args.command}"})
        sys.exit(1)

    try:
        result = handler(args)
        output_json(result)
    except Exception as e:
        output_json({"error": str(e)})
        sys.exit(1)


if __name__ == "__main__":
    main()
