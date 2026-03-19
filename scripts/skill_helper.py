#!/usr/bin/env python3
"""Consolidated skill helper for codeclaw.

Eliminates repeated logic across CodeClaw skills by providing single-call
subcommands that gather context, dispatch arguments, check state, and
manage worktrees.

All output is JSON.  Zero external dependencies — stdlib only.
"""

import argparse
import configparser
import json
import os
import platform as platform_mod
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Platform Adapter Support ───────────────────────────────────────────────
# Add scripts/ to path so platform_adapter module can be found
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# ── Constants ───────────────────────────────────────────────────────────────

SEPARATOR = "-" * 78
TASK_FILES = ["to-do.txt", "progressing.txt", "done.txt"]
IDEA_FILES = ["ideas.txt", "idea-disapproved.txt"]
ALL_FILES = TASK_FILES + IDEA_FILES

STATUS_MAP = {"[ ]": "todo", "[~]": "progressing", "[x]": "done", "[!]": "blocked"}

TASK_HEADER_RE = re.compile(r"^\[(.)\]\s+([A-Z]{3,5}-\d{4})\s+—\s+(.+)$")
IDEA_HEADER_RE = re.compile(r"^(IDEA-[A-Z]{3,5}-\d{4})\s+—\s+(.+)$")
TASK_CODE_RE = re.compile(r"^[A-Z]{3,5}-\d{4}$")
VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:-beta)?")

CLAUDE_MD_VAR_RE = re.compile(r'^([A-Z_]+)\s*=\s*"?([^"#]*)"?\s*(?:#.*)?$')


# ── Project Root Detection ──────────────────────────────────────────────────

def find_project_root() -> Path:
    """Find project root via git or by walking up to find to-do.txt."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        )
        root = Path(result.stdout.strip())
        if (root / "to-do.txt").exists():
            return root
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    d = Path.cwd()
    while d != d.parent:
        if (d / "to-do.txt").exists():
            return d
        d = d.parent
    return Path.cwd()


def get_main_repo_root() -> Path:
    """Return main repo root, even from inside a git worktree."""
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        git_dir = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        common_path = Path(common).resolve()
        git_dir_path = Path(git_dir).resolve()
        if common_path != git_dir_path:
            return common_path.parent
        return find_project_root()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return find_project_root()


def is_in_worktree() -> bool:
    """Return True if CWD is inside a git worktree (not the main repo)."""
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        git_dir = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return Path(common).resolve() != Path(git_dir).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


# ── Git Helpers ─────────────────────────────────────────────────────────────

def git_run(*args: str, cwd: str | None = None) -> str | None:
    """Run a git command and return stdout, or None on failure."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True, check=True,
            cwd=cwd,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def git_current_branch() -> str:
    return git_run("branch", "--show-current") or ""


def git_branch_exists(name: str) -> bool:
    return git_run("rev-parse", "--verify", f"refs/heads/{name}") is not None


def git_remote_branch_exists(name: str) -> bool:
    return git_run("rev-parse", "--verify", f"refs/remotes/origin/{name}") is not None


def git_worktree_list() -> list[dict]:
    """Parse git worktree list --porcelain output."""
    raw = git_run("worktree", "list", "--porcelain")
    if not raw:
        return []
    worktrees = []
    current: dict = {}
    for line in raw.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line[9:]}
        elif line.startswith("HEAD "):
            current["head"] = line[5:]
        elif line.startswith("branch "):
            current["branch"] = line[7:]
        elif line == "bare":
            current["bare"] = True
        elif line == "detached":
            current["detached"] = True
    if current:
        worktrees.append(current)
    return worktrees


# ── Submodule Detection ────────────────────────────────────────────────────

def _detect_submodules(root: Path) -> list[dict]:
    """Parse .gitmodules and return list of submodule info dicts.

    Returns list of {name, path, url, branch} for each submodule.
    """
    gitmodules = root / ".gitmodules"
    if not gitmodules.exists():
        return []
    cfg = configparser.ConfigParser()
    try:
        cfg.read(str(gitmodules), encoding="utf-8")
    except (configparser.Error, OSError):
        return []
    submodules = []
    for section in cfg.sections():
        # section looks like 'submodule "name"'
        name_match = re.match(r'^submodule\s+"(.+)"$', section)
        name = name_match.group(1) if name_match else section
        path = cfg.get(section, "path", fallback="")
        url = cfg.get(section, "url", fallback="")
        branch = cfg.get(section, "branch", fallback="")
        if path:
            submodules.append({
                "name": name,
                "path": path,
                "url": url,
                "branch": branch,
            })
    return submodules


# ── File Helpers ────────────────────────────────────────────────────────────

def read_lines(filepath: Path) -> list[str]:
    """Read file lines, stripping \\r.  Returns empty list if missing."""
    if not filepath.exists():
        return []
    return filepath.read_text(encoding="utf-8").replace("\r", "").splitlines()


def is_separator(line: str) -> bool:
    return line.strip() == SEPARATOR


# ── Simple Block Parser ────────────────────────────────────────────────────

def parse_blocks(filepath: Path) -> list[dict]:
    """Parse task/idea blocks from a file (simplified version for status).

    Returns list of dicts with: code, title, status_symbol, status,
    block_type, priority, dependencies.
    """
    lines = read_lines(filepath)
    blocks: list[dict] = []
    i = 0
    while i < len(lines):
        if not is_separator(lines[i]):
            i += 1
            continue
        if i + 2 >= len(lines):
            i += 1
            continue
        header_line = lines[i + 1]
        task_m = TASK_HEADER_RE.match(header_line)
        idea_m = IDEA_HEADER_RE.match(header_line) if not task_m else None
        if not task_m and not idea_m:
            i += 1
            continue
        if not is_separator(lines[i + 2]):
            i += 1
            continue

        # Gather content lines
        content_start = i + 3
        content_end = content_start
        while content_end < len(lines) and not is_separator(lines[content_end]):
            content_end += 1

        block: dict = {}
        if task_m:
            sym = f"[{task_m.group(1)}]"
            block = {
                "block_type": "task",
                "code": task_m.group(2),
                "title": task_m.group(3).strip(),
                "status_symbol": sym,
                "status": STATUS_MAP.get(sym, "unknown"),
            }
        else:
            block = {
                "block_type": "idea",
                "code": idea_m.group(1),
                "title": idea_m.group(2).strip(),
                "status_symbol": "",
                "status": "idea",
            }

        # Extract priority and dependencies from content
        priority = ""
        dependencies = ""
        for cl in lines[content_start:content_end]:
            s = cl.strip()
            if s.startswith("Priority:"):
                priority = s[len("Priority:"):].strip()
            elif s.startswith("Dependencies:"):
                dependencies = s[len("Dependencies:"):].strip()
        block["priority"] = priority
        block["dependencies"] = dependencies
        blocks.append(block)
        i = content_end

    return blocks


# ── CLAUDE.md Parser ───────────────────────────────────────────────────────

def parse_claude_md(root: Path) -> dict[str, str]:
    """Extract key=value pairs from the bash code block in CLAUDE.md."""
    claude_md = root / "CLAUDE.md"
    if not claude_md.exists():
        return {}
    content = claude_md.read_text(encoding="utf-8")
    # Find the first ```bash ... ``` block
    m = re.search(r"```bash\n(.*?)```", content, re.DOTALL)
    if not m:
        return {}
    pairs: dict[str, str] = {}
    for line in m.group(1).splitlines():
        vm = CLAUDE_MD_VAR_RE.match(line)
        if vm:
            val = vm.group(2).strip().strip('"')
            if val:
                pairs[vm.group(1)] = val
    return pairs


def claude_md_info(root: Path) -> dict:
    """Return metadata about CLAUDE.md."""
    claude_md = root / "CLAUDE.md"
    if not claude_md.exists():
        return {"exists": False, "lines": 0, "has_claw_section": False}
    content = claude_md.read_text(encoding="utf-8")
    lines = content.splitlines()
    return {
        "exists": True,
        "lines": len(lines),
        "has_claw_section": "<!-- CodeClaw:START -->" in content,
    }


# ── Platform Config ────────────────────────────────────────────────────────

def read_platform_config(root: Path) -> dict:
    """Read .claude/issues-tracker.json (or legacy .claude/github-issues.json)."""
    # No size limit: config files are local and trusted; adding a limit could break legitimate large configs
    for name in ("issues-tracker.json", "github-issues.json"):
        p = root / ".claude" / name
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                return data
            except (json.JSONDecodeError, OSError):
                pass
    return {}


def _write_platform_config(root: Path, data: dict) -> str:
    """Write data back to the issues-tracker config file. Returns the path used.

    Uses locked_config_write for atomic, race-condition-safe writes.
    Falls back to direct write if config_lock is not available.
    """
    target: Path | None = None
    for name in ("issues-tracker.json", "github-issues.json"):
        p = root / ".claude" / name
        if p.exists():
            target = p
            break

    if target is None:
        target = root / ".claude" / "issues-tracker.json"
        target.parent.mkdir(parents=True, exist_ok=True)

    try:
        from config_lock import locked_config_write
        locked_config_write(target, data)
    except ImportError:
        target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    return str(target)


def get_cached_branch_config(root: Path) -> dict:
    """Read cached branch topology/protection from issues-tracker.json.

    Returns the ``branches`` dict from the config, or an empty dict if
    no cache exists.
    """
    cfg = read_platform_config(root)
    return cfg.get("branches", {})


def refresh_branch_config(root: Path) -> dict:
    """Query platform API for branch protection and cache results.

    Fetches protection settings for production, staging, and development
    branches via ``gh api`` (GitHub) or ``glab api`` (GitLab) and writes
    them into the ``branches`` section of issues-tracker.json.

    Returns the updated ``branches`` dict.
    """
    cfg = read_platform_config(root)
    repo = cfg.get("repo", "")
    platform = cfg.get("platform", "github")
    if not repo:
        return {}

    # Determine branch names from CLAUDE.md or defaults
    md_vars = parse_claude_md(root)
    prod = md_vars.get("PRODUCTION_BRANCH", "") or "main"
    staging = md_vars.get("STAGING_BRANCH", "") or "staging"
    dev = md_vars.get("DEVELOPMENT_BRANCH", "") or "develop"

    role_map = {
        prod: "production",
        staging: "staging",
        dev: "development",
    }

    branches: dict = cfg.get("branches", {})
    old_ttl = branches.get("cache_ttl_hours", 24)

    for branch_name, role in role_map.items():
        entry: dict = {"role": role, "protected": False}
        if platform == "github":
            result = subprocess.run(
                ["gh", "api", f"repos/{repo}/branches/{branch_name}/protection",
                 "-H", "Accept: application/vnd.github+json"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                try:
                    prot = json.loads(result.stdout)
                    entry["protected"] = True
                    reviews = prot.get("required_pull_request_reviews", {})
                    entry["require_reviews"] = reviews.get(
                        "required_approving_review_count", 0
                    ) if reviews else 0
                    entry["allow_force_pushes"] = prot.get(
                        "allow_force_pushes", {}
                    ).get("enabled", False)
                    entry["allow_deletions"] = prot.get(
                        "allow_deletions", {}
                    ).get("enabled", False)
                except (json.JSONDecodeError, AttributeError):
                    pass
            # else: branch unprotected or not found — keep defaults

        elif platform == "gitlab":
            encoded = repo.replace("/", "%2F")
            result = subprocess.run(
                ["glab", "api", f"projects/{encoded}/protected_branches/{branch_name}"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                try:
                    prot = json.loads(result.stdout)
                    entry["protected"] = True
                    entry["allow_force_pushes"] = prot.get("allow_force_push", False)
                except (json.JSONDecodeError, AttributeError):
                    pass

        branches[branch_name] = entry

    # Detect merge strategy from repo-level settings (GitHub only, once for all branches)
    if platform == "github":
        repo_result = subprocess.run(
            ["gh", "api", f"repos/{repo}",
             "-H", "Accept: application/vnd.github+json",
             "--jq", ".allow_squash_merge,.allow_merge_commit,.allow_rebase_merge"],
            capture_output=True, text=True, timeout=30,
        )
        if repo_result.returncode == 0:
            lines = repo_result.stdout.strip().splitlines()
            if len(lines) >= 3:
                allow_squash = lines[0].strip().lower() == "true"
                allow_merge = lines[1].strip().lower() == "true"
                allow_rebase = lines[2].strip().lower() == "true"
                if allow_squash and not allow_merge and not allow_rebase:
                    detected_strategy = "squash"
                elif allow_rebase and not allow_squash and not allow_merge:
                    detected_strategy = "rebase"
                elif allow_merge:
                    detected_strategy = "merge"
                else:
                    detected_strategy = "squash"  # default if multiple
                # Apply to all branches (repo-level setting)
                for bname, bentry in branches.items():
                    if isinstance(bentry, dict) and "merge_strategy" not in bentry:
                        bentry["merge_strategy"] = detected_strategy

    # Mixed keys: separating requires schema migration; current structure is backward-compatible
    branches["cache_ttl_hours"] = old_ttl
    branches["last_refreshed"] = datetime.now(timezone.utc).isoformat()

    cfg["branches"] = branches
    _write_platform_config(root, cfg)
    return branches


def is_branch_cache_stale(root: Path) -> bool:
    """Return True if the cached branch config is missing or older than TTL."""
    branches = get_cached_branch_config(root)
    if not branches or "last_refreshed" not in branches:
        return True

    ttl_hours = branches.get("cache_ttl_hours", 24)
    try:
        last = datetime.fromisoformat(branches["last_refreshed"])
        age_hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600
        return age_hours > ttl_hours
    except (ValueError, TypeError):
        return True


def get_platform_info(root: Path) -> dict:
    """Build full platform context."""
    raw = read_platform_config(root)
    enabled = raw.get("enabled", False)
    sync = raw.get("sync", False)
    platform = raw.get("platform", "github")

    if not enabled:
        mode = "local-only"
    elif sync:
        mode = "dual-sync"
    else:
        mode = "platform-only"

    cli = "glab" if platform == "gitlab" else "gh"
    return {
        "mode": mode,
        "enabled": enabled,
        "sync": sync,
        "platform": platform,
        "cli": cli,
        "repo": raw.get("repo", ""),
        "labels": raw.get("labels", {}),
    }


# ── Version Detection ──────────────────────────────────────────────────────

def read_version_from_file(filepath: Path) -> str | None:
    """Detect version from a manifest file based on its name."""
    name = filepath.name
    try:
        if name == "package.json":
            data = json.loads(filepath.read_text(encoding="utf-8"))
            return data.get("version")
        elif name == "pyproject.toml":
            content = filepath.read_text(encoding="utf-8")
            m = re.search(r'version\s*=\s*"([^"]+)"', content)
            return m.group(1) if m else None
        elif name == "Cargo.toml":
            content = filepath.read_text(encoding="utf-8")
            in_pkg = False
            for line in content.splitlines():
                if line.strip() == "[package]":
                    in_pkg = True
                    continue
                if in_pkg and line.strip().startswith("["):
                    break
                if in_pkg:
                    m = re.match(r'version\s*=\s*"([^"]+)"', line.strip())
                    if m:
                        return m.group(1)
        elif name == "setup.py":
            content = filepath.read_text(encoding="utf-8")
            m = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
            return m.group(1) if m else None
    except (json.JSONDecodeError, FileNotFoundError, OSError):
        pass
    return None


MANIFEST_NAMES = ["package.json", "pyproject.toml", "Cargo.toml", "setup.py"]


def scan_manifests(root: Path) -> list[dict]:
    """Return list of {file, version} for all found manifest files."""
    results = []
    for name in MANIFEST_NAMES:
        fp = root / name
        if fp.exists():
            v = read_version_from_file(fp)
            if v:
                results.append({"file": name, "version": v})
    return results


def get_latest_tag(tag_prefix: str) -> str | None:
    """Get the latest git tag matching the prefix."""
    raw = git_run("tag", "-l", f"{tag_prefix}*", "--sort=-v:refname")
    if raw:
        tags = raw.splitlines()
        return tags[0] if tags else None
    return None


def detect_tag_prefix() -> str:
    """Auto-detect tag prefix from existing tags."""
    raw = git_run("tag", "-l", "--sort=-v:refname")
    if not raw:
        return "v"
    first = raw.splitlines()[0]
    m = re.match(r"^([a-zA-Z]*)(\d+\.\d+\.\d+)", first)
    if m:
        return m.group(1) or "v"
    return "v"


def _detect_mcp_server_status(root: Path) -> dict:
    """Detect MCP server availability and status.

    Checks whether the MCP server script exists, whether the ``mcp``
    Python package is installed, and whether the server is configured
    as enabled in project config.
    """
    scripts_dir = _SCRIPT_DIR
    mcp_script = scripts_dir / "mcp_server.py"

    status: dict = {
        "available": mcp_script.exists(),
        "status": "stopped",
        "sdk_installed": False,
        "enabled": False,
    }

    if not mcp_script.exists():
        status["status"] = "not_installed"
        return status

    # Check if mcp SDK is installed
    try:
        result = subprocess.run(
            [sys.executable, str(mcp_script), "--check"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            check_data = json.loads(result.stdout.strip())
            status["sdk_installed"] = check_data.get("mcp_sdk", False)
        else:
            status["sdk_installed"] = False
    except Exception:
        status["sdk_installed"] = False

    # Check project config for mcp_server.enabled
    for cfg_name in [
        root / ".claude" / "project-config.json",
        root / "config" / "project-config.json",
    ]:
        if cfg_name.exists():
            try:
                data = json.loads(cfg_name.read_text(encoding="utf-8"))
                mcp_cfg = data.get("mcp_server", {})
                status["enabled"] = mcp_cfg.get("enabled", False)
                break
            except (json.JSONDecodeError, OSError):
                pass

    if status["sdk_installed"] and status["enabled"]:
        status["status"] = "ready"
    elif status["sdk_installed"]:
        status["status"] = "disabled"
    else:
        status["status"] = "no_sdk"

    return status


# ════════════════════════════════════════════════════════════════════════════
# Subcommand: context
# ════════════════════════════════════════════════════════════════════════════

def cmd_context(_args) -> dict:
    """Return all context a skill needs in one call."""
    root = get_main_repo_root()
    md_vars = parse_claude_md(root)

    # ── platform ──
    platform = get_platform_info(root)

    # ── worktree ──
    in_wt = is_in_worktree()
    wt_list = git_worktree_list()
    try:
        wt_root = Path(subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()).resolve()
    except Exception:
        wt_root = None

    submodules = _detect_submodules(root)

    worktree = {
        "in_worktree": in_wt,
        "main_root": str(root),
        "worktree_root": str(wt_root) if in_wt and wt_root else None,
        "worktrees": [w.get("path", "") for w in wt_list],
        "submodules": submodules,
    }

    # ── branches ──
    dev_branch = md_vars.get("DEVELOPMENT_BRANCH", "")
    if not dev_branch:
        dev_branch = md_vars.get("RELEASE_BRANCH", "")
    if not dev_branch:
        dev_branch = "develop" if git_branch_exists("develop") else "main"
    staging_branch = md_vars.get("STAGING_BRANCH", "") or "staging"
    prod_branch = md_vars.get("PRODUCTION_BRANCH", "") or "main"

    # Read cached branch protection settings
    cached_branches = get_cached_branch_config(root)
    protection = {}
    for bname in (prod_branch, staging_branch, dev_branch):
        binfo = cached_branches.get(bname, {})
        if binfo:
            protection[bname] = {
                "role": binfo.get("role", ""),
                "protected": binfo.get("protected", False),
                "merge_strategy": binfo.get("merge_strategy", ""),
                "require_reviews": binfo.get("require_reviews", 0),
            }

    branches = {
        "current": git_current_branch(),
        "development": dev_branch,
        "staging": staging_branch,
        "production": prod_branch,
        "release_branch": dev_branch,
        "protection": protection,
        "cache_stale": is_branch_cache_stale(root),
    }

    # ── release_config ──
    tag_prefix = md_vars.get("TAG_PREFIX", "")
    if not tag_prefix:
        tag_prefix = detect_tag_prefix()
    repo_url = md_vars.get("GITHUB_REPO_URL", "")
    if not repo_url:
        url = git_run("remote", "get-url", "origin")
        if url:
            repo_url = url.replace(".git", "").replace("git@github.com:", "https://github.com/")
    changelog = md_vars.get("CHANGELOG_FILE", "") or "CHANGELOG.md"

    release_config = {
        "tag_prefix": tag_prefix,
        "package_paths": md_vars.get("PACKAGE_JSON_PATHS", ""),
        "changelog_file": changelog,
        "repo_url": repo_url,
        "verify_command": md_vars.get("VERIFY_COMMAND", ""),
        "test_command": md_vars.get("TEST_COMMAND", ""),
        "test_framework": md_vars.get("TEST_FRAMEWORK", ""),
    }

    # ── memory_agents ──
    memory_agents = {
        "active_agents": 0,
        "pending_conflicts": 0,
    }
    try:
        from memory_protocol import MemoryProtocol
        protocol = MemoryProtocol(root)
        proto_status = protocol.get_status()
        memory_agents["active_agents"] = proto_status.get("active_agents", 0)
        memory_agents["pending_conflicts"] = proto_status.get("pending_conflicts", 0)
    except (ImportError, Exception):
        pass

    # ── vector_memory ──
    vector_memory = _get_vector_memory_status(root)

    # ── mcp_server ──
    mcp_server = _detect_mcp_server_status(root)

    # ── os_info ──
    try:
        from platform_utils import detect_python_cmd, get_shell_info
        python_cmd = detect_python_cmd()
        shell_info = get_shell_info()
    except ImportError:
        python_cmd = "python3"
        shell_info = {"shell": "unknown", "path": None, "cat_cmd": None}

    os_info = {
        "system": platform_mod.system(),
        "release": platform_mod.release(),
        "python_command": python_cmd,
        "python_version": platform_mod.python_version(),
        "shell": shell_info,
    }

    return {
        "platform": platform,
        "worktree": worktree,
        "branches": branches,
        "release_config": release_config,
        "memory_agents": memory_agents,
        "vector_memory": vector_memory,
        "mcp_server": mcp_server,
        "os_info": os_info,
    }


def _get_vector_memory_status(root: Path) -> dict:
    """Get vector memory status for context JSON (non-fatal)."""
    try:
        from vector_memory import get_effective_config, load_stored_manifest, INDEX_META
        from deps_check import check_vector_memory_deps
        import json as _json

        config = get_effective_config(root)
        if not config.get("enabled"):
            return {"status": "disabled"}

        ok, missing = check_vector_memory_deps()
        if not ok:
            return {"status": "disabled", "reason": f"missing deps: {', '.join(missing)}"}

        index_dir = root / config["index_path"]
        meta_path = index_dir / INDEX_META
        if not meta_path.exists():
            return {"status": "not_indexed", "enabled": True}

        meta = _json.loads(meta_path.read_text(encoding="utf-8"))
        stored = load_stored_manifest(index_dir)
        return {
            "status": "indexed" if stored else "stale",
            "enabled": True,
            "last_indexed": meta.get("last_indexed", "unknown"),
            "file_count": meta.get("file_count", 0),
            "embedding_model": meta.get("embedding_model", ""),
        }
    except Exception:
        return {"status": "disabled"}


# ════════════════════════════════════════════════════════════════════════════
# Subcommand: dispatch
# ════════════════════════════════════════════════════════════════════════════

def _is_task_code(s: str) -> bool:
    return bool(TASK_CODE_RE.match(s))


def _is_version(s: str) -> bool:
    return bool(re.match(r"^\d+\.\d+\.\d+$", s))


def _task_in_progressing(code: str) -> bool:
    """Check if task code exists in progressing.txt."""
    root = get_main_repo_root()
    fp = root / "progressing.txt"
    if not fp.exists():
        return False
    content = fp.read_text(encoding="utf-8")
    return code.upper() in content


def dispatch_task(parts: list[str]) -> dict:
    """Dispatch for the task skill."""
    parts, yolo = _extract_yolo(parts)
    base = {"yolo": yolo}

    if not parts:
        return {**base, "flow": "status", "task_code": "", "remaining_args": ""}

    first = parts[0].lower()
    rest = parts[1:]

    if first == "pick":
        if rest and rest[0].lower() == "all":
            mode = rest[1].lower() if len(rest) > 1 else "parallel"
            return {**base, "flow": "pick-all", "task_code": "", "remaining_args": mode}
        code = rest[0].upper() if rest else ""
        remaining = " ".join(rest[1:]) if len(rest) > 1 else ""
        return {**base, "flow": "pick", "task_code": code, "remaining_args": remaining}
    elif first == "create":
        if rest and rest[0].lower() == "all":
            mode = rest[1].lower() if len(rest) > 1 else "parallel"
            return {**base, "flow": "create-all", "task_code": "", "remaining_args": mode}
        return {**base, "flow": "create", "task_code": "", "remaining_args": " ".join(rest)}
    elif first == "continue":
        if rest and rest[0].lower() == "all":
            mode = rest[1].lower() if len(rest) > 1 else "parallel"
            return {**base, "flow": "continue-all", "task_code": "", "remaining_args": mode}
        code = rest[0].upper() if rest else ""
        remaining = " ".join(rest[1:]) if len(rest) > 1 else ""
        return {**base, "flow": "continue", "task_code": code, "remaining_args": remaining}
    # Branch placement: follows existing dispatch pattern for consistency
    elif first == "edit":
        code = rest[0].upper() if rest else ""
        return {**base, "flow": "edit", "task_code": code, "remaining_args": " ".join(rest[1:])}
    elif first == "schedule":
        # Parse: schedule CODE [CODE2 ...] to VERSION
        to_idx = None
        for i, r in enumerate(rest):
            if r.lower() == "to":
                to_idx = i
                break
        if to_idx is not None:
            task_codes = [r.upper() for r in rest[:to_idx]]
            version = rest[to_idx + 1] if to_idx + 1 < len(rest) else ""
            return {**base, "flow": "schedule", "task_code": ",".join(task_codes),
                    "remaining_args": version}
        else:
            return {**base, "flow": "schedule", "task_code": "",
                    "remaining_args": " ".join(rest)}
    elif first == "status":
        return {**base, "flow": "status", "task_code": "", "remaining_args": " ".join(rest)}
    elif _is_task_code(parts[0].upper()):
        code = parts[0].upper()
        if _task_in_progressing(code):
            return {**base, "flow": "continue", "task_code": code, "remaining_args": " ".join(rest)}
        else:
            return {**base, "flow": "pick", "task_code": code, "remaining_args": " ".join(rest)}
    else:
        return {**base, "flow": "status", "task_code": "", "remaining_args": " ".join(parts)}


def dispatch_idea(parts: list[str]) -> dict:
    """Dispatch for the idea skill."""
    parts, yolo = _extract_yolo(parts)
    base = {"yolo": yolo}

    if not parts:
        return {**base, "flow": "list", "task_code": "", "remaining_args": ""}

    first = parts[0].lower()
    rest = parts[1:]

    if first == "create":
        return {**base, "flow": "create", "task_code": "", "remaining_args": " ".join(rest)}
    elif first == "approve":
        code = rest[0].upper() if rest else ""
        return {**base, "flow": "approve", "task_code": code, "remaining_args": " ".join(rest[1:])}
    elif first == "disapprove":
        code = rest[0].upper() if rest else ""
        return {**base, "flow": "disapprove", "task_code": code, "remaining_args": " ".join(rest[1:])}
    elif first == "edit":
        code = rest[0].upper() if rest else ""
        return {**base, "flow": "edit", "task_code": code, "remaining_args": " ".join(rest[1:])}
    elif first == "refactor":
        return {**base, "flow": "refactor", "task_code": "", "remaining_args": " ".join(rest)}
    elif first == "scout":
        return {**base, "flow": "scout", "task_code": "", "remaining_args": " ".join(rest)}
    else:
        return {**base, "flow": "list", "task_code": "", "remaining_args": " ".join(parts)}


def dispatch_setup(parts: list[str]) -> dict:
    """Dispatch for the setup skill."""
    if not parts:
        return {"flow": "standard", "task_code": "", "remaining_args": ""}

    first = parts[0].lower()
    rest = parts[1:]

    if first == "env":
        return {"flow": "env", "task_code": "", "remaining_args": " ".join(rest)}
    elif first == "init":
        return {"flow": "init", "task_code": "", "remaining_args": " ".join(rest)}
    elif first in ("branch-strategy", "branch_strategy"):
        return {"flow": "branch-strategy", "task_code": "", "remaining_args": " ".join(rest)}
    elif first in ("agentic-fleet", "agentic_fleet"):
        return {"flow": "agentic-fleet", "task_code": "", "remaining_args": " ".join(rest)}
    else:
        return {"flow": "standard", "task_code": "", "remaining_args": " ".join(parts)}


def _extract_yolo(parts: list[str]) -> tuple[list[str], bool]:
    """Extract yolo flag from argument list, return filtered parts and flag."""
    yolo = False
    filtered = []
    for p in parts:
        if p.lower() == "yolo":
            yolo = True
        else:
            filtered.append(p)
    return filtered, yolo


def dispatch_release(parts: list[str]) -> dict:
    """Dispatch for the release skill."""
    parts, yolo = _extract_yolo(parts)
    base = {"task_code": "", "remaining_args": "", "yolo": yolo}

    if not parts:
        return {**base, "flow": "auto"}

    first = parts[0].lower()
    rest = parts[1:]

    if first == "create":
        version = rest[0] if rest and _is_version(rest[0]) else ""
        return {**base, "flow": "create", "version": version,
                "remaining_args": " ".join(rest[1:]) if len(rest) > 1 else ""}
    elif first == "generate":
        return {**base, "flow": "generate", "remaining_args": " ".join(rest)}
    elif first == "continue":
        if rest and rest[0].lower() == "resume":
            return {**base, "flow": "resume", "remaining_args": " ".join(rest[1:])}
        version = rest[0] if rest and _is_version(rest[0]) else ""
        return {**base, "flow": "continue", "version": version,
                "remaining_args": " ".join(rest[1:]) if len(rest) > 1 else ""}
    elif first == "close":
        version = rest[0] if rest and _is_version(rest[0]) else ""
        return {**base, "flow": "close", "version": version,
                "remaining_args": " ".join(rest[1:]) if len(rest) > 1 else ""}
    elif first == "edit":
        version = rest[0] if rest and _is_version(rest[0]) else ""
        return {**base, "flow": "edit", "version": version,
                "remaining_args": " ".join(rest[1:]) if len(rest) > 1 else ""}
    elif first == "resume":
        return {**base, "flow": "resume", "remaining_args": " ".join(rest)}
    elif first in ("security-only", "security_only"):
        return {**base, "flow": "security-only", "remaining_args": " ".join(rest)}
    elif first in ("optimize-only", "optimize_only"):
        return {**base, "flow": "optimize-only", "remaining_args": " ".join(rest)}
    elif first in ("test-only", "test_only"):
        return {**base, "flow": "test-only", "remaining_args": " ".join(rest)}
    elif _is_version(first):
        # Bare version: treat as "continue X.X.X" for backward compat
        return {**base, "flow": "continue", "version": first,
                "remaining_args": " ".join(rest)}
    else:
        return {**base, "flow": "auto", "remaining_args": " ".join(parts)}


def dispatch_update(parts: list[str]) -> dict:
    """Dispatch for the update skill."""
    valid = {"all", "pipelines", "agentic", "scripts", "prompts", "skills", "claude-md"}
    if not parts:
        return {"flow": "all", "task_code": "", "remaining_args": ""}
    first = parts[0].lower()
    if first in valid:
        return {"flow": first, "task_code": "", "remaining_args": " ".join(parts[1:])}
    return {"flow": "all", "task_code": "", "remaining_args": " ".join(parts)}


def dispatch_docs(parts: list[str]) -> dict:
    """Dispatch for the docs skill."""
    parts, yolo = _extract_yolo(parts)
    base = {"task_code": "", "remaining_args": "", "yolo": yolo}

    if not parts:
        return {**base, "flow": "generate"}

    first = parts[0].lower()
    rest = parts[1:]

    if first in ("generate", "sync", "reset", "publish"):
        return {**base, "flow": first, "remaining_args": " ".join(rest)}
    else:
        return {**base, "flow": "generate", "remaining_args": " ".join(parts)}


def dispatch_tests(parts: list[str]) -> dict:
    """Dispatch for the tests skill."""
    if not parts:
        return {"flow": "scout", "task_code": "", "remaining_args": ""}

    first = parts[0].lower()
    rest = parts[1:]

    if first == "scout":
        return {"flow": "scout", "task_code": "", "remaining_args": " ".join(rest)}
    elif first == "create":
        return {"flow": "create", "task_code": "", "remaining_args": " ".join(rest)}
    elif first == "continue":
        return {"flow": "continue", "task_code": "", "remaining_args": " ".join(rest)}
    elif first == "coverage":
        return {"flow": "coverage", "task_code": "", "remaining_args": " ".join(rest)}
    else:
        # Treat unknown args as target for scout
        return {"flow": "scout", "task_code": "", "remaining_args": " ".join(parts)}


def dispatch_help(parts: list[str]) -> dict:
    """Dispatch for the help skill."""
    if not parts:
        return {"flow": "overview", "task_code": "", "remaining_args": ""}
    return {"flow": "query", "task_code": "", "remaining_args": " ".join(parts)}


def dispatch_crazy(parts: list[str]) -> dict:
    """Dispatch for the crazy skill. Always returns flow 'build'; yolo defaults True."""
    parts, _yolo = _extract_yolo(parts)
    # Crazy skill forces yolo=True regardless of flag presence
    return {"flow": "build", "task_code": "", "remaining_args": " ".join(parts), "yolo": True}


DISPATCHERS = {
    "task": dispatch_task,
    "idea": dispatch_idea,
    "setup": dispatch_setup,
    "release": dispatch_release,
    "release-start": dispatch_release,  # backward compat
    "update": dispatch_update,
    "docs": dispatch_docs,
    "tests": dispatch_tests,
    "help": dispatch_help,
    "crazy": dispatch_crazy,
}


def cmd_dispatch(args) -> dict:
    """Parse skill arguments and return the dispatch target."""
    skill = args.skill
    raw_args = args.args or ""
    parts = raw_args.split() if raw_args.strip() else []

    dispatcher = DISPATCHERS.get(skill)
    if not dispatcher:
        return {"error": f"Unknown skill: {skill}", "flow": "", "task_code": "", "remaining_args": raw_args}
    return dispatcher(parts)


# ════════════════════════════════════════════════════════════════════════════
# Subcommand: check-project-state
# ════════════════════════════════════════════════════════════════════════════

def cmd_check_project_state(_args) -> dict:
    """Return project file existence and CLAUDE.md status."""
    root = get_main_repo_root()

    existing = [f for f in ALL_FILES if (root / f).exists()]
    missing = [f for f in ALL_FILES if not (root / f).exists()]

    releases_json = root / "releases.json"
    platform_info = get_platform_info(root)
    uses_local = platform_info["mode"] != "platform-only"
    git_init = (root / ".git").exists() or git_run("rev-parse", "--git-dir") is not None

    # Check .gitignore for .worktrees/
    gitignore = root / ".gitignore"
    gitignore_has_wt = False
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        gitignore_has_wt = ".worktrees" in content or ".worktrees/" in content

    return {
        "existing_files": existing,
        "missing_files": missing,
        "claude_md": claude_md_info(root),
        "releases_json": {"exists": releases_json.exists(), "active": uses_local},
        "git_initialized": git_init,
        "gitignore_has_worktrees": gitignore_has_wt,
    }


# ════════════════════════════════════════════════════════════════════════════
# Subcommand: create-project-files
# ════════════════════════════════════════════════════════════════════════════

FILE_TEMPLATES = {
    "to-do.txt": """\
================================================================================
                     {project} — TASK BACKLOG
================================================================================

  SECTION A — Core Features
================================================================================

""",
    "progressing.txt": """\
================================================================================
                 {project} — TASKS IN PROGRESS
================================================================================

""",
    "done.txt": """\
================================================================================
                  {project} — COMPLETED TASKS
================================================================================

""",
    "ideas.txt": """\
================================================================================
                     {project} — IDEAS
================================================================================

""",
    "idea-disapproved.txt": """\
================================================================================
              {project} — DISAPPROVED IDEAS
================================================================================

""",
}


def cmd_create_project_files(args) -> dict:
    """Create missing task/idea files from built-in templates."""
    root = get_main_repo_root()
    project_name = args.project_name or "Project"

    created = []
    already_exist = []

    for filename, template in FILE_TEMPLATES.items():
        fp = root / filename
        if fp.exists():
            already_exist.append(filename)
        else:
            fp.write_text(template.format(project=project_name), encoding="utf-8")
            created.append(filename)

    return {
        "created": created,
        "already_existed": already_exist,
        "root": str(root),
    }


# ════════════════════════════════════════════════════════════════════════════
# Subcommand: detect-branch-strategy
# ════════════════════════════════════════════════════════════════════════════

def cmd_detect_branch_strategy(_args) -> dict:
    """Return current branch state and what needs to be created."""
    root = get_main_repo_root()
    md_vars = parse_claude_md(root)

    dev = md_vars.get("DEVELOPMENT_BRANCH", "") or md_vars.get("RELEASE_BRANCH", "") or "develop"
    staging = md_vars.get("STAGING_BRANCH", "") or "staging"
    prod = md_vars.get("PRODUCTION_BRANCH", "") or "main"

    names = {"develop": dev, "staging": staging, "main": prod}
    branches_exist: dict[str, bool] = {}
    branches_remote: dict[str, bool] = {}

    for key, branch_name in [("develop", dev), ("staging", staging), ("main", prod)]:
        branches_exist[key] = git_branch_exists(branch_name)
        branches_remote[key] = git_remote_branch_exists(branch_name)

    needs_creation = [k for k in ("develop", "staging", "main") if not branches_exist[k]]

    # Check if CLAUDE.md already has the values configured
    has_dev = bool(md_vars.get("DEVELOPMENT_BRANCH") or md_vars.get("RELEASE_BRANCH"))
    has_staging = bool(md_vars.get("STAGING_BRANCH"))
    has_prod = bool(md_vars.get("PRODUCTION_BRANCH"))
    needs_update = not (has_dev and has_staging and has_prod)

    return {
        "branches_exist": branches_exist,
        "branches_remote": branches_remote,
        "claude_md_config": {"development": dev, "staging": staging, "production": prod},
        "needs_creation": needs_creation,
        "needs_claude_md_update": needs_update,
    }


# ════════════════════════════════════════════════════════════════════════════
# Subcommand: setup-task-worktree
# ════════════════════════════════════════════════════════════════════════════

def _is_worktree_enabled(root: Path) -> bool:
    """Check whether worktree-based task isolation is enabled in project config.

    Reads ``worktrees.enabled`` from project-config.json.  Returns False
    (disabled) by default — worktrees are a [BETA] opt-in feature.
    """
    for cfg_name in [
        root / ".claude" / "project-config.json",
        root / "config" / "project-config.json",
    ]:
        if cfg_name.exists():
            try:
                data = json.loads(cfg_name.read_text(encoding="utf-8"))
                return bool(data.get("worktrees", {}).get("enabled", False))
            except (json.JSONDecodeError, OSError):
                pass
    return False


_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _get_active_release_version(root: Path) -> str | None:
    """Query the active release version from release-state.json.

    Returns the version string (e.g. '4.0.2') if an active release exists,
    or None if no release state is found or the version is malformed.
    """
    state_file = root / ".claude" / "release-state.json"
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            version = data.get("version", "")
            if version and _SEMVER_RE.match(version):
                return version
        except (json.JSONDecodeError, OSError):
            pass

    # Fallback: try running release_manager.py release-state-get
    try:
        result = subprocess.run(
            [sys.executable, str(_SCRIPT_DIR / "release_manager.py"), "release-state-get"],
            capture_output=True, text=True, timeout=15,
            cwd=str(root),
        )
        if result.returncode == 0:
            data = json.loads(result.stdout.strip())
            version = data.get("version", "")
            if version and "error" not in data and _SEMVER_RE.match(version):
                return version
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            json.JSONDecodeError, FileNotFoundError, OSError):
        pass

    return None


def cmd_setup_task_worktree(args) -> dict:
    """Consolidate 5-step worktree creation into one command.

    When ``worktrees.enabled`` is False (the default), falls back to
    standard branch switching instead of creating a git worktree.
    """
    task_code = args.task_code
    base_branch = args.base_branch or "develop"

    if not task_code:
        return {"success": False, "error": "task_code is required"}

    root = get_main_repo_root()

    # [BETA] Check if worktree isolation is enabled in project config
    if not _is_worktree_enabled(root):
        # Fallback: use shared release/<version> branch for all tasks
        # Query active release to determine the release branch name
        release_version = _get_active_release_version(root)
        if not release_version:
            return {
                "success": False,
                "error": "No active release. Run /release create X.X.X first.",
            }

        branch_name = f"release/{release_version}"

        # Fetch latest base branch
        git_run("fetch", "origin", base_branch, cwd=str(root))

        branch_exists = git_branch_exists(branch_name)
        try:
            if branch_exists:
                subprocess.run(
                    ["git", "checkout", branch_name],
                    capture_output=True, text=True, check=True,
                    cwd=str(root),
                )
            else:
                # Try from remote first, then local
                result = subprocess.run(
                    ["git", "checkout", "-b", branch_name, f"origin/{base_branch}"],
                    capture_output=True, text=True,
                    cwd=str(root),
                )
                if result.returncode != 0:
                    subprocess.run(
                        ["git", "checkout", "-b", branch_name, base_branch],
                        capture_output=True, text=True, check=True,
                        cwd=str(root),
                    )
        except subprocess.CalledProcessError as e:
            return {"success": False, "error": e.stderr.strip() or str(e)}

        return {
            "success": True,
            "worktree_dir": str(root),
            "branch": branch_name,
            "created": not branch_exists,
            "reused_existing": branch_exists,
            "worktree_mode": False,
            "release_version": release_version,
        }
    code_lower = task_code.lower()
    branch_name = f"task/{code_lower}"
    wt_dir = root / ".worktrees" / "task" / code_lower

    # 1. Ensure directories exist
    (root / ".worktrees" / "task").mkdir(parents=True, exist_ok=True)

    # 2. Ensure .gitignore has .worktrees/
    gitignore = root / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        if ".worktrees" not in content and ".worktrees/" not in content:
            with open(gitignore, "a", encoding="utf-8") as f:
                f.write("\n.worktrees/\n")
    else:
        gitignore.write_text(".worktrees/\n", encoding="utf-8")

    # 3. Check if worktree already exists
    if wt_dir.exists() and (wt_dir / ".git").exists():
        return {
            "success": True,
            "worktree_dir": str(wt_dir),
            "branch": branch_name,
            "created": False,
            "reused_existing": True,
        }

    # 4. Prune stale worktrees
    git_run("worktree", "prune", cwd=str(root))

    # 5. Fetch latest base branch
    git_run("fetch", "origin", base_branch, cwd=str(root))

    # 6. Check if branch exists
    branch_exists = git_branch_exists(branch_name)

    # Safe: content passed via argument list (not shell), no injection vector
    try:
        if branch_exists:
            result = subprocess.run(
                ["git", "worktree", "add", str(wt_dir), branch_name],
                capture_output=True, text=True, check=True,
                cwd=str(root),
            )
        else:
            result = subprocess.run(
                ["git", "worktree", "add", "-b", branch_name, str(wt_dir), f"origin/{base_branch}"],
                capture_output=True, text=True,
                cwd=str(root),
            )
            if result.returncode != 0:
                # Fallback: try from local base branch
                result = subprocess.run(
                    ["git", "worktree", "add", "-b", branch_name, str(wt_dir), base_branch],
                    capture_output=True, text=True, check=True,
                    cwd=str(root),
                )
    except subprocess.CalledProcessError as e:
        return {"success": False, "error": e.stderr.strip() or str(e)}

    # Initialize submodules in the new worktree (if any)
    submodules = _detect_submodules(root)
    if submodules:
        git_run("submodule", "update", "--init", "--recursive", cwd=str(wt_dir))

    return {
        "success": True,
        "worktree_dir": str(wt_dir),
        "branch": branch_name,
        "created": True,
        "reused_existing": False,
        "submodules_initialized": len(submodules) > 0,
    }


# ════════════════════════════════════════════════════════════════════════════
# Subcommand: status-report
# ════════════════════════════════════════════════════════════════════════════

def cmd_status_report(_args) -> dict:
    """Return pre-computed status data for the task status flow."""
    root = get_main_repo_root()

    todo_blocks = parse_blocks(root / "to-do.txt")
    prog_blocks = parse_blocks(root / "progressing.txt")
    done_blocks = parse_blocks(root / "done.txt")

    # Count tasks only (exclude ideas)
    todos = [b for b in todo_blocks if b["block_type"] == "task"]
    progs = [b for b in prog_blocks if b["block_type"] == "task"]
    dones = [b for b in done_blocks if b["block_type"] == "task"]

    blocked = [b for b in todos if b["status"] == "blocked"]
    non_blocked_todo = [b for b in todos if b["status"] != "blocked"]

    total = len(todos) + len(progs) + len(dones)
    progress = round(len(dones) / total * 100) if total > 0 else 0

    # In-progress tasks
    in_progress = [
        {"code": b["code"], "title": b["title"], "priority": b["priority"]}
        for b in progs
    ]

    # Blocked tasks
    blocked_items = [
        {"code": b["code"], "title": b["title"], "depends_on": b["dependencies"]}
        for b in blocked
    ]

    # Recommend next tasks: HIGH priority first, check deps satisfied
    progressing_codes = {b["code"] for b in progs}
    done_codes = {b["code"] for b in dones}
    resolved = progressing_codes | done_codes

    next_recommended = []
    for b in non_blocked_todo:
        deps = b["dependencies"]
        deps_satisfied = True
        if deps and deps.lower() != "none":
            dep_codes = re.findall(r"[A-Z]{3,5}-\d{4}", deps)
            deps_satisfied = all(dc in resolved for dc in dep_codes)
        next_recommended.append({
            "code": b["code"],
            "title": b["title"],
            "priority": b["priority"],
            "deps_satisfied": deps_satisfied,
        })

    # Sort: HIGH first, then deps_satisfied first
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "": 3}
    next_recommended.sort(
        key=lambda x: (priority_order.get(x["priority"].upper(), 3), not x["deps_satisfied"])
    )

    # Worktrees mapped to tasks
    wt_list = git_worktree_list()
    task_worktrees = []
    for wt in wt_list:
        branch = wt.get("branch", "")
        if "task/" in branch:
            code_part = branch.split("task/")[-1].upper().replace("/", "")
            # Try to map to a real code (best-effort)
            task_worktrees.append({
                "path": wt.get("path", ""),
                "branch": branch.replace("refs/heads/", ""),
                "task_code": code_part,
            })

    # Release plan from releases.json (only when using local file tracking)
    release_plan = None
    platform_info = get_platform_info(root)
    if platform_info["mode"] != "platform-only":
        releases_fp = root / "releases.json"
        if releases_fp.exists():
            try:
                release_plan = json.loads(releases_fp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

    return {
        "summary": {
            "todo": len(todos),
            "progressing": len(progs),
            "done": len(dones),
            "blocked": len(blocked),
            "total": total,
            "progress_percent": progress,
        },
        "in_progress": in_progress,
        "blocked": blocked_items,
        "next_recommended": next_recommended[:10],
        "worktrees": task_worktrees,
        "release_plan": release_plan,
    }


# ════════════════════════════════════════════════════════════════════════════
# Subcommand: list-submodules
# ════════════════════════════════════════════════════════════════════════════

def cmd_list_submodules(_args) -> dict:
    """Return detected submodules for the current project."""
    root = get_main_repo_root()
    submodules = _detect_submodules(root)
    return {
        "has_submodules": len(submodules) > 0,
        "count": len(submodules),
        "submodules": submodules,
    }


# ════════════════════════════════════════════════════════════════════════════
# Subcommand: detect-release-config
# ════════════════════════════════════════════════════════════════════════════

def cmd_detect_release_config(_args) -> dict:
    """Return all release configuration in one call."""
    root = get_main_repo_root()
    md_vars = parse_claude_md(root)

    tag_prefix = md_vars.get("TAG_PREFIX", "")
    if not tag_prefix:
        tag_prefix = detect_tag_prefix()

    last_tag = get_latest_tag(tag_prefix)
    current_version = "0.0.0"
    is_beta = False

    if last_tag:
        # Strip prefix
        v_str = last_tag.lstrip("".join(set(tag_prefix)))
        vm = VERSION_RE.match(v_str)
        if vm:
            current_version = f"{vm.group(1)}.{vm.group(2)}.{vm.group(3)}"
            is_beta = "-beta" in last_tag

    manifests = scan_manifests(root)
    if manifests and current_version == "0.0.0":
        v_str = manifests[0]["version"]
        vm = VERSION_RE.match(v_str)
        if vm:
            current_version = f"{vm.group(1)}.{vm.group(2)}.{vm.group(3)}"
            is_beta = "-beta" in v_str

    changelog_file = md_vars.get("CHANGELOG_FILE", "") or "CHANGELOG.md"
    changelog_exists = (root / changelog_file).exists()

    repo_url = md_vars.get("GITHUB_REPO_URL", "")
    if not repo_url:
        url = git_run("remote", "get-url", "origin")
        if url:
            repo_url = url.replace(".git", "").replace("git@github.com:", "https://github.com/")

    dev_branch = md_vars.get("DEVELOPMENT_BRANCH", "") or md_vars.get("RELEASE_BRANCH", "")
    if not dev_branch:
        dev_branch = "develop" if git_branch_exists("develop") else "main"

    return {
        "tag_prefix": tag_prefix,
        "last_tag": last_tag,
        "current_version": current_version,
        "is_beta": is_beta,
        "manifest_files": manifests,
        "changelog_file": changelog_file,
        "changelog_exists": changelog_exists,
        "repo_url": repo_url,
        "development_branch": dev_branch,
        "staging_branch": md_vars.get("STAGING_BRANCH", "") or "staging",
        "production_branch": md_vars.get("PRODUCTION_BRANCH", "") or "main",
    }


# ════════════════════════════════════════════════════════════════════════════
# Subcommand: detect-platform
# ════════════════════════════════════════════════════════════════════════════

def cmd_detect_platform(_args) -> dict:
    """Detect the current AI coding platform and return adapter info."""
    from platform_adapter import detect_platform, get_adapter, ALL_PLATFORMS

    platform = detect_platform()
    adapter = get_adapter(platform)
    skills = adapter.discover_skills()
    config = adapter.get_config()

    return {
        "detected_platform": platform,
        "adapter_class": type(adapter).__name__,
        "project_root": str(adapter.get_project_root()),
        "skills_found": len(skills),
        "skills": [{"name": s["name"], "path": s["path"]} for s in skills],
        "config": config,
        "all_supported_platforms": ALL_PLATFORMS,
    }


# ════════════════════════════════════════════════════════════════════════════
# Subcommand: adapter-invoke
# ════════════════════════════════════════════════════════════════════════════

def cmd_adapter_invoke(args) -> dict:
    """Invoke a tool through the detected platform adapter."""
    from platform_adapter import detect_platform, get_adapter

    platform = getattr(args, "platform", "") or detect_platform()
    tool = getattr(args, "tool", "")
    raw_args = getattr(args, "tool_args", "")

    if not tool:
        return {"error": "Missing --tool argument"}

    # Parse tool_args as key=value pairs
    arguments: dict = {}
    if raw_args:
        for pair in raw_args.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                arguments[k.strip()] = v.strip()

    adapter = get_adapter(platform)
    return adapter.invoke_tool(tool, arguments)


# ════════════════════════════════════════════════════════════════════════════
# Subcommand: refresh-branch-config
# ════════════════════════════════════════════════════════════════════════════

def cmd_refresh_branch_config(_args) -> dict:
    """Query platform API for branch protection rules and cache them."""
    root = get_main_repo_root()
    branches = refresh_branch_config(root)
    return {
        "success": True,
        "branches": branches,
    }


# ════════════════════════════════════════════════════════════════════════════
# CLI Entrypoint
# ════════════════════════════════════════════════════════════════════════════

def output_json(data: dict) -> None:
    """Print JSON to stdout."""
    json.dump(data, sys.stdout, indent=2, default=str)
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Consolidated skill helper for CodeClaw",
    )
    sub = parser.add_subparsers(dest="command")

    # context
    sub.add_parser("context", help="Return all context a skill needs in one call")

    # dispatch
    p_dispatch = sub.add_parser("dispatch", help="Parse skill arguments and return dispatch target")
    p_dispatch.add_argument("--skill", required=True, help="Skill name")
    p_dispatch.add_argument("--args", default="", help="Raw arguments string")

    # check-project-state
    sub.add_parser("check-project-state", help="Return project file existence and CLAUDE.md status")

    # create-project-files
    p_create = sub.add_parser("create-project-files", help="Create missing task/idea files")
    p_create.add_argument("--project-name", default="Project", help="Project name for templates")

    # detect-branch-strategy
    sub.add_parser("detect-branch-strategy", help="Return branch state and needs")

    # setup-task-worktree
    p_wt = sub.add_parser("setup-task-worktree", help="Create task worktree in one step")
    p_wt.add_argument("--task-code", required=True, help="Task code e.g. AUTH-0001")
    p_wt.add_argument("--base-branch", default="develop", help="Base branch")

    # status-report
    sub.add_parser("status-report", help="Return pre-computed task status data")

    # list-submodules
    sub.add_parser("list-submodules", help="Return detected git submodules")

    # detect-release-config
    sub.add_parser("detect-release-config", help="Return all release configuration")

    # detect-platform
    sub.add_parser("detect-platform", help="Detect AI coding platform and return adapter info")

    # refresh-branch-config
    sub.add_parser("refresh-branch-config",
                    help="Query platform API and cache branch protection settings")

    # adapter-invoke
    p_adapter = sub.add_parser("adapter-invoke", help="Invoke a tool through the platform adapter")
    p_adapter.add_argument("--platform", default="", help="Platform override (auto-detected if empty)")
    p_adapter.add_argument("--tool", required=True, help="Tool/subcommand name to invoke")
    p_adapter.add_argument("--tool-args", default="", help="Comma-separated key=value pairs")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    handlers = {
        "context": cmd_context,
        "dispatch": cmd_dispatch,
        "check-project-state": cmd_check_project_state,
        "create-project-files": cmd_create_project_files,
        "detect-branch-strategy": cmd_detect_branch_strategy,
        "setup-task-worktree": cmd_setup_task_worktree,
        "list-submodules": cmd_list_submodules,
        "status-report": cmd_status_report,
        "detect-release-config": cmd_detect_release_config,
        "detect-platform": cmd_detect_platform,
        "adapter-invoke": cmd_adapter_invoke,
        "refresh-branch-config": cmd_refresh_branch_config,
    }

    handler = handlers.get(args.command)
    if not handler:
        output_json({"error": f"Unknown command: {args.command}"})
        sys.exit(1)

    try:
        result = handler(args)
        output_json(result)
    except Exception as e:
        output_json({"error": str(e)})
        sys.exit(1)


if __name__ == "__main__":
    main()
