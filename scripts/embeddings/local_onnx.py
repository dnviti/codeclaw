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
_LEGACY_CACHE_DIR = Path.home() / ".cache" / "ctdf" / "models"


class LocalOnnxProvider(EmbeddingProvider):
    """Embedding provider using ONNX Runtime for local inference.

    Gracefully fails with clear error messages when dependencies
    are not installed.
    """

    def __init__(self, model_name_or_path: str = "all-MiniLM-L6-v2",
                 model_dir: str | None = None):
        self._model_id = model_name_or_path
        self._session = None
        self._tokenizer = None
        self._np = None

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
        # Use CPU provider for maximum compatibility
        self._session = ort.InferenceSession(
            str(model_path),
            sess_options,
            providers=["CPUExecutionProvider"],
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
