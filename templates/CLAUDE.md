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

# Common commands:
# [install command]
# [dev command]
# [build command]
# [test command]
# [lint command]
```

**Important:** Your project's verify command must pass before closing any task. Define it above and reference it throughout the skills.

## Environment Setup

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

- **Python command:** All scripts and skills reference `python3`. On Windows where only `python` is available, substitute `python` for `python3` in all commands.
- **Port management:** `app_manager.py` provides cross-platform port management — `lsof`/`ss` on Unix, `netstat`/`taskkill` on Windows. Used by generated Makefile/scripts.
- **File search:** `task_manager.py find-files` provides cross-platform file discovery (replaces Unix `find`).
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
