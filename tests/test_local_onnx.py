#!/usr/bin/env python3
"""Tests for GPU env var auto-creation and retry-with-fallback in local_onnx.

Covers:
- discover_gpu_lib_paths(create_if_missing=True) env var creation
- _inject_gpu_paths_if_needed() boolean return
- _retry_gpu_session() GPU recovery after silent fallback
- _persist_gpu_lib_paths() config persistence
- _ensure_init() end-to-end retry-then-fallback flow
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Add scripts/ to path so we can import the modules under test
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


# ============================================================================
# deps_check: discover_gpu_lib_paths tests
# ============================================================================

class TestDiscoverGpuLibPaths:
    """Tests for discover_gpu_lib_paths with create_if_missing."""

    @patch("deps_check.platform.system", return_value="Linux")
    @patch("deps_check.site")
    def test_create_if_missing_injects_env_var(
        self, mock_site, mock_system, tmp_path, monkeypatch
    ):
        """When create_if_missing=True and env var is unset, create it."""
        from deps_check import discover_gpu_lib_paths

        # Create a fake nvidia lib dir with a .so file
        nvidia_dir = tmp_path / "nvidia" / "cublas" / "lib"
        nvidia_dir.mkdir(parents=True)
        (nvidia_dir / "libcublas.so.12").touch()

        mock_site.getsitepackages.return_value = [str(tmp_path)]
        mock_site.getusersitepackages.return_value = str(tmp_path / "user")

        monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)

        result = discover_gpu_lib_paths(create_if_missing=True)

        assert result["env_created"] is True
        assert str(nvidia_dir) in os.environ.get("LD_LIBRARY_PATH", "")
        assert str(nvidia_dir) in result["paths"]

    @patch("deps_check.platform.system", return_value="Linux")
    @patch("deps_check.site")
    def test_create_if_missing_false_does_not_inject(
        self, mock_site, mock_system, tmp_path, monkeypatch
    ):
        """Default create_if_missing=False leaves env var untouched."""
        from deps_check import discover_gpu_lib_paths

        nvidia_dir = tmp_path / "nvidia" / "cublas" / "lib"
        nvidia_dir.mkdir(parents=True)
        (nvidia_dir / "libcublas.so.12").touch()

        mock_site.getsitepackages.return_value = [str(tmp_path)]
        mock_site.getusersitepackages.return_value = str(tmp_path / "user")

        monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)

        result = discover_gpu_lib_paths(create_if_missing=False)

        assert result["env_created"] is False
        assert "LD_LIBRARY_PATH" not in os.environ

    @patch("deps_check.platform.system", return_value="Linux")
    @patch("deps_check.site")
    def test_no_paths_discovered_no_env_created(
        self, mock_site, mock_system, tmp_path, monkeypatch
    ):
        """No GPU libs found means no env var creation."""
        from deps_check import discover_gpu_lib_paths

        mock_site.getsitepackages.return_value = [str(tmp_path)]
        mock_site.getusersitepackages.return_value = str(tmp_path / "user")

        monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)

        result = discover_gpu_lib_paths(create_if_missing=True)

        assert result["env_created"] is False
        assert result["paths"] == []


# ============================================================================
# deps_check: _persist_gpu_lib_paths tests
# ============================================================================

class TestPersistGpuLibPaths:
    """Tests for _persist_gpu_lib_paths config file updates."""

    def test_persist_writes_to_config(self, tmp_path, monkeypatch):
        """Lib paths are written to project-config.json."""
        from deps_check import _persist_gpu_lib_paths

        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        config_file = config_dir / "project-config.json"
        config_file.write_text(json.dumps({"vector_memory": {}}))

        # Create real directories so path validation passes
        cuda_dir = tmp_path / "cuda_lib"
        cudnn_dir = tmp_path / "cudnn_lib"
        cuda_dir.mkdir()
        cudnn_dir.mkdir()

        monkeypatch.chdir(tmp_path)

        # Mock allowlist validation to accept tmp_path dirs
        with patch(
            "deps_check.validate_gpu_paths",
            return_value=(
                [str(cuda_dir), str(cudnn_dir)], []
            ),
        ):
            result = _persist_gpu_lib_paths([str(cuda_dir), str(cudnn_dir)])

        assert result is True
        saved = json.loads(config_file.read_text())
        assert saved["vector_memory"]["gpu_acceleration"]["lib_paths"] == [
            str(cuda_dir), str(cudnn_dir)
        ]

    def test_persist_no_config_returns_false(self, tmp_path, monkeypatch):
        """Returns False when no project-config.json exists."""
        from deps_check import _persist_gpu_lib_paths

        monkeypatch.chdir(tmp_path)

        result = _persist_gpu_lib_paths(["/some/path"])

        assert result is False


# ============================================================================
# local_onnx: _inject_gpu_paths_if_needed tests
# ============================================================================

class TestInjectGpuPathsIfNeeded:
    """Tests for LocalOnnxProvider._inject_gpu_paths_if_needed return value."""

    @patch("embeddings.local_onnx._load_gpu_lib_paths_from_config")
    def test_returns_true_when_config_paths_found(self, mock_load):
        """Returns True when config has stored GPU lib paths."""
        from embeddings.local_onnx import LocalOnnxProvider

        mock_load.return_value = ["/fake/nvidia/lib"]

        provider = LocalOnnxProvider.__new__(LocalOnnxProvider)
        provider._gpu_mode = "auto"

        with patch("embeddings.local_onnx._inject_gpu_lib_paths"):
            result = provider._inject_gpu_paths_if_needed()

        assert result is True

    @patch("embeddings.local_onnx._load_gpu_lib_paths_from_config")
    def test_returns_false_when_no_paths(self, mock_load):
        """Returns False when no GPU lib paths are discoverable."""
        from embeddings.local_onnx import LocalOnnxProvider

        mock_load.return_value = []

        provider = LocalOnnxProvider.__new__(LocalOnnxProvider)
        provider._gpu_mode = "auto"

        # Mock deps_check imports to return nothing
        mock_discover = MagicMock(return_value={
            "paths": [], "env_created": False
        })
        mock_verify = MagicMock(return_value={"auto_fixed": False})

        with patch.dict("sys.modules", {
            "deps_check": MagicMock(
                discover_gpu_lib_paths=mock_discover,
                verify_gpu_provider=mock_verify,
            )
        }):
            result = provider._inject_gpu_paths_if_needed()

        assert result is False


# ============================================================================
# local_onnx: _retry_gpu_session tests
# ============================================================================

class TestRetryGpuSession:
    """Tests for LocalOnnxProvider._retry_gpu_session."""

    def _make_provider(self, gpu_mode="auto"):
        """Create a bare LocalOnnxProvider without full init."""
        from embeddings.local_onnx import LocalOnnxProvider

        p = LocalOnnxProvider.__new__(LocalOnnxProvider)
        p._gpu_mode = gpu_mode
        p._log_provider = False
        p._session = MagicMock()
        p._active_provider = "CPUExecutionProvider"
        return p

    def test_retry_succeeds_updates_session(self):
        """When retry finds GPU, session and provider are updated."""
        provider = self._make_provider("auto")

        mock_session = MagicMock()
        mock_session.get_providers.return_value = ["CUDAExecutionProvider"]

        mock_ort = MagicMock()
        mock_ort.InferenceSession.return_value = mock_session

        with patch.object(
            provider, "_inject_gpu_paths_if_needed", return_value=True
        ):
            with patch(
                "embeddings.local_onnx._detect_execution_providers",
                return_value=["CUDAExecutionProvider", "CPUExecutionProvider"],
            ):
                result = provider._retry_gpu_session(
                    mock_ort, "/fake/model.onnx", MagicMock()
                )

        assert result is True
        assert provider._active_provider == "CUDAExecutionProvider"
        assert provider._session is mock_session

    def test_retry_fails_returns_false(self):
        """When retry still falls back to CPU, returns False."""
        provider = self._make_provider("gpu")

        mock_session = MagicMock()
        mock_session.get_providers.return_value = ["CPUExecutionProvider"]

        mock_ort = MagicMock()
        mock_ort.InferenceSession.return_value = mock_session

        with patch.object(
            provider, "_inject_gpu_paths_if_needed", return_value=True
        ):
            with patch(
                "embeddings.local_onnx._detect_execution_providers",
                return_value=["CUDAExecutionProvider", "CPUExecutionProvider"],
            ):
                result = provider._retry_gpu_session(
                    mock_ort, "/fake/model.onnx", MagicMock()
                )

        assert result is False
        # Original session/provider unchanged
        assert provider._active_provider == "CPUExecutionProvider"

    def test_no_injection_skips_retry(self):
        """When no paths were injected, retry is skipped entirely."""
        provider = self._make_provider("auto")

        with patch.object(
            provider, "_inject_gpu_paths_if_needed", return_value=False
        ):
            result = provider._retry_gpu_session(
                MagicMock(), "/fake/model.onnx", MagicMock()
            )

        assert result is False

    def test_skip_inject_skips_discovery(self):
        """When skip_inject=True, path discovery is skipped."""
        provider = self._make_provider("auto")

        mock_session = MagicMock()
        mock_session.get_providers.return_value = ["CUDAExecutionProvider"]

        mock_ort = MagicMock()
        mock_ort.InferenceSession.return_value = mock_session

        with patch.object(
            provider, "_inject_gpu_paths_if_needed"
        ) as mock_inject:
            with patch(
                "embeddings.local_onnx._detect_execution_providers",
                return_value=["CUDAExecutionProvider", "CPUExecutionProvider"],
            ):
                result = provider._retry_gpu_session(
                    mock_ort, "/fake/model.onnx", MagicMock(),
                    skip_inject=True,
                )

        # _inject_gpu_paths_if_needed should NOT have been called
        mock_inject.assert_not_called()
        assert result is True
        assert provider._active_provider == "CUDAExecutionProvider"


# ============================================================================
# deps_check: GPU path allowlist tests
# ============================================================================

class TestGpuPathAllowlist:
    """Tests for the GPU path allowlist validation in deps_check."""

    def test_default_allowlist_permits_usr_lib(self):
        """Standard /usr/lib paths pass the default allowlist."""
        from deps_check import (
            _path_matches_allowlist,
            DEFAULT_GPU_PATH_ALLOWLIST,
        )

        assert _path_matches_allowlist(
            "/usr/lib/x86_64-linux-gnu", DEFAULT_GPU_PATH_ALLOWLIST
        )

    def test_default_allowlist_permits_cuda(self):
        """CUDA-style paths pass the default allowlist."""
        from deps_check import (
            _path_matches_allowlist,
            DEFAULT_GPU_PATH_ALLOWLIST,
        )

        assert _path_matches_allowlist(
            "/usr/local/cuda-12.2/lib64", DEFAULT_GPU_PATH_ALLOWLIST
        )

    def test_default_allowlist_permits_rocm(self):
        """ROCm paths pass the default allowlist."""
        from deps_check import (
            _path_matches_allowlist,
            DEFAULT_GPU_PATH_ALLOWLIST,
        )

        assert _path_matches_allowlist(
            "/opt/rocm/lib", DEFAULT_GPU_PATH_ALLOWLIST
        )

    def test_arbitrary_path_rejected(self):
        """An arbitrary path outside known GPU directories is rejected."""
        from deps_check import (
            _path_matches_allowlist,
            DEFAULT_GPU_PATH_ALLOWLIST,
        )

        assert not _path_matches_allowlist(
            "/tmp/evil/lib", DEFAULT_GPU_PATH_ALLOWLIST
        )

    def test_home_dir_rejected(self):
        """Home directory paths are rejected by the default allowlist."""
        from deps_check import (
            _path_matches_allowlist,
            DEFAULT_GPU_PATH_ALLOWLIST,
        )

        assert not _path_matches_allowlist(
            "/home/user/.local/evil/lib", DEFAULT_GPU_PATH_ALLOWLIST
        )

    def test_validate_gpu_paths_splits_correctly(self):
        """validate_gpu_paths returns correct allowed and rejected lists."""
        from deps_check import validate_gpu_paths

        allowed_path = "/usr/lib/nvidia"
        rejected_path = "/tmp/suspicious/lib"

        # Use an explicit allowlist for deterministic testing
        allowlist = ["/usr/lib", "/usr/local/lib"]

        allowed, rejected = validate_gpu_paths(
            [allowed_path, rejected_path],
            allowlist=allowlist,
        )

        assert allowed_path in allowed
        assert rejected_path in rejected

    def test_validate_gpu_paths_empty_allowlist_rejects_all(self):
        """An empty allowlist rejects all paths."""
        from deps_check import validate_gpu_paths

        allowed, rejected = validate_gpu_paths(
            ["/usr/lib/nvidia", "/opt/rocm/lib"],
            allowlist=[],
        )

        assert allowed == []
        assert len(rejected) == 2

    def test_glob_patterns_in_allowlist(self):
        """Glob patterns with wildcards work correctly."""
        from deps_check import _path_matches_allowlist

        allowlist = ["/usr/local/cuda*/lib*"]
        assert _path_matches_allowlist(
            "/usr/local/cuda-12.2/lib64", allowlist
        )
        assert not _path_matches_allowlist(
            "/tmp/cuda-fake/lib64", allowlist
        )

    def test_build_effective_allowlist_uses_defaults(self):
        """When config_allowlist is None, defaults are used."""
        from deps_check import _build_effective_allowlist

        result = _build_effective_allowlist(config_allowlist=None)
        # Should contain at least the default system paths
        assert any("/usr/lib" in p for p in result)

    def test_build_effective_allowlist_merges_config(self):
        """User config allowlist is merged with site-packages patterns."""
        from deps_check import _build_effective_allowlist

        custom = ["/my/custom/gpu/path"]
        result = _build_effective_allowlist(config_allowlist=custom)
        assert "/my/custom/gpu/path" in result

    def test_build_effective_allowlist_rejects_wildcard_only(self):
        """Overly-broad patterns like '*' are stripped from config allowlist."""
        from deps_check import _build_effective_allowlist

        config = ["*", "/my/safe/path", "?", "/*"]
        result = _build_effective_allowlist(config_allowlist=config)
        assert "*" not in result
        assert "?" not in result
        assert "/*" not in result
        assert "/my/safe/path" in result

    def test_load_allowlist_from_config(self, tmp_path, monkeypatch):
        """Allowlist is loaded from project-config.json."""
        from deps_check import _load_gpu_path_allowlist_from_config

        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        config_file = config_dir / "project-config.json"
        config_file.write_text(json.dumps({
            "vector_memory": {
                "gpu_acceleration": {
                    "gpu_path_allowlist": ["/custom/allowed/path"]
                }
            }
        }))

        monkeypatch.chdir(tmp_path)

        result = _load_gpu_path_allowlist_from_config()
        assert result == ["/custom/allowed/path"]

    def test_load_allowlist_absent_returns_none(self, tmp_path, monkeypatch):
        """When gpu_path_allowlist is not in config, returns None."""
        from deps_check import _load_gpu_path_allowlist_from_config

        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        config_file = config_dir / "project-config.json"
        config_file.write_text(json.dumps({
            "vector_memory": {
                "gpu_acceleration": {
                    "lib_paths": []
                }
            }
        }))

        monkeypatch.chdir(tmp_path)

        result = _load_gpu_path_allowlist_from_config()
        assert result is None

    def test_persist_rejects_disallowed_paths(self, tmp_path, monkeypatch):
        """_persist_gpu_lib_paths filters out paths not in the allowlist."""
        from deps_check import _persist_gpu_lib_paths

        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        config_file = config_dir / "project-config.json"
        config_file.write_text(json.dumps({"vector_memory": {}}))

        # Create real directories
        allowed_dir = tmp_path / "usr" / "lib" / "nvidia"
        allowed_dir.mkdir(parents=True)
        rejected_dir = tmp_path / "evil" / "lib"
        rejected_dir.mkdir(parents=True)

        monkeypatch.chdir(tmp_path)

        # Use explicit allowlist that only allows the first path
        with patch(
            "deps_check.validate_gpu_paths",
            return_value=([str(allowed_dir)], [str(rejected_dir)]),
        ):
            result = _persist_gpu_lib_paths(
                [str(allowed_dir), str(rejected_dir)]
            )

        assert result is True
        saved = json.loads(config_file.read_text())
        saved_paths = saved["vector_memory"]["gpu_acceleration"]["lib_paths"]
        assert str(allowed_dir) in saved_paths
        assert str(rejected_dir) not in saved_paths

    def test_inject_lib_paths_filters_by_allowlist(
        self, tmp_path, monkeypatch
    ):
        """_inject_lib_paths in deps_check validates against allowlist."""
        from deps_check import _inject_lib_paths

        # Create real directories
        gpu_dir = tmp_path / "nvidia" / "lib"
        gpu_dir.mkdir(parents=True)
        bad_dir = tmp_path / "bad" / "lib"
        bad_dir.mkdir(parents=True)

        monkeypatch.delenv("LD_LIBRARY_PATH", raising=False)

        lib_info = {
            "paths": [str(gpu_dir), str(bad_dir)],
            "env_var": "LD_LIBRARY_PATH",
            "platform": "linux",
        }

        # Mock validate_gpu_paths to only allow gpu_dir
        with patch(
            "deps_check.validate_gpu_paths",
            return_value=([str(gpu_dir)], [str(bad_dir)]),
        ):
            _inject_lib_paths(lib_info)

        ld_path = os.environ.get("LD_LIBRARY_PATH", "")
        assert str(gpu_dir) in ld_path
        assert str(bad_dir) not in ld_path
