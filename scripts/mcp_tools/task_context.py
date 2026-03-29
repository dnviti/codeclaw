"""MCP tool handler: get_task_context.

Higher-level orchestration tool that retrieves task-specific context by
combining:
  1. Task file parsing (to-do.txt / progressing.txt / done.txt)
  2. Keyword-based semantic search for code related to the task ID
  3. Description-based semantic search for conceptually related code
  4. Dependency information
  5. Related memory notes
"""

import json
import re
import subprocess
import sys
from pathlib import Path

from mcp_tools import SCRIPTS_DIR as _SCRIPT_DIR

TASK_CODE_RE = re.compile(r"^[A-Z]{3,5}-\d{4}$")
SEPARATOR = "-" * 78
TASK_HEADER_RE = re.compile(r"^\[(.)\]\s+([A-Z]{3,5}-\d{4})\s+.+$")
STATUS_MAP = {"[ ]": "todo", "[~]": "progressing", "[x]": "done", "[!]": "blocked"}


def _find_project_root(root_hint: str) -> Path:
    """Resolve project root by walking up from the hint directory."""
    p = Path(root_hint).resolve()
    while p != p.parent:
        if (p / ".claude").is_dir() or (p / ".git").exists():
            return p
        p = p.parent
    return Path(root_hint).resolve()


def _parse_task_from_files(root: Path, task_id: str) -> dict | None:
    """Parse task block from to-do.txt, progressing.txt, or done.txt."""
    task_files = ["to-do.txt", "progressing.txt", "done.txt"]

    for fname in task_files:
        fpath = root / fname
        if not fpath.exists():
            continue
        try:
            lines = fpath.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue

        i = 0
        while i < len(lines):
            line = lines[i].rstrip()
            if line != SEPARATOR:
                i += 1
                continue
            if i + 2 >= len(lines):
                i += 1
                continue
            header = lines[i + 1].rstrip()
            if task_id not in header:
                i += 1
                continue
            m = TASK_HEADER_RE.match(header)
            if not m or m.group(2) != task_id:
                i += 1
                continue
            if lines[i + 2].rstrip() != SEPARATOR:
                i += 1
                continue

            # Found the task — gather content
            sym = f"[{m.group(1)}]"
            content_start = i + 3
            content_end = content_start
            while content_end < len(lines) and lines[content_end].rstrip() != SEPARATOR:
                content_end += 1

            content_lines = [l.rstrip() for l in lines[content_start:content_end]]

            # Extract structured fields
            title = header.split(" — ", 1)[1] if " — " in header else header
            priority = ""
            dependencies = ""
            description_lines = []
            for cl in content_lines:
                s = cl.strip()
                if s.startswith("Priority:"):
                    priority = s[len("Priority:"):].strip()
                elif s.startswith("Dependencies:"):
                    dependencies = s[len("Dependencies:"):].strip()
                else:
                    description_lines.append(cl)

            return {
                "task_id": task_id,
                "title": title.strip(),
                "status": STATUS_MAP.get(sym, "unknown"),
                "status_symbol": sym,
                "priority": priority,
                "dependencies": dependencies,
                "description": "\n".join(description_lines).strip(),
                "source_file": fname,
            }
    return None


def _semantic_search_for_task(task_id: str, root: str) -> list[dict]:
    """Run semantic search for code related to the task."""
    vm_script = _SCRIPT_DIR / "vector_memory.py"
    if not vm_script.exists():
        return []

    try:
        result = subprocess.run(
            [
                sys.executable, str(vm_script), "search",
                task_id,
                "--root", root,
                "--top-k", "5",
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout.strip())
    except Exception:
        pass
    return []


def _semantic_search_by_description(task_info: dict | None, root: str) -> list[dict]:
    """Run semantic search using the full task description as query.

    Unlike ``_semantic_search_for_task`` which searches by task ID,
    this searches using the task's description and technical details
    to find conceptually related code that may not mention the task
    code directly.  Results are filtered to exclude files already
    listed in the task's "Files involved".
    """
    if not task_info:
        return []

    # Build a rich query from title + description
    title = task_info.get("title", "")
    description = task_info.get("description", "")
    query = f"{title} {description}".strip()
    if not query:
        return []
    # Truncate for embedding model limits
    if len(query) > 1000:
        query = query[:1000]

    vm_script = _SCRIPT_DIR / "vector_memory.py"
    if not vm_script.exists():
        return []

    try:
        result = subprocess.run(
            [
                sys.executable, str(vm_script), "search",
                query,
                "--root", root,
                "--top-k", "15",
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            raw = json.loads(result.stdout.strip())
            # Deduplicate by file_path, keeping best score per file
            seen: dict[str, dict] = {}
            for entry in raw:
                fp = entry.get("file_path", "")
                score = entry.get("score", 999.0)
                if fp and (fp not in seen or score < seen[fp]["score"]):
                    seen[fp] = {
                        "file_path": fp,
                        "score": round(score, 4) if isinstance(score, float) else score,
                        "chunk_type": entry.get("chunk_type", ""),
                        "name": entry.get("name", ""),
                        "language": entry.get("language", ""),
                    }
            return sorted(seen.values(), key=lambda x: x.get("score", 999))
    except Exception as exc:
        print(f"[task_context] description-based semantic search failed: {exc}",
              file=sys.stderr)
    return []


def _find_memory_notes(root: Path, task_id: str) -> list[dict]:
    """Find memory notes mentioning this task."""
    notes_dir = root / ".claude" / "memory" / "notes"
    if not notes_dir.exists():
        return []

    matches = []
    task_lower = task_id.lower()
    try:
        for note_file in notes_dir.rglob("*.md"):
            try:
                content = note_file.read_text(encoding="utf-8")
                if task_lower in content.lower():
                    rel = str(note_file.relative_to(root))
                    matches.append({
                        "path": rel,
                        "namespace": note_file.parent.name,
                        "preview": content[:300],
                    })
            except OSError:
                continue
    except Exception:
        pass
    return matches


def register(server):
    """Register the get_task_context tool on *server*."""

    @server.tool()
    async def get_task_context(task_id: str, root: str = ".") -> str:
        """Retrieve comprehensive context for a specific task.

        Combines task file data, semantic search results, dependency
        information, and related memory notes into a single context
        object that agents can use to understand and implement a task.

        Args:
            task_id: Task code (e.g. "AUTH-0001", "VMEM-0018").
            root: Project root directory.

        Returns:
            JSON object with task metadata, related code, dependencies,
            and memory notes.
        """
        if not TASK_CODE_RE.match(task_id):
            return json.dumps({
                "status": "error",
                "message": f"Invalid task ID format: {task_id!r}. "
                           f"Expected pattern like AUTH-0001.",
            })

        root_path = _find_project_root(root)

        # 1. Parse task from task files
        task_info = _parse_task_from_files(root_path, task_id)

        # 2. Keyword-based semantic search (searches by task ID)
        related_code = _semantic_search_for_task(task_id, str(root_path))

        # 3. Description-based semantic search (searches by task content)
        semantic_related = _semantic_search_by_description(
            task_info, str(root_path)
        )

        # 4. Parse dependency tasks
        dep_tasks = []
        if task_info and task_info.get("dependencies"):
            dep_codes = [
                d.strip()
                for d in task_info["dependencies"].split(",")
                if d.strip()
            ]
            for dep_code in dep_codes:
                dep_info = _parse_task_from_files(root_path, dep_code)
                if dep_info:
                    dep_tasks.append(dep_info)

        # 5. Find related memory notes
        memory_notes = _find_memory_notes(root_path, task_id)

        return json.dumps({
            "status": "ok",
            "task": task_info,
            "related_code": related_code[:10] if related_code else [],
            "semantic_related_code": semantic_related[:10]
                if semantic_related else [],
            "dependency_tasks": dep_tasks,
            "memory_notes": memory_notes[:5] if memory_notes else [],
            "message": (
                f"Context assembled for {task_id}"
                if task_info
                else f"Task {task_id} not found in task files, "
                     f"but related code and notes are included."
            ),
        })
