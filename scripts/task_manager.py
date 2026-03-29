#!/usr/bin/env python3
"""Task and idea manager CLI for codeclaw.

Provides deterministic file operations for Claude Code skills:
- Task/idea listing, parsing, ID computation
- Block moving between files, removal
- Duplicate detection, file verification
- PostToolUse hook for file-to-task correlation

All output is JSON (default) or formatted text (--format text).
Zero external dependencies — stdlib only.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Add scripts/ to path for sibling imports
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# ── Constants ───────────────────────────────────────────────────────────────

DEFAULT_GIT_TIMEOUT_SECONDS = 30
DEFAULT_ISSUE_FETCH_LIMIT = 200
DEFAULT_CI_RUNS_LIMIT = 20
DEFAULT_FIND_FILES_LIMIT = 50

SEPARATOR = "-" * 78
SECTION_SEP = "=" * 80
TASK_FILES = ["to-do.txt", "progressing.txt", "done.txt"]
IDEA_FILES = ["ideas.txt", "idea-disapproved.txt"]
ALL_FILES = TASK_FILES + IDEA_FILES

STATUS_MAP = {"[ ]": "todo", "[~]": "progressing", "[x]": "done", "[!]": "blocked"}
STATUS_REVERSE = {"todo": "[ ]", "progressing": "[~]", "done": "[x]", "blocked": "[!]"}
FILE_FOR_STATUS = {
    "todo": "to-do.txt",
    "progressing": "progressing.txt",
    "done": "done.txt",
}

# Known crypto/algorithm prefixes to exclude from task ID detection
CRYPTO_PREFIXES = {"AES", "SHA", "RSA", "MD5", "RC4", "DES", "DSA", "ECC", "CBC", "GCM", "CTR", "ECB"}

# ── Regexes ─────────────────────────────────────────────────────────────────

TASK_HEADER_RE = re.compile(r"^\[(.)\]\s+([A-Z]{3,5}-\d{4})\s+—\s+(.+)$")
IDEA_HEADER_RE = re.compile(r"^(IDEA-[A-Z]{3,5}-\d{4})\s+—\s+(.+)$")
TASK_CODE_RE = re.compile(r"[A-Z]{3,5}-(\d{4})")
IDEA_CODE_RE = re.compile(r"IDEA-[A-Z]{3,5}-(\d{4})")
SECTION_HEADER_RE = re.compile(r"^\s+SECTION\s+([A-Z])\s+—\s+(.+)$")

# ── Project Root Detection ──────────────────────────────────────────────────

from common import get_main_repo_root, load_project_config


# Frontend file extensions and directory patterns that indicate a frontend task
_FRONTEND_EXTENSIONS = {
    ".tsx", ".jsx", ".vue", ".svelte", ".astro",
    ".css", ".scss", ".sass", ".less", ".styl",
    ".html", ".ejs", ".hbs", ".pug",
}
_FRONTEND_DIRECTORIES = {
    "components", "pages", "views", "layouts", "templates",
    "styles", "css", "public", "static", "assets", "app",
}
_FRONTEND_KEYWORDS = {
    "frontend", "front-end", "ui", "component", "page", "layout",
    "style", "css", "theme", "design", "widget", "dashboard",
    "form", "modal", "dialog", "sidebar", "navbar", "header",
    "footer", "responsive", "animation", "transition",
}


def is_frontend_task(task: dict) -> bool:
    """Check if a task involves frontend work based on its metadata.

    Inspects the task description, category, and 'Files involved' for
    frontend indicators such as .tsx/.vue/.svelte extensions,
    components/pages directories, and UI-related keywords.

    Args:
        task: A parsed task dict (from parse_blocks or platform issue body)
              with keys like 'description', 'technical_details',
              'files_create', 'files_modify', 'title'.

    Returns:
        True if the task appears to involve frontend code.
    """
    # Check file extensions in files_create and files_modify
    for file_list_key in ("files_create", "files_modify"):
        for filepath in task.get(file_list_key, []):
            # O(1) extension check via set membership
            if Path(filepath).suffix.lower() in _FRONTEND_EXTENSIONS:
                return True
            # Check directory patterns
            path_parts = filepath.lower().replace("\\", "/").split("/")
            for part in path_parts:
                if part in _FRONTEND_DIRECTORIES:
                    return True

    # Check description and technical details for frontend keywords
    text_fields = [
        task.get("title", ""),
        task.get("description", ""),
        task.get("technical_details", ""),
    ]
    combined_text = " ".join(text_fields).lower()
    for keyword in _FRONTEND_KEYWORDS:
        if keyword in combined_text:
            return True

    return False


# ── File Reading Helpers ────────────────────────────────────────────────────

def read_lines(filepath: Path) -> list[str]:
    """Read file lines, stripping \\r. Returns empty list if file missing."""
    if not filepath.exists():
        return []
    return filepath.read_text(encoding="utf-8").replace("\r", "").splitlines()

def write_lines(filepath: Path, lines: list[str]) -> None:
    """Write lines back to file with \\n endings."""
    filepath.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")

# ── Block Parsing ───────────────────────────────────────────────────────────

def is_separator(line: str) -> bool:
    """Check if line is a 78-dash task/idea separator."""
    return line.strip() == SEPARATOR

def is_section_sep(line: str) -> bool:
    """Check if line is an 80-equals section separator."""
    return line.strip() == SECTION_SEP

def parse_blocks(filepath: Path) -> list[dict]:
    """Parse all task/idea blocks from a file.

    Returns list of dicts with keys:
      line_start, line_end (0-indexed, inclusive of separators)
      code, title, status_symbol, status
      priority, dependencies, description, technical_details
      files_create, files_modify
      raw (the full block text including separators)
      block_type: "task" | "idea"
    """
    lines = read_lines(filepath)
    blocks = []
    i = 0

    while i < len(lines):
        if not is_separator(lines[i]):
            i += 1
            continue

        sep_start = i
        # Next line should be a header
        if i + 1 >= len(lines):
            i += 1
            continue

        header_line = lines[i + 1]

        # Try task header
        task_match = TASK_HEADER_RE.match(header_line)
        idea_match = IDEA_HEADER_RE.match(header_line) if not task_match else None

        if not task_match and not idea_match:
            i += 1
            continue

        # Expect closing separator on line i+2
        if i + 2 >= len(lines) or not is_separator(lines[i + 2]):
            i += 1
            continue

        # Find the end of the block content (next separator or section sep or EOF)
        content_start = i + 3
        content_end = content_start
        while content_end < len(lines):
            if is_separator(lines[content_end]) or is_section_sep(lines[content_end]):
                break
            content_end += 1

        # Trim trailing blank lines from content
        actual_end = content_end
        while actual_end > content_start and lines[actual_end - 1].strip() == "":
            actual_end -= 1

        # The block spans from sep_start to content_end (exclusive)
        block_lines = lines[sep_start:content_end]
        content_lines = lines[content_start:actual_end]

        block = {
            "line_start": sep_start,
            "line_end": content_end - 1,  # inclusive
            "raw": "\n".join(block_lines),
        }

        if task_match:
            status_char = task_match.group(1)
            symbol = f"[{status_char}]"
            block.update({
                "block_type": "task",
                "status_symbol": symbol,
                "status": STATUS_MAP.get(symbol, "unknown"),
                "code": task_match.group(2),
                "title": task_match.group(3).strip(),
            })
        else:
            block.update({
                "block_type": "idea",
                "status_symbol": "",
                "status": "idea",
                "code": idea_match.group(1),
                "title": idea_match.group(2).strip(),
            })

        # Parse content fields
        _parse_content_fields(block, content_lines)
        blocks.append(block)
        i = content_end

    return blocks

def _parse_content_fields(block: dict, content_lines: list[str]) -> None:
    """Parse the indented fields from a block's content lines."""
    block["priority"] = ""
    block["dependencies"] = ""
    block["description"] = ""
    block["technical_details"] = ""
    block["files_create"] = []
    block["files_modify"] = []
    block["category"] = ""
    block["date"] = ""
    block["motivation"] = ""
    block["completed"] = ""
    block["rejection_reason"] = ""
    block["release"] = ""

    current_section = None
    section_lines = []

    def flush_section():
        if current_section and section_lines:
            text = "\n".join(section_lines).strip()
            if current_section == "description":
                block["description"] = text
            elif current_section == "technical_details":
                block["technical_details"] = text
            elif current_section == "motivation":
                block["motivation"] = text
            elif current_section == "rejection_reason":
                block["rejection_reason"] = text
            elif current_section == "files_involved":
                _parse_files_involved(block, section_lines)

    for line in content_lines:
        stripped = line.strip()

        # Single-line fields
        if stripped.startswith("Priority:"):
            block["priority"] = stripped[len("Priority:"):].strip()
            continue
        if stripped.startswith("Dependencies:"):
            block["dependencies"] = stripped[len("Dependencies:"):].strip()
            continue
        if stripped.startswith("Release:"):
            block["release"] = stripped[len("Release:"):].strip()
            continue
        if stripped.startswith("Category:"):
            block["category"] = stripped[len("Category:"):].strip()
            continue
        if stripped.startswith("Date:"):
            block["date"] = stripped[len("Date:"):].strip()
            continue
        if stripped.startswith("Last updated:"):
            continue
        if stripped.startswith("COMPLETED:"):
            block["completed"] = stripped[len("COMPLETED:"):].strip()
            continue

        # Multi-line section headers
        if stripped == "DESCRIPTION:":
            flush_section()
            current_section = "description"
            section_lines = []
            continue
        if stripped == "TECHNICAL DETAILS:":
            flush_section()
            current_section = "technical_details"
            section_lines = []
            continue
        if stripped == "MOTIVATION:":
            flush_section()
            current_section = "motivation"
            section_lines = []
            continue
        if stripped == "REJECTION REASON:":
            flush_section()
            current_section = "rejection_reason"
            section_lines = []
            continue
        if stripped.startswith("Files involved:"):
            flush_section()
            current_section = "files_involved"
            section_lines = []
            continue

        # Continuation of current section
        if current_section:
            section_lines.append(line)

    flush_section()

def _parse_files_involved(block: dict, lines: list[str]) -> None:
    """Parse CREATE: and MODIFY: entries from Files involved lines."""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("CREATE:"):
            path = stripped[len("CREATE:"):].strip()
            if path:
                block["files_create"].append(path)
        elif stripped.startswith("MODIFY:"):
            path = stripped[len("MODIFY:"):].strip()
            if path:
                block["files_modify"].append(path)

def find_block(filepath: Path, code: str) -> dict | None:
    """Find a specific block by its code."""
    for block in parse_blocks(filepath):
        if block["code"] == code:
            return block
    return None

def find_block_in_all(root: Path, code: str, file_list: list[str] | None = None) -> tuple[dict | None, str | None]:
    """Find a block across multiple files. Returns (block, filename) or (None, None)."""
    files = file_list or ALL_FILES
    for fname in files:
        fp = root / fname
        if fp.exists():
            block = find_block(fp, code)
            if block:
                return block, fname
    return None, None

# ── Section Parsing ─────────────────────────────────────────────────────────

def parse_sections(filepath: Path) -> list[dict]:
    """Parse section headers from a file.

    Returns list of {letter, name, line_number (0-indexed)}.
    """
    lines = read_lines(filepath)
    sections = []

    for i, line in enumerate(lines):
        if is_section_sep(line) and i + 1 < len(lines):
            m = SECTION_HEADER_RE.match(lines[i + 1])
            if m:
                sections.append({
                    "letter": m.group(1),
                    "name": m.group(2).strip(),
                    "line_number": i,
                })

    return sections

def find_section_range(filepath: Path, section_letter: str) -> tuple[int, int] | None:
    """Find the line range for a section (start of content to next section or EOF).

    Returns (content_start, content_end) as 0-indexed line numbers.
    content_start is the first line after the section separator block.
    content_end is the line before the next section separator (or EOF).
    """
    lines = read_lines(filepath)
    sections = parse_sections(filepath)

    target = None
    next_section_line = len(lines)

    for idx, sec in enumerate(sections):
        if sec["letter"] == section_letter:
            target = sec
            # Content starts after the closing = separator (line_number + 2)
            if idx + 1 < len(sections):
                next_section_line = sections[idx + 1]["line_number"]
            break

    if target is None:
        return None

    content_start = target["line_number"] + 3  # skip =, title, =
    return (content_start, next_section_line)

# ── Subcommand: platform-config ────────────────────────────────────────────

def cmd_platform_config(args):
    """Return platform tracker configuration as JSON."""
    root = get_main_repo_root()

    config_file = None
    data = {}
    for candidate in ["issues-tracker.json", "github-issues.json"]:
        fp = root / ".claude" / candidate
        if fp.exists():
            config_file = str(Path(".claude") / candidate)
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            break

    enabled = data.get("enabled", False)
    sync = data.get("sync", False)
    platform = data.get("platform", "github")

    if enabled and not sync:
        mode = "platform-only"
    elif enabled and sync:
        mode = "dual-sync"
    else:
        mode = "local-only"

    result = {
        "platform": platform,
        "enabled": enabled,
        "sync": sync,
        "repo": data.get("repo"),
        "mode": mode,
        "config_file": config_file,
        "cli": "glab" if platform == "gitlab" else "gh",
        "labels": data.get("labels"),
    }
    print(json.dumps(result, indent=2))

# ── Subcommand: next-id ─────────────────────────────────────────────────────

def _next_id_from_stdin(code_re, filter_crypto=True):
    """Parse task/idea codes from stdin lines, return (max_num, prefixes)."""
    max_num = 0
    prefixes = set()
    for line in sys.stdin:
        for m in code_re.finditer(line):
            full_match = m.group(0)
            num = int(m.group(1))
            prefix = full_match.rsplit("-", 1)[0]
            if filter_crypto and prefix in CRYPTO_PREFIXES:
                continue
            if num > max_num:
                max_num = num
            prefixes.add(prefix)
    return max_num, prefixes

def cmd_next_id(args):
    root = get_main_repo_root()
    max_num = 0
    prefixes = set()

    if args.source == "platform-titles":
        code_re = TASK_CODE_RE if args.type == "task" else IDEA_CODE_RE
        max_num, prefixes = _next_id_from_stdin(code_re, filter_crypto=True)
    else:
        # Shared numbering: scan ALL files (tasks + ideas) regardless of type
        all_files = [root / f for f in TASK_FILES + IDEA_FILES]
        for fp in all_files:
            if not fp.exists():
                continue
            for block in parse_blocks(fp):
                if block["block_type"] == "task":
                    code = block["code"]
                    prefix = code.rsplit("-", 1)[0]
                    num = int(code.rsplit("-", 1)[1])
                    if num > max_num:
                        max_num = num
                    prefixes.add(prefix)
                elif block["block_type"] == "idea":
                    code = block["code"]
                    num = int(code.rsplit("-", 1)[1])
                    if num > max_num:
                        max_num = num
                    # Extract domain prefix from idea code (e.g., IDEA-AUTH-0001 -> AUTH)
                    parts = code.split("-")
                    if len(parts) >= 3:
                        prefixes.add(parts[1])

    result = {
        "next_number": f"{max_num + 1:04d}",
        "max_found": max_num,
    }
    result["prefixes"] = sorted(prefixes)

    print(json.dumps(result))

# ── Subcommand: list ─────────────────────────────────────────────────────────

def cmd_list(args):
    root = get_main_repo_root()
    results = []

    if args.status == "all":
        files_to_scan = TASK_FILES
    elif args.status == "blocked":
        files_to_scan = ["to-do.txt"]
    else:
        files_to_scan = [FILE_FOR_STATUS.get(args.status, "to-do.txt")]

    for fname in files_to_scan:
        fp = root / fname
        if not fp.exists():
            continue
        for block in parse_blocks(fp):
            if block["block_type"] != "task":
                continue
            if args.status == "blocked" and block["status"] != "blocked":
                continue
            if args.status != "all" and args.status != "blocked" and block["status"] != args.status:
                continue
            results.append({
                "code": block["code"],
                "title": block["title"],
                "status": block["status"],
                "priority": block["priority"],
                "dependencies": block["dependencies"],
                "file": fname,
            })

    if args.format == "json":
        print(json.dumps(results, indent=2))
    else:
        if not results:
            print("(none)")
        else:
            for r in results:
                symbol = STATUS_REVERSE.get(r["status"], "[ ]")
                print(f"{symbol} {r['code']} — {r['title']}")

# ── Subcommand: list-ideas ───────────────────────────────────────────────────

def cmd_list_ideas(args):
    root = get_main_repo_root()
    results = []

    file_map = {
        "ideas": ["ideas.txt"],
        "disapproved": ["idea-disapproved.txt"],
        "all": IDEA_FILES,
    }
    files_to_scan = file_map.get(args.file, IDEA_FILES)

    for fname in files_to_scan:
        fp = root / fname
        if not fp.exists():
            continue
        for block in parse_blocks(fp):
            if block["block_type"] != "idea":
                continue
            results.append({
                "code": block["code"],
                "title": block["title"],
                "category": block["category"],
                "date": block["date"],
                "file": fname,
            })

    if args.format == "json":
        print(json.dumps(results, indent=2))
    else:
        if not results:
            print("(none)")
        else:
            for r in results:
                print(f"{r['code']} — {r['title']}")

# ── Subcommand: parse ────────────────────────────────────────────────────────

def cmd_parse(args):
    root = get_main_repo_root()
    code = args.code.upper()

    block, fname = find_block_in_all(root, code)
    if not block:
        print(json.dumps({"error": f"Block {code} not found in any file"}))
        sys.exit(1)

    block["source_file"] = fname
    # Remove internal line tracking from output
    output = {k: v for k, v in block.items() if k not in ("line_start", "line_end")}
    print(json.dumps(output, indent=2))

# ── Subcommand: summary ─────────────────────────────────────────────────────

def cmd_summary(args):
    root = get_main_repo_root()
    counts = {"done": 0, "progressing": 0, "todo": 0, "blocked": 0}

    for fname, expected in [
        ("done.txt", ["done"]),
        ("progressing.txt", ["progressing"]),
        ("to-do.txt", ["todo", "blocked"]),
    ]:
        fp = root / fname
        if not fp.exists():
            continue
        for block in parse_blocks(fp):
            if block["block_type"] == "task" and block["status"] in expected:
                counts[block["status"]] += 1

    total = sum(counts.values())
    pct = (counts["done"] * 100 // total) if total > 0 else 0

    result = {**counts, "total": total, "percent": pct}

    if args.format == "text":
        print("=== TASK SUMMARY ===")
        print(f"  Completed:   {counts['done']}/{total}")
        print(f"  In progress: {counts['progressing']}")
        print(f"  Todo:        {counts['todo']}")
        print(f"  Blocked:     {counts['blocked']}")
        if total > 0:
            print(f"  Progress:    {pct}%")
        print("=====================")
    else:
        print(json.dumps(result))

# ── Subcommand: prefixes ────────────────────────────────────────────────────

def cmd_prefixes(args):
    root = get_main_repo_root()
    prefixes = set()

    for fname in TASK_FILES:
        fp = root / fname
        if not fp.exists():
            continue
        for block in parse_blocks(fp):
            if block["block_type"] == "task":
                prefix = block["code"].rsplit("-", 1)[0]
                prefixes.add(prefix)

    print(json.dumps(sorted(prefixes)))

# ── Subcommand: sections ────────────────────────────────────────────────────

def cmd_sections(args):
    root = get_main_repo_root()
    fp = root / args.file
    if not fp.exists():
        print(json.dumps({"error": f"File {args.file} not found"}))
        sys.exit(1)

    sections = parse_sections(fp)
    print(json.dumps(sections, indent=2))

# ── Subcommand: duplicates ──────────────────────────────────────────────────

def cmd_duplicates(args):
    root = get_main_repo_root()
    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    files = [f.strip() for f in args.files.split(",")] if args.files else ALL_FILES

    matches = []
    for fname in files:
        fp = root / fname
        if not fp.exists():
            continue
        for i, line in enumerate(read_lines(fp), 1):
            line_lower = line.lower()
            for kw in keywords:
                if kw.lower() in line_lower:
                    matches.append({
                        "file": fname,
                        "line": i,
                        "keyword": kw,
                        "text": line.strip(),
                    })
                    break  # one match per line

    print(json.dumps(matches, indent=2))

# ── Subcommand: verify-files ────────────────────────────────────────────────

def cmd_verify_files(args):
    main_root = get_main_repo_root()
    source_root = get_main_repo_root()
    code = args.code.upper()

    block, fname = find_block_in_all(main_root, code, TASK_FILES)
    if not block:
        print(json.dumps({"error": f"Task {code} not found"}))
        sys.exit(1)

    report = {"code": code, "source_file": fname, "create": [], "modify": []}

    for f in block.get("files_create", []):
        exists = (source_root / f).exists()
        report["create"].append({"path": f, "exists": exists})

    for f in block.get("files_modify", []):
        exists = (source_root / f).exists()
        report["modify"].append({"path": f, "exists": exists})

    report["all_exist"] = (
        all(e["exists"] for e in report["create"])
        and all(e["exists"] for e in report["modify"])
    )

    print(json.dumps(report, indent=2))

# ── Subcommand: semantic-explore ─────────────────────────────────────────────

def _sanitize_query(text: str) -> str:
    """Strip control characters from query text to avoid downstream issues."""
    import unicodedata
    return "".join(
        ch for ch in text
        if unicodedata.category(ch)[0] != "C" or ch in ("\n", "\t")
    )


def semantic_explore(task_code: str, root: Path) -> dict:
    """Explore the codebase semantically for a task.

    1. Parses the task description (from local files or platform issue).
    2. Runs ``vector_memory.py search`` with the description as query.
    3. Filters out files already listed in "Files involved".
    4. Returns a ranked list of related files with relevance scores.

    Args:
        task_code: The task code (e.g. ``AUTH-0001``).
        root: Project root directory (main repo root).

    Returns:
        dict with ``task_code``, ``query_used``, ``related_files`` list,
        and ``files_involved`` (the already-known files from the task).
    """
    vm_script = _SCRIPT_DIR / "vector_memory.py"
    result = {
        "task_code": task_code,
        "query_used": "",
        "related_files": [],
        "files_involved": [],
        "skipped_reason": None,
    }

    # Validate task code format
    if not TASK_CODE_RE.search(task_code):
        result["skipped_reason"] = f"Invalid task code format: {task_code!r}"
        return result

    # Early-return if vector_memory.py is not available
    if not vm_script.exists():
        result["skipped_reason"] = "vector_memory.py not found"
        return result

    # --- 1. Parse task description ---
    block, _fname = find_block_in_all(root, task_code, TASK_FILES)
    description = ""
    title = ""
    files_involved: list[str] = []

    if block:
        title = block.get("title", "")
        description = block.get("description", "")
        tech_details = block.get("technical_details", "")
        if tech_details:
            description = f"{description}\n{tech_details}"
        files_involved = block.get("files_create", []) + block.get("files_modify", [])
    else:
        # Platform-only: try to get the issue body via gh
        try:
            search_result = subprocess.run(
                ["gh", "issue", "list", "--repo",
                 _get_repo_slug(), "--search", task_code,
                 "--json", "body,title", "--limit", "1"],
                capture_output=True, text=True, timeout=30,
            )
            if search_result.returncode == 0 and search_result.stdout.strip():
                issues = json.loads(search_result.stdout.strip())
                if issues:
                    title = issues[0].get("title", "")
                    body = issues[0].get("body", "")
                    description = body
                    # Extract files involved from markdown body
                    for line in body.splitlines():
                        stripped = line.strip()
                        if stripped.startswith("**MODIFY:**") or stripped.startswith("**CREATE:**"):
                            path = stripped.split("**", 2)[-1].strip()
                            if path:
                                files_involved.append(path)
        except Exception:
            pass

    if not description and not title:
        result["skipped_reason"] = f"Could not find task {task_code} or extract description"
        return result

    # Build the search query from title + description (sanitized and truncated)
    query = _sanitize_query(f"{title} {description}".strip())
    # Limit query length to avoid excessively long embeddings
    if len(query) > 1000:
        query = query[:1000]
    result["query_used"] = query
    result["files_involved"] = files_involved

    # --- 2. Run semantic search ---

    try:
        search_result = subprocess.run(
            [
                sys.executable, str(vm_script), "search",
                query,
                "--root", str(root),
                "--top-k", "20",
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if search_result.returncode != 0:
            stderr = search_result.stderr.strip()
            if "No vector index found" in stderr or "Error" in stderr:
                result["skipped_reason"] = "Vector index unavailable"
            else:
                result["skipped_reason"] = f"Search failed (exit {search_result.returncode})"
            return result

        raw_results = json.loads(search_result.stdout.strip()) if search_result.stdout.strip() else []
    except subprocess.TimeoutExpired:
        result["skipped_reason"] = "Semantic search timed out"
        return result
    except (json.JSONDecodeError, Exception):
        result["skipped_reason"] = "Failed to parse search results"
        return result

    # --- 3. Filter and deduplicate ---
    # Normalise files_involved for comparison
    involved_normalised = {f.strip().lstrip("./") for f in files_involved}

    seen_files: dict[str, dict] = {}  # file_path -> best entry
    for entry in raw_results:
        fpath = entry.get("file_path", "").strip().lstrip("./")
        if not fpath:
            continue
        # Skip files already known from the task
        if fpath in involved_normalised:
            continue
        # Keep the entry with the best (lowest) score per file
        score = entry.get("score", 999.0)
        if fpath not in seen_files or score < seen_files[fpath]["score"]:
            seen_files[fpath] = {
                "file_path": fpath,
                "score": round(score, 4),
                "chunk_type": entry.get("chunk_type", ""),
                "name": entry.get("name", ""),
                "language": entry.get("language", ""),
            }

    # Sort by score ascending (lower = more relevant)
    ranked = sorted(seen_files.values(), key=lambda x: x["score"])
    result["related_files"] = ranked

    return result


def _get_repo_slug() -> str:
    """Return 'owner/repo' slug from platform config or git remote."""
    try:
        cfg = _load_platform_config()
        repo = cfg.get("repo", "")
        if repo:
            return repo
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True,
        )
        url = result.stdout.strip()
        m = re.search(r"github\.com[/:]([^/]+/[^/.]+)", url)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def cmd_semantic_explore(args):
    """CLI handler for the semantic-explore subcommand."""
    root = get_main_repo_root()
    code = args.code.upper()

    result = semantic_explore(code, root)

    if args.format == "text":
        print(f"=== Semantic Exploration: {result['task_code']} ===")
        if result.get("skipped_reason"):
            print(f"  Skipped: {result['skipped_reason']}")
        else:
            print(f"  Query: {result['query_used'][:120]}...")
            print(f"  Files involved (already known): {len(result['files_involved'])}")
            print(f"  Additional related files found: {len(result['related_files'])}")
            print()
            for i, f in enumerate(result["related_files"], 1):
                print(f"  [{i}] {f['file_path']}  "
                      f"(score={f['score']:.4f}, {f['chunk_type']}: {f['name']})")
        print("=" * 50)
    else:
        print(json.dumps(result, indent=2))

# ── Subcommand: is-frontend-task ───────────────────────────────────────────

def cmd_is_frontend_task(args):
    """Check if a task involves frontend work."""
    main_root = get_main_repo_root()
    code = args.code.upper()

    block, fname = find_block_in_all(main_root, code, TASK_FILES)

    if not block:
        # For platform-only mode, accept JSON task data via --json-body
        _MAX_JSON_BODY_LEN = 100_000  # 100 KB limit to prevent DoS
        if args.json_body:
            if len(args.json_body) > _MAX_JSON_BODY_LEN:
                print(json.dumps({"error": "json-body exceeds 100KB limit", "is_frontend": False}))
                sys.exit(1)
            try:
                task_data = json.loads(args.json_body)
                result = is_frontend_task(task_data)
                print(json.dumps({"code": code, "is_frontend": result}))
                return
            except json.JSONDecodeError:
                pass
        print(json.dumps({"error": f"Task {code} not found", "is_frontend": False}))
        sys.exit(1)

    result = is_frontend_task(block)
    print(json.dumps({"code": code, "is_frontend": result, "source_file": fname}))

# ── Subcommand: move ────────────────────────────────────────────────────────

def cmd_add_test_procedure(args):
    root = get_main_repo_root()
    code = args.code.upper()
    prog_path = root / "progressing.txt"

    block = find_block(prog_path, code)
    if not block:
        print(json.dumps({"success": False, "error": f"Task {code} not found in progressing.txt"}))
        sys.exit(1)

    indented = "\n".join(f"  {line}" if line.strip() else "" for line in args.body.split("\n"))
    new_section = f"\n  TEST PROCEDURE:\n{indented}"

    lines = read_lines(prog_path)
    block_lines = lines[block["line_start"]:block["line_end"] + 1]
    block_text = "\n".join(block_lines)

    # Insert before the closing separator
    last_sep_pos = block_text.rfind(SEPARATOR)
    if last_sep_pos != -1:
        block_text = block_text[:last_sep_pos] + new_section + "\n" + block_text[last_sep_pos:]
    else:
        block_text += new_section

    new_block_lines = block_text.split("\n")
    new_lines = lines[:block["line_start"]] + new_block_lines + lines[block["line_end"] + 1:]
    write_lines(prog_path, new_lines)
    print(json.dumps({"success": True, "code": code}))

def cmd_move(args):
    root = get_main_repo_root()
    code = args.code.upper()
    target_status = args.to
    target_file = FILE_FOR_STATUS.get(target_status)

    if not target_file:
        print(json.dumps({"error": f"Invalid target status: {target_status}"}))
        sys.exit(1)

    # Find the block
    source_file = None
    block = None
    for fname in TASK_FILES:
        fp = root / fname
        if not fp.exists():
            continue
        b = find_block(fp, code)
        if b:
            source_file = fname
            block = b
            break

    if not block:
        print(json.dumps({"error": f"Task {code} not found in any task file"}))
        sys.exit(1)

    if source_file == target_file:
        print(json.dumps({"error": f"Task {code} is already in {target_file}"}))
        sys.exit(1)

    # Read source file and remove the block
    src_path = root / source_file
    src_lines = read_lines(src_path)
    start = block["line_start"]
    end = block["line_end"] + 1  # exclusive

    # Also remove trailing blank lines after the block
    while end < len(src_lines) and src_lines[end].strip() == "":
        end += 1
    # But keep at least one blank line if there's content after
    if end < len(src_lines) and src_lines[end].strip() != "":
        end -= 1

    removed_lines = src_lines[start:block["line_end"] + 1]  # just the block, no trailing blanks
    src_lines = src_lines[:start] + src_lines[end:]

    # Clean up triple+ blank lines in source
    cleaned = []
    blank_count = 0
    for line in src_lines:
        if line.strip() == "":
            blank_count += 1
            if blank_count <= 2:
                cleaned.append(line)
        else:
            blank_count = 0
            cleaned.append(line)
    src_lines = cleaned

    write_lines(src_path, src_lines)

    # Prepare the block for insertion
    block_text = "\n".join(removed_lines)

    # Update status symbol
    old_symbol = block["status_symbol"]
    new_symbol = STATUS_REVERSE[target_status]
    if old_symbol and old_symbol != new_symbol:
        block_text = block_text.replace(old_symbol, new_symbol, 1)

    # Add COMPLETED line if moving to done
    if target_status == "done" and args.completed_summary:
        # Insert after Dependencies line
        block_lines_list = block_text.split("\n")
        insert_idx = None
        for idx, line in enumerate(block_lines_list):
            if line.strip().startswith("Dependencies:"):
                insert_idx = idx + 1
                break
        if insert_idx is not None:
            block_lines_list.insert(insert_idx, f"  COMPLETED: {args.completed_summary}")
            block_text = "\n".join(block_lines_list)

    # Find insertion point in target file
    tgt_path = root / target_file
    tgt_lines = read_lines(tgt_path) if tgt_path.exists() else []

    # Find the best section to insert into
    # Try to match the section from the source file
    source_sections = parse_sections(src_path)
    target_sections = parse_sections(tgt_path)

    # Determine which section the block was in
    block_section = None
    for sec in parse_sections(root / source_file) if (root / source_file).exists() else source_sections:
        # This won't work after removal, use original block position
        pass

    # Simpler approach: find the last task block in the target file before the
    # RECOMMENDED IMPLEMENTATION ORDER or NOTES sections, and append there.
    # Or find the matching section letter.

    # Find the last content line before a section separator or EOF
    insert_pos = _find_insert_position(tgt_lines, target_sections)

    # Build insertion: two blank lines + block + blank line
    insertion = ["", ""] + block_text.split("\n") + [""]

    tgt_lines = tgt_lines[:insert_pos] + insertion + tgt_lines[insert_pos:]

    # Clean up triple+ blank lines
    cleaned = []
    blank_count = 0
    for line in tgt_lines:
        if line.strip() == "":
            blank_count += 1
            if blank_count <= 2:
                cleaned.append(line)
        else:
            blank_count = 0
            cleaned.append(line)

    write_lines(tgt_path, cleaned)

    print(json.dumps({
        "success": True,
        "code": code,
        "from_file": source_file,
        "to_file": target_file,
        "new_status": target_status,
    }))

def _find_insert_position(lines: list[str], sections: list[dict]) -> int:
    """Find the best position to insert a new block in a task file.

    Inserts before the RECOMMENDED IMPLEMENTATION ORDER section or NOTES section,
    or at the end of the last regular section's content.
    """
    # Look for RECOMMENDED or NOTES section and insert before it
    for i, line in enumerate(lines):
        if is_section_sep(line) and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if "RECOMMENDED" in next_line or "NOTES" in next_line:
                # Go back to find the right spot (skip blank lines)
                pos = i
                while pos > 0 and lines[pos - 1].strip() == "":
                    pos -= 1
                return pos

    # If no special sections found, find the last section content area
    if sections:
        last_sec = sections[-1]
        # Find end of that section's content
        start = last_sec["line_number"] + 3
        pos = start
        for j in range(start, len(lines)):
            if is_section_sep(lines[j]):
                pos = j
                while pos > 0 and lines[pos - 1].strip() == "":
                    pos -= 1
                return pos
            pos = j + 1
        return pos

    # Fallback: end of file
    return len(lines)

# ── Subcommand: remove ──────────────────────────────────────────────────────

def cmd_remove(args):
    root = get_main_repo_root()
    code = args.code.upper()
    fp = root / args.file

    if not fp.exists():
        print(json.dumps({"error": f"File {args.file} not found"}))
        sys.exit(1)

    block = find_block(fp, code)
    if not block:
        print(json.dumps({"error": f"Block {code} not found in {args.file}"}))
        sys.exit(1)

    lines = read_lines(fp)
    start = block["line_start"]
    end = block["line_end"] + 1

    # Also remove trailing blank lines
    while end < len(lines) and lines[end].strip() == "":
        end += 1
    # Keep at least one blank line
    if end < len(lines):
        end -= 1

    removed_text = "\n".join(lines[start:block["line_end"] + 1])
    lines = lines[:start] + lines[end:]

    # Clean up triple+ blank lines
    cleaned = []
    blank_count = 0
    for line in lines:
        if line.strip() == "":
            blank_count += 1
            if blank_count <= 2:
                cleaned.append(line)
        else:
            blank_count = 0
            cleaned.append(line)

    write_lines(fp, cleaned)

    print(json.dumps({
        "success": True,
        "code": code,
        "file": args.file,
        "removed_block": removed_text,
    }))

# ── Subcommand: set-release ──────────────────────────────────────────────────

def cmd_set_release(args):
    """Set or clear the Release: field on a task block."""
    root = get_main_repo_root()
    code = args.code.upper()
    version = args.version  # "None" or a semver string

    # Find the task across all task files
    block, source_file = find_block_in_all(root, code, TASK_FILES)
    if not block:
        print(json.dumps({"error": f"Task {code} not found in any task file"}))
        sys.exit(1)

    fp = root / source_file
    lines = read_lines(fp)

    # Find the Dependencies: line within the block range
    dep_line_idx = None
    release_line_idx = None
    for idx in range(block["line_start"], block["line_end"] + 1):
        stripped = lines[idx].strip()
        if stripped.startswith("Dependencies:"):
            dep_line_idx = idx
        if stripped.startswith("Release:"):
            release_line_idx = idx

    release_value = "None" if version in ("None", "none", "") else version
    new_release_line = f"  Release: {release_value}"

    if release_line_idx is not None:
        # Update existing Release: line
        lines[release_line_idx] = new_release_line
    elif dep_line_idx is not None:
        # Insert after Dependencies: line
        lines.insert(dep_line_idx + 1, new_release_line)
    else:
        # Fallback: insert after the second separator line (line_start + 2)
        insert_at = block["line_start"] + 2
        lines.insert(insert_at, new_release_line)

    write_lines(fp, lines)

    print(json.dumps({
        "success": True,
        "code": code,
        "file": source_file,
        "release": release_value,
    }))

# ── Subcommand: schedule-tasks ──────────────────────────────────────────────

def cmd_schedule_tasks(args):
    """Assign one or more tasks to a release milestone in a single call."""
    root = get_main_repo_root()
    version = args.version.lstrip("v")
    codes = [c.strip().upper() for c in args.codes.split(",") if c.strip()]

    if not codes:
        print(json.dumps({"error": "No task codes provided"}))
        sys.exit(1)

    # Verify release exists in releases.json
    releases_fp = root / "releases.json"
    if not releases_fp.exists():
        print(json.dumps({"error": "releases.json not found"}))
        sys.exit(1)
    try:
        data = json.loads(releases_fp.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(json.dumps({"error": f"Cannot read releases.json: {e}"}))
        sys.exit(1)

    releases = data.get("releases", [])
    target = None
    for r in releases:
        if r.get("version", "").lstrip("v") == version:
            target = r
            break
    if target is None:
        print(json.dumps({"error": f"Release {version} not found in releases.json"}))
        sys.exit(1)

    results = []
    for code in codes:
        # 1. Verify task exists
        block, source_file = find_block_in_all(root, code, TASK_FILES)
        if not block:
            results.append({"code": code, "success": False, "error": "Task not found"})
            continue

        # 2. Set Release: field on the task block
        fp = root / source_file
        lines = read_lines(fp)
        dep_line_idx = None
        release_line_idx = None
        for idx in range(block["line_start"], block["line_end"] + 1):
            stripped = lines[idx].strip()
            if stripped.startswith("Dependencies:"):
                dep_line_idx = idx
            if stripped.startswith("Release:"):
                release_line_idx = idx

        new_release_line = f"  Release: {version}"
        if release_line_idx is not None:
            lines[release_line_idx] = new_release_line
        elif dep_line_idx is not None:
            lines.insert(dep_line_idx + 1, new_release_line)
        else:
            insert_at = block["line_start"] + 2
            lines.insert(insert_at, new_release_line)
        write_lines(fp, lines)

        # 3. Add to releases.json tasks list (if not already there)
        if code not in target.get("tasks", []):
            target.setdefault("tasks", []).append(code)

        results.append({"code": code, "success": True, "version": version})

    # Write updated releases.json
    with open(releases_fp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    scheduled = sum(1 for r in results if r["success"])
    failed = sum(1 for r in results if not r["success"])
    print(json.dumps({
        "version": version,
        "results": results,
        "scheduled": scheduled,
        "failed": failed,
    }, indent=2))

# ── Subcommand: hook ─────────────────────────────────────────────────────────

def cmd_hook(args):
    root = get_main_repo_root()
    filepath = args.filepath
    filename = os.path.basename(filepath)

    # Check progressing tasks for file correlation
    prog_path = root / "progressing.txt"
    related = None
    if prog_path.exists():
        for block in parse_blocks(prog_path):
            if block["block_type"] != "task":
                continue
            all_files = block.get("files_create", []) + block.get("files_modify", [])
            for f in all_files:
                if os.path.basename(f) == filename or f == filepath:
                    related = block
                    break
            if related:
                break

    if related:
        print(f"\n--- Related Task ---")
        print(f"  File:   {filepath}")
        print(f"  Task:   [{related['code']}] {related['title']}")
        print(f"  Status: {related['status'].upper()}")
        print(f"--------------------")

    # Print summary
    counts = {"done": 0, "progressing": 0, "todo": 0, "blocked": 0}
    for fname, expected in [
        ("done.txt", ["done"]),
        ("progressing.txt", ["progressing"]),
        ("to-do.txt", ["todo", "blocked"]),
    ]:
        fp = root / fname
        if not fp.exists():
            continue
        for block in parse_blocks(fp):
            if block["block_type"] == "task" and block["status"] in expected:
                counts[block["status"]] += 1

    total = sum(counts.values())
    if total > 0:
        pct = counts["done"] * 100 // total
        print(f"\n=== TASK SUMMARY ===")
        print(f"  Completed:   {counts['done']}/{total}")
        print(f"  In progress: {counts['progressing']}")
        print(f"  Todo:        {counts['todo']}")
        print(f"  Blocked:     {counts['blocked']}")
        print(f"  Progress:    {pct}%")
        print(f"=====================")

# ── Subcommand: find-files ──────────────────────────────────────────────────

def cmd_find_files(args):
    """Cross-platform file search using pathlib glob."""
    root = get_main_repo_root()
    patterns = [p.strip() for p in args.patterns.split(",") if p.strip()]
    results = []

    for pattern in patterns:
        for match in sorted(root.rglob(pattern)):
            if not match.is_file():
                continue
            try:
                rel = match.relative_to(root)
            except ValueError:
                continue
            # Respect max-depth
            if args.max_depth is not None and len(rel.parts) > args.max_depth:
                continue
            # Skip common ignored directories
            parts_str = str(rel)
            if any(skip in parts_str for skip in ["node_modules", ".git", "__pycache__", ".venv", "venv"]):
                continue
            results.append(str(rel))
            if len(results) >= args.limit:
                break
        if len(results) >= args.limit:
            break

    if args.format == "json":
        print(json.dumps(results[:args.limit]))
    else:
        if not results:
            print("(none found)")
        else:
            for r in results[:args.limit]:
                print(r)

# ── Subcommand: platform-cmd ───────────────────────────────────────────────

def _load_platform_config():
    """Load platform config (reuses platform-config logic).

    # GitLab URL support: design decision pending; current implementation targets GitHub-only repos
    """
    root = get_main_repo_root()
    for candidate in ["issues-tracker.json", "github-issues.json"]:
        fp = root / ".claude" / candidate
        if fp.exists():
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            platform = data.get("platform", "github")
            return {
                "platform": platform,
                "repo": data.get("repo", ""),
                "cli": "glab" if platform == "gitlab" else "gh",
                "labels": data.get("labels", {}),
            }
    return {"platform": "github", "repo": "", "cli": "gh", "labels": {}}

def _get_cached_merge_strategy(target_branch: str) -> str:
    """Read the cached merge strategy for a target branch from issues-tracker.json.

    Returns one of 'squash', 'merge', 'rebase', or '' if not cached.
    Falls back to checking the production branch config if the target
    branch is not explicitly configured.
    """
    root = get_main_repo_root()
    for name in ("issues-tracker.json", "github-issues.json"):
        fp = root / ".claude" / name
        if fp.exists():
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
                branches = data.get("branches", {})
                # Direct match
                if target_branch and target_branch in branches:
                    info = branches[target_branch]
                    if isinstance(info, dict):
                        return info.get("merge_strategy", "")
                # Fall back to the production branch's merge strategy
                for bname, binfo in branches.items():
                    if isinstance(binfo, dict) and binfo.get("role") == "production" and binfo.get("merge_strategy"):
                        return binfo["merge_strategy"]
            except (json.JSONDecodeError, OSError):
                pass
            break
    return ""


def _get_cached_merge_flag(target_branch: str) -> str:
    """Return the gh CLI merge flag based on cached merge strategy.

    Returns '--squash', '--rebase', or '--merge' (default).
    """
    strategy = _get_cached_merge_strategy(target_branch)
    if strategy == "squash":
        return "--squash"
    elif strategy == "rebase":
        return "--rebase"
    return "--merge"


def _shlex_quote(s: str) -> str:
    """Quote a string for shell use (cross-platform safe)."""
    if not s:
        return "''"
    # Simple quoting: if no special chars, return as-is
    import shlex
    return shlex.quote(s)

def cmd_platform_cmd(args):
    """Generate the correct platform CLI command string."""
    cfg = _load_platform_config()
    cli = cfg["cli"]
    repo = cfg["repo"]
    op = args.operation

    # Collect all extra key=value args into a dict
    params = {}
    if args.params:
        for p in args.params:
            if "=" in p:
                k, v = p.split("=", 1)
                params[k] = v

    cmd = None

    if cli == "gh":
        if op == "list-issues":
            cmd = f'gh issue list --repo "{repo}"'
            if params.get("labels"):
                cmd += f' --label "{params["labels"]}"'
            cmd += f' --state {params.get("state", "open")}'
            cmd += f' --json {params.get("json", "number,title")}'
            if params.get("jq"):
                cmd += f" --jq '{params['jq']}'"
        elif op == "search-issues":
            cmd = f'gh issue list --repo "{repo}"'
            cmd += f' --search "{params.get("search", "")}"'
            if params.get("labels"):
                cmd += f' --label "{params["labels"]}"'
            cmd += f' --state {params.get("state", "open")}'
            cmd += f' --json {params.get("json", "number,title")}'
        elif op == "view-issue":
            cmd = f'gh issue view {params.get("number", "N")} --repo "{repo}"'
            cmd += f' --json {params.get("json", "body")} --jq \'{params.get("jq", ".body")}\''
        elif op == "edit-issue":
            cmd = f'gh issue edit {params.get("number", "N")} --repo "{repo}"'
            if params.get("add-labels"):
                cmd += f' --add-label "{params["add-labels"]}"'
            if params.get("remove-labels"):
                cmd += f' --remove-label "{params["remove-labels"]}"'
            if params.get("add-assignee"):
                cmd += f' --add-assignee "{params["add-assignee"]}"'
        elif op == "close-issue":
            cmd = f'gh issue close {params.get("number", "N")} --repo "{repo}"'
            if params.get("comment"):
                cmd += f' --comment "{params["comment"]}"'
        elif op == "comment-issue":
            cmd = f'gh issue comment {params.get("number", "N")} --repo "{repo}"'
            cmd += f' --body "{params.get("body", "")}"'
        elif op == "create-issue":
            cmd = f'gh issue create --repo "{repo}"'
            cmd += f' --title "{params.get("title", "")}"'
            cmd += f' --body "{params.get("body", "")}"'
            if params.get("labels"):
                cmd += f' --label "{params["labels"]}"'
            if params.get("assignee"):
                cmd += f' --assignee "{params["assignee"]}"'
        elif op == "create-pr":
            cmd = f'gh pr create'
            cmd += f' --base {params.get("base", "main")}'
            cmd += f' --head {params.get("head", "")}'
            cmd += f' --title "{params.get("title", "")}"'
            cmd += f' --body "{params.get("body", "")}"'
            if params.get("milestone"):
                cmd += f' --milestone "{params["milestone"]}"'
            if params.get("assignee"):
                cmd += f' --assignee "{params["assignee"]}"'  
        elif op == "list-pr":
            cmd = f'gh pr list'
            cmd += f' --base {params.get("base", "main")}'
            cmd += f' --head {params.get("head", "")}'
            cmd += f' --state {params.get("state", "open")}'
            cmd += f' --json {params.get("json", "number,url")}'
            if params.get("jq"):
                cmd += f" --jq '{params['jq']}'"
        elif op == "merge-pr":
            merge_flag = _get_cached_merge_flag(params.get("base", ""))
            pr_url = _shlex_quote(params.get("url", ""))
            cmd = f'gh pr merge {pr_url} --auto {merge_flag}'
        elif op == "create-release":
            cmd = f'gh release create "{params.get("tag", "")}" --repo "{repo}"'
            cmd += f' --title "{params.get("title", "")}"'
            cmd += f' --notes "{params.get("notes", "")}"'
            if params.get("prerelease") == "true":
                cmd += " --prerelease"
        elif op == "edit-release":
            cmd = f'gh release edit "{params.get("tag", "")}" --repo "{repo}"'
            cmd += f' --notes "{params.get("notes", "")}"'
        elif op == "list-ci-runs":
            ref = params.get("ref", "")
            cmd = f'gh run list --repo "{repo}" --json databaseId,name,status,conclusion,workflowName --limit {DEFAULT_CI_RUNS_LIMIT}'
            cmd += f""" -q '[.[] | select(.headBranch=="{ref}" or .headSha=="{ref}")]'"""
        elif op == "delete-release":
            cmd = f'gh release delete "{params.get("tag", "")}" --repo "{repo}" --yes'
        elif op == "create-milestone":
            title = _shlex_quote(params.get("title", ""))
            cmd = f'gh api repos/{repo}/milestones --method POST -f title={title}'
        elif op == "close-milestone":
            title = _shlex_quote(params.get("title", ""))
            # Two-step: resolve milestone number from title, then PATCH state to closed
            cmd = (
                f'gh api repos/{repo}/milestones --jq '
                f"'.[] | select(.title=={title}) | .number' "
                f'| xargs -I {{}} gh api repos/{repo}/milestones/{{}} '
                f'--method PATCH -f state=closed'
            )
        else:
            print(json.dumps({"error": f"Unknown operation: {op}"}))
            sys.exit(1)

    elif cli == "glab":
        if op == "list-issues":
            cmd = f'glab issue list -R "{repo}"'
            if params.get("labels"):
                cmd += f' -l "{params["labels"]}"'
            state = params.get("state", "open")
            cmd += f' --state {"opened" if state == "open" else state}'
            cmd += f' --output json'
            if params.get("jq"):
                cmd += f" | jq '{params['jq']}'"
        elif op == "search-issues":
            cmd = f'glab issue list -R "{repo}"'
            cmd += f' --search "{params.get("search", "")}"'
            if params.get("labels"):
                cmd += f' -l "{params["labels"]}"'
            cmd += ' --output json'
        elif op == "view-issue":
            cmd = f'glab issue view {params.get("number", "N")} -R "{repo}"'
            cmd += f' --output json | jq \'{params.get("jq", ".description")}\''
        elif op == "edit-issue":
            cmd = f'glab issue update {params.get("number", "N")} -R "{repo}"'
            if params.get("add-labels"):
                cmd += f' --label "{params["add-labels"]}"'
            if params.get("remove-labels"):
                cmd += f' --unlabel "{params["remove-labels"]}"'
            if params.get("add-assignee"):
                # GitLab CLI does not support --add-assignee; use API PATCH
                number = params.get("number", "N")
                encoded_repo = repo.replace("/", "%2F")
                cmd += f' && glab api --method PUT "projects/{encoded_repo}/issues/{number}" -f add_labels="" -f assignee_ids[]={params["add-assignee"]}'
        elif op == "close-issue":
            cmd = f'glab issue close {params.get("number", "N")} -R "{repo}"'
            if params.get("comment"):
                cmd += f'\nglab issue note {params.get("number", "N")} -R "{repo}" -m "{params["comment"]}"'
        elif op == "comment-issue":
            cmd = f'glab issue note {params.get("number", "N")} -R "{repo}"'
            cmd += f' -m "{params.get("body", "")}"'
        elif op == "create-issue":
            cmd = f'glab issue create -R "{repo}"'
            cmd += f' --title "{params.get("title", "")}"'
            cmd += f' --description "{params.get("body", "")}"'
            if params.get("labels"):
                cmd += f' -l "{params["labels"]}"'
            if params.get("assignee"):
                cmd += f' --assignee-id "{params["assignee"]}"'
        elif op == "create-pr":
            cmd = f'glab mr create'
            cmd += f' --target-branch {params.get("base", "main")}'
            cmd += f' --source-branch {params.get("head", "")}'
            cmd += f' --title "{params.get("title", "")}"'
            cmd += f' --description "{params.get("body", "")}"'
            if params.get("milestone"):
                cmd += f' --milestone "{params["milestone"]}"'
            if params.get("assignee"):
                cmd += f' --assignee "{params["assignee"]}"'  
        elif op == "list-pr":
            cmd = f'glab mr list'
            cmd += f' --target-branch {params.get("base", "main")}'
            cmd += f' --source-branch {params.get("head", "")}'
            state = params.get("state", "open")
            cmd += f' --state {"opened" if state == "open" else state}'
            cmd += ' --output json'
            if params.get("jq"):
                cmd += f" | jq '{params['jq']}'"
        elif op == "merge-pr":
            squash_flag = ""
            strategy = _get_cached_merge_strategy(params.get("base", ""))
            if strategy == "squash":
                squash_flag = " --squash"
            mr_number = _shlex_quote(params.get("number", ""))
            cmd = f'glab mr merge {mr_number} --auto-merge --when-pipeline-succeeds{squash_flag}'
        elif op == "create-release":
            cmd = f'glab release create "{params.get("tag", "")}" --name "{params.get("title", "")}"'
            cmd += f' --notes "{params.get("notes", "")}"'
        elif op == "edit-release":
            cmd = f'glab release update "{params.get("tag", "")}"'
            cmd += f' --notes "{params.get("notes", "")}"'
        elif op == "list-ci-runs":
            ref = params.get("ref", "")
            cmd = f'glab ci list --repo "{repo}" --ref "{ref}" --output json'
        elif op == "delete-release":
            cmd = f'glab release delete "{params.get("tag", "")}" --repo "{repo}" --yes'
        elif op == "create-milestone":
            title = _shlex_quote(params.get("title", ""))
            cmd = f'glab api projects/:id/milestones --method POST -f title={title}'
        elif op == "close-milestone":
            title = _shlex_quote(params.get("title", ""))
            # Two-step: resolve milestone ID from title, then PUT state_event to close
            cmd = (
                f'glab api projects/:id/milestones --jq '
                f"'.[] | select(.title=={title}) | .id' "
                f'| xargs -I {{}} glab api projects/:id/milestones/{{}} '
                f'--method PUT -f state_event=close'
            )
        else:
            print(json.dumps({"error": f"Unknown operation: {op}"}))
            sys.exit(1)

    print(cmd)

# ── Subcommand: sync-from-platform ────────────────────────────────────────

def cmd_sync_from_platform(args):
    """Reconcile local task files with platform issue state.

    Queries GitHub/GitLab for issues with status labels and compares
    against local files. Reports discrepancies and optionally fixes them.
    """
    cfg = _load_platform_config()

    if cfg["mode"] == "local-only":
        result = {"status": "skipped", "reason": "Platform integration not enabled (local-only mode)"}
        if args.format == "json":
            print(json.dumps(result, indent=2))
        else:
            print("Sync skipped: platform integration not enabled (local-only mode)")
        return

    cli = cfg["cli"]
    repo = cfg["repo"]
    labels = cfg.get("labels") or {}
    source_label = labels.get("source", "claude-code")
    task_label = labels.get("task", "task")
    status_labels = labels.get("status", {})

    # Map platform status labels to local status
    platform_to_local = {}
    for local_status, label_name in status_labels.items():
        platform_to_local[label_name] = local_status

    # ── Fetch issues from platform ───────────────────────────────────
    discrepancies = []

    if cli == "gh":
        result = subprocess.run(
            ["gh", "issue", "list", "--repo", repo,
             "--label", f"{task_label},{source_label}",
             "--state", "all", "--limit", str(DEFAULT_ISSUE_FETCH_LIMIT),
             "--json", "number,title,state,labels"],
            capture_output=True, text=True,
        )
    else:
        result = subprocess.run(
            ["glab", "issue", "list", "-R", repo,
             "-l", f"{task_label},{source_label}",
             "--state", "all", "--per-page", str(DEFAULT_ISSUE_FETCH_LIMIT),
             "--output", "json"],
            capture_output=True, text=True,
        )

    if result.returncode != 0:
        err = {"error": f"Failed to fetch issues: {result.stderr.strip()}"}
        print(json.dumps(err, indent=2) if args.format == "json" else err["error"])
        sys.exit(1)

    try:
        issues = json.loads(result.stdout) if result.stdout.strip() else []
    except json.JSONDecodeError:
        err = {"error": "Failed to parse platform response as JSON"}
        print(json.dumps(err, indent=2) if args.format == "json" else err["error"])
        sys.exit(1)

    # ── Parse local tasks ────────────────────────────────────────────
    root = get_main_repo_root()
    local_tasks = {}
    for tf in TASK_FILES:
        fp = root / tf
        if fp.exists():
            blocks = _parse_blocks(fp)
            for b in blocks:
                local_tasks[b["code"]] = {
                    "status": b["status"],
                    "title": b["title"],
                    "file": tf,
                }

    # ── Compare ──────────────────────────────────────────────────────
    for issue in issues:
        issue_labels = []
        if cli == "gh":
            issue_labels = [l["name"] for l in issue.get("labels", [])]
            issue_state = issue.get("state", "OPEN")
            issue_num = issue.get("number")
            issue_title = issue.get("title", "")
        else:
            issue_labels = [l.get("name", "") if isinstance(l, dict) else str(l)
                           for l in issue.get("labels", [])]
            issue_state = issue.get("state", "opened")
            issue_num = issue.get("iid", issue.get("number"))
            issue_title = issue.get("title", "")

        # Determine platform status from labels
        platform_status = None
        for label in issue_labels:
            if label in platform_to_local:
                platform_status = platform_to_local[label]
                break

        # Check if issue is closed on platform
        is_closed = issue_state in ("CLOSED", "closed")
        if is_closed:
            platform_status = "done"

        # Try to find matching local task by title keywords
        # (issues may not contain the task code directly)
        matched_code = None
        for code, info in local_tasks.items():
            if code in issue_title or info["title"] in issue_title:
                matched_code = code
                break

        if matched_code and platform_status:
            local_status = local_tasks[matched_code]["status"]
            # Normalize local status name
            local_status_name = local_status
            if local_status_name == "progressing":
                local_status_name = "in-progress"

            platform_status_name = platform_status
            if platform_status_name == "progressing":
                platform_status_name = "in-progress"

            if local_status_name != platform_status_name:
                discrepancies.append({
                    "task_code": matched_code,
                    "issue_number": issue_num,
                    "title": issue_title,
                    "local_status": local_status_name,
                    "platform_status": platform_status_name,
                    "local_file": local_tasks[matched_code]["file"],
                })

    # ── Output results ───────────────────────────────────────────────
    output = {
        "platform_issues_checked": len(issues),
        "local_tasks_checked": len(local_tasks),
        "discrepancies": discrepancies,
    }

    if args.format == "json":
        print(json.dumps(output, indent=2))
    else:
        print(f"Checked {len(issues)} platform issues against {len(local_tasks)} local tasks")
        if not discrepancies:
            print("No discrepancies found — local and platform are in sync.")
        else:
            print(f"\n{len(discrepancies)} discrepancy(ies) found:\n")
            for d in discrepancies:
                print(f"  {d['task_code']} (issue #{d['issue_number']}): "
                      f"local={d['local_status']}, platform={d['platform_status']}")
                if not args.dry_run:
                    # Map platform status back to local move target
                    target = d["platform_status"]
                    if target == "in-progress":
                        target = "progressing"
                    if target in FILE_FOR_STATUS:
                        print(f"    → Would move to {FILE_FOR_STATUS[target]} "
                              f"(run without --dry-run to apply)")
            if args.dry_run:
                print("\n  (dry-run mode — no changes made)")
            else:
                print("\n  To apply changes, use task_manager.py move <code> --to <status>")

# ── Subcommand: pr-body ───────────────────────────────────────────────────

PR_BODY_FOOTER = {
    "task-pick": "*Generated by Claude Code via `/task pick`*",
    "test-review": "*Generated by Claude Code via `/release`*",
    "release": "*Generated by Claude Code via `/release`*",
}

PR_BODY_TEMPLATES = {
    "task-pick": """## Task {task_code} — {title}

### Summary
{summary}

{issue_ref}
{footer}""",

    "test-review": """## Task {task_code} — {title}

### Summary
Task tested and verified by release test pipeline.

### Test Results
{summary}

{issue_ref}
{footer}""",

    "release": """## Changes
{summary}

{issue_ref}
{footer}""",
}

def cmd_pr_body(args):
    """Generate a PR body from template."""
    source = args.source
    template = PR_BODY_TEMPLATES.get(source, PR_BODY_TEMPLATES["task-pick"])

    issue_ref = ""
    if args.issue_num:
        issue_ref = f"### Related Issue\nRefs #{args.issue_num}"
        if args.task_code:
            issue_ref += f" ({args.task_code})"
        issue_ref += "\n"

    # Check if footer is enabled in project config
    project_cfg = load_project_config()
    show_footer = project_cfg.get("show_generated_footer", True)
    footer_text = ""
    if show_footer:
        footer_text = "---\n" + PR_BODY_FOOTER.get(source, PR_BODY_FOOTER["task-pick"])

    body = template.format(
        task_code=args.task_code or "",
        title=args.title or "",
        summary=args.summary or "",
        issue_ref=issue_ref,
        footer=footer_text,
    )

    # Clean up empty sections
    body = re.sub(r'\n\n\n+', '\n\n', body)
    print(body.strip())

# ── Release-task helpers ─────────────────────────────────────────────────────

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
                if enabled and not sync:
                    return False
                return True
            except (json.JSONDecodeError, OSError):
                pass
    return True

def _releases_path() -> Path:
    """Return path to releases.json in the main repo root."""
    return get_main_repo_root() / "releases.json"

def _read_releases_local() -> list[dict]:
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

def _write_releases_local(releases: list[dict]) -> None:
    """Write releases list to releases.json."""
    fp = _releases_path()
    with open(fp, "w", encoding="utf-8") as f:
        json.dump({"releases": releases}, f, indent=2)
        f.write("\n")

# ── Subcommand: list-release-tasks ──────────────────────────────────────────

def cmd_list_release_tasks(args):
    """Cross-reference a release's task list with local task file statuses."""
    if not _uses_local_files():
        print(json.dumps({"error": "releases.json is not used in platform-only mode. Use platform milestones instead."}))
        sys.exit(1)
    root = get_main_repo_root()
    version = args.version.lstrip("v")

    # Find the release entry
    releases = _read_releases_local()
    release_entry = None
    for r in releases:
        if r.get("version", "").lstrip("v") == version:
            release_entry = r
            break

    if release_entry is None:
        print(json.dumps({"error": f"Release {version} not found in releases.json"}))
        sys.exit(1)

    task_codes = release_entry.get("tasks", [])

    # Build a lookup of all tasks across local files
    task_lookup = {}
    for fname in TASK_FILES:
        fp = root / fname
        if not fp.exists():
            continue
        for block in parse_blocks(fp):
            if block["block_type"] == "task":
                task_lookup[block["code"]] = {
                    "code": block["code"],
                    "title": block["title"],
                    "status": block["status"],
                    "priority": block.get("priority", ""),
                    "dependencies": block.get("dependencies", "None"),
                    "file": fname,
                }

    # Build result list
    tasks = []
    counts = {"done": 0, "progressing": 0, "todo": 0, "not_found": 0}
    for code in task_codes:
        if code in task_lookup:
            entry = task_lookup[code]
            tasks.append(entry)
            status = entry["status"]
            if status == "done":
                counts["done"] += 1
            elif status == "progressing":
                counts["progressing"] += 1
            else:
                counts["todo"] += 1
        else:
            tasks.append({
                "code": code,
                "title": "",
                "status": "not-found",
                "priority": "",
                "dependencies": "None",
                "file": "",
            })
            counts["not_found"] += 1

    result = {
        "tasks": tasks,
        "total": len(tasks),
        "done": counts["done"],
        "progressing": counts["progressing"],
        "todo": counts["todo"],
        "not_found": counts["not_found"],
    }

    if args.format == "text":
        print(f"Release {version} — {len(tasks)} tasks")
        print(f"  Done: {counts['done']}  Progressing: {counts['progressing']}  "
              f"To-do: {counts['todo']}  Not found: {counts['not_found']}")
        print()
        fmt = "{:<12} {:<14} {:<10} {:<10} {}"
        print(fmt.format("CODE", "STATUS", "PRIORITY", "FILE", "TITLE"))
        print("-" * 78)
        for t in tasks:
            print(fmt.format(
                t["code"],
                t["status"],
                t["priority"] or "-",
                t["file"] or "-",
                t["title"] or "-",
            ))
    else:
        print(json.dumps(result, indent=2))

# ── Subcommand: create-patch-task ───────────────────────────────────────────

def cmd_create_patch_task(args):
    """Create a release patch task with auto-generated RPAT- code."""
    if not _uses_local_files():
        print(json.dumps({"error": "releases.json is not used in platform-only mode. Use platform issues instead."}))
        sys.exit(1)
    root = get_main_repo_root()
    version = args.release.lstrip("v")

    # Compute next RPAT-XXXX ID by scanning all task files
    max_num = 0
    rpat_re = re.compile(r"RPAT-(\d{4})")
    for fname in TASK_FILES:
        fp = root / fname
        if not fp.exists():
            continue
        for block in parse_blocks(fp):
            if block["block_type"] == "task":
                m = rpat_re.match(block["code"])
                if m:
                    num = int(m.group(1))
                    if num > max_num:
                        max_num = num
    next_num = max_num + 1
    code = f"RPAT-{next_num:04d}"

    # Build the task block
    block_text = (
        f"{SEPARATOR}\n"
        f"[ ] {code} — {args.title}\n"
        f"{SEPARATOR}\n"
        f"  Priority: {args.priority}\n"
        f"  Dependencies: None\n"
        f"  Release: {version}\n"
        f"\n"
        f"  DESCRIPTION:\n"
        f"  {args.description}\n"
        f"\n"
        f"  Source: {args.source}\n"
        f"\n"
        f"  TECHNICAL DETAILS:\n"
        f"  Patch task created by /release pipeline.\n"
        f"\n"
        f"  Files involved:\n"
        f"    MODIFY:  (to be determined during implementation)\n"
    )

    # Append to to-do.txt
    todo_path = root / "to-do.txt"
    existing = ""
    if todo_path.exists():
        existing = todo_path.read_text(encoding="utf-8")

    # Ensure a blank line before the new block if the file doesn't end with one
    if existing and not existing.endswith("\n\n"):
        if existing.endswith("\n"):
            existing += "\n"
        else:
            existing += "\n\n"

    with open(todo_path, "w", encoding="utf-8") as f:
        f.write(existing + block_text)

    # Update releases.json to add this task code to the release's tasks array
    releases = _read_releases_local()
    found = False
    for r in releases:
        if r.get("version", "").lstrip("v") == version:
            if "tasks" not in r:
                r["tasks"] = []
            r["tasks"].append(code)
            found = True
            break

    if found:
        _write_releases_local(releases)

    print(json.dumps({
        "success": True,
        "code": code,
        "release": version,
        "title": args.title,
    }))

# ── Subcommand: register-agent ─────────────────────────────────────────────

def cmd_register_agent(args):
    """Register an agent with the memory consistency protocol.

    Used by ``/task pick all`` and ``/release`` stage 4 when spawning
    parallel sub-agents. Each agent receives a unique ID and session.
    """
    main_root = get_main_repo_root()
    task_code = getattr(args, "task_code", "") or ""
    agent_type = getattr(args, "agent_type", "task") or "task"

    try:
        from memory_protocol import MemoryProtocol, generate_agent_id

        protocol = MemoryProtocol(main_root)
        agent_id = generate_agent_id(prefix=agent_type)
        session = protocol.register_agent(
            agent_id=agent_id,
            agent_type=agent_type,
            task_code=task_code,
        )
        print(json.dumps({
            "success": True,
            "agent_id": agent_id,
            "session_id": session.session_id,
            "agent_type": agent_type,
            "task_code": task_code,
            "env_vars": {
                "CLAW_AGENT_ID": agent_id,
                "CLAW_SESSION_ID": session.session_id,
                "CLAW_AGENT_TYPE": agent_type,
                "CLAW_TASK_CODE": task_code,
            },
        }))
    except ImportError:
        # memory_protocol not available — return stub values
        import uuid as _uuid
        fallback_id = f"{agent_type}-{str(_uuid.uuid4())[:8]}-{os.getpid()}"
        print(json.dumps({
            "success": True,
            "agent_id": fallback_id,
            "session_id": "",
            "agent_type": agent_type,
            "task_code": task_code,
            "env_vars": {
                "CLAW_AGENT_ID": fallback_id,
                "CLAW_SESSION_ID": "",
                "CLAW_AGENT_TYPE": agent_type,
                "CLAW_TASK_CODE": task_code,
            },
            "note": "memory_protocol not available — running without coordination",
        }))


def cmd_deregister_agent(args):
    """Deregister an agent session on completion."""
    main_root = get_main_repo_root()
    session_id = getattr(args, "session_id", "") or ""

    if not session_id:
        print(json.dumps({"success": False, "error": "session_id required"}))
        return

    try:
        from memory_protocol import MemoryProtocol

        protocol = MemoryProtocol(main_root)
        protocol.deregister_agent(session_id)
        print(json.dumps({
            "success": True,
            "session_id": session_id,
            "status": "completed",
        }))
    except ImportError:
        print(json.dumps({
            "success": True,
            "session_id": session_id,
            "note": "memory_protocol not available — no-op",
        }))


# ── CLI Setup ────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Task and idea manager CLI for codeclaw",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # platform-config
    p = sub.add_parser("platform-config", help="Return platform tracker configuration")
    p.set_defaults(func=cmd_platform_config)

    # next-id
    p = sub.add_parser("next-id", help="Compute next sequential ID")
    p.add_argument("--type", choices=["task", "idea"], default="task")
    p.add_argument("--source", choices=["local", "platform-titles"], default="local",
                    help="Data source: local files (default) or platform titles from stdin")
    p.set_defaults(func=cmd_next_id)

    # list
    p = sub.add_parser("list", help="List tasks by status")
    p.add_argument("--status", choices=["todo", "progressing", "done", "blocked", "all"], default="all")
    p.add_argument("--format", choices=["json", "summary"], default="json")
    p.set_defaults(func=cmd_list)

    # list-ideas
    p = sub.add_parser("list-ideas", help="List ideas")
    p.add_argument("--file", choices=["ideas", "disapproved", "all"], default="all")
    p.add_argument("--format", choices=["json", "summary"], default="json")
    p.set_defaults(func=cmd_list_ideas)

    # parse
    p = sub.add_parser("parse", help="Parse a task/idea block to JSON")
    p.add_argument("code", help="Task or idea code (e.g., AUTH-0001, IDEA-SEC-0003)")
    p.set_defaults(func=cmd_parse)

    # summary
    p = sub.add_parser("summary", help="Task counts and progress")
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=cmd_summary)

    # prefixes
    p = sub.add_parser("prefixes", help="List all task code prefixes")
    p.set_defaults(func=cmd_prefixes)

    # sections
    p = sub.add_parser("sections", help="List section headers from a file")
    p.add_argument("--file", required=True, help="File to scan (e.g., to-do.txt)")
    p.set_defaults(func=cmd_sections)

    # duplicates
    p = sub.add_parser("duplicates", help="Search for duplicate keywords")
    p.add_argument("--keywords", required=True, help="Comma-separated keywords")
    p.add_argument("--files", default=None, help="Comma-separated file list (default: all)")
    p.set_defaults(func=cmd_duplicates)

    # verify-files
    p = sub.add_parser("verify-files", help="Check file existence for a task")
    p.add_argument("code", help="Task code (e.g., AUTH-0001)")
    p.set_defaults(func=cmd_verify_files)

    # semantic-explore
    p = sub.add_parser("semantic-explore",
                        help="Explore codebase semantically for a task using vector search")
    p.add_argument("code", help="Task code (e.g., AUTH-0001)")
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=cmd_semantic_explore)

    # is-frontend-task
    p = sub.add_parser("is-frontend-task", help="Check if a task involves frontend work")
    p.add_argument("code", help="Task code (e.g., AUTH-0001)")
    p.add_argument("--json-body", default=None,
                    help="JSON task data for platform-only mode (description, files, etc.)")
    p.set_defaults(func=cmd_is_frontend_task)

    # add-test-procedure
    p = sub.add_parser("add-test-procedure", help="Append TEST PROCEDURE section to a progressing task block")
    p.add_argument("code", help="Task code (e.g., AUTH-0001)")
    p.add_argument("--body", required=True, help="Test procedure text")
    p.set_defaults(func=cmd_add_test_procedure)

    # move
    p = sub.add_parser("move", help="Move a task between files")
    p.add_argument("code", help="Task code (e.g., AUTH-0001)")
    p.add_argument("--to", required=True, choices=["todo", "progressing", "done"])
    p.add_argument("--completed-summary", default=None, help="Summary for COMPLETED field (when moving to done)")
    p.set_defaults(func=cmd_move)

    # remove
    p = sub.add_parser("remove", help="Remove a block from a file")
    p.add_argument("code", help="Task or idea code")
    p.add_argument("--file", required=True, help="File to remove from")
    p.set_defaults(func=cmd_remove)

    # set-release
    p = sub.add_parser("set-release", help="Set or clear the Release field on a task")
    p.add_argument("code", help="Task code (e.g., AUTH-0001)")
    p.add_argument("--version", required=True, help="Release version (e.g., 1.1.0) or 'None' to clear")
    p.set_defaults(func=cmd_set_release)

    # schedule-tasks
    p = sub.add_parser("schedule-tasks", help="Assign one or more tasks to a release milestone")
    p.add_argument("--codes", required=True, help="Comma-separated task codes (e.g., AUTH-0001,FEAT-0002)")
    p.add_argument("--version", required=True, help="Release version (e.g., 1.2.0)")
    p.set_defaults(func=cmd_schedule_tasks)

    # hook
    p = sub.add_parser("hook", help="PostToolUse hook mode")
    p.add_argument("filepath", nargs="?", default="", help="Modified file path")
    p.set_defaults(func=cmd_hook)

    # find-files
    p = sub.add_parser("find-files", help="Cross-platform file search")
    p.add_argument("--patterns", required=True, help="Comma-separated glob patterns")
    p.add_argument("--max-depth", type=int, default=None, help="Max directory depth")
    p.add_argument("--limit", type=int, default=DEFAULT_FIND_FILES_LIMIT, help="Max results")
    p.add_argument("--format", choices=["json", "text"], default="text")
    p.set_defaults(func=cmd_find_files)

    # platform-cmd
    p = sub.add_parser("platform-cmd", help="Generate platform-specific CLI command")
    p.add_argument("operation", help="Operation name (e.g., create-issue, list-issues)")
    p.add_argument("params", nargs="*", help="Key=value parameters (e.g., title=T labels=L)")
    p.set_defaults(func=cmd_platform_cmd)

    # sync-from-platform
    p = sub.add_parser("sync-from-platform", help="Reconcile local files with platform issue state")
    p.add_argument("--dry-run", action="store_true", help="Show discrepancies without making changes")
    p.add_argument("--format", choices=["json", "text"], default="text")
    p.set_defaults(func=cmd_sync_from_platform)

    # pr-body
    p = sub.add_parser("pr-body", help="Generate PR body from template")
    p.add_argument("--task-code", default=None, help="Task code (e.g., AUTH-0001)")
    p.add_argument("--title", default=None, help="Task or PR title")
    p.add_argument("--summary", default=None, help="Summary of changes")
    p.add_argument("--issue-num", default=None, help="Related issue number")
    p.add_argument("--source", choices=["task-pick", "test-review", "release"],
                    default="task-pick", help="Source skill for template selection")
    p.set_defaults(func=cmd_pr_body)

    # list-release-tasks
    p = sub.add_parser("list-release-tasks", help="Cross-reference release tasks with local statuses")
    p.add_argument("--version", required=True, help="Release version (e.g., 1.2.0)")
    p.add_argument("--format", choices=["json", "text"], default="json")
    p.set_defaults(func=cmd_list_release_tasks)

    # create-patch-task
    p = sub.add_parser("create-patch-task", help="Create a release patch task with RPAT- code")
    p.add_argument("--title", required=True, help="Task title")
    p.add_argument("--release", required=True, help="Release version to assign to")
    p.add_argument("--priority", choices=["HIGH", "MEDIUM", "LOW"], default="HIGH")
    p.add_argument("--description", required=True, help="Task description")
    p.add_argument("--source", required=True,
                    help="Source stage (e.g., code-optimize, security, test, merge-conflict)")
    p.set_defaults(func=cmd_create_patch_task)

    # register-agent
    p = sub.add_parser("register-agent",
                        help="Register an agent with the memory consistency protocol")
    p.add_argument("--task-code", default="", help="Associated task code")
    p.add_argument("--agent-type", default="task",
                    choices=["task", "scout", "release", "docs", "pr-analysis", "monitor"],
                    help="Type of agent being spawned")
    p.set_defaults(func=cmd_register_agent)

    # deregister-agent
    p = sub.add_parser("deregister-agent",
                        help="Deregister an agent session on completion")
    p.add_argument("--session-id", required=True, help="Session ID to deregister")
    p.set_defaults(func=cmd_deregister_agent)

    return parser

def main():
    parser = build_parser()
    is_hook = len(sys.argv) > 1 and sys.argv[1] == "hook"
    try:
        args = parser.parse_args()
        args.func(args)
    except SystemExit as e:
        if is_hook:
            sys.exit(0)
        raise
    except Exception as e:
        if is_hook:
            sys.exit(0)
        print(json.dumps({"error": str(e), "type": type(e).__name__}))
        sys.exit(1)

if __name__ == "__main__":
    main()
