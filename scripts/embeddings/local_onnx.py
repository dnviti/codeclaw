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
import sys
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from embeddings import EmbeddingProvider


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
        self._model_id = model_name_or_path
        self._session = None
        self._tokenizer = None
        self._np = None
        self._gpu_mode = gpu_mode
        self._log_provider = log_provider
        self._active_provider = None

        # Determine model directory
        if model_dir:
            self._model_dir = Path(model_dir)
        elif model_name_or_path in _MODEL_REGISTRY:
            # Check legacy cache path first for backward compatibility,
            # then use the new default path
            legacy_dir = _LEGACY_CACHE_DIR / model_name_or_path
            if legacy_dir.exists() and (legacy_dir / "model.onnx").exists():
                self._model_dir = legacy_dir
            else:
                self._model_dir = _DEFAULT_CACHE_DIR / model_name_or_path
        else:
            self._model_dir = Path(model_name_or_path)

        # Lazy init — don't import optional deps at construction time
        self._initialized = False

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

        # Ensure model files exist
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

        # ── Post-init GPU verification with retry ─────────────────────
        # Detect silent GPU-to-CPU fallback and attempt recovery
        _fell_back_to_cpu = (
            self._active_provider == "CPUExecutionProvider"
            and len(providers) > 1
        )

        if _fell_back_to_cpu and self._gpu_mode in ("auto", "gpu"):
            # Attempt env var creation + retry before giving up on GPU
            retried = self._retry_gpu_session(ort, model_path, sess_options)
            if not retried and self._gpu_mode == "gpu":
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
        """Download model files if they don't exist locally."""
        if self._model_id not in _MODEL_REGISTRY:
            # Custom model path — files must already exist
            if not (self._model_dir / "model.onnx").exists():
                raise FileNotFoundError(
                    f"ONNX model not found at {self._model_dir}/model.onnx"
                )
            return

        registry = _MODEL_REGISTRY[self._model_id]
        self._model_dir.mkdir(parents=True, exist_ok=True)

        files_to_download = [
            ("model.onnx", registry["onnx_url"]),
            ("tokenizer.json", registry["tokenizer_url"]),
        ]
        if "config_url" in registry:
            files_to_download.append(
                ("tokenizer_config.json", registry["config_url"])
            )

        for filename, url in files_to_download:
            dest = self._model_dir / filename
            if dest.exists():
                continue
            print(f"  Downloading {filename}...", file=sys.stderr, flush=True)
            try:
                urllib.request.urlretrieve(url, str(dest))
            except (urllib.error.URLError, OSError) as e:
                raise RuntimeError(
                    f"Failed to download {filename} from {url}: {e}\n"
                    f"You can manually download the model files to: "
                    f"{self._model_dir}"
                )

    def _inject_gpu_paths_if_needed(self) -> bool:
        """Inject GPU library paths into the environment if needed.

        Checks three sources in order:
        1. project-config.json gpu_acceleration.lib_paths (persisted by
           /setup)
        2. Runtime discovery via deps_check.discover_gpu_lib_paths()
           with create_if_missing=True (creates env var if absent)
        3. deps_check.verify_gpu_provider(auto_fix=True) as last resort

        Returns:
            True if new paths were injected, False otherwise.
        """
        # Source 1: stored config paths
        config_paths = _load_gpu_lib_paths_from_config()
        if config_paths:
            _inject_gpu_lib_paths(config_paths)
            return True

        # Source 2: runtime discovery with env var creation
        try:
            script_dir = Path(__file__).resolve().parent.parent
            if str(script_dir) not in sys.path:
                sys.path.insert(0, str(script_dir))
            from deps_check import discover_gpu_lib_paths
            lib_info = discover_gpu_lib_paths(create_if_missing=True)
            if lib_info.get("env_created"):
                return True
            if lib_info.get("paths"):
                _inject_gpu_lib_paths(lib_info["paths"])
                return True
        except ImportError:
            pass

        # Source 3: full verify-gpu auto-fix (discovers, injects, persists)
        try:
            from deps_check import verify_gpu_provider
            result = verify_gpu_provider(auto_fix=True)
            if result.get("auto_fixed"):
                return True
        except ImportError:
            pass

        return False

    def _retry_gpu_session(self, ort, model_path, sess_options) -> bool:
        """Attempt to recover GPU after silent fallback to CPU.

        Discovers missing GPU library paths, injects them into the
        environment, and re-creates the ONNX InferenceSession. If the
        retry succeeds with a GPU provider, updates self._session and
        self._active_provider.

        Returns:
            True if GPU was recovered, False if still on CPU.
        """
        # Try to discover and inject missing env vars
        injected = self._inject_gpu_paths_if_needed()
        if not injected:
            return False

        # Re-detect providers (env may have changed)
        providers = _detect_execution_providers(self._gpu_mode)

        try:
            session = ort.InferenceSession(
                str(model_path),
                sess_options,
                providers=providers,
            )
            active = session.get_providers()[0] \
                if session.get_providers() else providers[0]

            if active != "CPUExecutionProvider":
                # GPU recovered
                self._session = session
                self._active_provider = active
                if self._log_provider:
                    print(
                        f"  ONNX GPU recovered after env var fix: "
                        f"{active} (mode={self._gpu_mode})",
                        file=sys.stderr, flush=True,
                    )
                return True
        except Exception:
            pass

        return False

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
