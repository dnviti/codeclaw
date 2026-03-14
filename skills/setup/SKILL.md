---
name: setup
description: Initialize task and idea tracking files in an existing project. Creates to-do.txt, progressing.txt, done.txt, ideas.txt, idea-disapproved.txt, and adds framework guidance to CLAUDE.md.
disable-model-invocation: true
argument-hint: "[project name] or agentic-fleet"
---

# Setup Task Tracking

You are a setup assistant for the CTDF plugin. Your job is to initialize the task and idea tracking files in the user's project so that all other CTDF skills (`/task-create`, `/task-pick`, `/idea-create`, etc.) work correctly.

**Special mode:** If `$ARGUMENTS` contains `agentic-fleet`, skip the normal task file setup and go directly to [Agentic Fleet Setup](#agentic-fleet-setup) below.

## Current Directory State

### Existing task files:
`python3 -c "from pathlib import Path; files=['to-do.txt','progressing.txt','done.txt','ideas.txt','idea-disapproved.txt']; existing=[f for f in files if Path(f).exists()]; missing=[f for f in files if not Path(f).exists()]; print(f'Existing: {existing or \"none\"}'); print(f'Missing: {missing or \"none\"}')"`

### CLAUDE.md status:
`python3 -c "from pathlib import Path; p=Path('CLAUDE.md'); print(f'Exists ({len(p.read_text().splitlines())} lines)') if p.exists() else print('Not found')"`

## Arguments

The user invoked with: **$ARGUMENTS**

## Instructions

### Step 1: Determine Project Name

If `$ARGUMENTS` provides a project name, use it. Otherwise, infer the project name from the current directory name. Use this as the header in `to-do.txt`.

### Step 2: Create Task and Idea Files

For each missing file, create it with the appropriate template. **Never overwrite existing files.**

**to-do.txt** (if missing):
```
================================================================================
[PROJECT NAME] — Task Backlog
================================================================================

================================================================================
SECTION A — Core Features
================================================================================

(No tasks yet — use /task-create to add tasks)
```

**progressing.txt** (if missing):
```
================================================================================
[PROJECT NAME] — In Progress
================================================================================

(No tasks in progress — use /task-pick to start a task)
```

**done.txt** (if missing):
```
================================================================================
[PROJECT NAME] — Completed Tasks
================================================================================

(No tasks completed yet)
```

**ideas.txt** (if missing):
```
================================================================================
[PROJECT NAME] — Idea Backlog
================================================================================

(No ideas yet — use /idea-create to add ideas)
```

**idea-disapproved.txt** (if missing):
```
================================================================================
[PROJECT NAME] — Disapproved Ideas
================================================================================

(No disapproved ideas)
```

### Step 3: Update CLAUDE.md

Check if CLAUDE.md exists and whether it already contains the `<!-- CTDF:START -->` marker.

**If CLAUDE.md does not exist**, create it with the full template:

```markdown
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

# Release
RELEASE_BRANCH=""                        # e.g., develop, main
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

Use `/idea-create` to add ideas, `/idea-approve` to promote an idea to a task, `/idea-refactor` to update ideas based on codebase changes, and `/idea-disapprove` to reject an idea. Ideas must never be picked up directly by `/task-pick`.

### Task & Idea Management Modes

Tasks and ideas support three operating modes, controlled by `.claude/issues-tracker.json`:

| `enabled` | `sync` | Mode | Data Source |
|-----------|--------|------|-------------|
| `true` | `false` (or absent) | **Platform-only** | GitHub Issues or GitLab Issues only. No local files. |
| `true` | `true` | **Dual sync** | Local files first, then platform issues. |
| `false` | — | **Local only** | Local text files only (default). |

The `platform` field (`"github"` or `"gitlab"`) determines which CLI tool (`gh` or `glab`) is used. If omitted, defaults to `"github"`.

## Cross-Platform Notes

This framework supports **Windows, macOS, and Linux** with automatic OS detection.

- **Python command:** All scripts and skills reference `python3`. On Windows where only `python` is available, substitute `python` for `python3` in all commands.
- **Port management:** `app_manager.py` automatically uses the correct OS tools — `lsof`/`ss` on Unix, `netstat`/`taskkill` on Windows.
- **File search:** `task_manager.py find-files` provides cross-platform file discovery (replaces Unix `find`).
<!-- CTDF:END -->

## File Naming Conventions
```

**If CLAUDE.md exists but does NOT contain `<!-- CTDF:START -->`**, append the framework section (from `<!-- CTDF:START -->` to `<!-- CTDF:END -->`) at the end of the file.

**If CLAUDE.md exists and already contains `<!-- CTDF:START -->`**, skip — the framework sections are already present.

### Step 4: Report

Present a summary to the user:

```
## CTDF Setup Complete

**Project:** [PROJECT NAME]

### Files Created
- [list of files created, or "All files already existed"]

### CLAUDE.md
- [Created / Updated with framework sections / Already configured]

### Next Steps
1. Customize `CLAUDE.md` — fill in Development Commands, Environment Setup, and Architecture
2. Customize `to-do.txt` — rename sections to match your project areas
3. Use `/task-create [description]` to create your first task
4. Use `/idea-create [description]` to capture ideas
5. (Optional) Run `/project-initialization` for full project scaffolding
6. (Optional) Enable Issues tracker — see the CTDF README for setup instructions
```

---

## Agentic Fleet Setup

This mode is activated when `$ARGUMENTS` contains `agentic-fleet`. It configures CI/CD pipelines that spawn AI agent fleets to automate idea scouting and/or task implementation.

Both pipelines are fully headless — all decisions are made by the model autonomously.

### Step A1: Detect Platform

Determine the platform from the issues tracker config:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py platform-config
```

Use the `platform` field (`github` or `gitlab`). If no config exists, ask the user which platform they use:

Use `AskUserQuestion` with these options:
- **"GitHub"** — set platform to `github`
- **"GitLab"** — set platform to `gitlab`

STOP HERE after calling `AskUserQuestion`. Do NOT proceed until the user responds.

### Step A2: Select Pipelines

Ask the user which agentic pipelines to enable:

Use `AskUserQuestion` with these options:
- **"Idea Scout only"** — on release publish, scouts new ideas
- **"Task Implementation only"** — on cron schedule, implements tasks and opens PRs
- **"Docs only"** — on push to release branch, auto-updates documentation
- **"All"** — all three pipelines
- **"Custom"** — pick specific pipelines (follow up to ask which combination)
- **"Cancel"** — abort setup

STOP HERE after calling `AskUserQuestion`. Do NOT proceed until the user responds.

### Step A3: Configure Cron (Task Implementation only)

**Skip this step if only "Idea Scout" was selected.**

Ask the user how often the task implementation pipeline should run:

Use `AskUserQuestion` with these options:
- **"Every 4 hours"** — cron: `0 */4 * * *`
- **"Every 6 hours"** — cron: `0 */6 * * *`
- **"Every 8 hours"** — cron: `0 */8 * * *`
- **"Every 12 hours"** — cron: `0 */12 * * *`
- **"Every 24 hours"** — cron: `0 0 * * *`
- **"Custom"** — ask the user for a custom cron expression

STOP HERE after calling `AskUserQuestion`. Do NOT proceed until the user responds.

Store the selected cron expression for the report in Step A7.

### Step A4: Copy Pipeline Templates

Based on the detected platform and selected pipelines:

- **GitHub:**
  ```bash
  mkdir -p .github/workflows
  ```
  - If Idea Scout selected: `cp ${CLAUDE_PLUGIN_ROOT}/templates/github/workflows/agentic-fleet.yml .github/workflows/agentic-fleet.yml`
  - If Task Implementation selected:
    ```bash
    cp ${CLAUDE_PLUGIN_ROOT}/templates/github/workflows/agentic-task.yml .github/workflows/agentic-task.yml
    sed -i 's|__AGENTIC_TASK_CRON__|<selected cron expression>|' .github/workflows/agentic-task.yml
    ```
  - If Docs selected: `cp ${CLAUDE_PLUGIN_ROOT}/templates/github/workflows/agentic-docs.yml .github/workflows/agentic-docs.yml`

- **GitLab:**
  - If Idea Scout selected: `cp ${CLAUDE_PLUGIN_ROOT}/templates/gitlab/agentic-fleet.gitlab-ci.yml .`
  - If Task Implementation selected: `cp ${CLAUDE_PLUGIN_ROOT}/templates/gitlab/agentic-task.gitlab-ci.yml .`
  - If Docs selected: `cp ${CLAUDE_PLUGIN_ROOT}/templates/gitlab/agentic-docs.gitlab-ci.yml .`
  - If a `.gitlab-ci.yml` already exists, instruct the user to add `include:` directives pointing to the new file(s), or merge the stages manually.

### Step A5: Copy Memory Builder Script

```bash
mkdir -p .claude/scripts
cp ${CLAUDE_PLUGIN_ROOT}/scripts/memory_builder.py .claude/scripts/memory_builder.py
```

### Step A6: Verify Files

Confirm the copied files exist. Check each pipeline file that was selected plus the memory builder script.

### Step A7: Report

Present a summary to the user:

```
## Agentic Fleet Setup Complete

### Pipelines Configured
[For each enabled pipeline:]

**Idea Scout Pipeline** (if enabled)
- **Trigger:** Runs automatically when a release is published (+ manual dispatch)
- **Fleet model:** Sonnet 4.6 (codebase reading)
- **Scout model:** Opus 4.6 (idea evaluation and creation)

**Task Implementation Pipeline** (if enabled)
- **Trigger:** Cron schedule: `[selected cron expression]` (+ manual dispatch)
- **Fleet model:** Sonnet 4.6 (codebase reading)
- **Implementation model:** Opus 4.6 (autonomous task implementation)

**Documentation Pipeline** (if enabled)
- **Trigger:** Push to release branch, excluding docs-only changes (+ manual dispatch)
- **Fleet model:** Sonnet 4.6 (codebase reading)
- **Docs model:** Opus 4.6 (runs `/docs update all` + `/docs claude-md`)
- **Behavior:** Commits updated docs directly to the release branch

### Platform: [GitHub / GitLab]

### Files Created
- [list of pipeline file paths]
- .claude/scripts/memory_builder.py

### Required Configuration
⚠️  **Secret:** Add `ANTHROPIC_API_KEY` as a [repository secret (GitHub) / CI/CD masked variable (GitLab)].

[If Task Implementation was selected on GitHub:]
The cron schedule `[selected cron expression]` has been written directly into `.github/workflows/agentic-task.yml`.
To change it later, edit the `cron:` line in that file.

[If Task Implementation was selected on GitLab:]
⚠️  **Pipeline Schedule:** Create a CI/CD Pipeline Schedule with the desired cron expression:
  - GitLab: CI/CD → Schedules → New schedule
  Alternatively, add `AGENTIC_TASK_CRON` as a CI/CD variable (uncheck "Protect" and "Mask").

### How It Works
1. **Build Memory** — Python script generates a structural codebase summary
2. **Deep Read (Sonnet 4.6 × 3)** — Three parallel agents analyze infrastructure, features, and code quality
3. **[Idea Scout]** Opus 4.6 runs /idea-scout with all reports → creates idea issues
   **[Task Implementation]** Opus 4.6 picks highest-priority task → implements it → opens a PR
4. **Result** — [Ideas / PRs] are created automatically on [GitHub / GitLab]

Both pipelines can also be triggered manually from the [GitHub Actions / GitLab CI/CD] interface.
```

---

## Important Rules

1. **NEVER overwrite existing files** — only create files that are missing
2. **Use exact formatting** — separator lines must be exactly 80 `=` characters for section headers and 78 `-` characters for task separators
3. **All output in English**
