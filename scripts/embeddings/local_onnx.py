"""Local ONNX Runtime embedding provider.

Uses the all-MiniLM-L6-v2 model (or compatible) via ONNX Runtime for
fully local, zero-server embedding generation.

Requires: onnxruntime, tokenizers, numpy (optional dependencies).

Model download:
    The ONNX model files are auto-downloaded on first use to
    ~/.cache/claw/models/<model_name>/ using urllib (stdlib).
"""

import json
import os
import platform
import re
import sys
import urllib.request
import urllib.error
import urllib.parse
from pathlib import Path
from typing import Optional

from embeddings import EmbeddingProvider


# ── Model Name Validation ────────────────────────────────────────────────────

# Allow only safe model name characters: alphanumeric, hyphens, underscores,
# dots, and forward slashes (for org/model patterns like "sentence-transformers/all-MiniLM-L6-v2").
# Rejects path traversal sequences (../), URL-encoded chars (%xx), and other
# characters that could be used for SSRF or path injection.
_MODEL_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]*$")


def _sanitize_model_name(model_name: str) -> str:
    """Validate and sanitize a model name to prevent SSRF and path traversal.

    Args:
        model_name: Model name from config or user input.

    Returns:
        The validated model name (unchanged if valid).

    Raises:
        ValueError: If the model name contains unsafe characters.
    """
    if not model_name or not _MODEL_NAME_RE.match(model_name):
        raise ValueError(
            f"Invalid model name: {model_name!r}. "
            f"Model names must contain only alphanumeric characters, "
            f"hyphens, underscores, dots, and forward slashes."
        )
    # Reject path traversal attempts
    if ".." in model_name or model_name.startswith("/"):
        raise ValueError(
            f"Invalid model name: {model_name!r}. "
            f"Model names must not contain '..' or start with '/'."
        )
    return model_name


# ── Model Registry ───────────────────────────────────────────────────────────

_MODEL_REGISTRY = {
    "all-MiniLM-L6-v2": {
        "dimension": 384,
        "onnx_url": "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/onnx/model.onnx",
        "tokenizer_url": "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/tokenizer.json",
        "config_url": "https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/tokenizer_config.json",
        "max_seq_length": 256,
    },
}

_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "claw" / "models"
# Legacy cache path for backward compatibility with existing installations
_LEGACY_CACHE_DIR = Path.home() / ".cache" / "claw" / "models"

_ALLOWED_DOWNLOAD_HOSTS = {"huggingface.co"}


# ── GPU Provider Detection ────────────────────────────────────────────────────

# Ranked by preference: best GPU provider first, CPU last
_PROVIDER_PREFERENCE = [
    "CUDAExecutionProvider",
    "ROCMExecutionProvider",
    "CoreMLExecutionProvider",
    "DmlExecutionProvider",
    "OpenVINOExecutionProvider",
    "CPUExecutionProvider",
]

_VALID_GPU_MODES = ("auto", "gpu", "cpu")


def _load_gpu_lib_paths_from_config() -> list[str]:
    """Load stored GPU library paths from project-config.json.

    Looks for vector_memory.gpu_acceleration.lib_paths in the config
    file located at .claude/project-config.json relative to the
    repository root.

    Returns:
        List of directory paths, or empty list if not configured.
    """
    # Try common config locations
    candidates = [
        Path(".claude/project-config.json"),
    ]
    # Also check relative to this file's location (plugin root)
    plugin_root = Path(__file__).resolve().parent.parent.parent
    candidates.append(plugin_root / ".claude" / "project-config.json")

    for config_path in candidates:
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                gpu_cfg = config.get("vector_memory", {}).get(
                    "gpu_acceleration", {}
                )
                raw_paths = gpu_cfg.get("lib_paths", [])
                # Validate: must be a list of strings
                if isinstance(raw_paths, list):
                    return [p for p in raw_paths if isinstance(p, str)]
                return []
            except (json.JSONDecodeError, OSError):
                continue
    return []


def _inject_gpu_lib_paths(paths: list[str]) -> None:
    """Prepend GPU library paths to the platform's library search path.

    Linux:  prepend to LD_LIBRARY_PATH
    Windows: prepend to PATH
    macOS:  no-op (CoreML is framework-based)

    Only injects paths that are not already present in the env var.
    Validates that each path is an existing directory before injection
    to prevent injection of arbitrary paths from config files.
    """
    if not paths:
        return

    system = platform.system()
    if system == "Darwin":
        return  # CoreML needs no path fix
    elif system == "Linux":
        env_var = "LD_LIBRARY_PATH"
        separator = ":"
    elif system == "Windows":
        env_var = "PATH"
        separator = ";"
    else:
        return

    current = os.environ.get(env_var, "")
    # Only inject paths that exist as directories and are not already present
    new_paths = [
        p for p in paths
        if p not in current and Path(p).is_dir()
    ]

    if new_paths:
        prefix = separator.join(new_paths)
        if current:
            os.environ[env_var] = prefix + separator + current
        else:
            os.environ[env_var] = prefix


def _build_platform_gpu_error_message(gpu_mode: str,
                                      active_provider: str) -> str:
    """Build a platform-aware actionable error message for GPU fallback.

    Args:
        gpu_mode: The requested GPU mode ("gpu").
        active_provider: The provider that actually loaded (e.g. "CPU").

    Returns:
        A detailed error message with platform-specific instructions.
    """
    system = platform.system()

    base_msg = (
        f"gpu_mode='{gpu_mode}' requested but ONNX Runtime silently fell "
        f"back to {active_provider}. The GPU shared libraries failed to load "
        f"at session creation time."
    )

    if system == "Linux":
        platform_msg = (
            "\n\nLinux fix options:\n"
            "  1. Auto-fix: python3 scripts/deps_check.py verify-gpu "
            "--auto-fix\n"
            "  2. Manual: export LD_LIBRARY_PATH to include "
            "site-packages/nvidia/*/lib/\n"
            "     Example: export LD_LIBRARY_PATH=$(python3 -c "
            "\"import nvidia.cublas.lib; import nvidia.cudnn.lib; "
            "print(':'.join([nvidia.cublas.lib.__path__[0], "
            "nvidia.cudnn.lib.__path__[0]]))\"):$LD_LIBRARY_PATH\n"
            "  3. Store lib paths in project-config.json under "
            "vector_memory.gpu_acceleration.lib_paths for automatic "
            "injection"
        )
    elif system == "Windows":
        platform_msg = (
            "\n\nWindows fix options:\n"
            "  1. Auto-fix: python scripts\\deps_check.py verify-gpu "
            "--auto-fix\n"
            "  2. Manual: Add site-packages\\nvidia\\*\\lib to your "
            "PATH environment variable\n"
            "  3. Store lib paths in project-config.json under "
            "vector_memory.gpu_acceleration.lib_paths for automatic "
            "injection"
        )
    elif system == "Darwin":
        platform_msg = (
            "\n\nmacOS: CoreML provider should not require library path "
            "fixes. Ensure onnxruntime-silicon is installed:\n"
            "  pip install onnxruntime-silicon"
        )
    else:
        platform_msg = (
            "\n\nEnsure GPU runtime libraries are on the system library "
            "search path."
        )

    return base_msg + platform_msg


def _detect_execution_providers(gpu_mode: str = "auto") -> list[str]:
    """Detect the best available ONNX Runtime execution providers.

    Args:
        gpu_mode: "auto" (try GPU, fall back to CPU), "gpu" (require GPU),
                  or "cpu" (force CPU only).

    Returns:
        Ordered list of providers to pass to InferenceSession.

    Raises:
        ValueError: If gpu_mode is not one of "auto", "gpu", "cpu".
        RuntimeError: If gpu_mode is "gpu" but no GPU provider is available.
    """
    if gpu_mode not in _VALID_GPU_MODES:
        raise ValueError(
            f"Invalid gpu_mode={gpu_mode!r}. "
            f"Must be one of: {', '.join(_VALID_GPU_MODES)}"
        )

    if gpu_mode == "cpu":
        return ["CPUExecutionProvider"]

    try:
        import onnxruntime as ort
        available = ort.get_available_providers()
    except (ImportError, AttributeError):
        return ["CPUExecutionProvider"]

    # Select providers in preference order, filtered to what's available
    selected = [p for p in _PROVIDER_PREFERENCE if p in available]

    if not selected:
        selected = ["CPUExecutionProvider"]

    if gpu_mode == "gpu":
        gpu_providers = [p for p in selected if p != "CPUExecutionProvider"]
        if not gpu_providers:
            raise RuntimeError(
                "gpu_mode='gpu' requested but no GPU execution provider is "
                "available. Install onnxruntime-gpu (NVIDIA), "
                "onnxruntime-rocm (AMD), onnxruntime-directml (Windows), "
                "or onnxruntime-silicon (macOS). "
                f"Available providers: {available}"
            )
        return gpu_providers

    # auto mode: return all available in preference order (GPU first, CPU last)
    return selected


def _resolve_model_dir(model_name: str,
                       model_dir: str | None = None) -> Path:
    """Resolve the local cache directory for a model.

    Centralised logic used by both ``__init__`` and ``validate_model`` to
    avoid duplicating the legacy-fallback resolution.

    Args:
        model_name: Model identifier (e.g. ``"all-MiniLM-L6-v2"``).
        model_dir:  Explicit override path.  When provided, returned as-is.

    Returns:
        ``Path`` pointing to the model directory.
    """
    if model_dir:
        return Path(model_dir)
    if model_name in _MODEL_REGISTRY:
        legacy = _LEGACY_CACHE_DIR / model_name
        if legacy.exists() and (legacy / "model.onnx").exists():
            return legacy
        return _DEFAULT_CACHE_DIR / model_name
    return _DEFAULT_CACHE_DIR / model_name


class LocalOnnxProvider(EmbeddingProvider):
    """Embedding provider using ONNX Runtime for local inference.

    Supports GPU acceleration with auto-detection. When gpu_mode is "auto"
    (default), the best available GPU provider is used with CPU fallback.

    Gracefully fails with clear error messages when dependencies
    are not installed.
    """

    def __init__(self, model_name_or_path: str = "all-MiniLM-L6-v2",
                 model_dir: str | None = None,
                 gpu_mode: str = "auto",
                 log_provider: bool = True):
        # Validate model name before using it in paths or URLs
        _sanitize_model_name(model_name_or_path)

        self._model_id = model_name_or_path
        self._session = None
        self._tokenizer = None
        self._np = None
        self._gpu_mode = gpu_mode
        self._log_provider = log_provider
        self._active_provider = None

        # Determine model directory (uses shared helper)
        self._model_dir = _resolve_model_dir(model_name_or_path, model_dir)

        # Lazy init — don't import optional deps at construction time
        self._initialized = False

    @classmethod
    def validate_model(cls, model_name: str,
                       model_dir: str | None = None) -> dict:
        """Check if a model is available locally or can be downloaded.

        Returns a dict with ``valid``, ``model``, ``path``, and ``error`` keys.
        Does **not** load the ONNX session or import heavy dependencies.
        """
        # Validate model name to prevent SSRF / path traversal
        try:
            _sanitize_model_name(model_name)
        except ValueError as e:
            return {
                "valid": False,
                "model": model_name,
                "path": "",
                "error": str(e),
            }

        mdir = _resolve_model_dir(model_name, model_dir)

        result: dict = {
            "valid": False,
            "model": model_name,
            "path": str(mdir),
            "error": None,
        }

        # Fast path: model files already present
        required = ["model.onnx", "tokenizer.json"]
        if all((mdir / f).exists() for f in required):
            result["valid"] = True
            return result

        # Determine download URL for the ONNX file to probe availability
        if model_name in _MODEL_REGISTRY:
            probe_url = _MODEL_REGISTRY[model_name]["onnx_url"]
        else:
            probe_url = (
                f"https://huggingface.co/sentence-transformers/"
                f"{model_name}/resolve/main/onnx/model.onnx"
            )

        # Validate URL host to prevent SSRF
        try:
            parsed = urllib.parse.urlparse(probe_url)
            if parsed.hostname not in _ALLOWED_DOWNLOAD_HOSTS:
                result["error"] = (
                    f"Download URL host '{parsed.hostname}' is not in the "
                    f"allowed list: {_ALLOWED_DOWNLOAD_HOSTS}"
                )
                return result
        except Exception:
            result["error"] = f"Could not parse probe URL: {probe_url}"
            return result

        # HEAD request to check if the model exists remotely
        try:
            req = urllib.request.Request(probe_url, method="HEAD")
            resp = urllib.request.urlopen(req, timeout=10)
            if resp.status == 200:
                result["valid"] = True
                return result
        except (urllib.error.URLError, OSError):
            pass

        result["error"] = (
            f"Model '{model_name}' not found locally at {mdir} and could "
            f"not be verified on HuggingFace. Change 'embedding_model' in "
            f"project-config.json or manually place model files in: {mdir}"
        )
        return result

    def _ensure_init(self):
        """Lazy initialization: import deps and load model on first use."""
        if self._initialized:
            return

        # Import optional dependencies
        try:
            import numpy as np
            self._np = np
        except ImportError:
            raise ImportError(
                "numpy is required for local embeddings. "
                "Install with: pip install numpy"
            )

        try:
            import onnxruntime as ort
        except ImportError:
            raise ImportError(
                "onnxruntime is required for local embeddings. "
                "Install with: pip install onnxruntime"
            )

        try:
            from tokenizers import Tokenizer
        except ImportError:
            raise ImportError(
                "tokenizers is required for local embeddings. "
                "Install with: pip install tokenizers"
            )

        # Ensure model files exist (download if needed)
        self._ensure_model_files()

        # Load tokenizer
        tokenizer_path = self._model_dir / "tokenizer.json"
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))

        # Load ONNX model
        model_path = self._model_dir / "model.onnx"
        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = (
            ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        )

        # ── Auto-inject GPU library paths before session creation ────
        if self._gpu_mode in ("auto", "gpu"):
            self._inject_gpu_paths_if_needed()

        # Select execution providers based on gpu_mode
        providers = _detect_execution_providers(self._gpu_mode)
        self._session = ort.InferenceSession(
            str(model_path),
            sess_options,
            providers=providers,
        )

        # Record which provider is actually active
        self._active_provider = self._session.get_providers()[0] \
            if self._session.get_providers() else providers[0]

        # ── Post-init GPU verification ───────────────────────────────
        # Catch silent fallback: GPU was requested but CPU is active
        if (self._gpu_mode == "gpu"
                and self._active_provider == "CPUExecutionProvider"):
            raise RuntimeError(
                _build_platform_gpu_error_message(
                    self._gpu_mode, self._active_provider
                )
            )

        if self._log_provider:
            fallback_note = ""
            if (self._gpu_mode == "auto"
                    and self._active_provider == "CPUExecutionProvider"
                    and len(providers) > 1):
                fallback_note = " [GPU unavailable, using CPU fallback]"
            print(
                f"  ONNX provider: {self._active_provider} "
                f"(mode={self._gpu_mode}){fallback_note}",
                file=sys.stderr, flush=True,
            )

        self._initialized = True

    def _ensure_model_files(self):
        """Download model files if they don't exist locally.

        For models in ``_MODEL_REGISTRY``, uses the exact URLs stored there.
        For any other model name, attempts a generic download from HuggingFace
        using the ``sentence-transformers/{model}`` URL pattern.  On download
        failure, raises ``RuntimeError`` with an actionable message.
        """
        if self._model_id in _MODEL_REGISTRY:
            registry = _MODEL_REGISTRY[self._model_id]
            files_to_download = [
                ("model.onnx", registry["onnx_url"]),
                ("tokenizer.json", registry["tokenizer_url"]),
            ]
            if "config_url" in registry:
                files_to_download.append(
                    ("tokenizer_config.json", registry["config_url"])
                )
        else:
            # Generic HuggingFace sentence-transformers download
            base = (
                f"https://huggingface.co/sentence-transformers/"
                f"{self._model_id}/resolve/main"
            )
            files_to_download = [
                ("model.onnx", f"{base}/onnx/model.onnx"),
                ("tokenizer.json", f"{base}/tokenizer.json"),
                ("tokenizer_config.json", f"{base}/tokenizer_config.json"),
            ]

        # Validate all download URLs against allowed hosts (SSRF prevention)
        for filename, url in files_to_download:
            parsed = urllib.parse.urlparse(url)
            if parsed.hostname not in _ALLOWED_DOWNLOAD_HOSTS:
                raise RuntimeError(
                    f"Download URL host '{parsed.hostname}' for {filename} "
                    f"is not in the allowed list: {_ALLOWED_DOWNLOAD_HOSTS}. "
                    f"Only HuggingFace downloads are permitted."
                )

        # Verify model dir stays inside cache (path traversal prevention)
        try:
            resolved = self._model_dir.resolve()
            cache_root = _DEFAULT_CACHE_DIR.resolve()
            resolved.relative_to(cache_root)
        except ValueError:
            raise RuntimeError(
                f"Model directory {self._model_dir} resolves outside the "
                f"allowed cache root {_DEFAULT_CACHE_DIR}. "
                f"This may indicate a path traversal attempt."
            )

        self._model_dir.mkdir(parents=True, exist_ok=True)

        for filename, url in files_to_download:
            dest = self._model_dir / filename
            if dest.exists():
                continue
            print(f"  Downloading {filename} for model "
                  f"'{self._model_id}'...", file=sys.stderr, flush=True)
            try:
                urllib.request.urlretrieve(url, str(dest))
            except (urllib.error.URLError, OSError) as e:
                # Clean up partial download
                if dest.exists():
                    dest.unlink(missing_ok=True)
                raise RuntimeError(
                    f"Failed to download {filename} from {url}: {e}\n"
                    f"Model '{self._model_id}' not found or could not be "
                    f"downloaded.\n"
                    f"Change 'embedding_model' in project-config.json or "
                    f"manually place model files in: {self._model_dir}"
                )

    def _inject_gpu_paths_if_needed(self) -> None:
        """Inject GPU library paths into the environment if needed.

        Checks two sources in order:
        1. project-config.json gpu_acceleration.lib_paths (persisted by
           /setup)
        2. Runtime discovery via deps_check.discover_gpu_lib_paths()
           (fallback)
        """
        # Source 1: stored config paths
        config_paths = _load_gpu_lib_paths_from_config()
        if config_paths:
            _inject_gpu_lib_paths(config_paths)
            return

        # Source 2: runtime discovery (fallback)
        try:
            # Import from sibling module -- deps_check is in scripts/
            script_dir = Path(__file__).resolve().parent.parent
            if str(script_dir) not in sys.path:
                sys.path.insert(0, str(script_dir))
            from deps_check import discover_gpu_lib_paths
            lib_info = discover_gpu_lib_paths()
            if lib_info.get("paths"):
                _inject_gpu_lib_paths(lib_info["paths"])
        except ImportError:
            pass  # deps_check not available; skip discovery

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using local ONNX model."""
        self._ensure_init()
        np = self._np

        if not texts:
            return []

        # Get max sequence length
        max_len = 256
        if self._model_id in _MODEL_REGISTRY:
            max_len = _MODEL_REGISTRY[self._model_id].get(
                "max_seq_length", 256
            )

        # Tokenize
        self._tokenizer.enable_truncation(max_length=max_len)
        self._tokenizer.enable_padding(length=max_len)
        encoded = self._tokenizer.encode_batch(texts)

        # Build numpy arrays
        input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
        attention_mask = np.array(
            [e.attention_mask for e in encoded], dtype=np.int64
        )
        token_type_ids = np.zeros_like(input_ids, dtype=np.int64)

        # Run inference
        feeds = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
            "token_type_ids": token_type_ids,
        }

        # Filter feeds to only include inputs the model expects
        model_inputs = {inp.name for inp in self._session.get_inputs()}
        feeds = {k: v for k, v in feeds.items() if k in model_inputs}

        outputs = self._session.run(None, feeds)

        # Mean pooling over token embeddings (output[0])
        token_embeddings = outputs[0]  # (batch, seq_len, hidden_dim)
        mask_expanded = np.expand_dims(attention_mask, axis=-1).astype(
            np.float32
        )
        sum_embeddings = np.sum(token_embeddings * mask_expanded, axis=1)
        sum_mask = np.clip(mask_expanded.sum(axis=1), a_min=1e-9, a_max=None)
        mean_pooled = sum_embeddings / sum_mask

        # L2 normalize
        norms = np.linalg.norm(mean_pooled, axis=1, keepdims=True)
        norms = np.clip(norms, a_min=1e-9, a_max=None)
        normalized = mean_pooled / norms

        return normalized.tolist()

    def dimension(self) -> int:
        if self._model_id in _MODEL_REGISTRY:
            return _MODEL_REGISTRY[self._model_id]["dimension"]
        # For custom models, we need to run a test embedding
        self._ensure_init()
        test = self.embed(["test"])
        return len(test[0]) if test else 384

    def model_name(self) -> str:
        return self._model_id

    def active_provider(self) -> str:
        """Return the name of the active ONNX execution provider.

        Hardware info: acceptable for local CLI tool; not exposed over network
        """
        if not self._initialized:
            return "not initialized"
        return self._active_provider or "unknown"
