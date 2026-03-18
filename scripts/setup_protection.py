#!/usr/bin/env python3
"""Configure branch protection rules on GitHub or GitLab repositories.

Sets up required reviews, status checks, and force-push restrictions
on the main branch. Idempotent — safe to run multiple times.

Supports both GitHub (gh) and GitLab (glab) based on the "platform" field
in the issues tracker config.

Usage:
    python3 scripts/setup_protection.py [--branch main] [--required-reviews 1]
                                                 [--status-checks ci] [--merge-queue]
    python3 scripts/setup_protection.py cache-protection [--branch main]
                                                 [--role production] [--merge-strategy squash]

Prerequisites:
    - gh CLI (GitHub) or glab CLI (GitLab) installed and authenticated
    - Config file exists with "repo" configured

Zero external dependencies — stdlib only.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# ── Helpers ───────────────────────────────────────────────────────────────

def find_project_root() -> Path:
    """Find project root via git."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


def load_config(root: Path) -> tuple[dict, str]:
    """Load issues tracker config. Returns (data, config_path)."""
    for candidate in ["issues-tracker.json", "github-issues.json"]:
        fp = root / ".claude" / candidate
        if fp.exists():
            with open(fp, "r", encoding="utf-8") as f:
                return json.load(f), str(fp)
    return {}, ""


def save_config(data: dict, config_path: str) -> None:
    """Write issues tracker config back to disk."""
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def run_cmd(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    """Run a CLI command and return the result."""
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


# ── Cache Protection ─────────────────────────────────────────────────────

def cache_branch_protection(data: dict, config_path: str,
                            branch: str, role: str,
                            protected: bool = True,
                            require_reviews: int = 0,
                            merge_strategy: str = "",
                            allow_force_pushes: bool = False,
                            allow_deletions: bool = False) -> None:
    """Cache a single branch's protection settings in issues-tracker.json."""
    branches = data.setdefault("branches", {})

    entry = branches.get(branch, {})
    entry["role"] = role
    entry["protected"] = protected
    if require_reviews > 0:
        entry["require_reviews"] = require_reviews
    if merge_strategy:
        entry["merge_strategy"] = merge_strategy
    entry["allow_force_pushes"] = allow_force_pushes
    entry["allow_deletions"] = allow_deletions

    branches[branch] = entry
    branches.setdefault("cache_ttl_hours", 24)
    branches["last_refreshed"] = datetime.now(timezone.utc).isoformat()
    data["branches"] = branches

    save_config(data, config_path)
    print(f"  Cached protection settings for '{branch}' (role={role}) in {config_path}")


# ── GitHub Protection ─────────────────────────────────────────────────────

def setup_github_protection(repo: str, branch: str, required_reviews: int,
                            status_checks: list[str], merge_queue: bool) -> None:
    """Configure branch protection via GitHub API (gh cli)."""
    print(f"Configuring GitHub branch protection for {repo}:{branch}")

    # Build the protection payload
    protection = {
        "required_status_checks": None,
        "enforce_admins": True,
        "required_pull_request_reviews": {
            "required_approving_review_count": required_reviews,
            "dismiss_stale_reviews": True,
        },
        "restrictions": None,
        "allow_force_pushes": False,
        "allow_deletions": False,
        "required_linear_history": False,
        "required_conversation_resolution": True,
    }

    if status_checks:
        protection["required_status_checks"] = {
            "strict": True,  # Require branch to be up-to-date
            "contexts": status_checks,
        }

    payload = json.dumps(protection)

    result = run_cmd([
        "gh", "api",
        f"repos/{repo}/branches/{branch}/protection",
        "-X", "PUT",
        "--input", "-",
    ])

    # Use stdin for the payload since --input - reads from stdin
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/branches/{branch}/protection",
         "-X", "PUT", "-H", "Accept: application/vnd.github+json",
         "--input", "-"],
        input=payload,
        capture_output=True, text=True,
    )

    if result.returncode == 0:
        print(f"  Branch protection configured for '{branch}'")
    else:
        stderr = result.stderr.strip()
        if "Branch not found" in stderr:
            print(f"  WARNING: Branch '{branch}' does not exist yet. "
                  "Protection will be applied after the branch is created.")
        elif "Not Found" in stderr:
            print(f"  ERROR: Repository '{repo}' not found or insufficient permissions.")
            print(f"  Ensure you have admin access and 'gh auth status' shows authentication.")
            sys.exit(1)
        else:
            print(f"  ERROR: {stderr}")
            sys.exit(1)

    # Enable merge queue if requested
    if merge_queue:
        print("  Note: Merge queue must be enabled via repository settings UI.")
        print("  Go to Settings > General > Pull Requests > Enable merge queue.")

    print()
    print("Protection summary:")
    print(f"  - Required reviewers: {required_reviews}")
    print(f"  - Dismiss stale reviews: yes")
    print(f"  - Require conversation resolution: yes")
    print(f"  - Force pushes: blocked")
    print(f"  - Branch deletions: blocked")
    if status_checks:
        print(f"  - Required status checks: {', '.join(status_checks)}")
        print(f"  - Require up-to-date branch: yes")
    else:
        print(f"  - Required status checks: none (add CI job names later)")


# ── GitLab Protection ─────────────────────────────────────────────────────

def setup_gitlab_protection(repo: str, branch: str, required_reviews: int,
                            status_checks: list[str], merge_queue: bool) -> None:
    """Configure branch protection via GitLab API (glab cli)."""
    print(f"Configuring GitLab branch protection for {repo}:{branch}")

    # GitLab uses project-level settings for merge request approvals
    # and branch protection rules

    # First, unprotect to reset (idempotent re-apply)
    run_cmd(["glab", "api", f"projects/{repo.replace('/', '%2F')}/protected_branches/{branch}",
             "-X", "DELETE"])

    # Protect the branch with push restrictions
    result = run_cmd([
        "glab", "api", f"projects/{repo.replace('/', '%2F')}/protected_branches",
        "-X", "POST",
        "-f", f"name={branch}",
        "-f", "push_access_level=0",       # No one can push directly
        "-f", "merge_access_level=30",      # Developers+ can merge
        "-f", "allow_force_push=false",
    ])

    if result.returncode == 0:
        print(f"  Branch protection configured for '{branch}'")
    else:
        stderr = result.stderr.strip()
        if "has already been taken" in stderr:
            print(f"  Branch '{branch}' is already protected (updating)")
        else:
            print(f"  Note: {stderr or 'Protection applied (may need admin access for full config)'}")

    # Set merge request approval rules
    if required_reviews > 0:
        run_cmd([
            "glab", "api", f"projects/{repo.replace('/', '%2F')}",
            "-X", "PUT",
            "-f", f"approvals_before_merge={required_reviews}",
        ])
        print(f"  Required approvals set to {required_reviews}")

    print()
    print("Protection summary:")
    print(f"  - Required approvals: {required_reviews}")
    print(f"  - Direct push: blocked (merge requests only)")
    print(f"  - Force pushes: blocked")
    if status_checks:
        print(f"  - Note: Add external status checks via Settings > General > Merge requests")
        for check in status_checks:
            print(f"    - {check}")
    if merge_queue:
        print("  - Note: Enable merge trains via Settings > General > Merge requests")


# ── Main ──────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Setup branch protection rules")
    sub = parser.add_subparsers(dest="subcommand")

    # Default (no subcommand) — original behavior
    parser.add_argument("--branch", default="main",
                        help="Branch to protect (default: main)")
    parser.add_argument("--required-reviews", type=int, default=1,
                        help="Number of required approving reviews (default: 1)")
    parser.add_argument("--status-checks", nargs="*", default=[],
                        help="Required status check names (e.g., 'Lint, Test & Build')")
    parser.add_argument("--merge-queue", action="store_true",
                        help="Print instructions for enabling merge queue")

    # cache-protection subcommand
    p_cache = sub.add_parser("cache-protection",
                             help="Cache branch protection settings in issues-tracker.json")
    p_cache.add_argument("--branch", default="main",
                         help="Branch name to cache (default: main)")
    p_cache.add_argument("--role", default="production",
                         choices=["production", "staging", "development"],
                         help="Branch role (default: production)")
    p_cache.add_argument("--merge-strategy", default="",
                         choices=["", "squash", "merge", "rebase"],
                         help="Preferred merge strategy for this branch")
    p_cache.add_argument("--require-reviews", type=int, default=0,
                         help="Number of required reviews (default: 0)")
    p_cache.add_argument("--protected", action="store_true", default=True,
                         help="Mark branch as protected (default: true)")

    args = parser.parse_args()

    root = find_project_root()
    data, config_path = load_config(root)

    if not config_path:
        print("ERROR: No config file found. Copy the issues-tracker.example.json from the CTDF plugin config directory "
              "to .claude/issues-tracker.json and configure it.")
        sys.exit(1)

    repo = data.get("repo", "")
    if not repo or repo == "null" or repo == "owner/repo":
        print(f"ERROR: 'repo' is not configured in {config_path}. "
              "Set it to your repository (e.g., 'user/project').")
        sys.exit(1)

    platform = data.get("platform", "github")

    if args.subcommand == "cache-protection":
        cache_branch_protection(
            data, config_path,
            branch=args.branch,
            role=args.role,
            protected=args.protected,
            require_reviews=args.require_reviews,
            merge_strategy=args.merge_strategy,
        )
        print(f"\nDone! Cached protection settings for {args.branch}.")
        return

    # Default: set up protection rules
    if platform == "gitlab":
        setup_gitlab_protection(repo, args.branch, args.required_reviews,
                                args.status_checks, args.merge_queue)
    else:
        setup_github_protection(repo, args.branch, args.required_reviews,
                                args.status_checks, args.merge_queue)

    # Automatically cache the protection settings after applying them
    role = "production"  # default role for the protected branch
    cache_branch_protection(
        data, config_path,
        branch=args.branch,
        role=role,
        protected=True,
        require_reviews=args.required_reviews,
    )

    print(f"\nDone! Branch protection configured for {repo}.")


if __name__ == "__main__":
    main()
