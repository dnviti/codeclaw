"""Multi-tool local analysis engine.

Orchestrates external linters, SAST tools, secret scanners, type checkers,
dependency auditors, and complexity analyzers across detected language stacks.
Language-agnostic: auto-detects project stacks and available tools.
"""

from abc import ABC, abstractmethod
import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

# Allow imports from sibling packages
sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyzers import (
    detect_ecosystems,
    detect_frameworks,
    detect_languages,
    load_gitignore_patterns,
    walk_source_files,
)

logger = logging.getLogger(__name__)

# ── Severity ────────────────────────────────────────────────────────────────

SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}

# ── Data Classes ────────────────────────────────────────────────────────────


@dataclass
class Finding:
    """A single finding from an analysis tool."""

    tool: str
    severity: str
    category: str
    file: str
    line: int = 0
    column: int = 0
    message: str = ""
    suggestion: str = ""
    auto_fixable: bool = False
    rule_id: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ToolStatus:
    """Status of an external tool."""

    name: str
    command: str
    available: bool = False
    version: str = ""
    stack: str = ""


# ── Language / Ecosystem Normalization ──────────────────────────────────────

LANGUAGE_NORMALIZATION: dict[str, str] = {
    "Python": "Python",
    "JavaScript": "JavaScript",
    "TypeScript": "JavaScript",
    "TypeScript/React": "JavaScript",
    "JavaScript/React": "JavaScript",
    "Vue": "JavaScript",
    "Svelte": "JavaScript",
    "Go": "Go",
    "Rust": "Rust",
    "Java": "Java",
    "Kotlin": "Java",
    "Scala": "Java",
    "C#": "CSharp",
    "F#": "CSharp",
    "Ruby": "Ruby",
    "PHP": "PHP",
    "C": "C_CPP",
    "C++": "C_CPP",
    "Objective-C": "C_CPP",
    "Elixir": "Elixir",
    "Swift": "Swift",
    "Dart": "Dart",
}

ECOSYSTEM_TO_STACK: dict[str, str] = {
    "Node.js": "JavaScript",
    "Python": "Python",
    "Go": "Go",
    "Rust": "Rust",
    "JVM": "Java",
    ".NET": "CSharp",
    "Ruby": "Ruby",
    "PHP": "PHP",
    "C/C++": "C_CPP",
    "Elixir": "Elixir",
    "Swift": "Swift",
    "Dart": "Dart",
}

# ── Tool Definitions ────────────────────────────────────────────────────────

# ToolDef: (binary_name, display_name)
ToolDef = tuple[str, str]

STACK_TOOLS: dict[str, dict[str, list[ToolDef]]] = {
    "Python": {
        "linters": [("flake8", "Flake8"), ("pylint", "Pylint"), ("bandit", "Bandit")],
        "type_checker": [("mypy", "Mypy")],
        "dep_audit": [("pip-audit", "pip-audit"), ("safety", "Safety")],
        "complexity": [("radon", "Radon"), ("vulture", "Vulture")],
        "formatter": [("black", "Black"), ("autopep8", "autopep8")],
    },
    "JavaScript": {
        "linters": [("eslint", "ESLint")],
        "type_checker": [("tsc", "TypeScript Compiler")],
        "dep_audit": [("npm", "npm audit")],
        "complexity": [("escomplex", "escomplex"), ("ts-prune", "ts-prune")],
        "formatter": [("prettier", "Prettier")],
    },
    "Go": {
        "linters": [("golangci-lint", "golangci-lint")],
        "type_checker": [("go", "go vet")],
        "dep_audit": [("govulncheck", "govulncheck")],
    },
    "Rust": {
        "linters": [("cargo", "cargo clippy")],
        "dep_audit": [("cargo", "cargo audit")],
    },
    "Java": {
        "linters": [("spotbugs", "SpotBugs")],
    },
    "CSharp": {
        "linters": [("dotnet", "dotnet format")],
    },
    "Ruby": {
        "linters": [("rubocop", "RuboCop")],
        "dep_audit": [("bundle-audit", "bundle-audit")],
    },
    "PHP": {
        "linters": [("phpstan", "PHPStan"), ("phpcs", "PHP_CodeSniffer")],
    },
    "C_CPP": {
        "linters": [("cppcheck", "cppcheck"), ("clang-tidy", "clang-tidy")],
    },
    "Elixir": {
        "linters": [("mix", "mix credo")],
    },
}

UNIVERSAL_TOOLS: dict[str, list[ToolDef]] = {
    "sast_deep": [("codeql", "CodeQL")],
    "sast_fast": [("semgrep", "Semgrep")],
    "secrets": [("gitleaks", "Gitleaks"), ("trufflehog", "TruffleHog")],
    "dep_audit_universal": [("trivy", "Trivy")],
}

# ── Install Guide ───────────────────────────────────────────────────────────

INSTALL_GUIDE: dict[str, str] = {
    "flake8": "pip install flake8",
    "pylint": "pip install pylint",
    "bandit": "pip install bandit",
    "mypy": "pip install mypy",
    "pip-audit": "pip install pip-audit",
    "safety": "pip install safety",
    "radon": "pip install radon",
    "vulture": "pip install vulture",
    "black": "pip install black",
    "autopep8": "pip install autopep8",
    "eslint": "npm install -g eslint",
    "tsc": "npm install -g typescript",
    "prettier": "npm install -g prettier",
    "escomplex": "npm install -g escomplex",
    "ts-prune": "npm install -g ts-prune",
    "golangci-lint": "go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest",
    "govulncheck": "go install golang.org/x/vuln/cmd/govulncheck@latest",
    "semgrep": "pip install semgrep",
    "gitleaks": "brew install gitleaks  # or: go install github.com/gitleaks/gitleaks/v8@latest",
    "trufflehog": "brew install trufflehog  # or: pip install trufflehog",
    "trivy": "brew install trivy  # or: curl -sfL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | sh",
    "codeql": "gh extension install github/gh-codeql  # or download from github.com/github/codeql-cli-binaries",
    "cppcheck": "apt install cppcheck  # or: brew install cppcheck",
    "clang-tidy": "apt install clang-tidy  # or: brew install llvm",
    "rubocop": "gem install rubocop",
    "bundle-audit": "gem install bundler-audit",
    "phpstan": "composer global require phpstan/phpstan",
    "phpcs": "composer global require squizlabs/php_codesniffer",
    "spotbugs": "brew install spotbugs  # or download from spotbugs.github.io",
    "dotnet": "# Included with .NET SDK: https://dot.net/download",
    "cargo": "# Included with Rust: https://rustup.rs",
    "go": "# Included with Go: https://go.dev/dl",
    "npm": "# Included with Node.js: https://nodejs.org",
    "mix": "# Included with Elixir: https://elixir-lang.org/install.html",
}

# ── Severity Map ────────────────────────────────────────────────────────────

SEVERITY_MAP: dict[str, dict[str, str]] = {
    "semgrep": {
        "ERROR": "high",
        "WARNING": "medium",
        "INFO": "low",
    },
    "flake8": {
        "E": "medium",
        "W": "low",
        "F": "high",
        "C": "low",
    },
    "pylint": {
        "E": "high",
        "W": "medium",
        "C": "low",
        "R": "low",
        "F": "critical",
    },
    "bandit": {
        "HIGH": "high",
        "MEDIUM": "medium",
        "LOW": "low",
    },
    "eslint": {
        "2": "high",
        "1": "medium",
        "error": "high",
        "warning": "medium",
    },
    "golangci-lint": {
        "error": "high",
        "warning": "medium",
    },
    "mypy": {
        "error": "high",
        "warning": "medium",
        "note": "info",
    },
    "tsc": {
        "error": "high",
        "warning": "medium",
    },
    "gitleaks": {
        "CRITICAL": "critical",
        "HIGH": "high",
        "MEDIUM": "medium",
        "LOW": "low",
    },
    "trufflehog": {
        "HIGH": "critical",
        "MEDIUM": "high",
        "LOW": "medium",
    },
    "codeql": {
        "error": "critical",
        "warning": "high",
        "recommendation": "medium",
    },
    "cargo_clippy": {
        "error": "high",
        "warning": "medium",
    },
    "cppcheck": {
        "error": "high",
        "warning": "medium",
        "style": "low",
        "performance": "medium",
        "portability": "low",
        "information": "info",
    },
    "radon": {
        "A": "info",
        "B": "low",
        "C": "medium",
        "D": "high",
        "E": "high",
        "F": "critical",
    },
    "trivy": {
        "CRITICAL": "critical",
        "HIGH": "high",
        "MEDIUM": "medium",
        "LOW": "low",
        "UNKNOWN": "info",
    },
    "pip-audit": {
        "CRITICAL": "critical",
        "HIGH": "high",
        "MODERATE": "medium",
        "LOW": "low",
    },
}


def normalize_severity(tool: str, raw: str) -> str:
    """Normalize a tool-specific severity to the standard set."""
    tool_map = SEVERITY_MAP.get(tool, {})
    normalized = tool_map.get(raw, None)
    if normalized:
        return normalized
    # Try case-insensitive match
    raw_lower = raw.lower()
    for key, val in tool_map.items():
        if key.lower() == raw_lower:
            return val
    # Fallback: if raw is already a standard severity, use it
    if raw_lower in SEVERITY_ORDER:
        return raw_lower
    return "medium"


# ── Stack Detection ─────────────────────────────────────────────────────────


def detect_active_stacks(root: Path) -> set[str]:
    """Detect which language stacks are active in the project."""
    stacks: set[str] = set()
    gitignore = load_gitignore_patterns(root)

    # From languages
    languages = detect_languages(root, gitignore)
    for lang in languages:
        normalized = LANGUAGE_NORMALIZATION.get(lang)
        if normalized:
            stacks.add(normalized)

    # From ecosystems
    ecosystems = detect_ecosystems(root, gitignore)
    for eco in ecosystems:
        normalized = ECOSYSTEM_TO_STACK.get(eco)
        if normalized:
            stacks.add(normalized)

    # From frameworks (additional signal)
    frameworks = detect_frameworks(root)
    for fw in frameworks:
        fw_lower = fw.lower()
        if any(k in fw_lower for k in ("react", "vue", "svelte", "next", "nuxt", "angular")):
            stacks.add("JavaScript")
        elif any(k in fw_lower for k in ("django", "flask", "fastapi")):
            stacks.add("Python")
        elif "spring" in fw_lower:
            stacks.add("Java")
        elif "rails" in fw_lower:
            stacks.add("Ruby")
        elif "laravel" in fw_lower or "symfony" in fw_lower:
            stacks.add("PHP")
        elif "phoenix" in fw_lower:
            stacks.add("Elixir")

    return stacks


# ── Tool Availability ───────────────────────────────────────────────────────


def check_tool_availability(stacks: set[str]) -> list[ToolStatus]:
    """Check which external tools are available on the system."""
    statuses: list[ToolStatus] = []

    # Stack-specific tools
    for stack in sorted(stacks):
        categories = STACK_TOOLS.get(stack, {})
        for cat, tools in categories.items():
            for binary, display in tools:
                status = ToolStatus(name=display, command=binary, stack=stack)
                status.available = _tool_available(binary)
                if status.available:
                    status.version = _get_tool_version(binary)
                statuses.append(status)

    # Universal tools
    for cat, tools in UNIVERSAL_TOOLS.items():
        for binary, display in tools:
            status = ToolStatus(name=display, command=binary, stack="universal")
            status.available = _tool_available(binary)
            if status.available:
                status.version = _get_tool_version(binary)
            statuses.append(status)

    return statuses


def _tool_available(binary: str) -> bool:
    """Check if a tool binary is available on PATH."""
    return shutil.which(binary) is not None


def _get_tool_version(binary: str) -> str:
    """Try to get the version string of a tool."""
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True, text=True, timeout=10,
        )
        output = (result.stdout or result.stderr or "").strip()
        # Return first line only
        return output.split("\n")[0][:80] if output else ""
    except Exception:
        return ""


def _run_tool(
    cmd: list[str],
    cwd: str | None = None,
    timeout: int = 120,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    """Run an external tool and return the result."""
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
            env=run_env,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Tool timed out: %s", " ".join(cmd))
        return subprocess.CompletedProcess(cmd, returncode=-1, stdout="", stderr="timeout")
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, returncode=-1, stdout="", stderr="not found")


# ── Base Analyzer ───────────────────────────────────────────────────────────


class BaseAnalyzer(ABC):
    """Abstract base class for all analyzers."""

    def __init__(self, root: Path):
        self.root = root

    @abstractmethod
    def is_applicable(self) -> bool:
        """Return True if this analyzer should run on the current project."""
        ...

    @abstractmethod
    def check_tools(self) -> list[ToolStatus]:
        """Return list of tool statuses for this analyzer."""
        ...

    @abstractmethod
    def run(self, changed_files: list[str] | None = None) -> list[Finding]:
        """Run analysis and return findings."""
        ...


# ── CodeQL Analyzer ─────────────────────────────────────────────────────────


class CodeQLAnalyzer(BaseAnalyzer):
    """Deep SAST via CodeQL."""

    def is_applicable(self) -> bool:
        return _tool_available("codeql")

    def check_tools(self) -> list[ToolStatus]:
        status = ToolStatus(name="CodeQL", command="codeql", stack="universal")
        status.available = _tool_available("codeql")
        return [status]

    def run(self, changed_files: list[str] | None = None) -> list[Finding]:
        if not _tool_available("codeql"):
            return []
        findings: list[Finding] = []
        result = _run_tool(
            ["codeql", "database", "analyze", "--format=json", "--output=-"],
            cwd=str(self.root),
            timeout=300,
        )
        if result.returncode == 0 and result.stdout:
            try:
                data = json.loads(result.stdout)
                for item in data if isinstance(data, list) else data.get("results", []):
                    findings.append(Finding(
                        tool="codeql",
                        severity=normalize_severity("codeql", item.get("severity", "warning")),
                        category="sast",
                        file=item.get("file", ""),
                        line=item.get("line", 0),
                        message=item.get("message", ""),
                        rule_id=item.get("ruleId", ""),
                    ))
            except (json.JSONDecodeError, KeyError):
                logger.debug("Failed to parse CodeQL output")
        return findings


# ── Semgrep Analyzer ────────────────────────────────────────────────────────


class SemgrepAnalyzer(BaseAnalyzer):
    """Fast SAST via Semgrep."""

    def is_applicable(self) -> bool:
        return _tool_available("semgrep")

    def check_tools(self) -> list[ToolStatus]:
        status = ToolStatus(name="Semgrep", command="semgrep", stack="universal")
        status.available = _tool_available("semgrep")
        return [status]

    def run(self, changed_files: list[str] | None = None) -> list[Finding]:
        if not _tool_available("semgrep"):
            return []
        findings: list[Finding] = []
        cmd = ["semgrep", "--json", "--config=auto", "--quiet"]
        if changed_files:
            cmd.extend(changed_files)
        else:
            cmd.append(str(self.root))
        result = _run_tool(cmd, cwd=str(self.root), timeout=180)
        if result.stdout:
            try:
                data = json.loads(result.stdout)
                for item in data.get("results", []):
                    findings.append(Finding(
                        tool="semgrep",
                        severity=normalize_severity(
                            "semgrep",
                            item.get("extra", {}).get("severity", "WARNING"),
                        ),
                        category="sast",
                        file=item.get("path", ""),
                        line=item.get("start", {}).get("line", 0),
                        column=item.get("start", {}).get("col", 0),
                        message=item.get("extra", {}).get("message", ""),
                        rule_id=item.get("check_id", ""),
                    ))
            except (json.JSONDecodeError, KeyError):
                logger.debug("Failed to parse Semgrep output")
        return findings


# ── Language Linter Analyzer ────────────────────────────────────────────────


class LanguageLinterAnalyzer(BaseAnalyzer):
    """Run language-specific linters based on detected stacks."""

    def __init__(self, root: Path):
        super().__init__(root)
        self._stacks: set[str] = set()

    def set_stacks(self, stacks: set[str]) -> None:
        self._stacks = stacks

    def is_applicable(self) -> bool:
        return len(self._stacks) > 0

    def check_tools(self) -> list[ToolStatus]:
        statuses: list[ToolStatus] = []
        for stack in sorted(self._stacks):
            linters = STACK_TOOLS.get(stack, {}).get("linters", [])
            for binary, display in linters:
                s = ToolStatus(name=display, command=binary, stack=stack)
                s.available = _tool_available(binary)
                statuses.append(s)
        return statuses

    def run(self, changed_files: list[str] | None = None) -> list[Finding]:
        findings: list[Finding] = []
        for stack in sorted(self._stacks):
            if stack == "Python":
                findings.extend(self._run_flake8(changed_files))
                findings.extend(self._run_pylint(changed_files))
                findings.extend(self._run_bandit(changed_files))
            elif stack == "JavaScript":
                findings.extend(self._run_eslint(changed_files))
            elif stack == "Go":
                findings.extend(self._run_golangci_lint(changed_files))
            elif stack == "Rust":
                findings.extend(self._run_cargo_clippy(changed_files))
        return findings

    def _run_flake8(self, changed_files: list[str] | None = None) -> list[Finding]:
        if not _tool_available("flake8"):
            return []
        cmd = ["flake8", "--format=json"]
        if changed_files:
            py_files = [f for f in changed_files if f.endswith(".py")]
            if not py_files:
                return []
            cmd.extend(py_files)
        else:
            cmd.append(".")
        result = _run_tool(cmd, cwd=str(self.root))
        findings: list[Finding] = []
        if result.stdout:
            try:
                data = json.loads(result.stdout)
                for filepath, issues in data.items():
                    for issue in issues:
                        code = issue.get("code", "")
                        severity_key = code[0] if code else "E"
                        findings.append(Finding(
                            tool="flake8",
                            severity=normalize_severity("flake8", severity_key),
                            category="lint",
                            file=filepath,
                            line=issue.get("line_number", 0),
                            column=issue.get("column_number", 0),
                            message=issue.get("text", ""),
                            rule_id=code,
                        ))
            except (json.JSONDecodeError, KeyError):
                logger.debug("Failed to parse flake8 output")
        return findings

    def _run_pylint(self, changed_files: list[str] | None = None) -> list[Finding]:
        if not _tool_available("pylint"):
            return []
        cmd = ["pylint", "--output-format=json"]
        if changed_files:
            py_files = [f for f in changed_files if f.endswith(".py")]
            if not py_files:
                return []
            cmd.extend(py_files)
        else:
            cmd.append(".")
        result = _run_tool(cmd, cwd=str(self.root))
        findings: list[Finding] = []
        if result.stdout:
            try:
                data = json.loads(result.stdout)
                for item in data:
                    findings.append(Finding(
                        tool="pylint",
                        severity=normalize_severity("pylint", item.get("type", "C")[0].upper()),
                        category="lint",
                        file=item.get("path", ""),
                        line=item.get("line", 0),
                        column=item.get("column", 0),
                        message=item.get("message", ""),
                        rule_id=item.get("message-id", ""),
                    ))
            except (json.JSONDecodeError, KeyError):
                logger.debug("Failed to parse pylint output")
        return findings

    def _run_bandit(self, changed_files: list[str] | None = None) -> list[Finding]:
        if not _tool_available("bandit"):
            return []
        cmd = ["bandit", "-f", "json"]
        if changed_files:
            py_files = [f for f in changed_files if f.endswith(".py")]
            if not py_files:
                return []
            cmd.extend(py_files)
        else:
            cmd.extend(["-r", "."])
        result = _run_tool(cmd, cwd=str(self.root))
        findings: list[Finding] = []
        output = result.stdout
        if output:
            try:
                data = json.loads(output)
                for item in data.get("results", []):
                    findings.append(Finding(
                        tool="bandit",
                        severity=normalize_severity("bandit", item.get("issue_severity", "MEDIUM")),
                        category="security",
                        file=item.get("filename", ""),
                        line=item.get("line_number", 0),
                        message=item.get("issue_text", ""),
                        rule_id=item.get("test_id", ""),
                    ))
            except (json.JSONDecodeError, KeyError):
                logger.debug("Failed to parse bandit output")
        return findings

    def _run_eslint(self, changed_files: list[str] | None = None) -> list[Finding]:
        if not _tool_available("eslint"):
            return []
        cmd = ["eslint", "--format=json"]
        if changed_files:
            js_files = [f for f in changed_files if f.endswith((".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte"))]
            if not js_files:
                return []
            cmd.extend(js_files)
        else:
            cmd.append(".")
        result = _run_tool(cmd, cwd=str(self.root))
        findings: list[Finding] = []
        if result.stdout:
            try:
                data = json.loads(result.stdout)
                for file_result in data:
                    filepath = file_result.get("filePath", "")
                    for msg in file_result.get("messages", []):
                        findings.append(Finding(
                            tool="eslint",
                            severity=normalize_severity("eslint", str(msg.get("severity", 1))),
                            category="lint",
                            file=filepath,
                            line=msg.get("line", 0),
                            column=msg.get("column", 0),
                            message=msg.get("message", ""),
                            auto_fixable=msg.get("fix") is not None,
                            rule_id=msg.get("ruleId", ""),
                        ))
            except (json.JSONDecodeError, KeyError):
                logger.debug("Failed to parse eslint output")
        return findings

    def _run_golangci_lint(self, changed_files: list[str] | None = None) -> list[Finding]:
        if not _tool_available("golangci-lint"):
            return []
        cmd = ["golangci-lint", "run", "--out-format=json"]
        if changed_files:
            go_files = [f for f in changed_files if f.endswith(".go")]
            if not go_files:
                return []
            # golangci-lint operates on packages, not individual files
        result = _run_tool(cmd, cwd=str(self.root))
        findings: list[Finding] = []
        if result.stdout:
            try:
                data = json.loads(result.stdout)
                for issue in data.get("Issues", []):
                    pos = issue.get("Pos", {})
                    findings.append(Finding(
                        tool="golangci-lint",
                        severity=normalize_severity("golangci-lint", issue.get("Severity", "warning")),
                        category="lint",
                        file=pos.get("Filename", ""),
                        line=pos.get("Line", 0),
                        column=pos.get("Column", 0),
                        message=issue.get("Text", ""),
                        rule_id=issue.get("FromLinter", ""),
                    ))
            except (json.JSONDecodeError, KeyError):
                logger.debug("Failed to parse golangci-lint output")
        return findings

    def _run_cargo_clippy(self, changed_files: list[str] | None = None) -> list[Finding]:
        if not _tool_available("cargo"):
            return []
        cmd = ["cargo", "clippy", "--message-format=json", "--quiet"]
        result = _run_tool(cmd, cwd=str(self.root), timeout=180)
        findings: list[Finding] = []
        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    if data.get("reason") == "compiler-message":
                        msg = data.get("message", {})
                        spans = msg.get("spans", [])
                        primary_span = next(
                            (s for s in spans if s.get("is_primary")),
                            spans[0] if spans else {},
                        )
                        findings.append(Finding(
                            tool="cargo_clippy",
                            severity=normalize_severity(
                                "cargo_clippy",
                                msg.get("level", "warning"),
                            ),
                            category="lint",
                            file=primary_span.get("file_name", ""),
                            line=primary_span.get("line_start", 0),
                            column=primary_span.get("column_start", 0),
                            message=msg.get("message", ""),
                            suggestion=primary_span.get("suggested_replacement", ""),
                            auto_fixable=primary_span.get("suggested_replacement") is not None,
                            rule_id=msg.get("code", {}).get("code", "") if msg.get("code") else "",
                        ))
                except (json.JSONDecodeError, KeyError):
                    continue
        return findings


# ── Type Checker Analyzer ──────────────────────────────────────────────────


class TypeCheckerAnalyzer(BaseAnalyzer):
    """Run type checkers for detected stacks."""

    def __init__(self, root: Path):
        super().__init__(root)
        self._stacks: set[str] = set()

    def set_stacks(self, stacks: set[str]) -> None:
        self._stacks = stacks

    def is_applicable(self) -> bool:
        for stack in self._stacks:
            checkers = STACK_TOOLS.get(stack, {}).get("type_checker", [])
            for binary, _ in checkers:
                if _tool_available(binary):
                    return True
        return False

    def check_tools(self) -> list[ToolStatus]:
        statuses: list[ToolStatus] = []
        for stack in sorted(self._stacks):
            for binary, display in STACK_TOOLS.get(stack, {}).get("type_checker", []):
                s = ToolStatus(name=display, command=binary, stack=stack)
                s.available = _tool_available(binary)
                statuses.append(s)
        return statuses

    def run(self, changed_files: list[str] | None = None) -> list[Finding]:
        findings: list[Finding] = []
        for stack in sorted(self._stacks):
            if stack == "Python":
                findings.extend(self._run_mypy(changed_files))
            elif stack == "JavaScript":
                findings.extend(self._run_tsc(changed_files))
            elif stack == "Go":
                findings.extend(self._run_go_vet(changed_files))
        return findings

    def _run_mypy(self, changed_files: list[str] | None = None) -> list[Finding]:
        if not _tool_available("mypy"):
            return []
        cmd = ["mypy", "--no-error-summary", "--show-column-numbers"]
        if changed_files:
            py_files = [f for f in changed_files if f.endswith(".py")]
            if not py_files:
                return []
            cmd.extend(py_files)
        else:
            cmd.append(".")
        result = _run_tool(cmd, cwd=str(self.root), timeout=120)
        findings: list[Finding] = []
        for line in (result.stdout or "").split("\n"):
            # Format: file.py:line:col: severity: message
            parts = line.split(":", 4)
            if len(parts) >= 5:
                severity_msg = parts[3].strip()
                severity_key = severity_msg.split()[0] if severity_msg else "error"
                findings.append(Finding(
                    tool="mypy",
                    severity=normalize_severity("mypy", severity_key),
                    category="type_check",
                    file=parts[0].strip(),
                    line=int(parts[1]) if parts[1].strip().isdigit() else 0,
                    column=int(parts[2]) if parts[2].strip().isdigit() else 0,
                    message=parts[4].strip() if len(parts) > 4 else "",
                ))
        return findings

    def _run_tsc(self, changed_files: list[str] | None = None) -> list[Finding]:
        if not _tool_available("tsc"):
            return []
        cmd = ["tsc", "--noEmit", "--pretty", "false"]
        result = _run_tool(cmd, cwd=str(self.root), timeout=120)
        findings: list[Finding] = []
        for line in (result.stdout or "").split("\n"):
            # Format: file.ts(line,col): error TS1234: message
            if "(" in line and "): " in line:
                try:
                    file_part, rest = line.split("(", 1)
                    pos_part, msg_part = rest.split("): ", 1)
                    line_num, col_num = pos_part.split(",")
                    severity_key = "error" if msg_part.startswith("error") else "warning"
                    findings.append(Finding(
                        tool="tsc",
                        severity=normalize_severity("tsc", severity_key),
                        category="type_check",
                        file=file_part.strip(),
                        line=int(line_num),
                        column=int(col_num),
                        message=msg_part.strip(),
                    ))
                except (ValueError, IndexError):
                    continue
        return findings

    def _run_go_vet(self, changed_files: list[str] | None = None) -> list[Finding]:
        if not _tool_available("go"):
            return []
        cmd = ["go", "vet", "./..."]
        result = _run_tool(cmd, cwd=str(self.root))
        findings: list[Finding] = []
        for line in (result.stderr or "").split("\n"):
            # Format: file.go:line:col: message
            parts = line.split(":", 3)
            if len(parts) >= 4 and parts[1].strip().isdigit():
                findings.append(Finding(
                    tool="go_vet",
                    severity="medium",
                    category="type_check",
                    file=parts[0].strip(),
                    line=int(parts[1]),
                    column=int(parts[2]) if parts[2].strip().isdigit() else 0,
                    message=parts[3].strip() if len(parts) > 3 else "",
                ))
        return findings


# ── Dependency Vulnerability Analyzer ──────────────────────────────────────


class DependencyVulnAnalyzer(BaseAnalyzer):
    """Audit dependencies for known vulnerabilities."""

    def __init__(self, root: Path):
        super().__init__(root)
        self._stacks: set[str] = set()

    def set_stacks(self, stacks: set[str]) -> None:
        self._stacks = stacks

    def is_applicable(self) -> bool:
        return len(self._stacks) > 0

    def check_tools(self) -> list[ToolStatus]:
        statuses: list[ToolStatus] = []
        for stack in sorted(self._stacks):
            for binary, display in STACK_TOOLS.get(stack, {}).get("dep_audit", []):
                s = ToolStatus(name=display, command=binary, stack=stack)
                s.available = _tool_available(binary)
                statuses.append(s)
        # Trivy (universal)
        for binary, display in UNIVERSAL_TOOLS.get("dep_audit_universal", []):
            s = ToolStatus(name=display, command=binary, stack="universal")
            s.available = _tool_available(binary)
            statuses.append(s)
        return statuses

    def run(self, changed_files: list[str] | None = None) -> list[Finding]:
        findings: list[Finding] = []
        for stack in sorted(self._stacks):
            if stack == "Python":
                findings.extend(self._run_pip_audit())
            elif stack == "JavaScript":
                findings.extend(self._run_npm_audit())
            elif stack == "Go":
                findings.extend(self._run_govulncheck())
            elif stack == "Rust":
                findings.extend(self._run_cargo_audit())
        # Universal fallback
        findings.extend(self._run_trivy())
        return findings

    def _run_pip_audit(self) -> list[Finding]:
        if not _tool_available("pip-audit"):
            return []
        cmd = ["pip-audit", "--format=json", "--desc"]
        result = _run_tool(cmd, cwd=str(self.root))
        findings: list[Finding] = []
        if result.stdout:
            try:
                data = json.loads(result.stdout)
                for vuln in data.get("dependencies", []):
                    for v in vuln.get("vulns", []):
                        findings.append(Finding(
                            tool="pip-audit",
                            severity=normalize_severity("pip-audit", v.get("fix_versions", [""])[0] if v.get("fix_versions") else "MEDIUM"),
                            category="dependency",
                            file="requirements.txt",
                            message=f"{vuln.get('name', '')} {vuln.get('version', '')}: {v.get('id', '')} - {v.get('description', '')}",
                            rule_id=v.get("id", ""),
                        ))
            except (json.JSONDecodeError, KeyError):
                logger.debug("Failed to parse pip-audit output")
        return findings

    def _run_npm_audit(self) -> list[Finding]:
        if not _tool_available("npm"):
            return []
        if not (self.root / "package-lock.json").exists() and not (self.root / "package.json").exists():
            return []
        cmd = ["npm", "audit", "--json"]
        result = _run_tool(cmd, cwd=str(self.root))
        findings: list[Finding] = []
        if result.stdout:
            try:
                data = json.loads(result.stdout)
                vulns = data.get("vulnerabilities", {})
                for pkg_name, info in vulns.items():
                    findings.append(Finding(
                        tool="npm_audit",
                        severity=normalize_severity("trivy", info.get("severity", "MEDIUM").upper()),
                        category="dependency",
                        file="package.json",
                        message=f"{pkg_name}: {info.get('title', info.get('via', [''])[0] if isinstance(info.get('via', []), list) and info.get('via') else '')}",
                        rule_id=pkg_name,
                    ))
            except (json.JSONDecodeError, KeyError):
                logger.debug("Failed to parse npm audit output")
        return findings

    def _run_govulncheck(self) -> list[Finding]:
        if not _tool_available("govulncheck"):
            return []
        cmd = ["govulncheck", "-json", "./..."]
        result = _run_tool(cmd, cwd=str(self.root))
        findings: list[Finding] = []
        if result.stdout:
            try:
                for line in result.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    if "vulnerability" in data:
                        v = data["vulnerability"]
                        findings.append(Finding(
                            tool="govulncheck",
                            severity="high",
                            category="dependency",
                            file="go.mod",
                            message=f"{v.get('id', '')}: {v.get('details', '')}",
                            rule_id=v.get("id", ""),
                        ))
            except (json.JSONDecodeError, KeyError):
                logger.debug("Failed to parse govulncheck output")
        return findings

    def _run_cargo_audit(self) -> list[Finding]:
        if not _tool_available("cargo"):
            return []
        cmd = ["cargo", "audit", "--json"]
        result = _run_tool(cmd, cwd=str(self.root))
        findings: list[Finding] = []
        if result.stdout:
            try:
                data = json.loads(result.stdout)
                for vuln in data.get("vulnerabilities", {}).get("list", []):
                    advisory = vuln.get("advisory", {})
                    findings.append(Finding(
                        tool="cargo_audit",
                        severity="high",
                        category="dependency",
                        file="Cargo.toml",
                        message=f"{advisory.get('id', '')}: {advisory.get('title', '')}",
                        rule_id=advisory.get("id", ""),
                    ))
            except (json.JSONDecodeError, KeyError):
                logger.debug("Failed to parse cargo audit output")
        return findings

    def _run_trivy(self) -> list[Finding]:
        if not _tool_available("trivy"):
            return []
        cmd = ["trivy", "fs", "--format=json", "--scanners=vuln", str(self.root)]
        result = _run_tool(cmd, cwd=str(self.root), timeout=180)
        findings: list[Finding] = []
        if result.stdout:
            try:
                data = json.loads(result.stdout)
                for res in data.get("Results", []):
                    for vuln in res.get("Vulnerabilities", []):
                        findings.append(Finding(
                            tool="trivy",
                            severity=normalize_severity("trivy", vuln.get("Severity", "MEDIUM")),
                            category="dependency",
                            file=res.get("Target", ""),
                            message=f"{vuln.get('VulnerabilityID', '')}: {vuln.get('Title', '')} ({vuln.get('PkgName', '')} {vuln.get('InstalledVersion', '')})",
                            rule_id=vuln.get("VulnerabilityID", ""),
                        ))
            except (json.JSONDecodeError, KeyError):
                logger.debug("Failed to parse trivy output")
        return findings


# ── Secret Scanner Analyzer ────────────────────────────────────────────────


class SecretScannerAnalyzer(BaseAnalyzer):
    """Scan for leaked secrets and credentials."""

    def is_applicable(self) -> bool:
        return _tool_available("gitleaks") or _tool_available("trufflehog")

    def check_tools(self) -> list[ToolStatus]:
        statuses: list[ToolStatus] = []
        for binary, display in UNIVERSAL_TOOLS.get("secrets", []):
            s = ToolStatus(name=display, command=binary, stack="universal")
            s.available = _tool_available(binary)
            statuses.append(s)
        return statuses

    def run(self, changed_files: list[str] | None = None) -> list[Finding]:
        findings: list[Finding] = []
        findings.extend(self._run_gitleaks())
        findings.extend(self._run_trufflehog())
        return findings

    def _run_gitleaks(self) -> list[Finding]:
        if not _tool_available("gitleaks"):
            return []
        cmd = ["gitleaks", "detect", "--report-format=json", "--report-path=/dev/stdout", "--no-git"]
        result = _run_tool(cmd, cwd=str(self.root))
        findings: list[Finding] = []
        if result.stdout:
            try:
                data = json.loads(result.stdout)
                if isinstance(data, list):
                    for item in data:
                        findings.append(Finding(
                            tool="gitleaks",
                            severity=normalize_severity(
                                "gitleaks",
                                item.get("Severity", "HIGH"),
                            ),
                            category="secret",
                            file=item.get("File", ""),
                            line=item.get("StartLine", 0),
                            message=f"Secret detected: {item.get('Description', '')} (rule: {item.get('RuleID', '')})",
                            rule_id=item.get("RuleID", ""),
                        ))
            except (json.JSONDecodeError, KeyError):
                logger.debug("Failed to parse gitleaks output")
        return findings

    def _run_trufflehog(self) -> list[Finding]:
        if not _tool_available("trufflehog"):
            return []
        cmd = ["trufflehog", "filesystem", "--json", str(self.root)]
        result = _run_tool(cmd, cwd=str(self.root), timeout=180)
        findings: list[Finding] = []
        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    findings.append(Finding(
                        tool="trufflehog",
                        severity=normalize_severity(
                            "trufflehog",
                            data.get("Severity", "HIGH"),
                        ),
                        category="secret",
                        file=data.get("SourceMetadata", {}).get("Data", {}).get("Filesystem", {}).get("file", ""),
                        message=f"Secret detected: {data.get('DetectorName', '')}",
                        rule_id=data.get("DetectorName", ""),
                    ))
                except (json.JSONDecodeError, KeyError):
                    continue
        return findings


# ── Complexity Analyzer ────────────────────────────────────────────────────


class ComplexityAnalyzer(BaseAnalyzer):
    """Analyze code complexity with radon, vulture, etc."""

    def __init__(self, root: Path):
        super().__init__(root)
        self._stacks: set[str] = set()

    def set_stacks(self, stacks: set[str]) -> None:
        self._stacks = stacks

    def is_applicable(self) -> bool:
        if "Python" in self._stacks:
            return _tool_available("radon") or _tool_available("vulture")
        return False

    def check_tools(self) -> list[ToolStatus]:
        statuses: list[ToolStatus] = []
        if "Python" in self._stacks:
            for binary, display in STACK_TOOLS.get("Python", {}).get("complexity", []):
                s = ToolStatus(name=display, command=binary, stack="Python")
                s.available = _tool_available(binary)
                statuses.append(s)
        return statuses

    def run(self, changed_files: list[str] | None = None) -> list[Finding]:
        findings: list[Finding] = []
        if "Python" in self._stacks:
            findings.extend(self._run_radon(changed_files))
            findings.extend(self._run_vulture(changed_files))
        return findings

    def _run_radon(self, changed_files: list[str] | None = None) -> list[Finding]:
        if not _tool_available("radon"):
            return []
        cmd = ["radon", "cc", "--json", "--min=C"]
        if changed_files:
            py_files = [f for f in changed_files if f.endswith(".py")]
            if not py_files:
                return []
            cmd.extend(py_files)
        else:
            cmd.append(".")
        result = _run_tool(cmd, cwd=str(self.root))
        findings: list[Finding] = []
        if result.stdout:
            try:
                data = json.loads(result.stdout)
                for filepath, blocks in data.items():
                    for block in blocks:
                        findings.append(Finding(
                            tool="radon",
                            severity=normalize_severity("radon", block.get("rank", "C")),
                            category="complexity",
                            file=filepath,
                            line=block.get("lineno", 0),
                            message=f"{block.get('type', '')} {block.get('name', '')}: complexity {block.get('complexity', '?')} (rank {block.get('rank', '?')})",
                            rule_id=f"cc-{block.get('rank', '?')}",
                        ))
            except (json.JSONDecodeError, KeyError):
                logger.debug("Failed to parse radon output")
        return findings

    def _run_vulture(self, changed_files: list[str] | None = None) -> list[Finding]:
        if not _tool_available("vulture"):
            return []
        cmd = ["vulture"]
        if changed_files:
            py_files = [f for f in changed_files if f.endswith(".py")]
            if not py_files:
                return []
            cmd.extend(py_files)
        else:
            cmd.append(".")
        result = _run_tool(cmd, cwd=str(self.root))
        findings: list[Finding] = []
        for line in (result.stdout or "").split("\n"):
            if not line.strip():
                continue
            # Format: file.py:line: unused X 'name' (confidence NN%)
            parts = line.split(":", 2)
            if len(parts) >= 3:
                findings.append(Finding(
                    tool="vulture",
                    severity="low",
                    category="complexity",
                    file=parts[0].strip(),
                    line=int(parts[1]) if parts[1].strip().isdigit() else 0,
                    message=parts[2].strip(),
                    rule_id="dead-code",
                ))
        return findings


# ── AI Code Review Analyzer (placeholder) ──────────────────────────────────


class AICodeReviewAnalyzer(BaseAnalyzer):
    """Placeholder for AI-powered code review integration."""

    def __init__(self, root: Path):
        super().__init__(root)
        self._findings: list[Finding] = []

    def set_findings(self, findings: list[Finding]) -> None:
        """Accept externally-generated findings (e.g., from Claude)."""
        self._findings = findings

    def is_applicable(self) -> bool:
        return len(self._findings) > 0

    def check_tools(self) -> list[ToolStatus]:
        return [ToolStatus(name="AI Code Review", command="n/a", available=True, stack="universal")]

    def run(self, changed_files: list[str] | None = None) -> list[Finding]:
        return self._findings


# ── Analyzer Registry ──────────────────────────────────────────────────────

ALL_ANALYZERS = [
    CodeQLAnalyzer,
    SemgrepAnalyzer,
    LanguageLinterAnalyzer,
    TypeCheckerAnalyzer,
    DependencyVulnAnalyzer,
    SecretScannerAnalyzer,
    ComplexityAnalyzer,
    AICodeReviewAnalyzer,
]

LAYER_NAMES: dict[str, str] = {
    "sast": "Static Application Security Testing",
    "lint": "Linting",
    "type_check": "Type Checking",
    "dependency": "Dependency Vulnerability Audit",
    "secret": "Secret Scanning",
    "complexity": "Complexity Analysis",
    "security": "Security Analysis",
    "ai_review": "AI Code Review",
}


def create_analyzers(root: Path, stacks: set[str] | None = None) -> list[BaseAnalyzer]:
    """Create and configure all applicable analyzers."""
    if stacks is None:
        stacks = detect_active_stacks(root)

    analyzers: list[BaseAnalyzer] = []
    for cls in ALL_ANALYZERS:
        analyzer = cls(root)
        # Inject stacks for analyzers that need them
        if hasattr(analyzer, "set_stacks"):
            analyzer.set_stacks(stacks)
        if analyzer.is_applicable():
            analyzers.append(analyzer)
    return analyzers


# ── Scan Orchestrator ──────────────────────────────────────────────────────


def scan(
    root: Path,
    changed_files: list[str] | None = None,
    stacks: set[str] | None = None,
) -> dict:
    """Run all applicable analyzers and return structured results."""
    root = root.resolve()
    if stacks is None:
        stacks = detect_active_stacks(root)

    analyzers = create_analyzers(root, stacks)
    all_findings: list[Finding] = []
    tool_statuses: list[ToolStatus] = []
    errors: list[str] = []

    for analyzer in analyzers:
        tool_statuses.extend(analyzer.check_tools())
        try:
            findings = analyzer.run(changed_files)
            all_findings.extend(findings)
        except Exception as e:
            errors.append(f"{analyzer.__class__.__name__}: {e}")
            logger.warning("Analyzer %s failed: %s", analyzer.__class__.__name__, e)

    # Sort findings by severity
    all_findings.sort(key=lambda f: SEVERITY_ORDER.get(f.severity, 99))

    # Group by severity
    by_severity: dict[str, int] = {}
    for f in all_findings:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1

    # Group by tool
    by_tool: dict[str, int] = {}
    for f in all_findings:
        by_tool[f.tool] = by_tool.get(f.tool, 0) + 1

    return {
        "findings": [f.to_dict() for f in all_findings],
        "summary": {
            "total": len(all_findings),
            "by_severity": by_severity,
            "by_tool": by_tool,
            "stacks": sorted(stacks),
        },
        "tools": [asdict(t) for t in tool_statuses],
        "errors": errors,
    }


# ── CLI ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Multi-tool local analysis engine",
    )
    subparsers = parser.add_subparsers(dest="command")

    # scan
    scan_p = subparsers.add_parser("scan", help="Run all applicable analyzers")
    scan_p.add_argument("--root", default=".", help="Project root directory")
    scan_p.add_argument("--files", nargs="*", help="Specific files to scan")
    scan_p.add_argument("--json", action="store_true", help="Output as JSON")

    # check
    check_p = subparsers.add_parser("check", help="Check available tools")
    check_p.add_argument("--root", default=".", help="Project root directory")
    check_p.add_argument("--json", action="store_true", help="Output as JSON")

    # install-guide
    guide_p = subparsers.add_parser("install-guide", help="Show install commands for missing tools")
    guide_p.add_argument("--root", default=".", help="Project root directory")

    args = parser.parse_args()

    if args.command == "scan":
        root = Path(args.root).resolve()
        result = scan(root, changed_files=args.files)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            total = result["summary"]["total"]
            print(f"Findings: {total}")
            for sev, count in sorted(
                result["summary"]["by_severity"].items(),
                key=lambda x: SEVERITY_ORDER.get(x[0], 99),
            ):
                print(f"  {sev}: {count}")
            if result["errors"]:
                print(f"\nErrors: {len(result['errors'])}")
                for err in result["errors"]:
                    print(f"  - {err}")
        sys.exit(1 if result["summary"].get("by_severity", {}).get("critical", 0) > 0 else 0)

    elif args.command == "check":
        root = Path(args.root).resolve()
        stacks = detect_active_stacks(root)
        statuses = check_tool_availability(stacks)
        if args.json:
            print(json.dumps([asdict(s) for s in statuses], indent=2))
        else:
            print(f"Detected stacks: {', '.join(sorted(stacks))}\n")
            for s in statuses:
                icon = "[ok]" if s.available else "[--]"
                print(f"  {icon} {s.name} ({s.command}) [{s.stack}]")

    elif args.command == "install-guide":
        root = Path(args.root).resolve()
        stacks = detect_active_stacks(root)
        statuses = check_tool_availability(stacks)
        missing = [s for s in statuses if not s.available]
        if not missing:
            print("All tools are installed.")
        else:
            print("Missing tools and install commands:\n")
            for s in missing:
                guide = INSTALL_GUIDE.get(s.command, f"# No install guide for {s.command}")
                print(f"  {s.name} ({s.stack}):")
                print(f"    {guide}\n")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
