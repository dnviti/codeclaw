"""MCP tool handler: index_repository.

Triggers a full or incremental re-index of the codebase via the
``vector_memory.py index`` subcommand.
"""

import json
import subprocess
import sys
from pathlib import Path

from mcp_tools import SCRIPTS_DIR as _SCRIPT_DIR


def register(server):
    """Register the index_repository tool on *server*."""

    @server.tool()
    async def index_repository(path: str = ".", incremental: bool = True) -> str:
        """Trigger codebase indexing for vector memory.

        Args:
            path: Project root directory to index (default: current directory).
            incremental: When True (default) only re-index changed files;
                         when False perform a full rebuild.

        Returns:
            JSON object with ``status``, ``message``, and optional diagnostics.
        """
        # Validate that path resolves to a plausible project directory
        resolved_path = Path(path).resolve()
        if not resolved_path.is_dir():
            return json.dumps({
                "status": "error",
                "message": f"Path is not a directory: {path!r}",
            })

        vm_script = _SCRIPT_DIR / "vector_memory.py"
        if not vm_script.exists():
            return json.dumps({
                "status": "error",
                "message": "vector_memory.py not found. VMEM-0017 must be installed.",
            })

        cmd = [sys.executable, str(vm_script), "index", "--root", str(resolved_path)]
        if not incremental:
            cmd.append("--full")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
            )
            output = result.stderr.strip() or result.stdout.strip()
            return json.dumps({
                "status": "ok" if result.returncode == 0 else "error",
                "message": output,
                "returncode": result.returncode,
            })
        except subprocess.TimeoutExpired:
            return json.dumps({
                "status": "error",
                "message": "Indexing timed out after 600 seconds.",
            })
        except Exception as exc:
            return json.dumps({
                "status": "error",
                "message": str(exc),
            })
