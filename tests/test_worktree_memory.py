"""Tests for worktree + shared memory integration (VMEM-0052)."""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest

# Add scripts/ to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


# ── _load_worktree_config tests ─────────────────────────────────────────────


class TestLoadWorktreeConfig:
    """Test that _load_worktree_config returns correct defaults and overrides."""

    def test_defaults_when_no_config(self, tmp_path):
        from skill_helper import _load_worktree_config

        result = _load_worktree_config(tmp_path)
        assert result["enabled"] is True
        assert result["max_count"] == 10
        assert result["cleanup_after_days"] == 7
        assert result["base_dir"] == ".worktrees"

    def test_reads_from_claude_config(self, tmp_path):
        from skill_helper import _load_worktree_config

        cfg_dir = tmp_path / ".claude"
        cfg_dir.mkdir()
        cfg = {
            "worktrees": {
                "enabled": False,
                "max_count": 5,
                "cleanup_after_days": 14,
                "base_dir": ".custom-wt",
                "_comment": "should be excluded",
            }
        }
        (cfg_dir / "project-config.json").write_text(json.dumps(cfg))

        result = _load_worktree_config(tmp_path)
        assert result["enabled"] is False
        assert result["max_count"] == 5
        assert result["cleanup_after_days"] == 14
        assert result["base_dir"] == ".custom-wt"
        assert "_comment" not in result

    def test_merges_partial_config_with_defaults(self, tmp_path):
        from skill_helper import _load_worktree_config

        cfg_dir = tmp_path / ".claude"
        cfg_dir.mkdir()
        cfg = {"worktrees": {"enabled": True}}
        (cfg_dir / "project-config.json").write_text(json.dumps(cfg))

        result = _load_worktree_config(tmp_path)
        assert result["enabled"] is True
        assert result["max_count"] == 10  # default
        assert result["cleanup_after_days"] == 7  # default

    def test_fallback_to_config_dir(self, tmp_path):
        from skill_helper import _load_worktree_config

        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        cfg = {"worktrees": {"enabled": False, "max_count": 3}}
        (cfg_dir / "project-config.json").write_text(json.dumps(cfg))

        result = _load_worktree_config(tmp_path)
        assert result["enabled"] is False
        assert result["max_count"] == 3

    def test_rejects_absolute_base_dir(self, tmp_path):
        from skill_helper import _load_worktree_config

        cfg_dir = tmp_path / ".claude"
        cfg_dir.mkdir()
        cfg = {"worktrees": {"base_dir": "/tmp/evil"}}
        (cfg_dir / "project-config.json").write_text(json.dumps(cfg))

        result = _load_worktree_config(tmp_path)
        assert result["base_dir"] == ".worktrees", "absolute base_dir should be rejected"

    def test_rejects_traversal_base_dir(self, tmp_path):
        from skill_helper import _load_worktree_config

        cfg_dir = tmp_path / ".claude"
        cfg_dir.mkdir()
        cfg = {"worktrees": {"base_dir": "../../etc"}}
        (cfg_dir / "project-config.json").write_text(json.dumps(cfg))

        result = _load_worktree_config(tmp_path)
        assert result["base_dir"] == ".worktrees", "traversal base_dir should be rejected"


# ── _is_worktree_enabled tests ──────────────────────────────────────────────


class TestIsWorktreeEnabled:
    """Test that default is now True."""

    def test_default_is_true(self, tmp_path):
        from skill_helper import _is_worktree_enabled

        assert _is_worktree_enabled(tmp_path) is True

    def test_explicit_false(self, tmp_path):
        from skill_helper import _is_worktree_enabled

        cfg_dir = tmp_path / ".claude"
        cfg_dir.mkdir()
        cfg = {"worktrees": {"enabled": False}}
        (cfg_dir / "project-config.json").write_text(json.dumps(cfg))

        assert _is_worktree_enabled(tmp_path) is False

    def test_explicit_true(self, tmp_path):
        from skill_helper import _is_worktree_enabled

        cfg_dir = tmp_path / ".claude"
        cfg_dir.mkdir()
        cfg = {"worktrees": {"enabled": True}}
        (cfg_dir / "project-config.json").write_text(json.dumps(cfg))

        assert _is_worktree_enabled(tmp_path) is True


# ── _is_worktree_dirty tests ────────────────────────────────────────────────


class TestIsWorktreeDirty:
    """Test dirty-state detection for worktrees."""

    def test_clean_worktree(self, tmp_path):
        from skill_helper import _is_worktree_dirty

        with mock.patch("skill_helper.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(stdout="", returncode=0)
            assert _is_worktree_dirty(str(tmp_path)) is False

    def test_dirty_worktree(self, tmp_path):
        from skill_helper import _is_worktree_dirty

        with mock.patch("skill_helper.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                stdout=" M scripts/skill_helper.py\n", returncode=0
            )
            assert _is_worktree_dirty(str(tmp_path)) is True

    def test_assumes_dirty_on_failure(self, tmp_path):
        from skill_helper import _is_worktree_dirty

        with mock.patch(
            "skill_helper.subprocess.run",
            side_effect=FileNotFoundError("git not found"),
        ):
            assert _is_worktree_dirty(str(tmp_path)) is True


# ── _enforce_worktree_limits tests ──────────────────────────────────────────


class TestEnforceWorktreeLimits:
    """Test worktree limit enforcement."""

    def test_returns_empty_when_no_worktrees(self, tmp_path):
        from skill_helper import _enforce_worktree_limits

        config = {"max_count": 10, "cleanup_after_days": 7, "base_dir": ".worktrees"}

        with mock.patch("skill_helper.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                stdout="worktree /main\n\n", returncode=0
            )
            result = _enforce_worktree_limits(tmp_path, config)

        assert result == []

    def test_returns_empty_on_git_failure(self, tmp_path):
        from skill_helper import _enforce_worktree_limits

        config = {"max_count": 10, "cleanup_after_days": 7}

        with mock.patch(
            "skill_helper.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "git"),
        ):
            result = _enforce_worktree_limits(tmp_path, config)

        assert result == []


# ── _verify_worktree_memory_sharing tests ───────────────────────────────────


class TestVerifyWorktreeMemorySharing:
    """Test memory sharing validation between worktrees."""

    def test_returns_true_when_roots_match(self, tmp_path):
        from skill_helper import _verify_worktree_memory_sharing

        wt_dir = tmp_path / ".worktrees" / "task" / "test"
        wt_dir.mkdir(parents=True)

        main_resolved = tmp_path.resolve()

        with mock.patch("skill_helper.subprocess.run") as mock_run:
            mock_run.return_value = mock.Mock(
                stdout=f"{main_resolved}/.git\n{wt_dir}/.git\n",
                returncode=0,
            )
            result = _verify_worktree_memory_sharing(tmp_path, wt_dir)

        assert result is True

    def test_returns_false_on_git_failure(self, tmp_path):
        from skill_helper import _verify_worktree_memory_sharing

        wt_dir = tmp_path / "wt"
        wt_dir.mkdir()

        with mock.patch(
            "skill_helper.subprocess.run",
            side_effect=FileNotFoundError("git not found"),
        ):
            result = _verify_worktree_memory_sharing(tmp_path, wt_dir)

        assert result is False


# ── Config file content tests ───────────────────────────────────────────────


class TestConfigFiles:
    """Verify config files have correct worktree defaults."""

    def test_project_config_worktrees_enabled(self):
        cfg_path = (
            Path(__file__).resolve().parent.parent
            / ".claude"
            / "project-config.json"
        )
        if not cfg_path.exists():
            pytest.skip("project-config.json not found")

        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        wt = data.get("worktrees", {})
        assert wt.get("enabled") is True, "worktrees.enabled should be True"
        assert "max_count" in wt, "worktrees.max_count should be configured"
        assert "cleanup_after_days" in wt, "worktrees.cleanup_after_days should be configured"

    def test_project_config_worktree_shared(self):
        cfg_path = (
            Path(__file__).resolve().parent.parent
            / ".claude"
            / "project-config.json"
        )
        if not cfg_path.exists():
            pytest.skip("project-config.json not found")

        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        vm = data.get("vector_memory", {})
        assert vm.get("worktree_shared") is True, "vector_memory.worktree_shared should be True"

    def test_example_config_worktrees_enabled(self):
        cfg_path = (
            Path(__file__).resolve().parent.parent
            / "config"
            / "project-config.example.json"
        )
        if not cfg_path.exists():
            pytest.skip("project-config.example.json not found")

        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        wt = data.get("worktrees", {})
        assert wt.get("enabled") is True, "example worktrees.enabled should be True"
        assert wt.get("max_count") == 10
        assert wt.get("cleanup_after_days") == 7
