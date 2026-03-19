"""MCP tool handler: semantic_search.

Performs semantic search over the vector index via
``vector_memory.py search``.
"""

import json
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

from mcp_tools import SCRIPTS_DIR as _SCRIPT_DIR

# Maximum allowed length for a single glob pattern (prevents pathological input)
_MAX_GLOB_LEN = 256


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
        backend: str = "",
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
            backend: Storage backend to query ("lancedb" or "sqlite").
                     Defaults to the configured backend in project-config.json.

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

        # Validate and sanitize glob patterns
        if file_globs is not None:
            if not isinstance(file_globs, list):
                file_globs = None
            else:
                sanitized = []
                for pat in file_globs:
                    if not isinstance(pat, str):
                        continue
                    if ".." in pat or "\x00" in pat:
                        continue
                    if len(pat) > _MAX_GLOB_LEN:
                        continue
                    sanitized.append(pat)
                file_globs = sanitized or None

        # When glob patterns are provided, fetch extra results so we can
        # filter client-side and still return up to top_k matches.
        effective_top_k = top_k * 5 if file_globs else top_k

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
        if backend and backend in ("lancedb", "sqlite"):
            cmd.extend(["--backend", backend])

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
