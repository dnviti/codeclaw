# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Language

Always respond and work in English, even if the user's prompt is written in another language.

## Development Commands

```bash
# Dev server
DEV_PORTS=                               # N/A (CLI plugin, no dev server)
START_COMMAND=""                          # N/A
PREDEV_COMMAND=""                         # N/A
VERIFY_COMMAND="python3 -m pytest --tb=short -q"

# Testing
TEST_FRAMEWORK="pytest"
TEST_COMMAND="python3 -m pytest --tb=short -q"
TEST_FILE_PATTERN="test_*.py"

# CI
CI_RUNTIME_SETUP="setup-python@v5 python-version=3.12"

# Branch Strategy
DEVELOPMENT_BRANCH="develop"
STAGING_BRANCH="staging"
PRODUCTION_BRANCH="main"

# Release
PACKAGE_JSON_PATHS=".claude-plugin/plugin.json"
CHANGELOG_FILE="CHANGELOG.md"
TAG_PREFIX="v"
GITHUB_REPO_URL="https://github.com/dnviti/claude-task-development-framework"

# Common commands:
# pip install -r requirements.txt   # install dependencies
# python3 -m pytest                 # run tests
# python3 -m flake8 scripts/        # lint
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

This is a **Claude Code plugin** (CodeClaw) providing project-agnostic task and release management via 8 skills.

```
.
├── .claude-plugin/       # Plugin manifest (plugin.json, marketplace.json)
├── .claude/              # Project config, issues tracker, coverage, memory
├── .github/workflows/    # CI, release, security, staging, issue triage
├── config/               # Example config templates
├── docs/                 # Generated documentation
├── hooks/                # Git/Claude hooks
├── scripts/              # Core Python scripts (release_manager, task_manager, etc.)
│   ├── adapters/         # Platform adapters (claude_code, opencode, openclaw)
│   ├── analyzers/        # Code analysis (coverage, features, quality, infrastructure)
│   ├── chunkers/         # Text chunking for vector memory
│   ├── embeddings/       # Embedding providers (local ONNX, API)
│   ├── hooks/            # Hook scripts (pre-tool offload)
│   ├── mcp_tools/        # MCP server tool definitions
│   └── social_platforms/ # Social media posting adapters
├── skills/               # Skill definitions (task, idea, release, setup, etc.)
└── templates/            # CLAUDE.md, CI workflow, and prompt templates
```

**Key entry points:**
- `scripts/task_manager.py` — Task CRUD, worktree management, platform integration
- `scripts/release_manager.py` — Release pipeline orchestration
- `scripts/skill_helper.py` — Skill dispatch, context resolution
- `scripts/mcp_server.py` — Vector memory MCP server
- `scripts/vector_memory.py` — Semantic indexing and search

<!-- CodeClaw:START -->
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

All scripts and skills reference `python3`. On Windows where only `python` is available, CodeClaw auto-detects the correct command:

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
- **Line endings:** Configure Git to handle line endings automatically: `git config --global core.autocrlf true`. CodeClaw text files use LF; Git will convert on checkout/commit.
- **Symlink permissions:** If your project uses symlinks, enable Developer Mode in Windows Settings or grant `SeCreateSymbolicLinkPrivilege` to your user account.

### Troubleshooting (Windows)

| Issue | Solution |
|-------|----------|
| `python3` not found | Install Python 3 from python.org and ensure "Add to PATH" is checked. Or set `python_command` in project config. |
| `cp -r` fails | All CodeClaw scripts use `shutil.copytree()` instead. If you see this error, update to the latest CodeClaw version. |
| `$(cat file)` fails in cmd.exe | CodeClaw uses direct file reading in Python. For manual commands, use PowerShell: `$(Get-Content -Raw file)` |
| Port check fails | Ensure `netstat` is available (built into Windows). Run as Administrator if needed. |
| Permission denied on kill | Run the terminal as Administrator for `taskkill` operations. |

### Vector Memory (opt-in)

CodeClaw includes an optional vector memory layer that indexes source code, tasks, and generated documents for semantic search. It is **disabled by default** and requires optional dependencies.

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
<!-- CodeClaw:END -->

### File Naming Conventions

| Layer | Pattern | Example |
|-------|---------|---------|
| Scripts | `snake_case.py` | `release_manager.py` |
| Skills | `skills/<name>/SKILL.md` | `skills/task/SKILL.md` |
| Config | `kebab-case.json` | `issues-tracker.json` |
| Templates | `kebab-case.yml` / `.md` | `agentic-task.yml` |
| Adapters | `snake_case.py` in `adapters/` | `claude_code.py` |
