"""MCP tool handler implementations for the CTDF vector memory MCP server.

Each submodule exposes a ``register(server)`` function that adds its tool(s)
to the MCP ``Server`` instance.

Modules:
    index         — index_repository tool
    search        — semantic_search tool
    store         — store_memory tool
    task_context  — get_task_context tool
"""

from pathlib import Path

# Common script directory reference (parent of mcp_tools/ = scripts/)
SCRIPTS_DIR = Path(__file__).resolve().parent.parent
