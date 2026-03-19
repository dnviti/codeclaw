"""MCP tool handler implementations for the CodeClaw vector memory MCP server.

Each submodule exposes a ``register(server)`` function that adds its tool(s)
to the MCP ``Server`` instance.

Modules:
    index         — index_repository tool
    search        — semantic_search tool
    store         — store_memory tool
    task_context  — get_task_context tool
"""

import json
import sys
from pathlib import Path

# Common script directory reference (parent of mcp_tools/ = scripts/)
SCRIPTS_DIR = Path(__file__).resolve().parent.parent

# Ensure scripts/ is on sys.path for sibling imports (vector_memory, etc.)
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def is_enabled(root: str | Path = ".") -> bool:
    """Check whether vector memory is enabled in project configuration.

    Delegates to ``vector_memory.load_config()`` so that config file
    discovery, parsing, and fallback logic remain in a single place.

    Returns ``True`` when the flag is explicitly ``true`` or when no config
    file exists (default-on behaviour).  Returns ``False`` only when the
    flag is explicitly set to ``false``, giving users an opt-out mechanism
    independent of installed dependencies.

    This utility is intended for defensive checks inside individual tool
    modules and the MCP server startup path.
    """
    from vector_memory import load_config

    root_path = Path(root).resolve()
    # Config permissions: trusted local file, OS-level ACLs apply
    vm_cfg = load_config(root_path)
    # Explicit False means disabled; anything else (True,
    # missing key, missing section) means enabled.
    return vm_cfg.get("enabled", True) is not False


# ── Cached config reader ────────────────────────────────────────────────────
# Avoids double config reads when multiple MCP resource/tool handlers need
# configuration during the same server lifecycle.

_config_cache: dict | None = None
_config_cache_root: str | None = None


def get_cached_config(root: str) -> dict:
    """Return the vector_memory config, cached across calls for the same root.

    The cache is process-scoped: once the MCP server reads config for a
    given root, subsequent calls reuse the result without re-reading disk.
    """
    global _config_cache, _config_cache_root
    resolved = str(Path(root).resolve())
    if _config_cache is not None and _config_cache_root == resolved:
        return _config_cache

    config_paths = [
        Path(resolved) / ".claude" / "project-config.json",
        Path(resolved) / "config" / "project-config.json",
    ]
    for cp in config_paths:
        if cp.exists():
            try:
                data = json.loads(cp.read_text(encoding="utf-8"))
                _config_cache = data.get("vector_memory", {})
                _config_cache_root = resolved
                return _config_cache
            except (json.JSONDecodeError, OSError):
                pass
    _config_cache = {}
    _config_cache_root = resolved
    return _config_cache
