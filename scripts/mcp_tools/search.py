"""MCP tool handler: semantic_search.

Performs semantic search over the vector index via
``vector_memory.py search``.

Glob-filtering logic is centralized in ``vector_memory.apply_search_filters``
and invoked through the subprocess CLI interface.  This avoids duplicating
the filter-building and sanitization code.
"""

import json
import subprocess
import sys
from pathlib import Path

from mcp_tools import SCRIPTS_DIR as _SCRIPT_DIR


def _resolve_main_repo_root(path_hint: str) -> Path:
    """Resolve path to the main repository root (worktree-aware).

    If *path_hint* is inside a git worktree, returns the main repository
    root so that the vector index is always read from one shared location.
    """
    resolved = Path(path_hint).resolve()
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, check=True,
            cwd=str(resolved),
        ).stdout.strip()
        git_dir = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True, text=True, check=True,
            cwd=str(resolved),
        ).stdout.strip()
        common_path = Path(common).resolve()
        git_dir_path = Path(git_dir).resolve()
        if common_path != git_dir_path:
            return common_path.parent
        return git_dir_path.parent
    except (FileNotFoundError, subprocess.CalledProcessError):
        return resolved


def register(server):
    """Register the semantic_search tool on *server*."""

    @server.tool()
    async def semantic_search(
        query: str,
        top_k: int = 10,
        file_filter: str = "",
        type_filter: str = "",
        root: str = ".",
    ) -> str:
        """Find relevant code and context via semantic similarity.

        Args:
            query: Natural-language search query.
            top_k: Maximum number of results to return (default 10).
            file_filter: Optional substring filter on file paths.
            type_filter: Optional chunk type filter (function, class, etc.).
            root: Project root directory.

        Returns:
            JSON array of search results with file_path, name, chunk_type,
            score, and content fields.
        """
        # Resolve to main repo root (worktree-aware)
        resolved_root = _resolve_main_repo_root(root)
        if not resolved_root.is_dir():
            return json.dumps({
                "status": "error",
                "message": f"Root is not a directory: {root!r}",
            })

        vm_script = _SCRIPT_DIR / "vector_memory.py"
        if not vm_script.exists():
            return json.dumps({
                "status": "error",
                "message": "vector_memory.py not found. VMEM-0017 must be installed.",
            })

        cmd = [
            sys.executable, str(vm_script), "search",
            query,
            "--root", str(resolved_root),
            "--top-k", str(top_k),
            "--json",
            "--full-content",
        ]
        if file_filter:
            cmd.extend(["--file-filter", file_filter])
        if type_filter:
            cmd.extend(["--type-filter", type_filter])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                return json.dumps({
                    "status": "error",
                    "message": result.stderr.strip() or "Search failed.",
                })
            # vector_memory.py search --json writes JSON to stdout
            return result.stdout.strip() or "[]"
        except subprocess.TimeoutExpired:
            return json.dumps({
                "status": "error",
                "message": "Search timed out after 120 seconds.",
            })
        except Exception as exc:
            return json.dumps({
                "status": "error",
                "message": str(exc),
            })
