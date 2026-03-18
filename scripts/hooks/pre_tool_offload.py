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
import unicodedata
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

# Maximum number of characters inspected from tool_args to prevent DoS via
# excessively large inputs.  Pattern matching is applied only on this prefix.
_MAX_TOOL_ARGS_INSPECT = 65_536  # 64 KiB

# Module-level cache: loaded once per process (hooks run as short-lived procs)
_CONFIG_CACHE: dict | None = None
_CONFIG_LOADED: bool = False


def _load_config() -> dict:
    """Load the Ollama config from the project root or current directory.

    The result is cached for the lifetime of the process so that repeated
    calls within the same hook invocation do not incur filesystem I/O.
    """
    global _CONFIG_CACHE, _CONFIG_LOADED  # noqa: PLW0603
    if _CONFIG_LOADED:
        return _CONFIG_CACHE or {}
    _CONFIG_LOADED = True
    # Try CWD first, then relative to _PROJECT_ROOT
    search_roots = [Path.cwd(), _PROJECT_ROOT]
    for root in search_roots:
        for candidate in _OLLAMA_CONFIG_CANDIDATES:
            cfg_path = root / candidate
            if cfg_path.exists():
                try:
                    _CONFIG_CACHE = json.loads(cfg_path.read_text(encoding="utf-8"))
                    return _CONFIG_CACHE
                except (json.JSONDecodeError, OSError):
                    pass
    _CONFIG_CACHE = {}
    return {}


def _tool_calls_enabled(config: dict, tool_name: str) -> bool:
    """Check whether tool call offloading is enabled for the given tool.

    Defaults to True when tool_calls section is absent or 'enabled' is not set,
    so the offloading level (0-10) becomes the single control point.
    """
    offloading_cfg = config.get("offloading", {})
    tool_calls_cfg = offloading_cfg.get("tool_calls", {})

    if not tool_calls_cfg.get("enabled", True):
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
    # S1: Collapse whitespace to prevent bypass via extra spaces.
    # Apply NFKC to canonicalize Unicode compatibility equivalences (e.g. fullwidth space U+3000,
    # fullwidth Latin letters, superscripts, ligatures).  Note: NFKC does NOT cover cross-script
    # visual lookalikes such as Cyrillic А → Latin A; those require a separate confusables check.
    args_lower = " ".join(unicodedata.normalize("NFKC", tool_args).split()).lower()
    for pattern in exclude_patterns:
        if " ".join(unicodedata.normalize("NFKC", pattern).split()).lower() in args_lower:
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
    # Guard against excessively large inputs; truncate for pattern matching only
    tool_args = tool_args[:_MAX_TOOL_ARGS_INSPECT]

    config = _load_config()

    # O2: Import and reuse get_offload_level from ollama_manager instead of local duplicate
    try:
        from ollama_manager import get_offload_level, should_offload_tool_call
        level = get_offload_level(config)
    except ImportError as exc:
        # Graceful degradation: if ollama_manager is unavailable, do not offload
        print(
            json.dumps({"action": "proceed", "reason": f"import_error: {exc}"}),
            file=sys.stderr,
        )
        print(json.dumps({"action": "proceed"}))
        sys.exit(0)

    # If tool call offloading is not active, pass through immediately
    if level <= 0 or not _tool_calls_enabled(config, tool_name):
        print(json.dumps({"action": "proceed"}))
        sys.exit(0)

    # Check exclude patterns (config-level safety list)
    if _matches_exclude_patterns(config, tool_args):
        print(json.dumps({"action": "proceed", "reason": "excluded_pattern"}))
        sys.exit(0)

    should = should_offload_tool_call(tool_name, tool_args, level)

    if not should:
        print(json.dumps({"action": "proceed"}))
        sys.exit(0)

    # Build offload payload
    ollama_model = config.get("model") or "qwen2.5-coder:7b"
    api_base = config.get("api_base", "http://localhost:11434")

    # S3: Warn if api_base does not use http:// or https:// (warning-only, do not block)
    if not (api_base.startswith("http://") or api_base.startswith("https://")):
        print(
            json.dumps({"warning": f"api_base '{api_base}' does not start with http:// or https://"}),
            file=sys.stderr,
        )

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
