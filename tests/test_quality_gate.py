"""Tests for quality_gate.py."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure scripts dir is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from quality_gate import (
    DEFAULT_CONFIG,
    _apply_auto_fixes,
    _run_verify,
    format_dashboard,
    load_config,
    run_quality_gate,
)


# ── TestConfigLoading ───────────────────────────────────────────────────────


class TestConfigLoading:
    def test_default_config_values(self):
        assert DEFAULT_CONFIG["enabled"] is True
        assert "critical" in DEFAULT_CONFIG["fail_on"]
        assert "high" in DEFAULT_CONFIG["fail_on"]
        assert DEFAULT_CONFIG["auto_fix"] is True
        assert DEFAULT_CONFIG["max_fix_iterations"] == 3

    def test_load_missing_config(self, tmp_path):
        config = load_config(None, tmp_path)
        assert config["enabled"] is True
        assert config["fail_on"] == ["critical", "high"]

    def test_load_valid_config(self, tmp_path):
        cfg_dir = tmp_path / ".claude"
        cfg_dir.mkdir()
        cfg_file = cfg_dir / "project-config.json"
        cfg_file.write_text(json.dumps({
            "quality_gate": {
                "enabled": False,
                "fail_on": ["critical"],
                "auto_fix": False,
                "max_fix_iterations": 5,
            }
        }))
        config = load_config(None, tmp_path)
        assert config["enabled"] is False
        assert config["fail_on"] == ["critical"]
        assert config["auto_fix"] is False
        assert config["max_fix_iterations"] == 5

    def test_load_explicit_path(self, tmp_path):
        cfg_file = tmp_path / "custom-config.json"
        cfg_file.write_text(json.dumps({
            "quality_gate": {
                "enabled": True,
                "fail_on": ["critical", "high", "medium"],
            }
        }))
        config = load_config(str(cfg_file), tmp_path)
        assert "medium" in config["fail_on"]

    def test_malformed_json_uses_defaults(self, tmp_path):
        cfg_dir = tmp_path / ".claude"
        cfg_dir.mkdir()
        cfg_file = cfg_dir / "project-config.json"
        cfg_file.write_text("not valid json{{{")
        config = load_config(None, tmp_path)
        assert config == DEFAULT_CONFIG


# ── TestOrchestratorPipeline ────────────────────────────────────────────────


class TestOrchestratorPipeline:
    @patch("quality_gate.scan")
    @patch("quality_gate._run_verify", return_value=(True, ""))
    def test_passes_with_no_findings(self, mock_verify, mock_scan):
        mock_scan.return_value = {
            "findings": [],
            "summary": {"total": 0, "by_severity": {}, "by_tool": {}, "stacks": ["Python"]},
            "tools": [],
            "errors": [],
        }
        result = run_quality_gate(Path("/fake"))
        assert result["passed"] is True
        assert result["summary"]["total"] == 0

    @patch("quality_gate.scan")
    @patch("quality_gate._run_verify", return_value=(True, ""))
    def test_fails_with_critical_findings(self, mock_verify, mock_scan):
        mock_scan.return_value = {
            "findings": [{"tool": "semgrep", "severity": "critical", "file": "a.py"}],
            "summary": {
                "total": 1,
                "by_severity": {"critical": 1},
                "by_tool": {"semgrep": 1},
                "stacks": ["Python"],
            },
            "tools": [],
            "errors": [],
        }
        result = run_quality_gate(Path("/fake"))
        assert result["passed"] is False

    @patch("quality_gate.scan")
    @patch("quality_gate._run_verify", return_value=(False, "tests failed"))
    def test_fails_with_verify_failure(self, mock_verify, mock_scan):
        mock_scan.return_value = {
            "findings": [],
            "summary": {"total": 0, "by_severity": {}, "by_tool": {}, "stacks": []},
            "tools": [],
            "errors": [],
        }
        result = run_quality_gate(Path("/fake"), verify_command="pytest")
        assert result["passed"] is False
        assert result["verify_result"]["success"] is False

    def test_disabled_gate_always_passes(self, tmp_path):
        cfg_dir = tmp_path / ".claude"
        cfg_dir.mkdir()
        cfg_file = cfg_dir / "project-config.json"
        cfg_file.write_text(json.dumps({"quality_gate": {"enabled": False}}))
        result = run_quality_gate(tmp_path)
        assert result["passed"] is True
        assert result["iterations"] == 0
        assert result["dashboard"] == "Quality gate disabled."


# ── TestFixLoop ─────────────────────────────────────────────────────────────


class TestFixLoop:
    @patch("quality_gate._apply_auto_fixes", return_value=2)
    @patch("quality_gate._run_verify", return_value=(True, ""))
    @patch("quality_gate.scan")
    def test_fix_loop_iterates(self, mock_scan, mock_verify, mock_fix):
        # First call: findings with auto_fixable. Second call: clean.
        mock_scan.side_effect = [
            {
                "findings": [{"tool": "eslint", "severity": "high", "file": "a.js", "auto_fixable": True}],
                "summary": {"total": 1, "by_severity": {"high": 1}, "by_tool": {"eslint": 1}, "stacks": ["JavaScript"]},
                "tools": [],
                "errors": [],
            },
            {
                "findings": [],
                "summary": {"total": 0, "by_severity": {}, "by_tool": {}, "stacks": ["JavaScript"]},
                "tools": [],
                "errors": [],
            },
        ]
        result = run_quality_gate(Path("/fake"))
        assert result["passed"] is True
        assert result["iterations"] == 2
        assert result["fixes_applied"] == 2

    @patch("quality_gate._apply_auto_fixes", return_value=0)
    @patch("quality_gate._run_verify", return_value=(True, ""))
    @patch("quality_gate.scan")
    def test_fix_loop_stops_when_no_fixes(self, mock_scan, mock_verify, mock_fix):
        mock_scan.return_value = {
            "findings": [{"tool": "semgrep", "severity": "high", "file": "a.py"}],
            "summary": {"total": 1, "by_severity": {"high": 1}, "by_tool": {"semgrep": 1}, "stacks": ["Python"]},
            "tools": [],
            "errors": [],
        }
        result = run_quality_gate(Path("/fake"))
        assert result["passed"] is False
        assert result["iterations"] == 1


# ── TestFixLoopMaxIterations ────────────────────────────────────────────────


class TestFixLoopMaxIterations:
    @patch("quality_gate._apply_auto_fixes", return_value=1)
    @patch("quality_gate._run_verify", return_value=(True, ""))
    @patch("quality_gate.scan")
    def test_respects_max_iterations(self, mock_scan, mock_verify, mock_fix):
        mock_scan.return_value = {
            "findings": [{"tool": "eslint", "severity": "high", "file": "a.js", "auto_fixable": True}],
            "summary": {"total": 1, "by_severity": {"high": 1}, "by_tool": {"eslint": 1}, "stacks": ["JavaScript"]},
            "tools": [],
            "errors": [],
        }
        result = run_quality_gate(Path("/fake"), max_iterations=2)
        # Should stop at max_iterations even if fixes keep being applied
        assert result["iterations"] <= 2

    @patch("quality_gate._apply_auto_fixes", return_value=1)
    @patch("quality_gate._run_verify", return_value=(True, ""))
    @patch("quality_gate.scan")
    def test_config_overrides_max_iterations(self, mock_scan, mock_verify, mock_fix, tmp_path):
        cfg_dir = tmp_path / ".claude"
        cfg_dir.mkdir()
        cfg_file = cfg_dir / "project-config.json"
        cfg_file.write_text(json.dumps({"quality_gate": {"max_fix_iterations": 1}}))
        mock_scan.return_value = {
            "findings": [{"tool": "eslint", "severity": "high", "file": "a.js", "auto_fixable": True}],
            "summary": {"total": 1, "by_severity": {"high": 1}, "by_tool": {"eslint": 1}, "stacks": []},
            "tools": [],
            "errors": [],
        }
        result = run_quality_gate(tmp_path, max_iterations=5)
        assert result["iterations"] <= 1


# ── TestExitCodes ───────────────────────────────────────────────────────────


class TestExitCodes:
    @patch("quality_gate.scan")
    @patch("quality_gate._run_verify", return_value=(True, ""))
    def test_passed_result_structure(self, mock_verify, mock_scan):
        mock_scan.return_value = {
            "findings": [],
            "summary": {"total": 0, "by_severity": {}, "by_tool": {}, "stacks": []},
            "tools": [],
            "errors": [],
        }
        result = run_quality_gate(Path("/fake"))
        assert "passed" in result
        assert "findings" in result
        assert "summary" in result
        assert "iterations" in result
        assert "dashboard" in result
        assert "verify_result" in result

    @patch("quality_gate.scan")
    @patch("quality_gate._run_verify", return_value=(True, ""))
    def test_low_severity_passes(self, mock_verify, mock_scan):
        mock_scan.return_value = {
            "findings": [{"tool": "flake8", "severity": "low", "file": "a.py"}],
            "summary": {"total": 1, "by_severity": {"low": 1}, "by_tool": {"flake8": 1}, "stacks": ["Python"]},
            "tools": [],
            "errors": [],
        }
        result = run_quality_gate(Path("/fake"))
        assert result["passed"] is True  # low severity doesn't block


# ── TestSeverityFiltering ───────────────────────────────────────────────────


class TestSeverityFiltering:
    @patch("quality_gate.scan")
    @patch("quality_gate._run_verify", return_value=(True, ""))
    def test_only_critical_blocks(self, mock_verify, mock_scan, tmp_path):
        cfg_dir = tmp_path / ".claude"
        cfg_dir.mkdir()
        cfg_file = cfg_dir / "project-config.json"
        cfg_file.write_text(json.dumps({"quality_gate": {"fail_on": ["critical"]}}))
        mock_scan.return_value = {
            "findings": [{"tool": "semgrep", "severity": "high", "file": "a.py"}],
            "summary": {"total": 1, "by_severity": {"high": 1}, "by_tool": {"semgrep": 1}, "stacks": ["Python"]},
            "tools": [],
            "errors": [],
        }
        result = run_quality_gate(tmp_path)
        assert result["passed"] is True  # high doesn't block when only critical blocks

    @patch("quality_gate.scan")
    @patch("quality_gate._run_verify", return_value=(True, ""))
    def test_medium_blocks_when_configured(self, mock_verify, mock_scan, tmp_path):
        cfg_dir = tmp_path / ".claude"
        cfg_dir.mkdir()
        cfg_file = cfg_dir / "project-config.json"
        cfg_file.write_text(json.dumps({"quality_gate": {"fail_on": ["critical", "high", "medium"]}}))
        mock_scan.return_value = {
            "findings": [{"tool": "flake8", "severity": "medium", "file": "a.py"}],
            "summary": {"total": 1, "by_severity": {"medium": 1}, "by_tool": {"flake8": 1}, "stacks": ["Python"]},
            "tools": [],
            "errors": [],
        }
        result = run_quality_gate(tmp_path)
        assert result["passed"] is False


# ── TestDashboard ───────────────────────────────────────────────────────────


class TestDashboard:
    def test_dashboard_contains_result(self):
        results = {
            "summary": {"total": 0, "by_severity": {}, "by_tool": {}, "stacks": ["Python"]},
            "tools": [],
            "errors": [],
        }
        dashboard = format_dashboard(results, 1, 3)
        assert "QUALITY GATE DASHBOARD" in dashboard
        assert "RESULT: PASS" in dashboard

    def test_dashboard_shows_blocking(self):
        results = {
            "summary": {"total": 2, "by_severity": {"critical": 1, "low": 1}, "by_tool": {"semgrep": 2}, "stacks": []},
            "tools": [],
            "errors": [],
        }
        dashboard = format_dashboard(results, 1, 3)
        assert "FAIL" in dashboard
        assert "BLOCKING" in dashboard

    def test_dashboard_shows_iterations(self):
        results = {
            "summary": {"total": 0, "by_severity": {}, "by_tool": {}, "stacks": ["Go"]},
            "tools": [{"name": "golangci-lint", "available": True}],
            "errors": [],
        }
        dashboard = format_dashboard(results, 2, 3)
        assert "2/3" in dashboard

    def test_dashboard_shows_errors(self):
        results = {
            "summary": {"total": 0, "by_severity": {}, "by_tool": {}, "stacks": []},
            "tools": [],
            "errors": ["SemgrepAnalyzer: timeout"],
        }
        dashboard = format_dashboard(results, 1, 1)
        assert "Errors: 1" in dashboard
        assert "timeout" in dashboard

    def test_dashboard_shows_tool_counts(self):
        results = {
            "summary": {"total": 0, "by_severity": {}, "by_tool": {}, "stacks": []},
            "tools": [
                {"name": "Flake8", "available": True},
                {"name": "Pylint", "available": False},
            ],
            "errors": [],
        }
        dashboard = format_dashboard(results, 1, 1)
        assert "Tools used: 1" in dashboard
        assert "Tools unavailable: 1" in dashboard
