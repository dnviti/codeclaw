"""Tests for local_analyzers.py."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure scripts dir is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from local_analyzers import (
    ALL_ANALYZERS,
    ECOSYSTEM_TO_STACK,
    LANGUAGE_NORMALIZATION,
    LAYER_NAMES,
    SEVERITY_ORDER,
    STACK_TOOLS,
    UNIVERSAL_TOOLS,
    CodeQLAnalyzer,
    ComplexityAnalyzer,
    DependencyVulnAnalyzer,
    Finding,
    LanguageLinterAnalyzer,
    SecretScannerAnalyzer,
    SemgrepAnalyzer,
    ToolStatus,
    check_tool_availability,
    create_analyzers,
    detect_active_stacks,
    normalize_severity,
)


# ── TestFinding ─────────────────────────────────────────────────────────────


class TestFinding:
    def test_defaults(self):
        f = Finding(tool="test", severity="high", category="lint", file="a.py")
        assert f.line == 0
        assert f.column == 0
        assert f.message == ""
        assert f.suggestion == ""
        assert f.auto_fixable is False
        assert f.rule_id == ""

    def test_to_dict(self):
        f = Finding(
            tool="flake8", severity="medium", category="lint",
            file="a.py", line=10, column=5, message="unused import",
            rule_id="F401",
        )
        d = f.to_dict()
        assert isinstance(d, dict)
        assert d["tool"] == "flake8"
        assert d["severity"] == "medium"
        assert d["line"] == 10
        assert d["rule_id"] == "F401"
        assert d["auto_fixable"] is False

    def test_all_fields(self):
        f = Finding(
            tool="eslint", severity="high", category="lint",
            file="b.js", line=1, column=2, message="msg",
            suggestion="fix it", auto_fixable=True, rule_id="no-var",
        )
        d = f.to_dict()
        assert d["auto_fixable"] is True
        assert d["suggestion"] == "fix it"


# ── TestToolStatus ──────────────────────────────────────────────────────────


class TestToolStatus:
    def test_defaults(self):
        s = ToolStatus(name="Test", command="test")
        assert s.available is False
        assert s.version == ""
        assert s.stack == ""

    def test_with_values(self):
        s = ToolStatus(
            name="Flake8", command="flake8",
            available=True, version="6.0.0", stack="Python",
        )
        assert s.available is True
        assert s.version == "6.0.0"
        assert s.stack == "Python"


# ── TestSeverityNormalization ───────────────────────────────────────────────


class TestSeverityNormalization:
    def test_known_tool_severity(self):
        assert normalize_severity("semgrep", "ERROR") == "high"
        assert normalize_severity("semgrep", "WARNING") == "medium"
        assert normalize_severity("semgrep", "INFO") == "low"

    def test_flake8_codes(self):
        assert normalize_severity("flake8", "E") == "medium"
        assert normalize_severity("flake8", "F") == "high"
        assert normalize_severity("flake8", "W") == "low"

    def test_pylint_codes(self):
        assert normalize_severity("pylint", "E") == "high"
        assert normalize_severity("pylint", "F") == "critical"

    def test_case_insensitive_fallback(self):
        assert normalize_severity("bandit", "high") == "high"
        assert normalize_severity("bandit", "HIGH") == "high"

    def test_unknown_tool_standard_severity(self):
        assert normalize_severity("unknown_tool", "critical") == "critical"
        assert normalize_severity("unknown_tool", "HIGH") == "high"

    def test_unknown_tool_unknown_severity(self):
        assert normalize_severity("unknown_tool", "XYZZY") == "medium"

    def test_trivy_severities(self):
        assert normalize_severity("trivy", "CRITICAL") == "critical"
        assert normalize_severity("trivy", "HIGH") == "high"
        assert normalize_severity("trivy", "UNKNOWN") == "info"

    def test_codeql_severities(self):
        assert normalize_severity("codeql", "error") == "critical"
        assert normalize_severity("codeql", "warning") == "high"


# ── TestLanguageNormalization ───────────────────────────────────────────────


class TestLanguageNormalization:
    def test_typescript_maps_to_javascript(self):
        assert LANGUAGE_NORMALIZATION["TypeScript"] == "JavaScript"
        assert LANGUAGE_NORMALIZATION["TypeScript/React"] == "JavaScript"

    def test_kotlin_maps_to_java(self):
        assert LANGUAGE_NORMALIZATION["Kotlin"] == "Java"
        assert LANGUAGE_NORMALIZATION["Scala"] == "Java"

    def test_vue_svelte_map_to_javascript(self):
        assert LANGUAGE_NORMALIZATION["Vue"] == "JavaScript"
        assert LANGUAGE_NORMALIZATION["Svelte"] == "JavaScript"

    def test_c_cpp_variants(self):
        assert LANGUAGE_NORMALIZATION["C"] == "C_CPP"
        assert LANGUAGE_NORMALIZATION["C++"] == "C_CPP"
        assert LANGUAGE_NORMALIZATION["Objective-C"] == "C_CPP"

    def test_python_stays_python(self):
        assert LANGUAGE_NORMALIZATION["Python"] == "Python"

    def test_ecosystem_to_stack(self):
        assert ECOSYSTEM_TO_STACK["Node.js"] == "JavaScript"
        assert ECOSYSTEM_TO_STACK["JVM"] == "Java"
        assert ECOSYSTEM_TO_STACK[".NET"] == "CSharp"
        assert ECOSYSTEM_TO_STACK["C/C++"] == "C_CPP"


# ── TestDetectActiveStacks ──────────────────────────────────────────────────


class TestDetectActiveStacks:
    @patch("local_analyzers.detect_frameworks", return_value=[])
    @patch("local_analyzers.detect_ecosystems", return_value={"Python": 10})
    @patch("local_analyzers.detect_languages", return_value={"Python": 10})
    @patch("local_analyzers.load_gitignore_patterns", return_value=[])
    def test_python_project(self, mock_gi, mock_lang, mock_eco, mock_fw):
        stacks = detect_active_stacks(Path("/fake"))
        assert "Python" in stacks

    @patch("local_analyzers.detect_frameworks", return_value=["React"])
    @patch("local_analyzers.detect_ecosystems", return_value={"Node.js": 5})
    @patch("local_analyzers.detect_languages", return_value={"TypeScript": 20})
    @patch("local_analyzers.load_gitignore_patterns", return_value=[])
    def test_typescript_react_project(self, mock_gi, mock_lang, mock_eco, mock_fw):
        stacks = detect_active_stacks(Path("/fake"))
        assert "JavaScript" in stacks

    @patch("local_analyzers.detect_frameworks", return_value=[])
    @patch("local_analyzers.detect_ecosystems", return_value={})
    @patch("local_analyzers.detect_languages", return_value={})
    @patch("local_analyzers.load_gitignore_patterns", return_value=[])
    def test_empty_project(self, mock_gi, mock_lang, mock_eco, mock_fw):
        stacks = detect_active_stacks(Path("/fake"))
        assert len(stacks) == 0


# ── TestCheckToolAvailability ───────────────────────────────────────────────


class TestCheckToolAvailability:
    @patch("local_analyzers._tool_available", return_value=False)
    @patch("local_analyzers._get_tool_version", return_value="")
    def test_no_tools_available(self, mock_ver, mock_avail):
        statuses = check_tool_availability({"Python"})
        assert len(statuses) > 0
        assert all(not s.available for s in statuses)

    @patch("local_analyzers._tool_available", return_value=True)
    @patch("local_analyzers._get_tool_version", return_value="1.0.0")
    def test_all_tools_available(self, mock_ver, mock_avail):
        statuses = check_tool_availability({"Python"})
        assert all(s.available for s in statuses)

    @patch("local_analyzers._tool_available", return_value=False)
    @patch("local_analyzers._get_tool_version", return_value="")
    def test_includes_universal_tools(self, mock_ver, mock_avail):
        statuses = check_tool_availability(set())
        # Should still have universal tools
        universal = [s for s in statuses if s.stack == "universal"]
        assert len(universal) > 0


# ── TestSemgrepAnalyzer ─────────────────────────────────────────────────────


class TestSemgrepAnalyzer:
    def test_not_applicable_without_binary(self):
        with patch("local_analyzers._tool_available", return_value=False):
            analyzer = SemgrepAnalyzer(Path("/fake"))
            assert analyzer.is_applicable() is False

    def test_applicable_with_binary(self):
        with patch("local_analyzers._tool_available", return_value=True):
            analyzer = SemgrepAnalyzer(Path("/fake"))
            assert analyzer.is_applicable() is True

    @patch("local_analyzers._tool_available", return_value=True)
    @patch("local_analyzers._run_tool")
    def test_parses_findings(self, mock_run, mock_avail):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "results": [
                    {
                        "path": "app.py",
                        "start": {"line": 5, "col": 1},
                        "extra": {"severity": "ERROR", "message": "SQL injection"},
                        "check_id": "python.sql-injection",
                    }
                ],
            }),
        )
        analyzer = SemgrepAnalyzer(Path("/fake"))
        findings = analyzer.run()
        assert len(findings) == 1
        assert findings[0].severity == "high"
        assert findings[0].tool == "semgrep"

    @patch("local_analyzers._tool_available", return_value=False)
    def test_returns_empty_when_unavailable(self, mock_avail):
        analyzer = SemgrepAnalyzer(Path("/fake"))
        assert analyzer.run() == []


# ── TestLanguageLinterAnalyzer ──────────────────────────────────────────────


class TestLanguageLinterAnalyzer:
    def test_not_applicable_without_stacks(self):
        analyzer = LanguageLinterAnalyzer(Path("/fake"))
        assert analyzer.is_applicable() is False

    def test_applicable_with_stacks(self):
        analyzer = LanguageLinterAnalyzer(Path("/fake"))
        analyzer.set_stacks({"Python"})
        assert analyzer.is_applicable() is True

    @patch("local_analyzers._tool_available", return_value=True)
    @patch("local_analyzers._run_tool")
    def test_run_flake8(self, mock_run, mock_avail):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "test.py": [
                    {"code": "E501", "line_number": 10, "column_number": 80, "text": "line too long"},
                ],
            }),
        )
        analyzer = LanguageLinterAnalyzer(Path("/fake"))
        analyzer.set_stacks({"Python"})
        findings = analyzer._run_flake8()
        assert len(findings) == 1
        assert findings[0].tool == "flake8"
        assert findings[0].rule_id == "E501"

    def test_check_tools_returns_statuses(self):
        with patch("local_analyzers._tool_available", return_value=False):
            analyzer = LanguageLinterAnalyzer(Path("/fake"))
            analyzer.set_stacks({"Python"})
            statuses = analyzer.check_tools()
            assert len(statuses) > 0
            assert all(s.stack == "Python" for s in statuses)


# ── TestDependencyVulnAnalyzer ──────────────────────────────────────────────


class TestDependencyVulnAnalyzer:
    def test_applicable_with_stacks(self):
        analyzer = DependencyVulnAnalyzer(Path("/fake"))
        analyzer.set_stacks({"Python"})
        assert analyzer.is_applicable() is True

    def test_not_applicable_without_stacks(self):
        analyzer = DependencyVulnAnalyzer(Path("/fake"))
        assert analyzer.is_applicable() is False

    @patch("local_analyzers._tool_available", return_value=False)
    def test_trivy_skipped_when_unavailable(self, mock_avail):
        analyzer = DependencyVulnAnalyzer(Path("/fake"))
        analyzer.set_stacks({"Python"})
        findings = analyzer._run_trivy()
        assert findings == []

    def test_check_tools_includes_universal(self):
        with patch("local_analyzers._tool_available", return_value=False):
            analyzer = DependencyVulnAnalyzer(Path("/fake"))
            analyzer.set_stacks({"Python"})
            statuses = analyzer.check_tools()
            universal = [s for s in statuses if s.stack == "universal"]
            assert len(universal) > 0


# ── TestSecretScannerAnalyzer ───────────────────────────────────────────────


class TestSecretScannerAnalyzer:
    @patch("local_analyzers._tool_available", return_value=False)
    def test_not_applicable_without_tools(self, mock_avail):
        analyzer = SecretScannerAnalyzer(Path("/fake"))
        assert analyzer.is_applicable() is False

    @patch("local_analyzers._tool_available", side_effect=lambda b: b == "gitleaks")
    def test_applicable_with_gitleaks(self, mock_avail):
        analyzer = SecretScannerAnalyzer(Path("/fake"))
        assert analyzer.is_applicable() is True

    @patch("local_analyzers._tool_available", return_value=True)
    @patch("local_analyzers._run_tool")
    def test_gitleaks_parses_findings(self, mock_run, mock_avail):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps([
                {
                    "File": "config.py",
                    "StartLine": 3,
                    "Description": "AWS key",
                    "RuleID": "aws-access-key",
                    "Severity": "HIGH",
                }
            ]),
        )
        analyzer = SecretScannerAnalyzer(Path("/fake"))
        findings = analyzer._run_gitleaks()
        assert len(findings) == 1
        assert findings[0].category == "secret"
        assert findings[0].tool == "gitleaks"


# ── TestComplexityAnalyzer ──────────────────────────────────────────────────


class TestComplexityAnalyzer:
    def test_not_applicable_without_python(self):
        with patch("local_analyzers._tool_available", return_value=False):
            analyzer = ComplexityAnalyzer(Path("/fake"))
            analyzer.set_stacks({"JavaScript"})
            assert analyzer.is_applicable() is False

    @patch("local_analyzers._tool_available", return_value=True)
    def test_applicable_with_python_and_radon(self, mock_avail):
        analyzer = ComplexityAnalyzer(Path("/fake"))
        analyzer.set_stacks({"Python"})
        assert analyzer.is_applicable() is True

    @patch("local_analyzers._tool_available", return_value=True)
    @patch("local_analyzers._run_tool")
    def test_radon_parses_findings(self, mock_run, mock_avail):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "complex.py": [
                    {
                        "type": "function",
                        "name": "do_stuff",
                        "lineno": 10,
                        "complexity": 15,
                        "rank": "D",
                    }
                ],
            }),
        )
        analyzer = ComplexityAnalyzer(Path("/fake"))
        analyzer.set_stacks({"Python"})
        findings = analyzer._run_radon()
        assert len(findings) == 1
        assert findings[0].severity == "high"
        assert findings[0].category == "complexity"


# ── TestCodeQLAnalyzer ──────────────────────────────────────────────────────


class TestCodeQLAnalyzer:
    @patch("local_analyzers._tool_available", return_value=False)
    def test_not_applicable_without_binary(self, mock_avail):
        analyzer = CodeQLAnalyzer(Path("/fake"))
        assert analyzer.is_applicable() is False
        assert analyzer.run() == []

    @patch("local_analyzers._tool_available", return_value=True)
    def test_applicable_with_binary(self, mock_avail):
        analyzer = CodeQLAnalyzer(Path("/fake"))
        assert analyzer.is_applicable() is True


# ── TestCreateAnalyzers ─────────────────────────────────────────────────────


class TestCreateAnalyzers:
    @patch("local_analyzers._tool_available", return_value=False)
    @patch("local_analyzers.detect_active_stacks", return_value={"Python"})
    def test_creates_applicable_analyzers(self, mock_stacks, mock_avail):
        analyzers = create_analyzers(Path("/fake"))
        # Should include at least LanguageLinterAnalyzer, DependencyVulnAnalyzer
        types = {type(a).__name__ for a in analyzers}
        assert "LanguageLinterAnalyzer" in types
        assert "DependencyVulnAnalyzer" in types

    @patch("local_analyzers._tool_available", return_value=False)
    def test_empty_stacks_minimal_analyzers(self, mock_avail):
        analyzers = create_analyzers(Path("/fake"), stacks=set())
        # Should not include stack-dependent analyzers
        for a in analyzers:
            assert not isinstance(a, LanguageLinterAnalyzer)


# ── TestCLIParsing ──────────────────────────────────────────────────────────


class TestCLIParsing:
    def test_scan_subcommand_exists(self):
        """Verify CLI accepts scan subcommand."""
        from local_analyzers import main
        import argparse
        # Just verify the function exists and is callable
        assert callable(main)

    def test_severity_order_completeness(self):
        """All standard severities have an order."""
        assert "critical" in SEVERITY_ORDER
        assert "high" in SEVERITY_ORDER
        assert "medium" in SEVERITY_ORDER
        assert "low" in SEVERITY_ORDER
        assert "info" in SEVERITY_ORDER
        assert SEVERITY_ORDER["critical"] < SEVERITY_ORDER["high"]
        assert SEVERITY_ORDER["high"] < SEVERITY_ORDER["medium"]


# ── TestLayerNames ──────────────────────────────────────────────────────────


class TestLayerNames:
    def test_all_categories_have_names(self):
        expected_keys = {"sast", "lint", "type_check", "dependency", "secret", "complexity", "security", "ai_review"}
        assert expected_keys == set(LAYER_NAMES.keys())

    def test_names_are_nonempty_strings(self):
        for key, name in LAYER_NAMES.items():
            assert isinstance(name, str)
            assert len(name) > 0

    def test_analyzer_count(self):
        assert len(ALL_ANALYZERS) == 8

    def test_stack_tools_have_known_stacks(self):
        for stack in STACK_TOOLS:
            assert stack in (
                "Python", "JavaScript", "Go", "Rust", "Java",
                "CSharp", "Ruby", "PHP", "C_CPP", "Elixir",
            )

    def test_universal_tools_have_known_categories(self):
        for cat in UNIVERSAL_TOOLS:
            assert cat in ("sast_deep", "sast_fast", "secrets", "dep_audit_universal")
