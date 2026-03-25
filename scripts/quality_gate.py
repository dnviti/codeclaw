"""Quality gate orchestrator.

Runs the local analysis engine, applies auto-fixes when possible,
re-verifies, and produces a pass/fail dashboard. Designed to be
invoked from skill steps, hooks, and CI.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Allow imports from sibling packages
sys.path.insert(0, str(Path(__file__).resolve().parent))

from local_analyzers import (
    SEVERITY_ORDER,
    Finding,
    create_analyzers,
    detect_active_stacks,
    scan,
)
from analyzers import load_gitignore_patterns

# ── Default Configuration ──────────────────────────────────────────────────

DEFAULT_CONFIG: dict = {
    "enabled": True,
    "fail_on": ["critical", "high"],
    "auto_fix": True,
    "max_fix_iterations": 3,
    "skip_tools": [],
    "extra_args": {},
}


def load_config(config_path: str | None, root: Path) -> dict:
    """Load quality gate configuration from project-config.json or a given path."""
    config = dict(DEFAULT_CONFIG)

    # Try project-config.json first
    project_config_path = root / ".claude" / "project-config.json"
    if config_path:
        project_config_path = Path(config_path)

    if project_config_path.exists():
        try:
            with open(project_config_path) as f:
                data = json.load(f)
            gate_config = data.get("quality_gate", {})
            config.update({k: v for k, v in gate_config.items() if k in DEFAULT_CONFIG})
        except (json.JSONDecodeError, OSError):
            pass

    return config


def _apply_auto_fixes(
    findings: list[dict],
    root: Path,
    changed_files: list[str] | None = None,
) -> int:
    """Attempt to auto-fix findings where tools support it.

    Returns the number of fixes applied.
    """
    fixes_applied = 0

    # Check for auto-fixable findings
    fixable_tools: dict[str, list[dict]] = {}
    for f in findings:
        if f.get("auto_fixable"):
            tool = f.get("tool", "")
            fixable_tools.setdefault(tool, []).append(f)

    # Run auto-fix commands for known tools
    for tool, tool_findings in fixable_tools.items():
        try:
            if tool == "eslint":
                cmd = ["eslint", "--fix"]
                files = list({f["file"] for f in tool_findings if f.get("file")})
                if files:
                    cmd.extend(files)
                    result = subprocess.run(
                        cmd, capture_output=True, text=True,
                        cwd=str(root), timeout=60,
                    )
                    if result.returncode == 0:
                        fixes_applied += len(tool_findings)
            elif tool == "black":
                cmd = ["black"]
                files = list({f["file"] for f in tool_findings if f.get("file")})
                if files:
                    cmd.extend(files)
                    result = subprocess.run(
                        cmd, capture_output=True, text=True,
                        cwd=str(root), timeout=60,
                    )
                    if result.returncode == 0:
                        fixes_applied += len(tool_findings)
            elif tool == "prettier":
                cmd = ["prettier", "--write"]
                files = list({f["file"] for f in tool_findings if f.get("file")})
                if files:
                    cmd.extend(files)
                    result = subprocess.run(
                        cmd, capture_output=True, text=True,
                        cwd=str(root), timeout=60,
                    )
                    if result.returncode == 0:
                        fixes_applied += len(tool_findings)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    return fixes_applied


def _run_verify(root: Path, verify_command: str) -> tuple[bool, str]:
    """Run the project's verify command. Returns (success, output)."""
    if not verify_command:
        return True, ""
    try:
        result = subprocess.run(
            verify_command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=300,
        )
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0, output.strip()
    except subprocess.TimeoutExpired:
        return False, "Verify command timed out"
    except OSError as e:
        return False, f"Verify command failed: {e}"


def format_dashboard(
    results: dict,
    iterations: int,
    max_iterations: int,
) -> str:
    """Format scan results as a human-readable dashboard."""
    lines: list[str] = []
    summary = results.get("summary", {})
    total = summary.get("total", 0)
    by_severity = summary.get("by_severity", {})
    by_tool = summary.get("by_tool", {})
    stacks = summary.get("stacks", [])

    lines.append("=" * 60)
    lines.append("QUALITY GATE DASHBOARD")
    lines.append("=" * 60)
    lines.append(f"Iteration: {iterations}/{max_iterations}")
    lines.append(f"Stacks: {', '.join(stacks) if stacks else 'none detected'}")
    lines.append(f"Total findings: {total}")
    lines.append("")

    if by_severity:
        lines.append("By severity:")
        for sev in sorted(by_severity, key=lambda s: SEVERITY_ORDER.get(s, 99)):
            count = by_severity[sev]
            marker = " ** BLOCKING **" if sev in ("critical", "high") else ""
            lines.append(f"  {sev}: {count}{marker}")
        lines.append("")

    if by_tool:
        lines.append("By tool:")
        for tool, count in sorted(by_tool.items()):
            lines.append(f"  {tool}: {count}")
        lines.append("")

    # Available/unavailable tools
    tools = results.get("tools", [])
    available = [t for t in tools if t.get("available")]
    unavailable = [t for t in tools if not t.get("available")]
    if available:
        lines.append(f"Tools used: {len(available)}")
    if unavailable:
        lines.append(f"Tools unavailable: {len(unavailable)} (run install-guide for details)")
    lines.append("")

    errors = results.get("errors", [])
    if errors:
        lines.append(f"Errors: {len(errors)}")
        for err in errors:
            lines.append(f"  - {err}")
        lines.append("")

    # Pass/fail determination
    blocking = sum(
        by_severity.get(sev, 0)
        for sev in ("critical", "high")
    )
    if blocking > 0:
        lines.append(f"RESULT: FAIL ({blocking} blocking finding(s))")
    else:
        lines.append("RESULT: PASS")

    lines.append("=" * 60)
    return "\n".join(lines)


def run_quality_gate(
    root: Path,
    changed_files: list[str] | None = None,
    config_path: str | None = None,
    verify_command: str = "",
    fix: bool = True,
    max_iterations: int = 3,
) -> dict:
    """Run the full quality gate pipeline with iterative fix loop.

    Returns:
        dict with keys: passed, findings, summary, iterations, dashboard, verify_result
    """
    root = root.resolve()
    config = load_config(config_path, root)

    if not config.get("enabled", True):
        return {
            "passed": True,
            "findings": [],
            "summary": {"total": 0, "by_severity": {}, "by_tool": {}, "stacks": []},
            "iterations": 0,
            "dashboard": "Quality gate disabled.",
            "verify_result": {"success": True, "output": ""},
        }

    effective_max = min(
        max_iterations,
        config.get("max_fix_iterations", 3),
    )
    fail_on = set(config.get("fail_on", ["critical", "high"]))
    do_fix = fix and config.get("auto_fix", True)

    iterations = 0
    results: dict = {}
    fixes_total = 0

    for iteration in range(1, effective_max + 1):
        iterations = iteration

        # Run scan
        results = scan(root, changed_files=changed_files)

        # Check for blocking findings
        by_severity = results.get("summary", {}).get("by_severity", {})
        blocking = sum(by_severity.get(sev, 0) for sev in fail_on)

        if blocking == 0:
            break

        # Try auto-fix if enabled and not last iteration
        if do_fix and iteration < effective_max:
            fixes = _apply_auto_fixes(results.get("findings", []), root, changed_files)
            fixes_total += fixes
            if fixes == 0:
                # No fixes applied, no point retrying
                break
        else:
            break

    # Run verify command
    verify_success, verify_output = _run_verify(root, verify_command)

    # Final determination
    by_severity = results.get("summary", {}).get("by_severity", {})
    blocking = sum(by_severity.get(sev, 0) for sev in fail_on)
    passed = blocking == 0 and verify_success

    dashboard = format_dashboard(results, iterations, effective_max)

    return {
        "passed": passed,
        "findings": results.get("findings", []),
        "summary": results.get("summary", {}),
        "iterations": iterations,
        "fixes_applied": fixes_total,
        "dashboard": dashboard,
        "verify_result": {
            "success": verify_success,
            "output": verify_output,
        },
    }


# ── CLI ─────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Quality gate orchestrator")
    parser.add_argument("--root", default=".", help="Project root directory")
    parser.add_argument("--files", nargs="*", help="Specific changed files to scan")
    parser.add_argument("--config", help="Path to config file")
    parser.add_argument("--verify-command", default="", help="Verify command to run")
    parser.add_argument("--no-fix", action="store_true", help="Disable auto-fix")
    parser.add_argument("--max-iterations", type=int, default=3, help="Max fix iterations")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()
    root = Path(args.root).resolve()

    result = run_quality_gate(
        root=root,
        changed_files=args.files,
        config_path=args.config,
        verify_command=args.verify_command,
        fix=not args.no_fix,
        max_iterations=args.max_iterations,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(result["dashboard"])

    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
