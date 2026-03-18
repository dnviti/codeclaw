#!/usr/bin/env python3
"""Ollama local model manager for CTDF.

Provides hardware detection, model recommendation, Ollama installation,
model pulling, and querying for local LLM offloading.

Zero external dependencies — stdlib only.
"""

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


# ── Constants ───────────────────────────────────────────────────────────────

OLLAMA_API_BASE = "http://localhost:11434"
OLLAMA_CONFIG_FILE = ".claude/ollama-config.json"

# Model tiers based on available RAM
MODEL_TIERS = [
    {
        "min_ram": 32,
        "name": "qwen2.5-coder:32b",
        "size_gb": 20,
        "description": "Full-featured coding model for high-end hardware",
        "capabilities": ["code-generation", "code-review", "refactoring", "complex-reasoning"],
    },
    {
        "min_ram": 16,
        "name": "codestral:22b",
        "size_gb": 13,
        "description": "Strong coding model for mid-to-high-end hardware",
        "capabilities": ["code-generation", "code-review", "refactoring"],
    },
    {
        "min_ram": 12,
        "name": "deepseek-coder-v2:16b",
        "size_gb": 9,
        "description": "Balanced coding model for mid-range hardware",
        "capabilities": ["code-generation", "code-review"],
    },
    {
        "min_ram": 8,
        "name": "qwen2.5-coder:7b",
        "size_gb": 4.5,
        "description": "Efficient coding model for standard hardware",
        "capabilities": ["code-generation", "simple-review"],
    },
    {
        "min_ram": 0,
        "name": "qwen2.5-coder:1.5b",
        "size_gb": 1,
        "description": "Lightweight coding model for resource-constrained systems",
        "capabilities": ["code-generation"],
    },
]

# Tasks suitable for local model offloading
OFFLOADABLE_TASKS = [
    "generate-boilerplate",
    "format-code",
    "write-docstrings",
    "simple-refactor",
    "generate-tests-simple",
    "explain-code",
    "variable-naming",
]

# Tool definitions for Ollama tool calling (OpenAI-compatible format, Ollama v0.3+)
OLLAMA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash_execute",
            "description": "Run a shell command and return stdout and stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute.",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file at the given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The file path to read.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file, creating it if it does not exist.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The file path to write to.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file.",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace an exact string in a file with a new string.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The file path to edit.",
                    },
                    "old_string": {
                        "type": "string",
                        "description": "The exact string to find and replace.",
                    },
                    "new_string": {
                        "type": "string",
                        "description": "The replacement string.",
                    },
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep_search",
            "description": "Search file contents for a regex pattern. Returns matching lines.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "The regex pattern to search for.",
                    },
                    "path": {
                        "type": "string",
                        "description": "File or directory to search in. Defaults to current directory.",
                    },
                    "glob": {
                        "type": "string",
                        "description": "Optional glob filter for file names (e.g. '*.py').",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "glob_search",
            "description": "Find files matching a glob pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "The glob pattern (e.g. '**/*.py').",
                    },
                    "path": {
                        "type": "string",
                        "description": "The directory to search in. Defaults to current directory.",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch a URL and return the response body as plain text.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch.",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web and return top results with titles and URLs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    },
                },
                "required": ["query"],
            },
        },
    },
]


# ── Hardware Detection ──────────────────────────────────────────────────────

def _get_ram_gb() -> float:
    """Detect total system RAM in GB."""
    system = platform.system()
    try:
        if system == "Linux":
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return round(kb / (1024 * 1024), 1)
        elif system == "Darwin":
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return round(int(result.stdout.strip()) / (1024 ** 3), 1)
        elif system == "Windows":
            result = subprocess.run(
                ["wmic", "ComputerSystem", "get", "TotalPhysicalMemory", "/value"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().splitlines():
                    if "TotalPhysicalMemory" in line:
                        val = line.split("=")[1].strip()
                        return round(int(val) / (1024 ** 3), 1)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return 0.0


def _get_cpu_cores() -> int:
    """Detect number of CPU cores."""
    try:
        count = os.cpu_count()
        return count if count else 0
    except Exception:
        return 0


def _get_gpu_info() -> tuple[float, str]:
    """Detect GPU VRAM and vendor.

    Returns:
        Tuple of (vram_gb, vendor) where vendor is one of:
        'nvidia', 'amd', 'apple', 'none'.
    """
    system = platform.system()

    # Check NVIDIA
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Sum VRAM across all GPUs (value is in MiB)
            total_mb = sum(
                int(line.strip())
                for line in result.stdout.strip().splitlines()
                if line.strip().isdigit()
            )
            if total_mb > 0:
                return round(total_mb / 1024, 1), "nvidia"
    except (OSError, subprocess.TimeoutExpired):
        pass

    # Check AMD
    try:
        result = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            # Parse rocm-smi JSON output for total VRAM
            total_bytes = 0
            for card_key, card_data in data.items():
                if isinstance(card_data, dict):
                    total_val = card_data.get("VRAM Total Memory (B)", 0)
                    if isinstance(total_val, (int, float)):
                        total_bytes += total_val
            if total_bytes > 0:
                return round(total_bytes / (1024 ** 3), 1), "amd"
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass

    # Check Apple Silicon (unified memory)
    if system == "Darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                # Apple Silicon shares RAM as unified memory; report ~75% as GPU-available
                total_bytes = int(result.stdout.strip())
                # Verify it is actually Apple Silicon
                arch_result = subprocess.run(
                    ["uname", "-m"], capture_output=True, text=True, timeout=10,
                )
                if arch_result.returncode == 0 and "arm64" in arch_result.stdout.strip():
                    unified_gb = round(total_bytes / (1024 ** 3) * 0.75, 1)
                    return unified_gb, "apple"
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass

    return 0.0, "none"


def detect_hardware() -> dict:
    """Detect system hardware capabilities and return as a dict."""
    ram_gb = _get_ram_gb()
    vram_gb, gpu_vendor = _get_gpu_info()
    cpu_cores = _get_cpu_cores()

    return {
        "ram_gb": ram_gb,
        "vram_gb": vram_gb,
        "gpu_vendor": gpu_vendor,
        "cpu_cores": cpu_cores,
        "os": platform.system().lower(),
        "arch": platform.machine(),
    }


# ── Model Recommendation ───────────────────────────────────────────────────

def recommend_model(ram_gb: float, vram_gb: float = 0.0) -> dict:
    """Recommend a model based on available RAM and VRAM.

    Uses the higher of RAM or VRAM for model selection when a
    dedicated GPU is available.
    """
    # Use effective memory: max of RAM and VRAM (dedicated GPU accelerates inference)
    effective_memory = max(ram_gb, vram_gb) if vram_gb > 0 else ram_gb

    for tier in MODEL_TIERS:
        if effective_memory >= tier["min_ram"]:
            return {
                "model": tier["name"],
                "size_gb": tier["size_gb"],
                "description": tier["description"],
                "capabilities": tier["capabilities"],
                "effective_memory_gb": effective_memory,
                "note": (
                    f"Selected for {effective_memory}GB effective memory "
                    f"(RAM: {ram_gb}GB, VRAM: {vram_gb}GB)"
                ),
            }

    # Unreachable: last tier has min_ram=0, so loop always matches.
    # Defensive fallback kept for safety.
    return {
        "model": MODEL_TIERS[-1]["name"],
        "size_gb": MODEL_TIERS[-1]["size_gb"],
        "description": MODEL_TIERS[-1]["description"],
        "capabilities": MODEL_TIERS[-1]["capabilities"],
        "effective_memory_gb": effective_memory,
        "note": "Fallback to smallest model due to limited memory",
    }


# ── Shared API Helper ──────────────────────────────────────────────────────

def _fetch_model_list() -> tuple[bool, list[str]]:
    """Fetch the list of available models from the Ollama API.

    Returns:
        Tuple of (server_running, model_names).
    """
    try:
        req = urllib.request.Request(f"{OLLAMA_API_BASE}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name", "") for m in data.get("models", [])]
                return True, models
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        pass
    return False, []


# ── Installation Check ──────────────────────────────────────────────────────

def check_install() -> dict:
    """Check if Ollama is installed, running, and which models are available."""
    result = {
        "installed": False,
        "version": None,
        "running": False,
        "models": [],
    }

    # Check installed
    try:
        version_result = subprocess.run(
            ["ollama", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        if version_result.returncode == 0:
            result["installed"] = True
            version_text = version_result.stdout.strip()
            # Extract version number from output like "ollama version 0.x.y"
            parts = version_text.split()
            result["version"] = parts[-1] if parts else version_text
    except (OSError, subprocess.TimeoutExpired):
        return result

    # Check running by hitting the API
    running, models = _fetch_model_list()
    result["running"] = running
    result["models"] = models

    return result


# ── Installation ────────────────────────────────────────────────────────────

def install_ollama(target_platform: str | None = None) -> dict:
    """Install Ollama via the platform-appropriate method.

    Args:
        target_platform: One of 'linux', 'macos', 'windows'.
                         Auto-detected if not provided.

    Returns:
        Dict with 'success', 'method', and 'message' keys.
    """
    if target_platform is None:
        system = platform.system().lower()
        target_platform = {
            "linux": "linux",
            "darwin": "macos",
            "windows": "windows",
        }.get(system, system)

    if target_platform == "linux":
        # Use the official install script
        print(
            "Warning: Installing via 'curl | sh' from https://ollama.com/install.sh. "
            "Review the script at this URL if you have security concerns.",
            file=sys.stderr,
        )
        try:
            result = subprocess.run(
                ["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0:
                return {
                    "success": True,
                    "method": "curl install script",
                    "message": "Ollama installed successfully via install script.",
                }
            return {
                "success": False,
                "method": "curl install script",
                "message": f"Installation failed: {result.stderr}",
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "method": "curl install script",
                "message": "Installation timed out after 5 minutes.",
            }

    elif target_platform == "macos":
        # Try Homebrew first
        try:
            result = subprocess.run(
                ["brew", "install", "ollama"],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0:
                return {
                    "success": True,
                    "method": "homebrew",
                    "message": "Ollama installed successfully via Homebrew.",
                }
        except (OSError, subprocess.TimeoutExpired):
            pass

        # Fallback to curl script
        print(
            "Warning: Installing via 'curl | sh' from https://ollama.com/install.sh. "
            "Review the script at this URL if you have security concerns.",
            file=sys.stderr,
        )
        try:
            result = subprocess.run(
                ["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0:
                return {
                    "success": True,
                    "method": "curl install script",
                    "message": "Ollama installed successfully via install script.",
                }
            return {
                "success": False,
                "method": "curl install script",
                "message": f"Installation failed: {result.stderr}",
            }
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "method": "curl install script",
                "message": "Installation timed out after 5 minutes.",
            }

    elif target_platform == "windows":
        return {
            "success": False,
            "method": "manual",
            "message": (
                "Automatic installation on Windows is not supported. "
                "Please download and install Ollama from https://ollama.com/download/windows"
            ),
        }

    return {
        "success": False,
        "method": "unknown",
        "message": f"Unsupported platform: {target_platform}",
    }


# ── Model Pulling ──────────────────────────────────────────────────────────

def pull_model(model_name: str) -> dict:
    """Pull a model using the Ollama CLI with progress output.

    Args:
        model_name: The model identifier (e.g., 'qwen2.5-coder:7b').

    Returns:
        Dict with 'success', 'model', and 'message' keys.
    """
    import re as _re
    if not _re.match(r'^[a-zA-Z0-9._:/-]+$', model_name):
        return {
            "success": False,
            "model": model_name,
            "message": f"Invalid model name: '{model_name}'. "
                       "Model names may only contain alphanumeric characters, dots, colons, hyphens, and slashes.",
        }
    try:
        print(f"Pulling model '{model_name}'...", file=sys.stderr)
        result = subprocess.run(
            ["ollama", "pull", model_name],
            capture_output=True, text=True, timeout=1800,  # 30 min timeout
        )
        if result.returncode == 0:
            return {
                "success": True,
                "model": model_name,
                "message": f"Model '{model_name}' pulled successfully.",
            }
        return {
            "success": False,
            "model": model_name,
            "message": f"Failed to pull model: {result.stderr}",
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "model": model_name,
            "message": "Model pull timed out after 30 minutes.",
        }
    except OSError as e:
        return {
            "success": False,
            "model": model_name,
            "message": f"Ollama not found or not accessible: {e}",
        }


# ── Query ───────────────────────────────────────────────────────────────────

def query_ollama(
    model: str,
    prompt: str,
    system_prompt: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 2048,
) -> dict:
    """Send a completion request to the Ollama REST API.

    Args:
        model: The model name to query.
        prompt: The user prompt.
        system_prompt: Optional system-level instruction.
        temperature: Sampling temperature (default 0.1 for deterministic output).
        max_tokens: Maximum tokens to generate.

    Returns:
        Dict with 'success', 'response', and optional 'error' keys.
    """
    # Validate parameters
    temperature = max(0.0, min(temperature, 2.0))
    max_tokens = max(1, min(max_tokens, 128000))

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    if system_prompt:
        payload["system"] = system_prompt

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_API_BASE}/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return {
                "success": True,
                "response": result.get("response", ""),
                "model": model,
                "eval_count": result.get("eval_count", 0),
                "eval_duration_ns": result.get("eval_duration", 0),
            }
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
        except Exception:
            pass
        return {
            "success": False,
            "response": "",
            "error": f"HTTP {e.code}: {body}",
        }
    except urllib.error.URLError as e:
        return {
            "success": False,
            "response": "",
            "error": f"Connection error: {e.reason}. Is Ollama running?",
        }
    except (OSError, json.JSONDecodeError) as e:
        return {
            "success": False,
            "response": "",
            "error": str(e),
        }


# ── Tool Calling ──────────────────────────────────────────────────────────

def _check_model_supports_tools(model: str) -> bool:
    """Check if a model supports tool calling via /api/show.

    Returns True if the model advertises tool support or if the check
    is inconclusive (optimistic default for newer models).
    """
    try:
        payload = json.dumps({"name": model}).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_API_BASE}/api/show",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        # Check capabilities list if present (Ollama v0.3+)
        capabilities = data.get("capabilities", [])
        if capabilities:
            return "tools" in capabilities

        # Check model template for tool support indicators
        template = data.get("template", "")
        if "tool_call" in template or ".ToolCalls" in template:
            return True

        # Optimistic: assume support and let /api/chat handle errors
        return True
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return True


def execute_tool(name: str, arguments: dict) -> str:
    """Execute a tool call and return the result as a string.

    Dispatches to the appropriate implementation based on tool name.
    Security posture matches Claude Code tool execution — no additional
    sandboxing.

    Args:
        name: The tool function name.
        arguments: The tool call arguments as a dict.

    Returns:
        The tool execution result as a string.
    """
    try:
        if name == "bash_execute":
            command = arguments.get("command", "")
            if not command:
                return "Error: no command provided."
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=120,
            )
            output_parts = []
            if result.stdout:
                output_parts.append(result.stdout)
            if result.stderr:
                output_parts.append(f"STDERR:\n{result.stderr}")
            if result.returncode != 0:
                output_parts.append(f"Exit code: {result.returncode}")
            return "\n".join(output_parts) or "(no output)"

        elif name == "read_file":
            file_path = arguments.get("path", "")
            if not file_path:
                return "Error: no path provided."
            return Path(file_path).read_text(encoding="utf-8")

        elif name == "write_file":
            file_path = arguments.get("path", "")
            content = arguments.get("content", "")
            if not file_path:
                return "Error: no path provided."
            p = Path(file_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"Written {len(content)} bytes to {file_path}"

        elif name == "edit_file":
            file_path = arguments.get("path", "")
            old_string = arguments.get("old_string", "")
            new_string = arguments.get("new_string", "")
            if not file_path:
                return "Error: no path provided."
            if not old_string:
                return "Error: no old_string provided."
            p = Path(file_path)
            content = p.read_text(encoding="utf-8")
            if old_string not in content:
                return f"Error: old_string not found in {file_path}"
            count = content.count(old_string)
            content = content.replace(old_string, new_string, 1)
            p.write_text(content, encoding="utf-8")
            return f"Replaced 1 occurrence in {file_path}" + (
                f" ({count - 1} more occurrences remain)" if count > 1 else ""
            )

        elif name == "grep_search":
            pattern = arguments.get("pattern", "")
            search_path = arguments.get("path", ".")
            file_glob = arguments.get("glob", "")
            if not pattern:
                return "Error: no pattern provided."
            # Try ripgrep first
            rg_cmd = ["rg", "-n", "--no-heading", pattern, search_path]
            if file_glob:
                rg_cmd.extend(["--glob", file_glob])
            try:
                result = subprocess.run(
                    rg_cmd, capture_output=True, text=True, timeout=30,
                )
                if result.returncode <= 1:
                    return result.stdout[:8192] or "(no matches)"
            except (OSError, subprocess.TimeoutExpired):
                pass
            # Fallback: Python re search
            matches = []
            search_p = Path(search_path)
            files = [search_p] if search_p.is_file() else search_p.rglob(file_glob or "*")
            for fp in files:
                if not fp.is_file():
                    continue
                try:
                    for i, line in enumerate(
                        fp.read_text(encoding="utf-8", errors="replace").splitlines(), 1
                    ):
                        if re.search(pattern, line):
                            matches.append(f"{fp}:{i}:{line}")
                            if len(matches) >= 200:
                                break
                except OSError:
                    continue
                if len(matches) >= 200:
                    break
            return "\n".join(matches)[:8192] or "(no matches)"

        elif name == "glob_search":
            pattern = arguments.get("pattern", "")
            search_path = arguments.get("path", ".")
            if not pattern:
                return "Error: no pattern provided."
            results = sorted(Path(search_path).glob(pattern))
            if not results:
                return "(no matches)"
            return "\n".join(str(r) for r in results[:500])

        elif name == "web_fetch":
            url = arguments.get("url", "")
            if not url:
                return "Error: no url provided."
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; CTDF/1.0)"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            # Strip HTML tags for cleaner text
            text = re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:16384]

        elif name == "web_search":
            query = arguments.get("query", "")
            if not query:
                return "Error: no query provided."
            encoded = urllib.parse.urlencode({"q": query})
            url = f"https://lite.duckduckgo.com/lite/?{encoded}"
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; CTDF/1.0)"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            # Parse DuckDuckGo lite results
            results = []
            links = re.findall(
                r'<a[^>]+href="([^"]+)"[^>]*class="[^"]*result-link[^"]*"[^>]*>(.*?)</a>',
                html, re.DOTALL | re.IGNORECASE,
            )
            if not links:
                # Fallback: extract all external links
                links = re.findall(
                    r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                    html, re.DOTALL | re.IGNORECASE,
                )
            for href, title in links[:10]:
                clean_title = re.sub(r"<[^>]+>", "", title).strip()
                if clean_title and "duckduckgo" not in href.lower():
                    results.append(f"- {clean_title}\n  {href}")
            return "\n".join(results) or "(no results found)"

        else:
            return f"Error: unknown tool '{name}'"

    except OSError as e:
        return f"Error executing {name}: {e}"
    except Exception as e:
        return f"Error executing {name}: {type(e).__name__}: {e}"


def query_ollama_with_tools(
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    system_prompt: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 4096,
    max_tool_rounds: int = 10,
) -> dict:
    """Send a chat request with tool definitions and execute a tool-calling loop.

    Uses the /api/chat endpoint with the ``tools`` parameter (OpenAI-compatible
    format, supported since Ollama v0.3). Runs a conversation loop: send
    request with tool definitions -> receive tool_calls from the model ->
    execute each tool locally -> send results back as tool role messages ->
    repeat until the model produces a final content-only response.

    Args:
        model: The model name to query.
        messages: Initial conversation messages (list of role/content dicts).
        tools: Tool definitions in OpenAI-compatible format. Defaults to OLLAMA_TOOLS.
        system_prompt: Optional system-level instruction.
        temperature: Sampling temperature.
        max_tokens: Maximum tokens per response.
        max_tool_rounds: Maximum number of tool-calling round trips.

    Returns:
        Dict with 'success', 'response', 'tool_rounds', and optional 'error'.
    """
    if tools is None:
        tools = OLLAMA_TOOLS

    temperature = max(0.0, min(temperature, 2.0))
    max_tokens = max(1, min(max_tokens, 128000))

    msgs = []
    if system_prompt:
        msgs.append({"role": "system", "content": system_prompt})
    msgs.extend(messages)

    for round_num in range(max_tool_rounds):
        payload = {
            "model": model,
            "messages": msgs,
            "tools": tools,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                f"{OLLAMA_API_BASE}/api/chat",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8")
            except Exception:
                pass
            return {
                "success": False,
                "response": "",
                "tool_rounds": round_num,
                "error": f"HTTP {e.code}: {body}",
            }
        except urllib.error.URLError as e:
            return {
                "success": False,
                "response": "",
                "tool_rounds": round_num,
                "error": f"Connection error: {e.reason}. Is Ollama running?",
            }
        except (OSError, json.JSONDecodeError) as e:
            return {
                "success": False,
                "response": "",
                "tool_rounds": round_num,
                "error": str(e),
            }

        message = result.get("message", {})
        tool_calls = message.get("tool_calls")

        if not tool_calls:
            # Final response — model produced content without tool calls
            return {
                "success": True,
                "response": message.get("content", ""),
                "tool_rounds": round_num + 1,
                "model": model,
            }

        # Append the assistant message (with tool_calls) to the conversation
        msgs.append(message)

        # Execute each tool call and append results
        for tc in tool_calls:
            fn = tc.get("function", {})
            tool_name = fn.get("name", "")
            tool_args = fn.get("arguments", {})
            if isinstance(tool_args, str):
                try:
                    tool_args = json.loads(tool_args)
                except json.JSONDecodeError:
                    tool_args = {}

            print(
                f"  [tool round {round_num + 1}] {tool_name}("
                f"{json.dumps(tool_args)[:120]})",
                file=sys.stderr,
            )

            tool_result = execute_tool(tool_name, tool_args)
            msgs.append({
                "role": "tool",
                "content": tool_result,
            })

    # Exhausted all rounds — return whatever content we have
    last_content = ""
    for m in reversed(msgs):
        if m.get("role") == "assistant" and m.get("content"):
            last_content = m["content"]
            break

    return {
        "success": True,
        "response": last_content,
        "tool_rounds": max_tool_rounds,
        "model": model,
        "error": f"Reached maximum of {max_tool_rounds} tool-calling rounds.",
    }


# ── Health Check ────────────────────────────────────────────────────────────

def health_check(expected_model: str | None = None) -> dict:
    """Check Ollama server status and optionally verify a model is available.

    Args:
        expected_model: If provided, verify this model is loaded.

    Returns:
        Dict with 'healthy', 'server_running', 'model_available', 'models', and 'message'.
    """
    result = {
        "healthy": False,
        "server_running": False,
        "model_available": None,
        "models": [],
        "message": "",
    }

    # Check server
    running, models = _fetch_model_list()
    if not running:
        result["message"] = "Ollama server is not running or not reachable."
        return result

    result["server_running"] = True
    result["models"] = models

    # Check model availability
    if expected_model:
        available = result["models"]
        # Exact match: compare full name (e.g., "qwen2.5-coder:7b")
        # or match name without tag when expected_model has no tag
        model_available = any(
            m == expected_model or
            (":latest" not in expected_model and m == f"{expected_model}:latest")
            for m in available
        )
        result["model_available"] = model_available
        if not model_available:
            result["message"] = (
                f"Model '{expected_model}' is not available. "
                f"Available models: {', '.join(available) if available else 'none'}"
            )
            return result

    result["healthy"] = True
    result["message"] = "Ollama is running and ready."
    return result


def is_available() -> bool:
    """Quick check whether the Ollama server is reachable.

    Returns True if the server responds to a model list request,
    False otherwise.  This is a lightweight probe intended for use
    by ``ConflictJudge`` to decide which provider to fall back to.
    """
    running, _ = _fetch_model_list()
    return running


# ── Configuration Management ───────────────────────────────────────────────

def load_ollama_config(config_path: str | None = None) -> dict | None:
    """Load Ollama configuration from the project config file.

    Args:
        config_path: Override path to config file. Defaults to OLLAMA_CONFIG_FILE.

    Returns:
        Config dict or None if not found/invalid.
    """
    path = Path(config_path) if config_path else Path(OLLAMA_CONFIG_FILE)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_ollama_config(config: dict, config_path: str | None = None) -> None:
    """Save Ollama configuration to the project config file.

    Args:
        config: The configuration dict to save.
        config_path: Override path to config file. Defaults to OLLAMA_CONFIG_FILE.
    """
    path = Path(config_path) if config_path else Path(OLLAMA_CONFIG_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


# ── Task Offloading Logic ──────────────────────────────────────────────────

# Keyword sets used for scoring task complexity (0=trivial, 10=most complex)
_TRIVIAL_KEYWORDS = [
    "boilerplate", "docstring", "format", "rename",
    "variable name", "import sort", "add comment",
    "type annotation", "whitespace", "indentation",
]

_SIMPLE_KEYWORDS = [
    "simple test", "unit test stub", "explain", "summarize",
    "describe", "type hint", "simple refactor", "minor edit",
]

_MEDIUM_KEYWORDS = [
    "refactor", "test generation", "code review", "review",
    "generate test", "add test", "docstring update", "extract function",
]

_COMPLEX_KEYWORDS = [
    "architect", "design", "migrate", "performance",
    "optimize", "concurrency", "race condition", "overhaul",
    "major refactor", "restructure",
]

_CRITICAL_KEYWORDS = [
    "security", "vulnerability", "critical", "breaking change",
    "debug critical", "production issue", "data loss",
]


def compute_offload_score(task_description: str) -> int:
    """Compute an offloadability score (0-10) for a task description.

    Higher scores indicate the task is MORE suitable for local model
    offloading (i.e., simpler/more routine). Lower scores indicate
    frontier-level reasoning is required.

    Scoring:
        0-2  — critical/security/architecture tasks (never offload at normal levels)
        3-4  — complex tasks
        5-6  — medium tasks
        7-8  — simple tasks
        9-10 — trivial tasks (boilerplate, formatting, docstrings)

    Args:
        task_description: A short description of the task.

    Returns:
        Integer score 0-10.
    """
    # O1: Normalize input to ensure consistent scoring regardless of casing/whitespace
    task_description = " ".join(task_description.strip().split())
    description_lower = task_description.lower()

    # Critical overrides everything
    for keyword in _CRITICAL_KEYWORDS:
        if keyword in description_lower:
            return 1

    # Complex tasks
    for keyword in _COMPLEX_KEYWORDS:
        if keyword in description_lower:
            return 3

    # Medium tasks
    for keyword in _MEDIUM_KEYWORDS:
        if keyword in description_lower:
            return 5

    # Simple tasks
    for keyword in _SIMPLE_KEYWORDS:
        if keyword in description_lower:
            return 7

    # Trivial tasks
    for keyword in _TRIVIAL_KEYWORDS:
        if keyword in description_lower:
            return 9

    # Unknown/unclassified: treat as medium
    return 5


def should_offload(task_description: str, level: int) -> bool:
    """Determine if a task should be offloaded to the local Ollama model.

    Offloads when the task's computed score is >= the configured level.
    A higher level allows more aggressive offloading.

    Args:
        task_description: A short description of the task.
        level: Configured offloading level (0-10). Level 0 = never offload,
               level 10 = offload everything.

    Returns:
        True if the task should be routed to Ollama.
    """
    if level <= 0:
        return False
    if level >= 10:
        return True
    score = compute_offload_score(task_description)
    return score >= level


# Patterns that must never be offloaded regardless of level (destructive commands)
_ALWAYS_EXCLUDED_PATTERNS = [
    "git push --force", "git push -f",
    "git reset --hard", "rm -rf /",
    "sudo rm", "chmod 777", "chown root",
    "format c:", "del /f /s /q",
]


def should_offload_tool_call(tool_name: str, tool_args: str, level: int) -> bool:
    """Determine if a tool call should be routed to the local Ollama model.

    Tool call routing rules:
        Bash:       simple commands (ls, cat, git status) at level >= 3
                    complex piped commands at level >= 7
        Read/Grep/Glob: offload pattern generation at level >= 6
        Edit/Write: simple edits (formatting, imports) at level >= 4
                    structural edits at level >= 8

    Args:
        tool_name: Name of the tool (e.g., 'Bash', 'Read', 'Edit').
        tool_args: The arguments/content passed to the tool.
        level: Configured offloading level (0-10).

    Returns:
        True if the tool call should be routed to Ollama.
    """
    if level <= 0:
        return False

    # S1: Normalize whitespace before pattern matching to prevent bypass via extra spaces.
    # Apply NFKC to canonicalize Unicode compatibility equivalences (e.g. fullwidth space U+3000,
    # fullwidth Latin letters, superscripts, ligatures).  Note: NFKC does NOT map cross-script
    # visual lookalikes such as Cyrillic А → Latin A; those require a separate confusables check.
    args_normalized = " ".join(unicodedata.normalize("NFKC", tool_args).split()) if tool_args else ""

    if level >= 10:
        # Even at level 10, exclude dangerous destructive commands
        args_lower = args_normalized.lower()
        for pattern in _ALWAYS_EXCLUDED_PATTERNS:
            if pattern in args_lower:
                return False
        return True

    tool_upper = tool_name.upper() if tool_name else ""
    args_lower = args_normalized.lower()

    if tool_upper == "BASH":
        # Excluded / dangerous patterns — never offload regardless of level
        dangerous_patterns = [
            "git push", "git reset", "rm -rf", "sudo", "chmod", "chown",
        ]
        for pattern in dangerous_patterns:
            if pattern in args_lower:
                return False

        # Simple commands at level >= 3
        simple_bash_keywords = [
            "ls ", "ls\n", "cat ", "git status", "git log",
            "git diff", "git branch", "pwd", "echo ", "which ",
            "find ", "head ", "tail ",
        ]
        if level >= 7:
            # Complex piped commands at level >= 7
            return True
        if level >= 3:
            for kw in simple_bash_keywords:
                if kw in args_lower:
                    return True
            # Single simple command (no pipes, redirects, semicolons).
            # Use args_normalized (post-NFKC) so fullwidth metacharacters (e.g. U+FF5C ｜)
            # cannot bypass this check — SEC-1 fix.
            if not any(c in args_normalized for c in ["|", ">", "<", ";", "&&", "||"]):
                return True
        return False

    elif tool_upper in ("READ", "GREP", "GLOB"):
        # Pattern/search operations at level >= 6
        return level >= 6

    elif tool_upper in ("EDIT", "WRITE"):
        # Structural edits at level >= 8
        structural_indicators = [
            "class ", "def ", "function ", "import ", "from ",
            "struct ", "interface ", "module ",
        ]
        if level >= 8:
            return True
        if level >= 4:
            # Simple edits: formatting, whitespace, comments, imports
            simple_edit_indicators = [
                "format", "whitespace", "indent", "comment",
                "docstring", "type hint", "type annotation",
            ]
            for indicator in simple_edit_indicators:
                if indicator in args_lower:
                    return True
            # Short edits (under 5 lines) heuristic
            line_count = len(tool_args.splitlines())
            if line_count <= 5 and not any(ind in args_lower for ind in structural_indicators):
                return True
        return False

    # Unknown tools: conservative — do not offload
    return False


def get_offload_level(config: dict) -> int:
    """Extract the numeric offload level from the Ollama config dict.

    Args:
        config: The Ollama configuration dictionary (as loaded from ollama-config.json).

    Returns:
        Integer offload level 0-10. Returns 0 if offloading is disabled or not configured.
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


def is_offloadable(task_description: str) -> bool:
    """Determine if a task is suitable for local model offloading.

    .. deprecated::
        Use :func:`should_offload` with an explicit level instead.
        This function is kept for backward compatibility and is equivalent
        to ``should_offload(task_description, level=5)``.

    Args:
        task_description: A short description of the task.

    Returns:
        True if the task can be offloaded to the local model.
    """
    return should_offload(task_description, level=5)


# ── CLI Entry Point ─────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ollama local model manager for CTDF.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 ollama_manager.py detect-hardware\n"
            "  python3 ollama_manager.py recommend-model --ram 16 --vram 8\n"
            "  python3 ollama_manager.py check-install\n"
            "  python3 ollama_manager.py install --platform linux\n"
            "  python3 ollama_manager.py pull-model --name qwen2.5-coder:7b\n"
            '  python3 ollama_manager.py query --model qwen2.5-coder:7b --prompt "Write a hello world"\n'
            "  python3 ollama_manager.py health\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # detect-hardware
    subparsers.add_parser("detect-hardware", help="Detect system hardware capabilities")

    # recommend-model
    rec_parser = subparsers.add_parser("recommend-model", help="Recommend a model based on specs")
    rec_parser.add_argument("--ram", type=float, required=True, help="Total RAM in GB")
    rec_parser.add_argument("--vram", type=float, default=0.0, help="GPU VRAM in GB")

    # check-install
    subparsers.add_parser("check-install", help="Check Ollama installation status")

    # install
    inst_parser = subparsers.add_parser("install", help="Install Ollama")
    inst_parser.add_argument(
        "--platform",
        choices=["linux", "macos", "windows"],
        default=None,
        help="Target platform (auto-detected if omitted)",
    )

    # pull-model
    pull_parser = subparsers.add_parser("pull-model", help="Pull a model from Ollama registry")
    pull_parser.add_argument("--name", required=True, help="Model name (e.g., qwen2.5-coder:7b)")

    # query
    query_parser = subparsers.add_parser("query", help="Send a completion request to Ollama")
    query_parser.add_argument("--model", required=True, help="Model name to query")
    query_parser.add_argument("--prompt", required=True, help="User prompt")
    query_parser.add_argument("--system", default=None, help="System prompt")
    query_parser.add_argument("--temperature", type=float, default=0.1, help="Sampling temperature")
    query_parser.add_argument("--max-tokens", type=int, default=2048, help="Max tokens to generate")
    tools_group = query_parser.add_mutually_exclusive_group()
    tools_group.add_argument(
        "--with-tools", action="store_true", default=None,
        help="Enable tool calling via /api/chat (default when model supports it)",
    )
    tools_group.add_argument(
        "--no-tools", action="store_true",
        help="Disable tool calling, use /api/generate",
    )
    query_parser.add_argument(
        "--max-tool-rounds", type=int, default=10,
        help="Maximum tool-calling round trips (default 10)",
    )

    # health
    health_parser = subparsers.add_parser("health", help="Check Ollama server health")
    health_parser.add_argument("--model", default=None, help="Expected model to verify")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "detect-hardware":
        print(json.dumps(detect_hardware(), indent=2))

    elif args.command == "recommend-model":
        print(json.dumps(recommend_model(args.ram, args.vram), indent=2))

    elif args.command == "check-install":
        print(json.dumps(check_install(), indent=2))

    elif args.command == "install":
        result = install_ollama(args.platform)
        print(json.dumps(result, indent=2))
        if not result["success"]:
            sys.exit(1)

    elif args.command == "pull-model":
        result = pull_model(args.name)
        print(json.dumps(result, indent=2))
        if not result["success"]:
            sys.exit(1)

    elif args.command == "query":
        # Determine tool-calling mode
        use_tools = None
        if getattr(args, "with_tools", None):
            use_tools = True
        elif getattr(args, "no_tools", None):
            use_tools = False

        if use_tools is None:
            use_tools = _check_model_supports_tools(args.model)

        if use_tools:
            messages = [{"role": "user", "content": args.prompt}]
            result = query_ollama_with_tools(
                model=args.model,
                messages=messages,
                system_prompt=args.system,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
                max_tool_rounds=getattr(args, "max_tool_rounds", 10),
            )
        else:
            result = query_ollama(
                model=args.model,
                prompt=args.prompt,
                system_prompt=args.system,
                temperature=args.temperature,
                max_tokens=args.max_tokens,
            )
        print(json.dumps(result, indent=2))
        if not result["success"]:
            sys.exit(1)

    elif args.command == "health":
        result = health_check(args.model)
        print(json.dumps(result, indent=2))
        if not result["healthy"]:
            sys.exit(1)


if __name__ == "__main__":
    main()
