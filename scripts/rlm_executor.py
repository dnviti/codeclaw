#!/usr/bin/env python3
"""RLM REPL executor for CTDF — sandboxed context analysis via code generation.

Constructs and executes Python code snippets that slice and query context
programmatically. The LLM generates analysis code that operates on context
loaded as a variable, enabling symbolic recursion over arbitrarily long inputs.

Security: Execution is sandboxed via subprocess with timeout and memory limits.
No network access, no filesystem writes, no imports beyond a safe allowlist.

Zero external dependencies — stdlib only.
"""

import json
import os
import platform
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Optional


# ── Constants ────────────────────────────────────────────────────────────────

# Maximum output size from a single execution (bytes)
MAX_OUTPUT_SIZE = 1024 * 1024  # 1 MB

# Safe built-in modules allowed in the sandbox
SAFE_MODULES = frozenset({
    "re", "json", "math", "statistics", "collections",
    "itertools", "functools", "textwrap", "difflib",
    "string", "unicodedata", "hashlib",
})

# Patterns that indicate potentially unsafe code
UNSAFE_PATTERNS = [
    "import os", "import sys", "import subprocess",
    "import shutil", "import socket", "import http",
    "import urllib", "import requests", "import pathlib",
    "import importlib", "import ctypes", "import _thread",
    "import multiprocessing", "import pickle", "import marshal",
    "import signal", "import code", "import codeop",
    "__import__", "eval(", "exec(", "compile(",
    "open(", "globals(", "locals(", "vars(",
    "getattr(", "setattr(", "delattr(",
    "breakpoint(", "exit(", "quit(",
    "__subclasses__", "__bases__", "__class__",
    "sys.modules", "pickle.loads", "marshal.loads",
]


# ── Sandbox Code Template ────────────────────────────────────────────────────

# Template is built via string concatenation, NOT str.format(), to avoid
# injection via curly braces in LLM-generated analysis code or context data.
# Context data is loaded from a separate temp file to prevent string-escape
# breakout attacks via malicious file content.

_SANDBOX_PREAMBLE = textwrap.dedent('''\
    import sys
    import json

    # Only allow safe imports
    _ALLOWED_MODULES = %%ALLOWED_MODULES%%

    _original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

    def _safe_import(name, *args, **kwargs):
        top_level = name.split(".")[0]
        if top_level not in _ALLOWED_MODULES:
            raise ImportError(f"Module '{name}' is not allowed in the RLM sandbox")
        return _original_import(name, *args, **kwargs)

    if hasattr(__builtins__, '__import__'):
        __builtins__.__import__ = _safe_import
    else:
        import builtins
        builtins.__import__ = _safe_import

    # Load context data from separate file (avoids string-injection attacks)
    with __builtins__.open(sys.argv[1], "r", encoding="utf-8") as _ctx_f:
        CONTEXT = json.load(_ctx_f)

    # Analysis results collector
    RESULTS = []

    def emit(finding):
        """Record an analysis finding."""
        if isinstance(finding, str):
            RESULTS.append({"type": "text", "content": finding})
        elif isinstance(finding, dict):
            RESULTS.append(finding)
        else:
            RESULTS.append({"type": "text", "content": str(finding)})

    def slice_context(start=None, end=None, key=None):
        """Slice context data for focused analysis."""
        if key and isinstance(CONTEXT, dict):
            return CONTEXT.get(key, "")
        if isinstance(CONTEXT, str):
            return CONTEXT[start:end]
        if isinstance(CONTEXT, list):
            return CONTEXT[start:end]
        return CONTEXT

    def search_context(pattern):
        """Search context for a regex pattern, returning matches."""
        import re
        text = CONTEXT if isinstance(CONTEXT, str) else json.dumps(CONTEXT)
        return re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)

    def summarize_structure():
        """Return structural summary of the context."""
        if isinstance(CONTEXT, dict):
            return {k: type(v).__name__ for k, v in CONTEXT.items()}
        if isinstance(CONTEXT, list):
            return {"length": len(CONTEXT), "types": list(set(type(x).__name__ for x in CONTEXT[:20]))}
        if isinstance(CONTEXT, str):
            lines = CONTEXT.splitlines()
            return {"lines": len(lines), "chars": len(CONTEXT)}
        return {"type": type(CONTEXT).__name__}

    # ── User analysis code ──
''')

_SANDBOX_EPILOGUE = textwrap.dedent('''\

    # Output results
    output = {"results": RESULTS, "success": True}
    print(json.dumps(output))
''')


# ── Executor ─────────────────────────────────────────────────────────────────

class ExecutionResult:
    """Result of a sandboxed code execution."""

    def __init__(self, success: bool, results: list, stdout: str = "",
                 stderr: str = "", error: str = ""):
        self.success = success
        self.results = results
        self.stdout = stdout
        self.stderr = stderr
        self.error = error

    def to_dict(self) -> dict:
        d = {
            "success": self.success,
            "results": self.results,
        }
        if self.error:
            d["error"] = self.error
        if self.stderr:
            d["stderr"] = self.stderr[:2000]
        return d


def validate_code(code: str) -> tuple[bool, str]:
    """Validate analysis code for safety before execution.

    Uses string-pattern checks plus AST-based analysis as a secondary layer.

    Args:
        code: Python code string to validate.

    Returns:
        Tuple of (is_safe, reason). If is_safe is False, reason explains why.
    """
    for pattern in UNSAFE_PATTERNS:
        if pattern in code:
            return False, f"Unsafe pattern detected: {pattern}"

    # Check for excessive length (likely prompt injection)
    if len(code) > 50000:
        return False, "Code exceeds maximum allowed length (50000 chars)"

    # AST-based secondary validation: catches obfuscated patterns that string
    # matching may miss (e.g. getattr via variable, indirect __import__)
    import ast
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Code has syntax errors: {e}"

    for node in ast.walk(tree):
        # Block Import / ImportFrom for disallowed modules
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in SAFE_MODULES:
                    return False, f"AST: disallowed import '{alias.name}'"
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if top not in SAFE_MODULES:
                    return False, f"AST: disallowed import from '{node.module}'"
        # Block calls to dangerous built-ins (eval, exec, compile, open, __import__)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in (
                "eval", "exec", "compile", "open", "__import__",
                "breakpoint", "exit", "quit",
            ):
                return False, f"AST: disallowed call to '{func.id}'"
        # Block attribute access to dunder internals used for sandbox escapes
        elif isinstance(node, ast.Attribute):
            if node.attr in ("__subclasses__", "__bases__", "__class__",
                             "__import__", "__builtins__"):
                return False, f"AST: disallowed attribute access '{node.attr}'"

    return True, ""


def build_sandbox_code(context_data, analysis_code: str) -> tuple[str, str]:
    """Build the complete sandbox script from context and analysis code.

    Context data is written to a separate JSON file to prevent string-escape
    injection attacks. The sandbox script reads context from that file at
    runtime via sys.argv[1].

    Args:
        context_data: The context to make available (will be JSON-serialized).
        analysis_code: The LLM-generated analysis code.

    Returns:
        Tuple of (script_code, context_json_string).
    """
    # Serialize context — kept separate from the script to avoid injection
    context_json = json.dumps(context_data)

    allowed_modules_str = repr(set(SAFE_MODULES))

    # Use simple string replacement on a known placeholder (not str.format)
    # to avoid issues with curly braces in analysis_code
    preamble = _SANDBOX_PREAMBLE.replace("%%ALLOWED_MODULES%%", allowed_modules_str)

    script = preamble + analysis_code + "\n" + _SANDBOX_EPILOGUE

    return script, context_json


def execute_analysis(
    context_data,
    analysis_code: str,
    timeout_seconds: int = 30,
    max_memory_mb: int = 256,
) -> ExecutionResult:
    """Execute analysis code in a sandboxed subprocess.

    The context data is loaded as a variable in the sandbox, and the
    LLM-generated analysis code can use helper functions (emit, slice_context,
    search_context, summarize_structure) to analyze it.

    Args:
        context_data: Data to analyze (any JSON-serializable type).
        analysis_code: Python code for analysis (will be validated first).
        timeout_seconds: Maximum execution time in seconds.
        max_memory_mb: Maximum memory usage in MB (Linux only via ulimit).

    Returns:
        ExecutionResult with findings or error information.
    """
    # Validate code safety
    is_safe, reason = validate_code(analysis_code)
    if not is_safe:
        return ExecutionResult(
            success=False,
            results=[],
            error=f"Code validation failed: {reason}",
        )

    # Build the sandbox script
    try:
        script, context_json = build_sandbox_code(context_data, analysis_code)
    except (TypeError, ValueError) as e:
        return ExecutionResult(
            success=False,
            results=[],
            error=f"Failed to build sandbox: {e}",
        )

    # Write context to a separate temp file (prevents string-injection attacks)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as ctx_f:
        ctx_f.write(context_json)
        context_path = ctx_f.name

    # Write script to temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(script)
        script_path = f.name

    try:
        # Build command — no shell=True for security
        cmd = [sys.executable, script_path, context_path]

        env = os.environ.copy()
        # Restrict environment for safety
        env.pop("PYTHONSTARTUP", None)
        env.pop("PYTHONPATH", None)

        # Set memory limits via preexec_fn on Linux/macOS (no shell=True)
        preexec = None
        if platform.system() in ("Linux", "Darwin"):
            memory_bytes = max_memory_mb * 1024 * 1024

            def _set_memory_limit():
                """Set virtual memory limit via resource module."""
                try:
                    import resource
                    resource.setrlimit(
                        resource.RLIMIT_AS,
                        (memory_bytes, memory_bytes),
                    )
                except (ImportError, ValueError, OSError):
                    pass  # Best-effort; proceed without limit

            preexec = _set_memory_limit

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
            cwd=tempfile.gettempdir(),
            preexec_fn=preexec,
        )

        if result.returncode != 0:
            return ExecutionResult(
                success=False,
                results=[],
                stdout=result.stdout[:MAX_OUTPUT_SIZE],
                stderr=result.stderr[:MAX_OUTPUT_SIZE],
                error=f"Execution failed with exit code {result.returncode}",
            )

        # Parse output
        stdout = result.stdout[:MAX_OUTPUT_SIZE]
        try:
            output = json.loads(stdout)
            return ExecutionResult(
                success=output.get("success", False),
                results=output.get("results", []),
                stdout=stdout,
                stderr=result.stderr[:2000],
            )
        except json.JSONDecodeError:
            return ExecutionResult(
                success=True,
                results=[{"type": "text", "content": stdout}],
                stdout=stdout,
                stderr=result.stderr[:2000],
            )

    except subprocess.TimeoutExpired:
        return ExecutionResult(
            success=False,
            results=[],
            error=f"Execution timed out after {timeout_seconds}s",
        )
    except OSError as e:
        return ExecutionResult(
            success=False,
            results=[],
            error=f"Execution error: {e}",
        )
    finally:
        # Clean up temp files
        for tmp_path in (script_path, context_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def build_analysis_prompt(query: str, context_summary: dict) -> str:
    """Build a prompt asking the LLM to generate analysis code.

    Args:
        query: The user's search/analysis query.
        context_summary: Structural summary of the available context.

    Returns:
        Prompt string for the LLM to generate Python analysis code.
    """
    # Prompt injection: inherent to LLM-in-the-loop; mitigated by sandbox validation of generated code
    return textwrap.dedent(f"""\
        You are analyzing a codebase context. Write Python code to answer the
        following query. Use the provided helper functions.

        Query: {query}

        Context structure: {json.dumps(context_summary, indent=2)}

        Available helpers:
        - CONTEXT: The full context data (dict/str/list)
        - emit(finding): Record a finding (str or dict)
        - slice_context(start, end, key): Get a slice of context
        - search_context(pattern): Regex search over context
        - summarize_structure(): Get context structure summary
        - Safe imports: {', '.join(sorted(SAFE_MODULES))}

        Rules:
        - Call emit() for each finding
        - Do NOT use open(), os, sys, subprocess, or any I/O
        - Keep code concise and focused on the query
        - Output structured findings with emit({{"type": "...", "content": "..."}})

        Write ONLY the Python analysis code, no markdown or explanation:
    """)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    """CLI entry point for testing the RLM executor."""
    import argparse

    parser = argparse.ArgumentParser(
        description="RLM REPL executor — sandboxed context analysis",
    )
    sub = parser.add_subparsers(dest="command")

    # execute
    ex = sub.add_parser("execute", help="Execute analysis code on context")
    ex.add_argument("--context-file", required=True,
                    help="JSON file containing context data")
    ex.add_argument("--code-file", required=True,
                    help="Python file containing analysis code")
    ex.add_argument("--timeout", type=int, default=30,
                    help="Execution timeout in seconds")
    ex.add_argument("--max-memory", type=int, default=256,
                    help="Max memory in MB")

    # validate
    val = sub.add_parser("validate", help="Validate analysis code safety")
    val.add_argument("--code-file", required=True,
                     help="Python file to validate")

    # build-prompt
    bp = sub.add_parser("build-prompt",
                        help="Build analysis prompt for LLM")
    bp.add_argument("--query", required=True, help="Analysis query")
    bp.add_argument("--context-file", required=True,
                    help="JSON file for context summary")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "execute":
        ctx = json.loads(Path(args.context_file).read_text(encoding="utf-8"))
        code = Path(args.code_file).read_text(encoding="utf-8")
        result = execute_analysis(ctx, code, args.timeout, args.max_memory)
        print(json.dumps(result.to_dict(), indent=2))
        if not result.success:
            sys.exit(1)

    elif args.command == "validate":
        code = Path(args.code_file).read_text(encoding="utf-8")
        is_safe, reason = validate_code(code)
        print(json.dumps({"safe": is_safe, "reason": reason}, indent=2))
        if not is_safe:
            sys.exit(1)

    elif args.command == "build-prompt":
        ctx = json.loads(Path(args.context_file).read_text(encoding="utf-8"))
        prompt = build_analysis_prompt(args.query, ctx)
        print(prompt)


if __name__ == "__main__":
    main()
