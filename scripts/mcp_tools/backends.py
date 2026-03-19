"""MCP tool handlers: list_backends and backend_health.

Provides MCP tools for querying the memory orchestrator's backend
registry, including listing available backends and their health status.
"""

import json
import os
import sys
from pathlib import Path

from mcp_tools import SCRIPTS_DIR as _SCRIPT_DIR


def register(server):
    """Register backend management tools on *server*."""

    @server.tool()
    async def list_backends(
        root: str = ".",
    ) -> str:
        """List all configured memory backends and their availability.

        Returns a JSON array of backend objects, each containing:
        - name: Backend identifier (lancedb, sqlite, rlm)
        - configured: Whether the backend is in the project config
        - available: Whether the backend's dependencies are installed
        - weight: RRF routing weight for this backend

        Args:
            root: Project root directory.
        """
        resolved_root = Path(root).resolve()
        if not resolved_root.is_dir():
            return json.dumps({
                "status": "error",
                "message": f"Root is not a directory: {root!r}",
            })

        try:
            # Ensure scripts/ is on path
            scripts_dir = str(_SCRIPT_DIR)
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)

            from memory_orchestrator import MemoryOrchestrator
            orch = MemoryOrchestrator(root=resolved_root)
            backends = orch.list_backends()
            return json.dumps(backends, indent=2)
        except ImportError:
            return json.dumps({
                "status": "error",
                "message": "memory_orchestrator.py not found. MORC-0040 must be installed.",
            })
        except Exception as exc:
            return json.dumps({
                "status": "error",
                "message": str(exc),
            })

    @server.tool()
    async def backend_health(
        backend: str = "",
        root: str = ".",
    ) -> str:
        """Check health status of memory backends.

        When a specific backend is named, returns detailed health for that
        backend only. Otherwise returns health for all configured backends.

        Args:
            backend: Specific backend name to check (lancedb, sqlite, rlm).
                     If empty, checks all configured backends.
            root: Project root directory.

        Returns:
            JSON object with backend health information including
            availability, index status, and any error details.
        """
        resolved_root = Path(root).resolve()
        if not resolved_root.is_dir():
            return json.dumps({
                "status": "error",
                "message": f"Root is not a directory: {root!r}",
            })

        try:
            scripts_dir = str(_SCRIPT_DIR)
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)

            from memory_orchestrator import MemoryOrchestrator
            orch = MemoryOrchestrator(root=resolved_root)

            if backend:
                health = orch.registry.health(backend)
                return json.dumps(health, indent=2)
            else:
                health = orch.registry.all_health()
                return json.dumps(health, indent=2)
        except ImportError:
            return json.dumps({
                "status": "error",
                "message": "memory_orchestrator.py not found. MORC-0040 must be installed.",
            })
        except Exception as exc:
            return json.dumps({
                "status": "error",
                "message": str(exc),
            })
