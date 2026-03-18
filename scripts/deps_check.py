#!/usr/bin/env python3
"""Optional dependency checker for CTDF vector memory layer.

Validates that opt-in dependencies (LanceDB, ONNX Runtime, sentence-transformers
tokenizer) are installed and provides clear installation instructions when they
are missing.

Zero external dependencies in this module itself — stdlib only.
"""

import importlib
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

    Returns a list of available GPU provider names (excluding CPU).
    Returns empty list if onnxruntime is not installed.
    """
    try:
        import onnxruntime as ort
        all_providers = ort.get_available_providers()
        return [p for p in all_providers if p != "CPUExecutionProvider"]
    except (ImportError, AttributeError):
        return []


def print_status():
    """Print a human-readable status table of all optional deps."""
    statuses = check_all()
    print("CTDF Vector Memory — Optional Dependencies")
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

if __name__ == "__main__":
    print_status()
    ok, _ = check_vector_memory_deps()
    sys.exit(0 if ok else 1)
