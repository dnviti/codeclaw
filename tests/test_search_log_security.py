#!/usr/bin/env python3
"""Tests for search log security controls (RPAT-0003).

Covers:
- Opt-in behavior (disabled by default)
- Privacy notice emission
- Retention-based auto-purge of expired entries
- Restrictive file permissions (0o600)
- Config defaults for search_log including retention_days
- Path traversal guard
"""

import json
import os
import stat
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Add scripts/ to path so we can import the modules under test
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


class TestSearchLogDefaults:
    """Verify search_log config defaults include retention_days."""

    def test_search_log_disabled_by_default(self, tmp_path):
        """Search log is disabled by default when no config exists."""
        from vector_memory import get_effective_config

        config = get_effective_config(tmp_path)
        assert config["search_log"]["enabled"] is False

    def test_retention_days_default(self, tmp_path):
        """retention_days defaults to 30 when not configured."""
        from vector_memory import get_effective_config

        config = get_effective_config(tmp_path)
        assert config["search_log"]["retention_days"] == 30

    def test_retention_days_from_config(self, tmp_path):
        """retention_days is loaded from user configuration."""
        from vector_memory import get_effective_config

        config_dir = tmp_path / ".claude"
        config_dir.mkdir()
        (config_dir / "project-config.json").write_text(json.dumps({
            "vector_memory": {
                "search_log": {
                    "enabled": True,
                    "retention_days": 7,
                }
            }
        }))

        config = get_effective_config(tmp_path)
        assert config["search_log"]["retention_days"] == 7
        assert config["search_log"]["enabled"] is True

    def test_search_log_all_defaults_present(self, tmp_path):
        """All expected default keys are present in search_log config."""
        from vector_memory import get_effective_config

        config = get_effective_config(tmp_path)
        log_cfg = config["search_log"]
        assert "enabled" in log_cfg
        assert "path" in log_cfg
        assert "include_content" in log_cfg
        assert "max_size_mb" in log_cfg
        assert "retention_days" in log_cfg


class TestSearchLogOptIn:
    """Verify search logging is opt-in only."""

    @pytest.fixture(autouse=True)
    def _reset_flags(self):
        """Reset module-level flags before each test."""
        import vector_memory
        vector_memory._search_log_purge_done = False

    def test_log_search_noop_when_disabled(self, tmp_path):
        """_log_search returns immediately when search_log is disabled."""
        from vector_memory import _log_search

        config = {"search_log": {"enabled": False}}
        mock_df = MagicMock()
        mock_df.iterrows.return_value = []

        _log_search(tmp_path, config, "test query", 10, "", "", mock_df)

        # No log file should be created
        log_files = list(tmp_path.rglob("*.jsonl"))
        assert len(log_files) == 0

    def test_log_search_writes_when_enabled(self, tmp_path):
        """_log_search writes to the log file when enabled."""
        import vector_memory
        vector_memory._search_log_privacy_notice_shown = False

        from vector_memory import _log_search

        log_path = tmp_path / ".claude" / "memory" / "search_log.jsonl"
        config = {
            "search_log": {
                "enabled": True,
                "path": ".claude/memory/search_log.jsonl",
                "include_content": False,
                "max_size_mb": 10,
                "retention_days": 30,
            }
        }
        mock_df = MagicMock()
        mock_df.iterrows.return_value = iter([
            (0, {"file_path": "test.py", "name": "test_fn",
                 "chunk_type": "function", "_distance": 0.5}),
        ])

        _log_search(tmp_path, config, "test query", 10, "", "", mock_df)

        assert log_path.exists()
        content = log_path.read_text(encoding="utf-8").strip()
        record = json.loads(content)
        assert record["query"] == "test query"
        assert record["result_count"] == 1


class TestPrivacyNotice:
    """Verify privacy notice is emitted when search logging is active."""

    @pytest.fixture(autouse=True)
    def _reset_flags(self):
        """Reset module-level flags before each test."""
        import vector_memory
        vector_memory._search_log_purge_done = False

    def test_privacy_notice_emitted_on_first_use(self, tmp_path, capsys):
        """Privacy notice is printed to stderr on first search log call."""
        import vector_memory
        vector_memory._search_log_privacy_notice_shown = False

        from vector_memory import _log_search

        config = {
            "search_log": {
                "enabled": True,
                "path": ".claude/memory/search_log.jsonl",
                "include_content": False,
                "max_size_mb": 10,
                "retention_days": 30,
            }
        }
        mock_df = MagicMock()
        mock_df.iterrows.return_value = iter([])

        _log_search(tmp_path, config, "query", 5, "", "", mock_df)

        captured = capsys.readouterr()
        assert "PRIVACY NOTICE" in captured.err
        assert "search query logging is enabled" in captured.err.lower()

    def test_privacy_notice_shown_once_per_process(self, tmp_path, capsys):
        """Privacy notice is only shown once per process lifetime."""
        import vector_memory
        vector_memory._search_log_privacy_notice_shown = False

        from vector_memory import _log_search

        config = {
            "search_log": {
                "enabled": True,
                "path": ".claude/memory/search_log.jsonl",
                "include_content": False,
                "max_size_mb": 10,
                "retention_days": 30,
            }
        }
        mock_df = MagicMock()
        mock_df.iterrows.return_value = iter([])

        _log_search(tmp_path, config, "query1", 5, "", "", mock_df)
        captured1 = capsys.readouterr()
        assert "PRIVACY NOTICE" in captured1.err

        mock_df.iterrows.return_value = iter([])
        _log_search(tmp_path, config, "query2", 5, "", "", mock_df)
        captured2 = capsys.readouterr()
        # Second call should NOT print the notice again
        assert "PRIVACY NOTICE" not in captured2.err


class TestRetentionPurge:
    """Verify retention-based auto-purge of expired log entries."""

    @pytest.fixture(autouse=True)
    def _reset_purge_flag(self):
        """Reset the session-once purge flag before each test."""
        import vector_memory
        vector_memory._search_log_purge_done = False

    def test_purge_removes_old_entries(self, tmp_path):
        """Entries older than retention_days are purged."""
        from vector_memory import _purge_expired_log_entries

        log_path = tmp_path / "search_log.jsonl"
        old_ts = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() - 40 * 86400),  # 40 days ago
        )
        recent_ts = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() - 5 * 86400),  # 5 days ago
        )
        old_entry = json.dumps({"timestamp": old_ts, "query": "old query"})
        recent_entry = json.dumps({"timestamp": recent_ts, "query": "recent query"})
        log_path.write_text(old_entry + "\n" + recent_entry + "\n")

        _purge_expired_log_entries(log_path, retention_days=30)

        remaining = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(remaining) == 1
        assert "recent query" in remaining[0]

    def test_purge_keeps_all_when_within_retention(self, tmp_path):
        """No entries are purged when all are within retention window."""
        from vector_memory import _purge_expired_log_entries

        log_path = tmp_path / "search_log.jsonl"
        recent_ts = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() - 2 * 86400),  # 2 days ago
        )
        entry = json.dumps({"timestamp": recent_ts, "query": "recent"})
        log_path.write_text(entry + "\n")

        _purge_expired_log_entries(log_path, retention_days=30)

        remaining = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(remaining) == 1

    def test_purge_disabled_with_zero_retention(self, tmp_path):
        """Purge is disabled when retention_days is 0."""
        from vector_memory import _purge_expired_log_entries

        log_path = tmp_path / "search_log.jsonl"
        old_ts = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() - 365 * 86400),  # 1 year ago
        )
        entry = json.dumps({"timestamp": old_ts, "query": "ancient query"})
        log_path.write_text(entry + "\n")

        _purge_expired_log_entries(log_path, retention_days=0)

        remaining = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(remaining) == 1  # not purged

    def test_purge_handles_unparseable_lines(self, tmp_path):
        """Unparseable lines are kept (fail-safe)."""
        from vector_memory import _purge_expired_log_entries

        log_path = tmp_path / "search_log.jsonl"
        old_ts = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() - 40 * 86400),
        )
        old_entry = json.dumps({"timestamp": old_ts, "query": "old"})
        log_path.write_text(
            old_entry + "\n"
            "not valid json line\n"
        )

        _purge_expired_log_entries(log_path, retention_days=30)

        remaining = log_path.read_text(encoding="utf-8").strip().splitlines()
        # Old entry purged, unparseable line kept
        assert len(remaining) == 1
        assert "not valid json" in remaining[0]

    def test_purge_nonexistent_file_is_noop(self, tmp_path):
        """Purge on a nonexistent file does nothing."""
        from vector_memory import _purge_expired_log_entries

        log_path = tmp_path / "nonexistent.jsonl"
        _purge_expired_log_entries(log_path, retention_days=30)
        assert not log_path.exists()


class TestFilePermissions:
    """Verify log files are created with restrictive permissions."""

    @pytest.fixture(autouse=True)
    def _reset_flags(self):
        """Reset module-level flags before each test."""
        import vector_memory
        vector_memory._search_log_purge_done = False

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="POSIX file permissions not applicable on Windows",
    )
    def test_log_file_created_with_0o600(self, tmp_path):
        """Log file is created with 0o600 (owner read/write only)."""
        import vector_memory
        vector_memory._search_log_privacy_notice_shown = False

        from vector_memory import _log_search

        config = {
            "search_log": {
                "enabled": True,
                "path": ".claude/memory/search_log.jsonl",
                "include_content": False,
                "max_size_mb": 10,
                "retention_days": 30,
            }
        }
        mock_df = MagicMock()
        mock_df.iterrows.return_value = iter([])

        _log_search(tmp_path, config, "test", 5, "", "", mock_df)

        log_path = tmp_path / ".claude" / "memory" / "search_log.jsonl"
        assert log_path.exists()
        mode = stat.S_IMODE(log_path.stat().st_mode)
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"


class TestPathTraversal:
    """Verify path traversal guard prevents writes outside project root."""

    @pytest.fixture(autouse=True)
    def _reset_flags(self):
        """Reset module-level flags before each test."""
        import vector_memory
        vector_memory._search_log_purge_done = False

    def test_path_traversal_blocked(self, tmp_path, capsys):
        """Log path resolving outside project root is rejected."""
        import vector_memory
        vector_memory._search_log_privacy_notice_shown = False

        from vector_memory import _log_search

        config = {
            "search_log": {
                "enabled": True,
                "path": "../../etc/search_log.jsonl",
                "include_content": False,
                "max_size_mb": 10,
                "retention_days": 30,
            }
        }
        mock_df = MagicMock()
        mock_df.iterrows.return_value = iter([])

        _log_search(tmp_path, config, "test", 5, "", "", mock_df)

        captured = capsys.readouterr()
        assert "resolves outside" in captured.err
