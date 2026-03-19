#!/usr/bin/env python3
"""Optional dependency checker for CodeClaw vector memory layer.

Validates that opt-in dependencies (LanceDB, ONNX Runtime, sentence-transformers
tokenizer) are installed and provides clear installation instructions when they
are missing.

Also provides GPU hardware detection for selecting the correct ONNX Runtime
package variant during setup.

Zero external dependencies in this module itself — stdlib only.
"""

import importlib
import json
import platform
import subprocess
import sys
from typing import NamedTuple


class DepStatus(NamedTuple):
    name: str
    installed: bool
    version: str
    pip_install: str
    purpose: str


# ── Dependency Registry ──────────────────────────────────────────────────────

OPTIONAL_DEPS: list[dict[str, str]] = [
    {
        "module": "lancedb",
        "name": "LanceDB",
        "pip": "lancedb",
        "purpose": "Embedded vector database (Apache Arrow format, zero-server)",
    },
    {
        "module": "onnxruntime",
        "name": "ONNX Runtime",
        "pip": "onnxruntime",
        "purpose": "Local embedding model inference (all-MiniLM-L6-v2)",
    },
    {
        "module": "tokenizers",
        "name": "HuggingFace Tokenizers",
        "pip": "tokenizers",
        "purpose": "Fast BPE/WordPiece tokenization for local embedding models",
    },
    {
        "module": "pyarrow",
        "name": "PyArrow",
        "pip": "pyarrow",
        "purpose": "Apache Arrow support required by LanceDB",
    },
    {
        "module": "numpy",
        "name": "NumPy",
        "pip": "numpy",
        "purpose": "Numerical array operations for embedding vectors",
    },
]


def _get_version(module_name: str) -> str:
    """Try to get the version of an installed module."""
    try:
        mod = importlib.import_module(module_name)
        for attr in ("__version__", "VERSION", "version"):
            v = getattr(mod, attr, None)
            if v:
                return str(v)
    except Exception:
        pass
    return "unknown"


def check_dep(module_name: str) -> bool:
    """Check if a single module is importable."""
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


def check_all() -> list[DepStatus]:
    """Check all optional dependencies and return their status."""
    results = []
    for dep in OPTIONAL_DEPS:
        installed = check_dep(dep["module"])
        version = _get_version(dep["module"]) if installed else ""
        results.append(DepStatus(
            name=dep["name"],
            installed=installed,
            version=version,
            pip_install=dep["pip"],
            purpose=dep["purpose"],
        ))
    return results


def check_vector_memory_deps() -> tuple[bool, list[str]]:
    """Check the minimum deps needed for vector memory.

    Returns (all_ok, list_of_missing_package_names).
    Core deps: lancedb, onnxruntime, pyarrow, numpy.
    """
    core = ["lancedb", "onnxruntime", "pyarrow", "numpy"]
    missing = [m for m in core if not check_dep(m)]
    return len(missing) == 0, missing


def install_instructions(missing: list[str] | None = None) -> str:
    """Generate pip install instructions for missing dependencies."""
    if missing is None:
        _, missing = check_vector_memory_deps()
    if not missing:
        return "All vector memory dependencies are installed."

    pip_names = []
    for dep in OPTIONAL_DEPS:
        if dep["module"] in missing:
            pip_names.append(dep["pip"])

    lines = [
        "Vector memory requires the following optional dependencies:",
        "",
    ]
    for dep in OPTIONAL_DEPS:
        if dep["module"] in missing:
            lines.append(f"  - {dep['name']}: {dep['purpose']}")
    lines.append("")
    lines.append("Install all at once:")
    lines.append(f"  pip install {' '.join(pip_names)}")
    lines.append("")
    lines.append("Or install the convenience bundle:")
    lines.append("  pip install lancedb onnxruntime tokenizers numpy pyarrow")
    return "\n".join(lines)


def detect_gpu_providers() -> list[str]:
    """Detect available ONNX Runtime GPU execution providers.

    Separate GPU detection: deps_check.py is stdlib-only by design; cannot import local_onnx

    Returns a list of available GPU provider names (excluding CPU).
    Returns empty list if onnxruntime is not installed.
    """
    try:
        import onnxruntime as ort
        all_providers = ort.get_available_providers()
        return [p for p in all_providers if p != "CPUExecutionProvider"]
    except (ImportError, AttributeError):
        return []


def detect_gpu() -> dict:
    """Detect GPU hardware and recommend the correct ONNX Runtime package.

    Reuses the GPU detection logic from ollama_manager.py (_get_gpu_info)
    to identify the GPU vendor and VRAM, then maps to the appropriate
    onnxruntime pip package variant.

    Returns:
        Dict with vendor, vram_gb, recommended_package, and gpu_mode fields.
        Example: {"vendor": "nvidia", "vram_gb": 8.0,
                  "recommended_package": "onnxruntime-gpu", "gpu_mode": "gpu"}
    """
    vendor, vram_gb = _detect_gpu_hardware()

    # Map vendor to recommended pip package
    system = platform.system()
    package_map = {
        "nvidia": "onnxruntime-gpu",
        "amd": "onnxruntime-rocm",
        "apple": "onnxruntime-silicon",
    }

    if vendor == "none":
        # Check for Windows DirectML support
        if system == "Windows":
            recommended = "onnxruntime-directml"
            gpu_mode = "gpu"
        else:
            recommended = "onnxruntime"
            gpu_mode = "cpu"
    else:
        recommended = package_map.get(vendor, "onnxruntime")
        gpu_mode = "gpu"

    return {
        "vendor": vendor,
        "vram_gb": vram_gb,
        "recommended_package": recommended,
        "gpu_mode": gpu_mode,
    }


def _detect_gpu_hardware() -> tuple:
    """Detect GPU VRAM and vendor using platform-specific tools.

    Mirrors the logic from ollama_manager.py _get_gpu_info() to avoid
    a cross-module import (deps_check.py is stdlib-only by design).

    Returns:
        Tuple of (vendor: str, vram_gb: float) where vendor is one of:
        'nvidia', 'amd', 'apple', 'none'.
    """
    system = platform.system()

    # Check NVIDIA via nvidia-smi
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            total_mb = sum(
                int(line.strip())
                for line in result.stdout.strip().splitlines()
                if line.strip().isdigit()
            )
            if total_mb > 0:
                return "nvidia", round(total_mb / 1024, 1)
    except (OSError, subprocess.TimeoutExpired):
        pass

    # Check AMD via rocm-smi
    try:
        result = subprocess.run(
            ["rocm-smi", "--showmeminfo", "vram", "--json"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            total_bytes = 0
            for card_key, card_data in data.items():
                if isinstance(card_data, dict):
                    total_val = card_data.get("VRAM Total Memory (B)", 0)
                    if isinstance(total_val, (int, float)):
                        total_bytes += total_val
            if total_bytes > 0:
                return "amd", round(total_bytes / (1024 ** 3), 1)
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
                total_bytes = int(result.stdout.strip())
                arch_result = subprocess.run(
                    ["uname", "-m"],
                    capture_output=True, text=True, timeout=10,
                )
                if (arch_result.returncode == 0
                        and "arm64" in arch_result.stdout.strip()):
                    unified_gb = round(total_bytes / (1024 ** 3) * 0.75, 1)
                    return "apple", unified_gb
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass

    return "none", 0.0


def verify_gpu_provider() -> dict:
    """Verify that the installed ONNX Runtime has a working GPU provider.

    Checks whether a GPU execution provider is actually available after
    the appropriate onnxruntime package has been installed.

    Returns:
        Dict with available (bool), providers (list), and message (str).
    """
    gpu_providers = detect_gpu_providers()
    if gpu_providers:
        return {
            "available": True,
            "providers": gpu_providers,
            "message": (
                f"GPU provider(s) available: {', '.join(gpu_providers)}. "
                "GPU acceleration is ready."
            ),
        }
    else:
        ort_installed = check_dep("onnxruntime")
        if ort_installed:
            return {
                "available": False,
                "providers": [],
                "message": (
                    "ONNX Runtime is installed but no GPU provider detected. "
                    "Falling back to CPU. To enable GPU, install the correct "
                    "variant: onnxruntime-gpu (NVIDIA), onnxruntime-rocm (AMD), "
                    "onnxruntime-directml (Windows), onnxruntime-silicon (macOS)."
                ),
            }
        return {
            "available": False,
            "providers": [],
            "message": "ONNX Runtime is not installed.",
        }


def print_status():
    """Print a human-readable status table of all optional deps."""
    statuses = check_all()
    print("CodeClaw Vector Memory — Optional Dependencies")
    print("=" * 55)
    for s in statuses:
        mark = "OK" if s.installed else "MISSING"
        ver = f" ({s.version})" if s.version else ""
        print(f"  [{mark:>7}] {s.name:<25}{ver}")
        if not s.installed:
            print(f"           pip install {s.pip_install}")
    print()

    # GPU acceleration status
    gpu_providers = detect_gpu_providers()
    print("GPU Acceleration")
    print("-" * 55)
    if gpu_providers:
        print(f"  Available GPU providers: {', '.join(gpu_providers)}")
        print("  GPU acceleration will be used automatically (mode=auto).")
    else:
        ort_installed = check_dep("onnxruntime")
        if ort_installed:
            print("  No GPU providers detected (CPU-only onnxruntime installed).")
            print("  For GPU acceleration, install the appropriate variant:")
            print("    NVIDIA:  pip install onnxruntime-gpu")
            print("    AMD:     pip install onnxruntime-rocm")
            print("    Windows: pip install onnxruntime-directml")
            print("    macOS:   pip install onnxruntime-silicon")
        else:
            print("  ONNX Runtime not installed — GPU detection skipped.")
    print()

    ok, missing = check_vector_memory_deps()
    if ok:
        print("Status: Ready for vector memory indexing.")
    else:
        print(f"Status: {len(missing)} core dependency(ies) missing.")
        print("        Vector memory features will be disabled.")


# ── CLI ──────────────────────────────────────────────────────────────────────

def _cli_detect_gpu():
    """CLI handler for the detect-gpu subcommand."""
    result = detect_gpu()
    print(json.dumps(result, indent=2))


def _cli_verify_gpu():
    """CLI handler for the verify-gpu subcommand."""
    result = verify_gpu_provider()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["available"] else 1)


if __name__ == "__main__":
    # Support subcommands: detect-gpu, verify-gpu, or default status
    if len(sys.argv) > 1:
        subcmd = sys.argv[1]
        if subcmd == "detect-gpu":
            _cli_detect_gpu()
        elif subcmd == "verify-gpu":
            _cli_verify_gpu()
        else:
            print(f"Unknown subcommand: {subcmd}", file=sys.stderr)
            print("Usage: deps_check.py [detect-gpu|verify-gpu]",
                  file=sys.stderr)
            sys.exit(1)
    else:
        print_status()
        ok, _ = check_vector_memory_deps()
        sys.exit(0 if ok else 1)
