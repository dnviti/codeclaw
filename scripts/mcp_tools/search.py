"""MCP tool handler: semantic_search.

Performs semantic search over the vector index via
``vector_memory.py search``.
"""

import json
import subprocess
import sys
from pathlib import Path

from mcp_tools import SCRIPTS_DIR as _SCRIPT_DIR


def register(server):
    """Register the semantic_search tool on *server*."""

    @server.tool()
    async def semantic_search(
        query: str,
        top_k: int = 10,
        file_filter: str = "",
        file_globs: list[str] | None = None,
        type_filter: str = "",
        root: str = ".",
    ) -> str:
        """Find relevant code and context via semantic similarity.

        Args:
            query: Natural-language search query.
            top_k: Maximum number of results to return (default 10).
            file_filter: Optional substring filter on file paths.
            file_globs: Optional list of glob patterns to filter file paths
                (e.g. ``["skills/*/SKILL.md", "docs/**/*.md"]``).
                Results must match at least one pattern. Applied client-side
                after the vector search returns.
            type_filter: Optional chunk type filter (function, class, etc.).
            root: Project root directory.

        Returns:
            JSON array of search results with file_path, name, chunk_type,
            score, and content fields.
        """
        # Validate root path
        resolved_root = Path(root).resolve()
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

        # When glob patterns are provided, fetch extra results so we can
        # filter client-side and still return up to top_k matches.
        effective_top_k = top_k * 3 if file_globs else top_k

        cmd = [
            sys.executable, str(vm_script), "search",
            query,
            "--root", str(resolved_root),
            "--top-k", str(effective_top_k),
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
            raw = result.stdout.strip() or "[]"

            # Apply glob filtering client-side if requested
            if file_globs:
                from fnmatch import fnmatch
                try:
                    records = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    records = []
                if isinstance(records, list):
                    filtered = [
                        r for r in records
                        if any(
                            fnmatch(r.get("file_path", ""), pat)
                            for pat in file_globs
                        )
                    ]
                    return json.dumps(filtered[:top_k], indent=2)

            return raw
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
