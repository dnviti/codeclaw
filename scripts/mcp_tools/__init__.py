"""MCP tool handler implementations for the CTDF vector memory MCP server.

Each submodule exposes a ``register(server)`` function that adds its tool(s)
to the MCP ``Server`` instance.

Modules:
    index         — index_repository tool
    search        — semantic_search tool
    store         — store_memory tool
    task_context  — get_task_context tool
"""

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
    vm_cfg = load_config(root_path)
    # Explicit False means disabled; anything else (True,
    # missing key, missing section) means enabled.
    return vm_cfg.get("enabled", True) is not False
