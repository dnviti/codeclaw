# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

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
PACKAGE_JSON_PATHS=".claude-plugin/plugin.json .claude-plugin/marketplace.json"
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
- `scripts/task_manager.py` — Task CRUD, branch management, platform integration
- `scripts/release_manager.py` — Release pipeline orchestration
- `scripts/skill_helper.py` — Skill dispatch, context resolution
- `scripts/mcp_server.py` — Vector memory MCP server
- `scripts/vector_memory.py` — Semantic indexing and search

## Skill Shorthand Aliases

All skills share these command aliases. Each skill uses the subset it needs.

| Alias | Expands to |
|-------|------------|
| `TM`  | `python3 ${CLAW_ROOT}/scripts/task_manager.py` |
| `SH`  | `python3 ${CLAW_ROOT}/scripts/skill_helper.py` |
| `RM`  | `python3 ${CLAW_ROOT}/scripts/release_manager.py` |
| `PM`  | `TM platform-cmd` |
| `DM`  | `python3 ${CLAW_ROOT}/scripts/docs_manager.py` |
| `SA`  | `python3 ${CLAW_ROOT}/scripts/social_announcer.py` |
| `TESTS` | `python3 ${CLAW_ROOT}/scripts/test_manager.py` |

## Yolo Mode

When `yolo` is `true` in the `SH dispatch` result, **auto-select the recommended (first) option at every GATE** without waiting for user input. Log each auto-selected choice. Yolo never auto-selects destructive or cancel options. At loop counter >= 5, yolo pauses and asks the user.

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

### Task Branch Isolation

Every task gets a dedicated `task/<code-lowercase>` branch created from `DEVELOPMENT_BRANCH`.

| Concept | Location |
|---------|----------|
| Branch naming | `task/<code-lowercase>` |
| Base branch | `DEVELOPMENT_BRANCH` |
| Task files | Always in main repository root |
| PR target | `DEVELOPMENT_BRANCH` (or `PRODUCTION_BRANCH` for simplified pipeline) |

**Lifecycle:**
- `/task pick` creates a `task/<code>` branch from develop and checks it out
- `/task continue` checks out the existing task branch
- When a task is closed (marked done), the branch is preserved for PR
- `task_manager.py` always reads/writes task files from the main repo root via `get_main_repo_root()`
- `/release` and `/setup env` should be run from the main repository

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

## Workflow Orchestration

### 1. Plan Mode Default

- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent / Agent Teams Strategy

- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution
- When `$CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` = `"1"`: use Agent Teams with dedicated QA, security, and documentation roles (see [Agent Teams Mode](#agent-teams-mode-experimental))

### 3. Self-Improvement Loop

- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done

- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)

- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes — don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing

- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

## Task Management

- **Plan First:** Write plan to `tasks/todo.md` with checkable items
- **Verify Plan:** Check in before starting implementation
- **Track Progress:** Mark items complete as you go
- **Explain Changes:** High-level summary at each step
- **Document Results:** Add review section to `tasks/todo.md`
- **Capture Lessons:** Update `tasks/lessons.md` after corrections

## Core Principles

- **Simplicity First:** Make every change as simple as possible. Impact minimal code.
- **No Laziness:** Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact:** Only touch what's necessary. No side effects with new bugs.

### File Naming Conventions

| Layer | Pattern | Example |
|-------|---------|---------|
| Scripts | `snake_case.py` | `release_manager.py` |
| Skills | `skills/<name>/SKILL.md` | `skills/task/SKILL.md` |
| Config | `kebab-case.json` | `issues-tracker.json` |
| Templates | `kebab-case.yml` / `.md` | `agentic-task.yml` |
| Adapters | `snake_case.py` in `adapters/` | `claude_code.py` |
