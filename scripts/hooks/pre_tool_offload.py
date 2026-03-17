#!/usr/bin/env python3
"""PreToolUse hook: evaluate tool calls against Ollama offloading policy.

When the configured offloading level indicates a tool call should be routed
to the local Ollama model, this hook emits a JSON decision payload that
Claude Code can use to redirect the call.

Exit codes:
    0 — proceed normally (do not offload)
    2 — block the tool call (offload evaluation failed gracefully)

Environment variables consumed:
    CLAUDE_TOOL_NAME   — name of the tool being invoked (e.g. "Bash")
    CLAUDE_TOOL_INPUT  — serialised arguments / content for the tool

The hook also accepts positional arguments for easier testing:
    python3 pre_tool_offload.py <tool_name> <tool_input>

Zero external dependencies — stdlib only.
"""

import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path bootstrap: make sibling scripts importable
# ---------------------------------------------------------------------------
_HOOK_DIR = Path(__file__).resolve().parent          # scripts/hooks/
_SCRIPTS_DIR = _HOOK_DIR.parent                      # scripts/
_PROJECT_ROOT = _SCRIPTS_DIR.parent                  # repo root (heuristic)

for _path in (_SCRIPTS_DIR, str(_SCRIPTS_DIR)):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

# ---------------------------------------------------------------------------
# Config loading helpers (inline to stay self-contained)
# ---------------------------------------------------------------------------

_OLLAMA_CONFIG_CANDIDATES = [
    ".claude/ollama-config.json",
    "ollama-config.json",
]


def _load_config() -> dict:
    """Load the Ollama config from the project root or current directory."""
    # Try CWD first, then relative to _PROJECT_ROOT
    search_roots = [Path.cwd(), _PROJECT_ROOT]
    for root in search_roots:
        for candidate in _OLLAMA_CONFIG_CANDIDATES:
            cfg_path = root / candidate
            if cfg_path.exists():
                try:
                    return json.loads(cfg_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    pass
    return {}


def _get_offload_level(config: dict) -> int:
    """Extract the numeric offload level from the Ollama config.

    Mirrors ``agent_runner.get_offload_level()`` to stay self-contained.
    """
    if not config.get("enabled", False):
        return 0

    offloading_cfg = config.get("offloading", {})

    if "level" in offloading_cfg:
        raw = offloading_cfg["level"]
        if isinstance(raw, bool):
            return 5 if raw else 0
        if isinstance(raw, (int, float)):
            return max(0, min(10, int(raw)))

    # Legacy boolean field
    if "enabled" in offloading_cfg:
        return 5 if offloading_cfg["enabled"] else 0

    return 0


def _tool_calls_enabled(config: dict, tool_name: str) -> bool:
    """Check whether tool call offloading is enabled for the given tool."""
    offloading_cfg = config.get("offloading", {})
    tool_calls_cfg = offloading_cfg.get("tool_calls", {})

    if not tool_calls_cfg.get("enabled", False):
        return False

    include_tools = tool_calls_cfg.get("include_tools", [])
    if include_tools and tool_name not in include_tools:
        return False

    return True


def _matches_exclude_patterns(config: dict, tool_args: str) -> bool:
    """Return True if tool_args matches any configured exclude pattern."""
    offloading_cfg = config.get("offloading", {})
    tool_calls_cfg = offloading_cfg.get("tool_calls", {})
    exclude_patterns = tool_calls_cfg.get("exclude_patterns", [])
    args_lower = tool_args.lower()
    for pattern in exclude_patterns:
        if pattern.lower() in args_lower:
            return True
    return False


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

def evaluate(tool_name: str, tool_args: str) -> None:
    """Evaluate whether the tool call should be offloaded to Ollama.

    Writes a JSON result to stdout and exits:
    - Exit 0 with ``{"action": "proceed"}``   — do not offload
    - Exit 0 with ``{"action": "offload", ...}`` — offload to Ollama
    """
    config = _load_config()
    level = _get_offload_level(config)

    # If tool call offloading is not active, pass through immediately
    if level <= 0 or not _tool_calls_enabled(config, tool_name):
        print(json.dumps({"action": "proceed"}))
        sys.exit(0)

    # Check exclude patterns (config-level safety list)
    if _matches_exclude_patterns(config, tool_args):
        print(json.dumps({"action": "proceed", "reason": "excluded_pattern"}))
        sys.exit(0)

    # Import offloading logic
    try:
        from ollama_manager import should_offload_tool_call
    except ImportError as exc:
        # Graceful degradation: if ollama_manager is unavailable, do not offload
        print(
            json.dumps({"action": "proceed", "reason": f"import_error: {exc}"}),
            file=sys.stderr,
        )
        print(json.dumps({"action": "proceed"}))
        sys.exit(0)

    should = should_offload_tool_call(tool_name, tool_args, level)

    if not should:
        print(json.dumps({"action": "proceed"}))
        sys.exit(0)

    # Build offload payload
    ollama_model = config.get("model") or "qwen2.5-coder:7b"
    api_base = config.get("api_base", "http://localhost:11434")

    result = {
        "action": "offload",
        "provider": "ollama",
        "model": ollama_model,
        "api_base": api_base,
        "tool_name": tool_name,
        "offload_level": level,
    }
    print(json.dumps(result))
    sys.exit(0)


def main() -> None:
    # Prefer positional CLI arguments; fall back to environment variables
    if len(sys.argv) >= 3:
        tool_name = sys.argv[1]
        tool_args = sys.argv[2]
    else:
        tool_name = os.environ.get("CLAUDE_TOOL_NAME", "")
        tool_args = os.environ.get("CLAUDE_TOOL_INPUT", "")

    try:
        evaluate(tool_name, tool_args)
    except Exception as exc:  # noqa: BLE001
        # Never crash the hook — always exit cleanly
        print(
            json.dumps({"action": "proceed", "reason": f"hook_error: {exc}"}),
            file=sys.stderr,
        )
        print(json.dumps({"action": "proceed"}))
        sys.exit(0)


if __name__ == "__main__":
    main()
