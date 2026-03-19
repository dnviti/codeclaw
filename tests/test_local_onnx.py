#!/usr/bin/env python3
"""Tests for local_onnx module: download robustness, GPU retry, and integrity.

Covers:
- _download_file() timeout, retry with backoff, and integrity checks
- _verify_downloaded_file() file-type validation
- _load_download_timeout() config loading
- discover_gpu_lib_paths(create_if_missing=True) env var creation
- _inject_gpu_paths_if_needed() boolean return
- _retry_gpu_session() GPU recovery after silent fallback
- _persist_gpu_lib_paths() config persistence
- _ensure_init() end-to-end retry-then-fallback flow
"""

import io
import json
import os
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock, call

import pytest

# Add scripts/ to path so we can import the modules under test
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


# ============================================================================
# local_onnx: _verify_downloaded_file tests
# ============================================================================

class TestVerifyDownloadedFile:
    """Tests for _verify_downloaded_file integrity checks."""

    def test_missing_file_raises(self, tmp_path):
        """Non-existent file triggers RuntimeError."""
        from embeddings.local_onnx import _verify_downloaded_file

        missing = tmp_path / "missing.onnx"
        with pytest.raises(RuntimeError, match="does not exist"):
            _verify_downloaded_file(missing, "https://example.com/model.onnx")

    def test_empty_file_raises(self, tmp_path):
        """Empty file (0 bytes) triggers RuntimeError and is deleted."""
        from embeddings.local_onnx import _verify_downloaded_file

        empty = tmp_path / "empty.onnx"
        empty.write_bytes(b"")
        with pytest.raises(RuntimeError, match="is empty"):
            _verify_downloaded_file(empty, "https://example.com/model.onnx")
        assert not empty.exists()  # cleaned up

    def test_onnx_below_min_size_raises(self, tmp_path):
        """ONNX file below minimum size threshold is rejected."""
        from embeddings.local_onnx import _verify_downloaded_file

        small = tmp_path / "model.onnx"
        small.write_bytes(b"x" * 100)  # way below 1 MB minimum
        with pytest.raises(RuntimeError, match="minimum expected"):
            _verify_downloaded_file(small, "https://example.com/model.onnx")
        assert not small.exists()

    def test_onnx_above_min_size_passes(self, tmp_path):
        """ONNX file above minimum size threshold passes."""
        from embeddings.local_onnx import _verify_downloaded_file

        big = tmp_path / "model.onnx"
        big.write_bytes(b"x" * 2_000_000)
        _verify_downloaded_file(big, "https://example.com/model.onnx")
        assert big.exists()

    def test_invalid_json_raises(self, tmp_path):
        """Invalid JSON content triggers RuntimeError and is deleted."""
        from embeddings.local_onnx import _verify_downloaded_file

        bad_json = tmp_path / "tokenizer.json"
        # Must be >= 50 bytes so it passes the min-size check first
        bad_json.write_text(
            "this is definitely not valid json content {{{{{{{{{",
            encoding="utf-8",
        )
        with pytest.raises(RuntimeError, match="not valid JSON"):
            _verify_downloaded_file(
                bad_json, "https://example.com/tokenizer.json"
            )
        assert not bad_json.exists()

    def test_valid_json_passes(self, tmp_path):
        """Valid JSON file passes integrity check."""
        from embeddings.local_onnx import _verify_downloaded_file

        good_json = tmp_path / "tokenizer.json"
        # Must be >= 50 bytes to pass the min-size check
        good_json.write_text(
            json.dumps({"key": "value", "list": [1, 2, 3], "padding": "x" * 30}),
            encoding="utf-8",
        )
        _verify_downloaded_file(
            good_json, "https://example.com/tokenizer.json"
        )
        assert good_json.exists()

    def test_json_below_min_size_raises(self, tmp_path):
        """JSON file below 50 bytes is rejected."""
        from embeddings.local_onnx import _verify_downloaded_file

        tiny_json = tmp_path / "config.json"
        tiny_json.write_text("{}", encoding="utf-8")  # only 2 bytes
        with pytest.raises(RuntimeError, match="minimum expected"):
            _verify_downloaded_file(
                tiny_json, "https://example.com/config.json"
            )

    def test_unknown_extension_no_min_size(self, tmp_path):
        """Files with unknown extensions skip minimum size check."""
        from embeddings.local_onnx import _verify_downloaded_file

        txt = tmp_path / "readme.txt"
        txt.write_text("hi", encoding="utf-8")
        _verify_downloaded_file(txt, "https://example.com/readme.txt")
        assert txt.exists()


# ============================================================================
# local_onnx: _load_download_timeout tests
# ============================================================================

class TestLoadDownloadTimeout:
    """Tests for _load_download_timeout config loading."""

    def test_returns_default_when_no_config(self, tmp_path, monkeypatch):
        """Returns default (300) when no project-config.json exists."""
        from embeddings.local_onnx import (
            _load_download_timeout, _DEFAULT_DOWNLOAD_TIMEOUT,
        )

        monkeypatch.chdir(tmp_path)
        assert _load_download_timeout() == _DEFAULT_DOWNLOAD_TIMEOUT

    def test_reads_custom_timeout(self, tmp_path, monkeypatch):
        """Reads custom timeout from project-config.json."""
        from embeddings.local_onnx import _load_download_timeout

        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        config_file = config_dir / "project-config.json"
        config_file.write_text(json.dumps({
            "vector_memory": {"download_timeout": 600}
        }))

        monkeypatch.chdir(tmp_path)
        assert _load_download_timeout() == 600

    def test_ignores_invalid_timeout(self, tmp_path, monkeypatch):
        """Ignores non-positive or non-numeric timeout values."""
        from embeddings.local_onnx import (
            _load_download_timeout, _DEFAULT_DOWNLOAD_TIMEOUT,
        )

        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        config_file = config_dir / "project-config.json"
        config_file.write_text(json.dumps({
            "vector_memory": {"download_timeout": -10}
        }))

        monkeypatch.chdir(tmp_path)
        assert _load_download_timeout() == _DEFAULT_DOWNLOAD_TIMEOUT


# ============================================================================
# local_onnx: _download_file tests
# ============================================================================

class TestDownloadFile:
    """Tests for _download_file with timeout, retry, and integrity."""

    def _make_response(self, content, status=200, content_length=None):
        """Create a mock HTTP response."""
        resp = MagicMock()
        resp.status = status
        resp.read = MagicMock(side_effect=[content, b""])
        if content_length is not None:
            resp.headers = {"Content-Length": str(content_length)}
        else:
            resp.headers = {"Content-Length": None}
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    @patch("embeddings.local_onnx._load_download_timeout", return_value=30)
    @patch("embeddings.local_onnx._verify_downloaded_file")
    @patch("urllib.request.urlopen")
    def test_successful_download(self, mock_urlopen, mock_verify,
                                 mock_timeout, tmp_path):
        """Successful download writes file and verifies."""
        from embeddings.local_onnx import _download_file

        content = b"model data here"
        resp = self._make_response(content)
        mock_urlopen.return_value = resp

        dest = tmp_path / "model.onnx"
        _download_file("https://huggingface.co/model.onnx", dest, timeout=30)

        assert dest.exists()
        assert dest.read_bytes() == content
        mock_verify.assert_called_once_with(dest, "https://huggingface.co/model.onnx")

    @patch("embeddings.local_onnx._load_download_timeout", return_value=30)
    @patch("embeddings.local_onnx._verify_downloaded_file")
    @patch("urllib.request.urlopen")
    def test_passes_timeout_to_urlopen(self, mock_urlopen, mock_verify,
                                       mock_timeout, tmp_path):
        """Timeout is passed through to urlopen."""
        from embeddings.local_onnx import _download_file

        resp = self._make_response(b"data")
        mock_urlopen.return_value = resp

        dest = tmp_path / "file.json"
        _download_file("https://huggingface.co/f.json", dest, timeout=42)

        args, kwargs = mock_urlopen.call_args
        assert kwargs.get("timeout") == 42

    @patch("embeddings.local_onnx.time.sleep")
    @patch("embeddings.local_onnx._load_download_timeout", return_value=30)
    @patch("embeddings.local_onnx._verify_downloaded_file")
    @patch("urllib.request.urlopen")
    def test_retries_on_http_503(self, mock_urlopen, mock_verify,
                                 mock_timeout, mock_sleep, tmp_path):
        """Retries on HTTP 503 with exponential backoff."""
        from embeddings.local_onnx import _download_file

        # First call: 503, second call: success
        error_503 = urllib.error.HTTPError(
            "https://example.com", 503, "Service Unavailable", {}, None
        )
        resp = self._make_response(b"ok data")

        mock_urlopen.side_effect = [error_503, resp]

        dest = tmp_path / "retry.json"
        _download_file("https://huggingface.co/retry.json", dest, timeout=10)

        assert mock_urlopen.call_count == 2
        mock_sleep.assert_called_once_with(2)  # backoff_base ** 1

    @patch("embeddings.local_onnx.time.sleep")
    @patch("embeddings.local_onnx._load_download_timeout", return_value=30)
    @patch("urllib.request.urlopen")
    def test_retries_on_network_error(self, mock_urlopen, mock_timeout,
                                      mock_sleep, tmp_path):
        """Retries on URLError (network failure) up to max retries."""
        from embeddings.local_onnx import _download_file

        net_err = urllib.error.URLError("Connection refused")
        mock_urlopen.side_effect = [net_err, net_err, net_err]

        dest = tmp_path / "fail.onnx"
        with pytest.raises(RuntimeError, match="after 3 attempts"):
            _download_file(
                "https://huggingface.co/fail.onnx", dest, timeout=10
            )

        assert mock_urlopen.call_count == 3

    @patch("embeddings.local_onnx.time.sleep")
    @patch("embeddings.local_onnx._load_download_timeout", return_value=30)
    @patch("urllib.request.urlopen")
    def test_no_retry_on_http_404(self, mock_urlopen, mock_timeout,
                                  mock_sleep, tmp_path):
        """Does NOT retry on HTTP 404 (non-transient error)."""
        from embeddings.local_onnx import _download_file

        error_404 = urllib.error.HTTPError(
            "https://example.com", 404, "Not Found", {}, None
        )
        mock_urlopen.side_effect = error_404

        dest = tmp_path / "missing.onnx"
        with pytest.raises(RuntimeError, match="after 3 attempts"):
            _download_file(
                "https://huggingface.co/missing.onnx", dest, timeout=10
            )

        # Only 1 call: 404 is not retryable, breaks immediately
        assert mock_urlopen.call_count == 1
        mock_sleep.assert_not_called()

    @patch("embeddings.local_onnx.time.sleep")
    @patch("embeddings.local_onnx._load_download_timeout", return_value=30)
    @patch("embeddings.local_onnx._verify_downloaded_file")
    @patch("urllib.request.urlopen")
    def test_content_length_mismatch_raises(self, mock_urlopen, mock_verify,
                                            mock_timeout, mock_sleep,
                                            tmp_path):
        """Size mismatch between Content-Length and actual bytes raises."""
        from embeddings.local_onnx import _download_file

        def make_mismatch_response():
            resp = MagicMock()
            resp.headers = {"Content-Length": "99999"}
            resp.read = MagicMock(side_effect=[b"short", b""])
            resp.__enter__ = MagicMock(return_value=resp)
            resp.__exit__ = MagicMock(return_value=False)
            return resp

        # Provide a fresh response for each retry attempt
        mock_urlopen.side_effect = [
            make_mismatch_response(),
            make_mismatch_response(),
            make_mismatch_response(),
        ]

        dest = tmp_path / "mismatch.onnx"
        with pytest.raises(RuntimeError, match="Size mismatch"):
            _download_file(
                "https://huggingface.co/mismatch.onnx", dest, timeout=10
            )

    @patch("embeddings.local_onnx._load_download_timeout", return_value=30)
    @patch("embeddings.local_onnx._verify_downloaded_file")
    @patch("urllib.request.urlopen")
    def test_temp_file_cleaned_on_success(self, mock_urlopen, mock_verify,
                                          mock_timeout, tmp_path):
        """Temp .tmp file is removed after successful rename."""
        from embeddings.local_onnx import _download_file

        resp = self._make_response(b"clean data")
        mock_urlopen.return_value = resp

        dest = tmp_path / "clean.json"
        _download_file("https://huggingface.co/clean.json", dest, timeout=10)

        tmp_file = dest.with_suffix(".json.tmp")
        assert not tmp_file.exists()
        assert dest.exists()


# ============================================================================
# local_onnx: _ensure_model_files integration tests
# ============================================================================

class TestEnsureModelFilesIntegration:
    """Tests that _ensure_model_files uses the new download infrastructure."""

    def _make_provider(self, model_id="all-MiniLM-L6-v2", model_dir=None):
        """Create a bare LocalOnnxProvider for testing."""
        from embeddings.local_onnx import LocalOnnxProvider, _resolve_model_dir

        p = LocalOnnxProvider.__new__(LocalOnnxProvider)
        p._model_id = model_id
        p._model_dir = _resolve_model_dir(model_id, model_dir)
        return p

    @patch("embeddings.local_onnx._download_file")
    def test_calls_download_file_not_urlretrieve(self, mock_dl, tmp_path):
        """Verify _ensure_model_files uses _download_file, not urlretrieve."""
        from embeddings.local_onnx import _DEFAULT_CACHE_DIR

        provider = self._make_provider(
            model_dir=str(tmp_path / "test-model")
        )
        provider._model_dir = tmp_path / "test-model"
        provider._model_dir.mkdir(parents=True)

        # Patch cache root check to accept tmp_path
        with patch(
            "embeddings.local_onnx._DEFAULT_CACHE_DIR",
            tmp_path,
        ):
            provider._ensure_model_files()

        # _download_file should be called for each missing model file
        assert mock_dl.call_count == 3  # model.onnx, tokenizer.json, config
        for c in mock_dl.call_args_list:
            assert "label" in c.kwargs

    @patch("embeddings.local_onnx._download_file")
    def test_skips_existing_files(self, mock_dl, tmp_path):
        """Already-present files are not re-downloaded."""
        provider = self._make_provider(
            model_dir=str(tmp_path / "existing-model")
        )
        provider._model_dir = tmp_path / "existing-model"
        provider._model_dir.mkdir(parents=True)

        # Pre-create all model files
        (provider._model_dir / "model.onnx").write_bytes(b"x" * 2_000_000)
        (provider._model_dir / "tokenizer.json").write_text(
            '{"key": "val"}', encoding="utf-8"
        )
        (provider._model_dir / "tokenizer_config.json").write_text(
            '{"key": "val"}', encoding="utf-8"
        )

        with patch(
            "embeddings.local_onnx._DEFAULT_CACHE_DIR",
            tmp_path,
        ):
            provider._ensure_model_files()

        mock_dl.assert_not_called()


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
