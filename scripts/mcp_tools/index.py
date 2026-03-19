"""MCP tool handler: index_repository.

Triggers a full or incremental re-index of the codebase via the
``vector_memory.py index`` subcommand.
"""

import json
import subprocess
import sys
from pathlib import Path

from mcp_tools import SCRIPTS_DIR as _SCRIPT_DIR


def _resolve_main_repo_root(path_hint: str) -> Path:
    """Resolve path to the main repository root (worktree-aware).

    If *path_hint* is inside a git worktree, returns the main repository
    root so that the vector index is always stored in one shared location.
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
        # Resolve to main repo root (worktree-aware)
        resolved_path = _resolve_main_repo_root(path)
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
