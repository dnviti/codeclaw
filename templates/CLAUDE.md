# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Language

Always respond and work in English, even if the user's prompt is written in another language.

## Development Commands

```bash
# Dev server
DEV_PORTS=                               # Port(s) the dev server listens on
START_COMMAND=""                          # Command to start dev server
PREDEV_COMMAND=""                         # Optional pre-start setup
VERIFY_COMMAND=""                         # Quality gate (lint + test + build)

# Testing
TEST_FRAMEWORK=""                        # e.g., Vitest, pytest, go test
TEST_COMMAND=""                           # e.g., npm run test, pytest
TEST_FILE_PATTERN=""                      # e.g., *.test.ts, test_*.py

# CI
CI_RUNTIME_SETUP=""                      # GitHub Actions setup step YAML

# Branch Strategy
DEVELOPMENT_BRANCH=""                    # e.g., develop (default: develop)
STAGING_BRANCH=""                        # e.g., staging (default: staging)
PRODUCTION_BRANCH=""                     # e.g., main (default: main)

# Release
PACKAGE_JSON_PATHS=""                    # Space-separated manifest paths
CHANGELOG_FILE=""                        # e.g., CHANGELOG.md
TAG_PREFIX=""                            # e.g., v
GITHUB_REPO_URL=""                       # HTTPS repo URL

# Social Announcements (optional)
# Configure in project-config.json under "social_announce".
# Credentials via env vars: CTDF_BLUESKY_HANDLE, CTDF_BLUESKY_APP_PASSWORD,
# CTDF_MASTODON_INSTANCE, CTDF_MASTODON_TOKEN, CTDF_DISCORD_WEBHOOK,
# CTDF_SLACK_WEBHOOK. Never store credentials in config files.

# Common commands:
# [install command]
# [dev command]
# [build command]
# [test command]
# [lint command]
```

**Important:** Your project's verify command must pass before closing any task. Define it above and reference it throughout the skills.

## Environment Setup

### Ollama Local Model (Optional)

If configured via `/setup`, a local Ollama model can handle lightweight, repetitive tasks (boilerplate generation, docstrings, simple refactoring) to reduce API costs and latency. Configuration is stored in `.claude/ollama-config.json`.

```bash
# Check Ollama status
python3 scripts/ollama_manager.py health

# Query the local model directly
python3 scripts/ollama_manager.py query --model <MODEL> --prompt "..."

# Detect hardware capabilities
python3 scripts/ollama_manager.py detect-hardware
```

When offloading is enabled, Claude Code acts as an orchestrator and automatically routes simple tasks to the local model. Complex tasks requiring frontier-level reasoning remain with the cloud provider.

## Architecture

<!-- CTDF:START -->
## Key Patterns

### Task Files

Tasks are split across three files by status:

| File | Status | Symbol |
|------|--------|--------|
| `to-do.txt` | Pending tasks | `[ ]` |
| `progressing.txt` | In-progress tasks | `[~]` |
| `done.txt` | Completed tasks | `[x]` |

When a task changes status, move it to the corresponding file.

**Additional platform label:** Tasks in `progressing.txt` may also carry `status:to-test` on the platform, indicating they are awaiting test verification. Task branches must not be merged into the release branch until testing is confirmed.

### Idea Files

Ideas are stored separately from tasks and must be explicitly approved before entering the task pipeline:

| File | Purpose |
|------|---------|
| `ideas.txt` | Ideas awaiting evaluation |
| `idea-disapproved.txt` | Rejected ideas archive |

Use `/idea create` to add ideas, `/idea approve` to promote an idea to a task, `/idea refactor` to update ideas based on codebase changes, and `/idea disapprove` to reject an idea. Ideas must never be picked up directly by `/task pick`.

### Task & Idea Management Modes

Tasks and ideas support three operating modes, controlled by `.claude/issues-tracker.json` (or legacy `.claude/github-issues.json`):

| `enabled` | `sync` | Mode | Data Source |
|-----------|--------|------|-------------|
| `true` | `false` (or absent) | **Platform-only** | GitHub Issues or GitLab Issues only. No local files. |
| `true` | `true` | **Dual sync** | Local files first, then platform issues. |
| `false` | — | **Local only** | Local text files only (default). |

The `platform` field (`"github"` or `"gitlab"`) determines which CLI tool (`gh` or `glab`) is used. If omitted, defaults to `"github"`.

### Worktree-Based Task Isolation

Tasks are developed in isolated git worktrees instead of branch switching, enabling parallel task work:

| Concept | Location |
|---------|----------|
| Worktree directory | `.worktrees/task/<code-lowercase>/` (mirrors branch name) |
| Branch naming | `task/<code-lowercase>` |
| Task files | Always in main repository root |
| Source code | In the worktree directory |

**Lifecycle:**
- `/task pick` creates a worktree when a task is picked up
- When a task is closed (marked done), the worktree is **automatically removed**
- `/task continue` creates a **fresh worktree** from the existing branch (since the old one was dismissed at close)
- `task_manager.py` always reads/writes task files from the main repo root via `get_main_repo_root()`
- `/release` and `/setup env` should be run from the main repository
- `.worktrees/` must be in `.gitignore`

## Cross-Platform Notes

This framework supports **Windows, macOS, and Linux** with automatic OS detection.

### Python Command Auto-Detection

All scripts and skills reference `python3`. On Windows where only `python` is available, CTDF auto-detects the correct command:

- **Auto-detection:** `platform_utils.detect_python_cmd()` tries `python3` first, then `python`, verifying each is Python 3.x via `shutil.which()`.
- **Manual override:** Set `python_command` in `config/project-config.json` to skip auto-detection (e.g., `"python_command": "python"`).
- **CI/CD:** The CI workflow includes a `Detect Python command` step that sets the correct command per OS.

### Cross-Platform Utilities

| Utility | File | Purpose |
|---------|------|---------|
| `platform_utils.py` | `scripts/` | Python cmd detection, shell info, safe file copy, command runner |
| `app_manager.py` | `scripts/` | Port/process management — `lsof`/`ss` on Unix, `netstat`/`taskkill` on Windows |
| `task_manager.py find-files` | `scripts/` | Cross-platform file discovery (replaces Unix `find`) |

### Windows Requirements

- **PowerShell Core (pwsh):** Required for shell-expansion features (e.g., inline file reading in agent invocations). Install from https://github.com/PowerShell/PowerShell. The legacy `cmd.exe` has limited support — commands that rely on inline expansion will fall back to direct Python file reading.
- **Long path support:** Enable long paths in the Windows registry or via Group Policy if your project has deeply nested directories. Run: `New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force`
- **Line endings:** Configure Git to handle line endings automatically: `git config --global core.autocrlf true`. CTDF text files use LF; Git will convert on checkout/commit.
- **Symlink permissions:** If your project uses symlinks, enable Developer Mode in Windows Settings or grant `SeCreateSymbolicLinkPrivilege` to your user account.

### Troubleshooting (Windows)

| Issue | Solution |
|-------|----------|
| `python3` not found | Install Python 3 from python.org and ensure "Add to PATH" is checked. Or set `python_command` in project config. |
| `cp -r` fails | All CTDF scripts use `shutil.copytree()` instead. If you see this error, update to the latest CTDF version. |
| `$(cat file)` fails in cmd.exe | CTDF uses direct file reading in Python. For manual commands, use PowerShell: `$(Get-Content -Raw file)` |
| Port check fails | Ensure `netstat` is available (built into Windows). Run as Administrator if needed. |
| Permission denied on kill | Run the terminal as Administrator for `taskkill` operations. |

### Vector Memory (opt-in)

CTDF includes an optional vector memory layer that indexes source code, tasks, and generated documents for semantic search. It is **disabled by default** and requires optional dependencies.

| Component | Purpose |
|-----------|---------|
| `vector_memory.py index` | Build/update the semantic index |
| `vector_memory.py search "query"` | Search indexed content semantically |
| `vector_memory.py status` | Check index health and staleness |
| `vector_memory.py clear --force` | Reset the vector index |

**Setup:**
1. Install dependencies: `pip install lancedb onnxruntime tokenizers numpy pyarrow`
2. Enable in `project-config.json`: set `vector_memory.enabled` to `true`
3. Run initial index: `python3 scripts/vector_memory.py index --full`

**Configuration** (`project-config.json` > `vector_memory`):
- `enabled`: Enable/disable vector memory (default: `false`)
- `auto_index`: Auto-reindex on file Edit/Write hooks (default: `false`)
- `embedding_provider`: `"local"` (default), `"openai"`, or `"voyage"`
- `embedding_model`: Model name (default: `"all-MiniLM-L6-v2"`)
- `chunk_size`: Max characters per chunk (default: `2000`)
- `index_path`: Index storage path (default: `".claude/memory/vectors"`)

Vectors are stored in `.claude/memory/vectors/` (auto-added to `.gitignore`).
<!-- CTDF:END -->

### File Naming Conventions

<!-- [TODO: Define your project's file naming conventions] -->
<!-- Example:
| Layer | Pattern | Example |
|-------|---------|---------|
| Routes | `*.routes.ts` | `auth.routes.ts` |
| Controllers | `*.controller.ts` | `user.controller.ts` |
| Services | `*.service.ts` | `auth.service.ts` |
| Components | `*.tsx` | `Dashboard.tsx` |
| Stores | `*Store.ts` | `authStore.ts` |
| Hooks | `use*.ts` | `useAuth.ts` |
-->
