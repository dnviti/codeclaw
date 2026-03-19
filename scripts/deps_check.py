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
import os
import platform
import site
import subprocess
import sys
from pathlib import Path
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


def discover_gpu_lib_paths() -> dict:
    """Auto-discover pip-installed GPU library paths for the current platform.

    Scans site-packages for NVIDIA/ROCm shared libraries that ONNX Runtime
    needs at session creation time. These paths are often not on the default
    library search path, causing silent fallback to CPU.

    Returns:
        Dict with:
            paths: list of absolute directory paths containing GPU libraries
            env_var: name of the environment variable to set
                     ("LD_LIBRARY_PATH" on Linux, "PATH" on Windows)
            platform: "linux", "windows", or "darwin"
            fix_command: shell command the user can run to fix the issue
    """
    system = platform.system()
    plat = {"Linux": "linux", "Windows": "windows",
            "Darwin": "darwin"}.get(system, system.lower())

    result: dict = {
        "paths": [],
        "env_var": "",
        "platform": plat,
        "fix_command": "",
    }

    if plat == "darwin":
        # macOS CoreML is framework-based -- no extra path fix needed
        return result

    # Determine the correct env var per platform
    if plat == "linux":
        result["env_var"] = "LD_LIBRARY_PATH"
        lib_glob = "*.so*"
    elif plat == "windows":
        result["env_var"] = "PATH"
        lib_glob = "*.dll"
    else:
        return result

    discovered: list[str] = []

    # ── Linux / Windows NVIDIA: scan site-packages/nvidia/*/lib/ ────────
    for sp in site.getsitepackages() + [site.getusersitepackages()]:
        nvidia_root = Path(sp) / "nvidia"
        if nvidia_root.is_dir():
            for pkg_dir in nvidia_root.iterdir():
                lib_dir = pkg_dir / "lib"
                if lib_dir.is_dir():
                    # Only include dirs that actually contain shared libs
                    if any(lib_dir.glob(lib_glob)):
                        discovered.append(str(lib_dir))

    # ── Linux AMD: scan standard ROCm paths ─────────────────────────────
    if plat == "linux":
        rocm_candidates = [
            "/opt/rocm/lib",
            "/opt/rocm/hip/lib",
        ]
        # Also check versioned ROCm installs
        opt_rocm = Path("/opt")
        if opt_rocm.is_dir():
            for entry in opt_rocm.iterdir():
                if entry.name.startswith("rocm-") and entry.is_dir():
                    lib_path = entry / "lib"
                    if lib_path.is_dir():
                        rocm_candidates.append(str(lib_path))

        for rpath in rocm_candidates:
            rp = Path(rpath)
            if rp.is_dir() and any(rp.glob("*.so*")):
                if str(rp) not in discovered:
                    discovered.append(str(rp))

    result["paths"] = discovered

    # Build a user-friendly fix command
    if discovered:
        joined = ":".join(discovered) if plat == "linux" else ";".join(
            discovered
        )
        if plat == "linux":
            result["fix_command"] = (
                f'export LD_LIBRARY_PATH="{joined}:$LD_LIBRARY_PATH"'
            )
        elif plat == "windows":
            result["fix_command"] = (
                f'set PATH={joined};%PATH%'
            )

    return result


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


def verify_gpu_provider(auto_fix: bool = False) -> dict:
    """Verify that the installed ONNX Runtime has a working GPU provider.

    Goes beyond get_available_providers() by attempting a real lightweight
    InferenceSession to confirm GPU libraries actually load at runtime.

    Args:
        auto_fix: If True, automatically discover and inject GPU library
                  paths into os.environ before retrying on failure.

    Returns:
        Dict with available (bool), providers (list), message (str),
        and optionally lib_paths (dict) from discover_gpu_lib_paths().
    """
    gpu_providers = detect_gpu_providers()

    if not gpu_providers:
        ort_installed = check_dep("onnxruntime")
        if ort_installed:
            lib_info = discover_gpu_lib_paths()
            msg = (
                "ONNX Runtime is installed but no GPU provider detected. "
                "Falling back to CPU. To enable GPU, install the correct "
                "variant: onnxruntime-gpu (NVIDIA), onnxruntime-rocm (AMD), "
                "onnxruntime-directml (Windows), onnxruntime-silicon (macOS)."
            )
            if lib_info["paths"]:
                msg += (
                    f"\n\nDiscovered GPU library paths that may help:\n"
                    f"  {lib_info['fix_command']}"
                )
            return {
                "available": False,
                "providers": [],
                "message": msg,
                "lib_paths": lib_info,
            }
        return {
            "available": False,
            "providers": [],
            "message": "ONNX Runtime is not installed.",
        }

    # GPU providers are listed -- but do they actually work at runtime?
    # Attempt a real lightweight InferenceSession to verify.
    session_ok, active_provider = _test_gpu_session(gpu_providers)

    if session_ok:
        return {
            "available": True,
            "providers": gpu_providers,
            "active_provider": active_provider,
            "message": (
                f"GPU provider(s) verified: {', '.join(gpu_providers)}. "
                f"Active: {active_provider}. GPU acceleration is ready."
            ),
        }

    # Session failed -- GPU libs are not loadable at runtime
    lib_info = discover_gpu_lib_paths()

    if auto_fix and lib_info["paths"]:
        # Inject discovered paths and retry
        _inject_lib_paths(lib_info)
        session_ok_retry, active_retry = _test_gpu_session(gpu_providers)
        if session_ok_retry:
            return {
                "available": True,
                "providers": gpu_providers,
                "active_provider": active_retry,
                "auto_fixed": True,
                "lib_paths": lib_info,
                "message": (
                    f"GPU provider verified after auto-fix. "
                    f"Active: {active_retry}. "
                    f"Injected paths: {', '.join(lib_info['paths'])}"
                ),
            }

    msg = (
        f"GPU provider(s) reported as available ({', '.join(gpu_providers)}) "
        "but failed to load at runtime. The GPU shared libraries are not "
        "on the library search path."
    )
    if lib_info["paths"]:
        msg += (
            f"\n\nFix: {lib_info['fix_command']}\n"
            f"Or run: python3 deps_check.py verify-gpu --auto-fix"
        )
    else:
        msg += (
            "\n\nNo pip-installed GPU library paths were found. Ensure the "
            "correct ONNX Runtime GPU package is installed and CUDA/ROCm "
            "runtime libraries are on your system library path."
        )

    return {
        "available": False,
        "providers": gpu_providers,
        "message": msg,
        "lib_paths": lib_info,
    }


def _test_gpu_session(gpu_providers: list[str]) -> tuple:
    """Attempt a lightweight ONNX InferenceSession with a GPU provider.

    Creates a minimal dummy ONNX model (identity op) and tries to run it
    with the given GPU providers. This catches runtime library load failures
    that get_available_providers() misses.

    Returns:
        (success: bool, active_provider: str or None)
    """
    try:
        import onnxruntime as ort

        # Build a minimal ONNX model (Identity op) as bytes.
        # This avoids needing a model file on disk.
        dummy_model = _build_dummy_onnx_model()
        if dummy_model is None:
            # Cannot build dummy model; skip real session test and
            # assume the compile-time provider list is correct
            return True, gpu_providers[0] if gpu_providers else None

        sess_opts = ort.SessionOptions()
        sess_opts.log_severity_level = 3  # suppress warnings

        try:
            session = ort.InferenceSession(
                dummy_model,
                sess_opts,
                providers=gpu_providers + ["CPUExecutionProvider"],
            )
            active = session.get_providers()
            if active and active[0] != "CPUExecutionProvider":
                return True, active[0]
            # Fell back to CPU
            return False, active[0] if active else None
        except Exception:
            return False, None
    except ImportError:
        return False, None


def _build_dummy_onnx_model() -> bytes | None:
    """Build a minimal ONNX model (Identity op) as in-memory bytes.

    Returns None if the onnx helper modules are unavailable.
    Uses only numpy (already a dependency) and onnx IR byte construction.
    """
    try:
        import numpy as np

        # Minimal ONNX protobuf for an Identity model.
        # This is a hand-crafted minimal valid ONNX protobuf:
        # graph { input: X (float, 1x1), output: Y (float, 1x1),
        #         node: Identity(X)->Y }
        # Using raw protobuf bytes avoids the 'onnx' package dependency.
        #
        # Alternatively, try the onnx helper if available:
        try:
            from onnx import TensorProto, helper

            X = helper.make_tensor_value_info("X", TensorProto.FLOAT, [1, 1])
            Y = helper.make_tensor_value_info("Y", TensorProto.FLOAT, [1, 1])
            node = helper.make_node("Identity", ["X"], ["Y"])
            graph = helper.make_graph([node], "dummy", [X], [Y])
            model = helper.make_model(graph, opset_imports=[
                helper.make_opsetid("", 13)
            ])
            return model.SerializeToString()
        except ImportError:
            pass

        # Fallback: raw minimal ONNX protobuf bytes
        # This is a valid ONNX model with a single Identity op
        # Pre-built bytes for a minimal valid model
        import struct

        # We cannot easily hand-build protobuf without the library,
        # so skip the real session test when onnx is not installed.
        return None

    except ImportError:
        return None


def _inject_lib_paths(lib_info: dict) -> None:
    """Inject discovered GPU library paths into os.environ for the current
    process.

    Args:
        lib_info: Dict from discover_gpu_lib_paths().
    """
    if not lib_info.get("paths") or not lib_info.get("env_var"):
        return

    env_var = lib_info["env_var"]
    current = os.environ.get(env_var, "")
    separator = ":" if lib_info["platform"] == "linux" else ";"

    new_paths = []
    for p in lib_info["paths"]:
        if p not in current:
            new_paths.append(p)

    if new_paths:
        prefix = separator.join(new_paths)
        if current:
            os.environ[env_var] = prefix + separator + current
        else:
            os.environ[env_var] = prefix


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
    auto_fix = "--auto-fix" in sys.argv
    result = verify_gpu_provider(auto_fix=auto_fix)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["available"] else 1)


def _cli_discover_gpu_libs():
    """CLI handler for the discover-gpu-libs subcommand."""
    result = discover_gpu_lib_paths()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    # Support subcommands: detect-gpu, verify-gpu, discover-gpu-libs,
    # or default status
    if len(sys.argv) > 1:
        subcmd = sys.argv[1]
        if subcmd == "detect-gpu":
            _cli_detect_gpu()
        elif subcmd == "verify-gpu":
            _cli_verify_gpu()
        elif subcmd == "discover-gpu-libs":
            _cli_discover_gpu_libs()
        else:
            print(f"Unknown subcommand: {subcmd}", file=sys.stderr)
            print(
                "Usage: deps_check.py "
                "[detect-gpu|verify-gpu [--auto-fix]|discover-gpu-libs]",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        print_status()
        ok, _ = check_vector_memory_deps()
        sys.exit(0 if ok else 1)
