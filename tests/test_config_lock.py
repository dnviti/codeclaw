#!/usr/bin/env python3
"""Tests for cross-platform config file locking in config_lock.py.

Covers:
    - locked_config_read: reads JSON under lock
    - locked_config_write: atomic write under lock
    - locked_config_update: read-modify-write under lock
    - Lock contention and retry logic
    - Atomic write (temp + rename) safety
    - Error handling for corrupt/missing files
"""

import json
import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

# Add scripts/ to path so config_lock can be imported
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from config_lock import (
    ConfigLockError,
    locked_config_read,
    locked_config_write,
    locked_config_update,
    _config_file_lock,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def config_dir(tmp_path):
    """Provide a temporary directory with a sample config file."""
    config_path = tmp_path / "project-config.json"
    config_path.write_text(
        json.dumps({"project_context": "sample context"}, indent=2) + "\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def config_path(config_dir):
    """Return the path to the sample config file."""
    return config_dir / "project-config.json"


# ── locked_config_read tests ─────────────────────────────────────────────────


class TestLockedConfigRead:
    """Tests for locked_config_read."""

    def test_read_existing_file(self, config_path):
        data = locked_config_read(config_path)
        assert data == {"project_context": "sample context"}

    def test_read_nonexistent_file(self, tmp_path):
        data = locked_config_read(tmp_path / "nonexistent.json")
        assert data == {}

    def test_read_corrupt_file(self, config_dir):
        config_path = config_dir / "corrupt.json"
        config_path.write_text("{invalid json", encoding="utf-8")
        data = locked_config_read(config_path)
        assert data == {}

    def test_read_creates_lock_file(self, config_path):
        locked_config_read(config_path)
        lock_path = config_path.with_suffix(".lock")
        assert lock_path.exists()


# ── locked_config_write tests ────────────────────────────────────────────────


class TestLockedConfigWrite:
    """Tests for locked_config_write."""

    def test_write_new_data(self, config_path):
        new_data = {"project_context": "updated context", "new_key": "value"}
        result = locked_config_write(config_path, new_data)
        assert result is True

        written = json.loads(config_path.read_text(encoding="utf-8"))
        assert written == new_data

    def test_write_creates_parent_dirs(self, tmp_path):
        config_path = tmp_path / "deep" / "nested" / "config.json"
        result = locked_config_write(config_path, {"key": "value"})
        assert result is True
        assert config_path.exists()

        written = json.loads(config_path.read_text(encoding="utf-8"))
        assert written == {"key": "value"}

    def test_write_preserves_json_formatting(self, config_path):
        locked_config_write(config_path, {"a": 1, "b": 2})
        content = config_path.read_text(encoding="utf-8")
        # Should be indented with 2 spaces and end with newline
        assert "  " in content
        assert content.endswith("\n")

    def test_write_atomic_no_partial_on_crash(self, config_path):
        """Verify that a failed write does not corrupt the original file."""
        original = json.loads(config_path.read_text(encoding="utf-8"))

        # Simulate a crash during os.replace by patching it to raise
        with patch("config_lock.os.replace", side_effect=OSError("simulated crash")):
            with pytest.raises(ConfigLockError):
                locked_config_write(config_path, {"corrupted": True})

        # Original file should be unchanged
        after = json.loads(config_path.read_text(encoding="utf-8"))
        assert after == original


# ── locked_config_update tests ───────────────────────────────────────────────


class TestLockedConfigUpdate:
    """Tests for locked_config_update."""

    def test_update_existing_key(self, config_path):
        def update_context(cfg):
            cfg["project_context"] = "updated context"
            return cfg

        result = locked_config_update(config_path, update_context)
        assert result is True

        written = json.loads(config_path.read_text(encoding="utf-8"))
        assert written["project_context"] == "updated context"

    def test_update_adds_new_key(self, config_path):
        def add_key(cfg):
            cfg["new_section"] = {"setting": 42}
            return cfg

        result = locked_config_update(config_path, add_key)
        assert result is True

        written = json.loads(config_path.read_text(encoding="utf-8"))
        assert written["new_section"]["setting"] == 42
        # Original key should still be present
        assert "project_context" in written

    def test_update_nonexistent_file_creates_it(self, tmp_path):
        config_path = tmp_path / "new-config.json"

        def init_config(cfg):
            cfg["initialized"] = True
            return cfg

        result = locked_config_update(config_path, init_config)
        assert result is True
        assert config_path.exists()

        written = json.loads(config_path.read_text(encoding="utf-8"))
        assert written == {"initialized": True}

    def test_update_with_corrupt_file_starts_fresh(self, config_dir):
        config_path = config_dir / "bad.json"
        config_path.write_text("not valid json!!!", encoding="utf-8")

        def add_data(cfg):
            cfg["recovered"] = True
            return cfg

        result = locked_config_update(config_path, add_data)
        assert result is True

        written = json.loads(config_path.read_text(encoding="utf-8"))
        assert written == {"recovered": True}


# ── Concurrency tests ────────────────────────────────────────────────────────


class TestConcurrency:
    """Tests for lock contention under concurrent access."""

    def test_concurrent_writes_do_not_corrupt(self, config_path):
        """Multiple threads writing concurrently should not corrupt the file."""
        errors = []
        write_count = 10

        def writer(thread_id):
            try:
                for i in range(write_count):
                    locked_config_update(
                        config_path,
                        lambda cfg, tid=thread_id, idx=i: {
                            **cfg,
                            f"thread_{tid}": idx,
                        },
                    )
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Concurrent writes produced errors: {errors}"

        # File should be valid JSON
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_lock_contention_with_timeout(self, config_path):
        """A second lock attempt should timeout when the first holds the lock."""
        lock_path = config_path.with_suffix(".lock")
        acquired = threading.Event()
        release = threading.Event()

        def hold_lock():
            with _config_file_lock(lock_path, timeout=10.0):
                acquired.set()
                release.wait(timeout=10.0)

        holder = threading.Thread(target=hold_lock)
        holder.start()
        acquired.wait(timeout=5.0)

        try:
            # This should timeout quickly since the lock is held
            with pytest.raises(ConfigLockError):
                with _config_file_lock(lock_path, timeout=0.3):
                    pass  # Should not reach here
        finally:
            release.set()
            holder.join(timeout=5.0)


# ── Retry logic tests ────────────────────────────────────────────────────────


class TestRetryLogic:
    """Tests for retry behavior on lock contention."""

    def test_write_retries_on_lock_error(self, config_path):
        """locked_config_write should retry when lock acquisition fails."""
        call_count = {"value": 0}
        original_lock = _config_file_lock

        from contextlib import contextmanager

        @contextmanager
        def flaky_lock(*args, **kwargs):
            call_count["value"] += 1
            if call_count["value"] == 1:
                raise ConfigLockError("transient failure")
            with original_lock(*args, **kwargs):
                yield

        with patch("config_lock._config_file_lock", side_effect=flaky_lock):
            result = locked_config_write(
                config_path,
                {"retried": True},
                max_retries=3,
            )

        assert result is True
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert data == {"retried": True}

    def test_write_exhausts_retries(self, config_path):
        """locked_config_write should raise after exhausting retries."""
        from contextlib import contextmanager

        @contextmanager
        def always_fail(*args, **kwargs):
            raise ConfigLockError("persistent failure")
            yield  # pragma: no cover

        with patch("config_lock._config_file_lock", side_effect=always_fail):
            with pytest.raises(ConfigLockError, match="3 attempts"):
                locked_config_write(
                    config_path,
                    {"should_fail": True},
                    max_retries=3,
                )
