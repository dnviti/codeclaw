#!/usr/bin/env python3
"""MCP stdio server for the CodeClaw vector memory layer.

Exposes the vector memory subsystem (VMEM-0017) as an MCP (Model Context
Protocol) server using the stdio transport.  Any MCP-compatible AI assistant
(Claude Code, Cursor, Continue.dev, etc.) can connect and use the tools.

Tools provided:
    index_repository   — trigger codebase indexing (full or incremental)
    semantic_search    — find relevant code and context (orchestrator-aware)
    store_memory       — persist agent learnings and discoveries
    get_task_context   — retrieve comprehensive task-specific context
    list_backends      — list configured memory backends and availability
    backend_health     — check health status of memory backends

Resources provided:
    memory://status    — current index status and available namespaces
    memory://backends  — available backends and their health status

Requirements:
    pip install mcp

    The vector memory dependencies (lancedb, onnxruntime, etc.) are only
    needed when tools are actually invoked — the server itself starts
    without them.

Usage:
    python3 mcp_server.py                     # stdio transport (default)
    python3 mcp_server.py --root /path/to/project

Zero required heavy dependencies for startup — only the ``mcp`` package
is needed.  Vector memory deps are loaded lazily by the tool handlers.
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Add scripts/ to path for sibling imports
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


# ── Dependency Check ─────────────────────────────────────────────────────────

def _check_mcp_sdk() -> bool:
    """Return True if the ``mcp`` package is importable."""
    try:
        import mcp  # noqa: F401
        return True
    except ImportError:
        return False


# ── Resource Helpers ─────────────────────────────────────────────────────────

from mcp_tools import is_enabled


def _build_status(root: str) -> dict:
    """Build a status dict describing the vector memory index."""
    root_path = Path(root).resolve()

    # If vector memory is disabled by config, return immediately
    if not is_enabled(root):
        return {
            "status": "disabled_by_config",
            "enabled": False,
            "message": (
                "Vector memory is disabled via vector_memory.enabled=false "
                "in project-config.json. Set it to true to enable."
            ),
            "namespaces": _list_namespaces(root_path),
        }

    # Try to get status from vector_memory.py
    vm_script = _SCRIPT_DIR / "vector_memory.py"
    if vm_script.exists():
        import subprocess
        try:
            result = subprocess.run(
                [sys.executable, str(vm_script), "status", "--root", root, "--json"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                status = json.loads(result.stdout.strip())
                # Add namespace listing
                status["namespaces"] = _list_namespaces(root_path)
                return status
        except Exception:
            pass

    # Fallback: basic status
    return {
        "enabled": False,
        "dependencies_installed": False,
        "index_exists": False,
        "namespaces": _list_namespaces(root_path),
        "message": "vector_memory.py not found or status check failed.",
    }


def _list_namespaces(root_path: Path) -> list[str]:
    """List available memory note namespaces."""
    notes_dir = root_path / ".claude" / "memory" / "notes"
    if not notes_dir.exists():
        return []
    try:
        return sorted(
            d.name for d in notes_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )
    except OSError:
        return []


def _build_backends_status(root: str) -> dict:
    """Build a status dict describing available memory backends."""
    root_path = Path(root).resolve()

    try:
        from memory_orchestrator import MemoryOrchestrator
        orch = MemoryOrchestrator(root=root_path)
        return orch.status()
    except ImportError:
        return {
            "orchestrator_available": False,
            "message": "memory_orchestrator.py not found. MORC-0040 must be installed.",
        }
    except Exception as e:
        return {
            "orchestrator_available": False,
            "error": str(e),
        }


# ── Server Setup ─────────────────────────────────────────────────────────────

def _load_lock_backend_config(root: str) -> dict:
    """Load the lock_backend configuration from project-config.json.

    Returns the lock_backend section with defaults applied.
    Falls back gracefully if the config file is missing or malformed.
    """
    config_paths = [
        Path(root).resolve() / ".claude" / "project-config.json",
        Path(root).resolve() / "config" / "project-config.json",
    ]
    for cp in config_paths:
        if cp.exists():
            try:
                # Config permissions: trusted local file, OS-level ACLs apply
                data = json.loads(cp.read_text(encoding="utf-8"))
                vm_cfg = data.get("vector_memory", {})
                lb_cfg = vm_cfg.get("lock_backend", {})
                return {
                    "type": lb_cfg.get("type", "file"),
                    "sqlite_path": lb_cfg.get(
                        "sqlite_path", ".claude/memory/locks/lock.db"
                    ),
                    "redis_url": lb_cfg.get(
                        "redis_url", "redis://localhost:6379"
                    ),
                    "redis_key_prefix": lb_cfg.get(
                        "redis_key_prefix", "ctdf:"
                    ),
                    "timeout": lb_cfg.get("timeout", 30),
                    "auto_renew_interval": lb_cfg.get(
                        "auto_renew_interval", 10
                    ),
                }
            except (json.JSONDecodeError, OSError):
                pass
    return {"type": "file", "timeout": 30}


def create_server(root: str = "."):
    """Create and configure the MCP server instance.

    Returns the ``FastMCP`` object ready for ``run()``.

    Loads the lock backend configuration and passes it to the
    server context so tool handlers can access it.

    When ``vector_memory.enabled`` is ``false`` in the project config, the
    server starts without registering vector memory tools (index_repository,
    semantic_search, store_memory, get_task_context).  The ``memory://status``
    resource is always registered and reports ``disabled_by_config`` when the
    toggle is off.
    """
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("claw-vector-memory")

    # Load lock backend config for tool handlers
    lock_backend_config = _load_lock_backend_config(root)

    # Intentional: env vars propagate config to child processes (subprocess communication pattern)
    os.environ.setdefault("CTDF_LOCK_BACKEND_TYPE", lock_backend_config.get("type", "file"))

    # ── Conditionally register vector memory tools ──
    vm_enabled = is_enabled(root)

    if vm_enabled:
        from mcp_tools import index, search, store, task_context
        from mcp_tools import backends as backends_tools

        index.register(server)
        search.register(server)
        store.register(server)
        task_context.register(server)
        backends_tools.register(server)

    # ── Register resources (always available) ──
    @server.resource("memory://status")
    async def resource_status() -> str:
        """Current vector memory index status and available namespaces."""
        status = _build_status(root)
        status["lock_backend"] = lock_backend_config.get("type", "file")
        return json.dumps(status, indent=2)

    @server.resource("memory://backends")
    async def resource_backends() -> str:
        """Available memory backends and their health status."""
        return json.dumps(_build_backends_status(root), indent=2)

    return server


def run_server(root: str = "."):
    """Run the MCP server with stdio transport."""
    server = create_server(root)
    server.run(transport="stdio")


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="CodeClaw Vector Memory MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s                          # Start MCP stdio server
  %(prog)s --root /path/to/project  # Specify project root
  %(prog)s --check                  # Check if MCP SDK is installed

The server communicates via stdin/stdout using the MCP stdio protocol.
Configure your MCP client to launch this script as a subprocess.
""",
    )
    parser.add_argument(
        "--root", default=".",
        help="Project root directory (default: current directory)",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Check if the MCP SDK is installed and exit",
    )

    args = parser.parse_args()

    if args.check:
        if _check_mcp_sdk():
            print(json.dumps({"mcp_sdk": True, "status": "ok"}))
            sys.exit(0)
        else:
            print(json.dumps({
                "mcp_sdk": False,
                "status": "error",
                "install": 'pip install "mcp>=1.0" "lancedb>=0.5.0,<1.0" "sentence-transformers>=2.7.0,<3.0"',
            }))
            sys.exit(1)

    if not _check_mcp_sdk():
        # Design: exit(0) is intentional — disabled MCP server should terminate
        # cleanly, not error
        print(
            "Error: The 'mcp' Python package is not installed.\n"
            "Install all required packages with:\n"
            '  pip install "mcp>=1.0" "lancedb>=0.5.0,<1.0" "sentence-transformers>=2.7.0,<3.0"\n'
            "\n"
            "Or enable vector memory MCP via the /setup skill for automatic installation.\n",
            file=sys.stderr,
        )
        sys.exit(1)

    # Intentional: env vars propagate config to child processes (subprocess communication pattern)
    os.environ.setdefault("CLAW_PROJECT_ROOT", str(Path(args.root).resolve()))

    run_server(args.root)


if __name__ == "__main__":
    main()
