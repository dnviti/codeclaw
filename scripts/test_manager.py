#!/usr/bin/env python3
"""Test manager for the CTDF /tests skill.

Provides test discovery, gap analysis, suggestion, execution,
persistent coverage tracking with regression detection, semantic
gap analysis, and test pattern discovery via vector memory.
All output is JSON. Zero external dependencies — stdlib only
(vector memory features degrade gracefully when deps are missing).

Usage:
    python3 test_manager.py discover --root /path/to/project
    python3 test_manager.py analyze-gaps --root /path/to/project [--target file]
    python3 test_manager.py suggest --root /path/to/project
    python3 test_manager.py run --root /path/to/project [--target file]
    python3 test_manager.py semantic-gaps --root /path/to/project
    python3 test_manager.py similar-tests --root /path/to/project --target file
    python3 test_manager.py reindex-test --root /path/to/project --target file
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

# ── Constants ───────────────────────────────────────────────────────────────

TEST_RE = re.compile("|".join(TEST_FILE_PATTERNS), re.IGNORECASE)
FUNC_RE = re.compile("|".join(FUNCTION_PATTERNS), re.MULTILINE)

# CLAUDE.md variable parsing
CLAUDE_MD_VAR_RE = re.compile(r'^([A-Z_]+)\s*=\s*"?([^"#]*)"?\s*(?:#.*)?$')


# ── Helpers ─────────────────────────────────────────────────────────────────

def parse_claude_md(root: Path) -> dict[str, str]:
    """Extract key=value pairs from the bash code block in CLAUDE.md."""
    claude_md = root / "CLAUDE.md"
    if not claude_md.exists():
        return {}
    content = claude_md.read_text(encoding="utf-8")
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


def get_test_config(root: Path) -> dict:
    """Read test configuration from CLAUDE.md."""
    md_vars = parse_claude_md(root)
    return {
        "framework": md_vars.get("TEST_FRAMEWORK", ""),
        "command": md_vars.get("TEST_COMMAND", ""),
        "file_pattern": md_vars.get("TEST_FILE_PATTERN", ""),
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
            "error": "No test command configured. Set TEST_COMMAND in CLAUDE.md.",
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
            timeout=300,
        )
        return {
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "command": cmd,
            "output": result.stdout[-5000:] if len(result.stdout) > 5000 else result.stdout,
            "errors": result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Test execution timed out after 300 seconds.",
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

# High-risk semantic patterns to search for untested critical paths
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


def _vmem_search(root: Path, query: str, top_k: int = 10,
                 file_filter: str | None = None,
                 type_filter: str | None = None) -> list[dict]:
    """Run a semantic search against the vector memory index.

    Returns a list of result dicts or an empty list if vector memory
    is unavailable (missing deps, no index, etc.).
    """
    try:
        # Import vector_memory utilities
        from vector_memory import (
            get_effective_config, _check_deps, _open_db,
            _sanitize_filter_value, TABLE_NAME,
        )
        from contextlib import nullcontext

        config = get_effective_config(root)
        if config.get("enabled") is False:
            return []

        ok, _ = _check_deps()
        if not ok:
            return []

        index_dir = root / config["index_path"]
        if not (index_dir / "lancedb").exists():
            return []

        from embeddings import create_provider

        emb_config = {
            "provider": config["embedding_provider"],
            "model": config["embedding_model"],
            "api_key_env": config["embedding_api_key_env"],
        }
        provider = create_provider(emb_config)
        query_embedding = provider.embed([query])[0]

        # Acquire read lock if available
        lock = None
        try:
            from memory_lock import MemoryLock
            import os as _os
            agent_id = _os.environ.get("CTDF_AGENT_ID", f"agent-{_os.getpid()}")
            lock = MemoryLock(index_dir, agent_id=agent_id)
        except ImportError:
            pass

        _ctx = lock.read() if lock else nullcontext()
        with _ctx:
            db = _open_db(index_dir)
            try:
                table = db.open_table(TABLE_NAME)
            except Exception:
                return []

            results = table.search(query_embedding).limit(top_k * 3)

            if file_filter:
                safe = _sanitize_filter_value(file_filter)
                results = results.where(f"file_path LIKE '%{safe}%'")
            if type_filter:
                safe = _sanitize_filter_value(type_filter)
                results = results.where(f"chunk_type = '{safe}'")

            df = results.limit(top_k).to_pandas()

        records = []
        for _, row in df.iterrows():
            records.append({
                "file_path": row.get("file_path", ""),
                "name": row.get("name", ""),
                "chunk_type": row.get("chunk_type", ""),
                "language": row.get("language", ""),
                "start_line": int(row.get("start_line", 0)),
                "end_line": int(row.get("end_line", 0)),
                "score": float(row.get("_distance", 0.0)),
                "content": row.get("content", "")[:500],
            })
        return records
    except Exception:
        return []


def semantic_gap_analysis(root: Path) -> dict:
    """Query the vector store for high-risk untested code patterns.

    Searches for error handling, validation logic, authentication,
    payment processing, and other security-sensitive code semantically,
    then cross-references with existing test coverage to identify
    critical paths that lack tests.

    Returns a dict with ``semantic_risks`` entries grouped by category.
    """
    root = root.resolve()
    gitignore = load_gitignore_patterns(root)

    # Gather existing test files for cross-reference
    test_files: list[str] = []
    for rel, _fpath, ext, _size in walk_source_files(root, gitignore):
        if ext not in SOURCE_EXTS:
            continue
        if is_test_file(rel):
            test_files.append(rel)

    risks: list[dict] = []
    categories_found: dict[str, int] = {}

    for pattern_info in SEMANTIC_RISK_PATTERNS:
        query = pattern_info["query"]
        category = pattern_info["category"]

        results = _vmem_search(root, query, top_k=15)
        if not results:
            continue

        for result in results:
            file_path = result.get("file_path", "")
            # Skip files that are themselves tests
            if is_test_file(file_path):
                continue
            # Check if this source file has a matching test
            has_test = find_matching_test(file_path, test_files) is not None
            if not has_test:
                risks.append({
                    "file_path": file_path,
                    "name": result.get("name", ""),
                    "category": category,
                    "chunk_type": result.get("chunk_type", ""),
                    "start_line": result.get("start_line", 0),
                    "end_line": result.get("end_line", 0),
                    "score": result.get("score", 0.0),
                    "content_preview": result.get("content", "")[:200],
                })
                categories_found[category] = categories_found.get(category, 0) + 1

    # Deduplicate by (file_path, name) keeping highest score
    seen: dict[tuple[str, str], dict] = {}
    for risk in risks:
        key = (risk["file_path"], risk["name"])
        existing = seen.get(key)
        if existing is None or risk["score"] < existing["score"]:
            seen[key] = risk
    unique_risks = sorted(seen.values(), key=lambda r: r["score"])

    return {
        "semantic_risks": unique_risks,
        "total_risks": len(unique_risks),
        "categories": categories_found,
        "patterns_searched": len(SEMANTIC_RISK_PATTERNS),
        "vector_memory_available": len(unique_risks) > 0 or _vmem_available(root),
    }


def _vmem_available(root: Path) -> bool:
    """Check whether vector memory is available and has an index."""
    try:
        from vector_memory import get_effective_config, _check_deps
        config = get_effective_config(root)
        if config.get("enabled") is False:
            return False
        ok, _ = _check_deps()
        if not ok:
            return False
        index_dir = root / config["index_path"]
        return (index_dir / "lancedb").exists()
    except Exception:
        return False


def find_similar_tests(target_file: str, root: Path) -> dict:
    """Search for test files semantically similar to the target source file.

    Before generating tests, discovers existing test files in the project
    that cover similar domains, so the agent can replicate established
    patterns, mocking strategies, and assertion styles.

    Args:
        target_file: Relative path to the source file being tested.
        root: Project root directory.

    Returns:
        A dict with ``similar_tests`` listing relevant test files,
        and ``patterns`` summarising discovered conventions.
    """
    root = root.resolve()

    # Read the target file to build a semantic query from its content
    target_path = root / target_file
    content = read_file_safe(target_path)
    if not content:
        return {
            "similar_tests": [],
            "patterns": {},
            "error": f"Could not read target file: {target_file}",
        }

    # Build a search query from the file stem and extracted function names
    stem = Path(target_file).stem
    # Extract clean function/method names from the raw regex matches
    name_re = re.compile(r'\b(?:def|function|fn|func)\s+(\w+)', re.IGNORECASE)
    raw_matches = FUNC_RE.findall(content)
    func_names_list: list[str] = []
    for match in raw_matches[:15]:
        m = name_re.search(match)
        if m:
            func_names_list.append(m.group(1))
    func_names = " ".join(func_names_list[:10])
    query = f"test {stem} {func_names}".strip()

    # Search for test files semantically
    results = _vmem_search(root, query, top_k=20, file_filter="test")

    similar_tests: list[dict] = []
    seen_files: set[str] = set()

    for result in results:
        fp = result.get("file_path", "")
        if not is_test_file(fp):
            continue
        if fp in seen_files:
            continue
        seen_files.add(fp)
        similar_tests.append({
            "test_file": fp,
            "name": result.get("name", ""),
            "score": result.get("score", 0.0),
            "content_preview": result.get("content", "")[:300],
        })

    # Analyze discovered patterns from similar test files
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

        # Detect assertion styles
        if "assert " in test_content:
            _add_unique(patterns["assertion_styles"], "plain assert")
        if "assertEqual" in test_content or "self.assert" in test_content:
            _add_unique(patterns["assertion_styles"], "unittest assert methods")
        if "expect(" in test_content:
            _add_unique(patterns["assertion_styles"], "expect()")
        if "should." in test_content or "should(" in test_content:
            _add_unique(patterns["assertion_styles"], "should-style")

        # Detect mocking libraries
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

        # Detect test frameworks
        if "import pytest" in test_content or "@pytest" in test_content:
            _add_unique(patterns["frameworks"], "pytest")
        if "import unittest" in test_content:
            _add_unique(patterns["frameworks"], "unittest")
        if "describe(" in test_content:
            _add_unique(patterns["frameworks"], "describe/it (BDD)")
        if "import { test" in test_content or "import { it" in test_content:
            _add_unique(patterns["frameworks"], "vitest/jest")

        # Detect naming conventions
        test_name = Path(test_info["test_file"]).name
        if test_name.startswith("test_"):
            _add_unique(patterns["naming_conventions"], "test_<module>.py")
        elif test_name.endswith("_test.py"):
            _add_unique(patterns["naming_conventions"], "<module>_test.py")
        elif ".test." in test_name:
            _add_unique(patterns["naming_conventions"], "<module>.test.<ext>")
        elif ".spec." in test_name:
            _add_unique(patterns["naming_conventions"], "<module>.spec.<ext>")

    return {
        "similar_tests": similar_tests[:10],
        "patterns": patterns,
        "target_file": target_file,
        "query_used": query,
        "vector_memory_available": len(similar_tests) > 0 or _vmem_available(root),
    }


def _add_unique(lst: list[str], item: str) -> None:
    """Append item to list only if not already present."""
    if item not in lst:
        lst.append(item)


def reindex_test(test_path: str, root: Path) -> dict:
    """Incrementally index a newly created or modified test file.

    Called after writing a test file so that subsequent scout or create
    runs reflect the updated coverage in the vector index.

    Args:
        test_path: Relative path to the test file.
        root: Project root directory.

    Returns:
        A dict indicating success/failure.
    """
    root = root.resolve()
    abs_path = (root / test_path).resolve()

    if not abs_path.exists():
        return {"success": False, "error": f"File not found: {test_path}"}

    try:
        from vector_memory import hook_file_changed
        hook_file_changed(str(abs_path))
        return {
            "success": True,
            "file": test_path,
            "message": f"Vector index updated for {test_path}",
        }
    except ImportError:
        return {
            "success": False,
            "error": "Vector memory dependencies not available.",
            "file": test_path,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "file": test_path,
        }


# ── Subcommand wrappers for new semantic features ──────────────────────────

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


def cmd_reindex_test(args) -> dict:
    """CLI wrapper for reindex_test."""
    root = Path(args.root).resolve()
    target = args.target
    if not target:
        return {"error": "No target file specified. Use --target <file>."}
    return reindex_test(target, root)


# ── CLI Entrypoint ──────────────────────────────────────────────────────────

def output_json(data: dict) -> None:
    """Print JSON to stdout."""
    json.dump(data, sys.stdout, indent=2, default=str)
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Test manager for CTDF /tests skill",
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
                             help="Semantic gap analysis via vector memory")
    p_sgaps.add_argument("--root", default=".", help="Project root directory")

    # similar-tests
    p_sim = sub.add_parser("similar-tests",
                           help="Find test files similar to a target source file")
    p_sim.add_argument("--root", default=".", help="Project root directory")
    p_sim.add_argument("--target", required=True,
                       help="Source file to find similar tests for")

    # reindex-test
    p_reidx = sub.add_parser("reindex-test",
                             help="Incrementally reindex a test file in vector memory")
    p_reidx.add_argument("--root", default=".", help="Project root directory")
    p_reidx.add_argument("--target", required=True,
                         help="Test file to reindex")

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
        "reindex-test": cmd_reindex_test,
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
