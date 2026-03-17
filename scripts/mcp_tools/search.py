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
