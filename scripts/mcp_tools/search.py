"""MCP tool handler: semantic_search.

Routes semantic search through the memory orchestrator when available,
falling back to direct ``vector_memory.py`` subprocess call for
backwards compatibility.
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
        backend: str = "",
        strategy: str = "auto",
        backends: str = "",
    ) -> str:
        """Find relevant code and context via semantic similarity.

        Searches across one or more memory backends (LanceDB vector,
        SQLite hybrid FTS5+vec, RLM recursive) using the unified
        orchestrator. Results from multiple backends are merged via
        Reciprocal Rank Fusion (RRF).

        Args:
            query: Natural-language search query.
            top_k: Maximum number of results to return (default 10).
            file_filter: Optional substring filter on file paths.
            type_filter: Optional chunk type filter (function, class, etc.).
            root: Project root directory.
            backend: Legacy: single backend name ("lancedb" or "sqlite").
                     Prefer using 'strategy' and 'backends' instead.
            strategy: Routing strategy:
                - "auto": classify query and route to best backend (default)
                - "all": fan-out to all available backends, merge via RRF
                - "specific": use only the named backend(s)
            backends: Comma-separated list of backend names for
                      strategy="specific" (e.g., "lancedb,sqlite").

        Returns:
            JSON array of search results with file_path, name, chunk_type,
            score, and content fields. When multiple backends contribute,
            results include rrf_score and sources fields.
        """
        # Validate root path
        resolved_root = Path(root).resolve()
        if not resolved_root.is_dir():
            return json.dumps({
                "status": "error",
                "message": f"Root is not a directory: {root!r}",
            })

        # Try orchestrator-based search first
        try:
            scripts_dir = str(_SCRIPT_DIR)
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)

            from memory_orchestrator import MemoryOrchestrator

            orch = MemoryOrchestrator(root=resolved_root)

            # Resolve backend parameters
            backend_list = None
            effective_strategy = strategy

            if backend and backend in ("lancedb", "sqlite", "rlm"):
                # Legacy single-backend parameter
                backend_list = [backend]
                effective_strategy = "specific"
            elif backends:
                backend_list = [
                    b.strip() for b in backends.split(",") if b.strip()
                ]
                if backend_list:
                    effective_strategy = "specific"

            results = orch.search(
                query=query,
                strategy=effective_strategy,
                top_k=top_k,
                file_filter=file_filter,
                type_filter=type_filter,
                backends=backend_list,
            )
            return json.dumps(results, indent=2)

        except ImportError:
            pass  # Orchestrator not available, fall back
        except Exception:
            pass  # Orchestrator error, fall back

        # Fallback: direct vector_memory.py subprocess call
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
