---
name: setup
description: Initialize task and idea tracking files in an existing project. Creates to-do.txt, progressing.txt, done.txt, ideas.txt, idea-disapproved.txt, and adds framework guidance to CLAUDE.md.
disable-model-invocation: true
argument-hint: "[project name]"
---

# Setup Task Tracking

You are a setup assistant for the CTDF plugin. Your job is to initialize the task and idea tracking files in the user's project so that all other CTDF skills (`/ctdf:task-create`, `/ctdf:task-pick`, `/ctdf:idea-create`, etc.) work correctly.

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

(No tasks yet — use /ctdf:task-create to add tasks)
```

**progressing.txt** (if missing):
```
================================================================================
[PROJECT NAME] — In Progress
================================================================================

(No tasks in progress — use /ctdf:task-pick to start a task)
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

(No ideas yet — use /ctdf:idea-create to add ideas)
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
# [TODO: Add your project's development commands here]
# Example:
# npm run dev          # Start development server
# npm run build        # Build for production
# npm run test         # Run tests
```

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

Use `/ctdf:idea-create` to add ideas, `/ctdf:idea-approve` to promote an idea to a task, `/ctdf:idea-refactor` to update ideas based on codebase changes, and `/ctdf:idea-disapprove` to reject an idea. Ideas must never be picked up directly by `/ctdf:task-pick`.

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
3. Use `/ctdf:task-create [description]` to create your first task
4. Use `/ctdf:idea-create [description]` to capture ideas
5. (Optional) Run `/ctdf:project-initialization` for full project scaffolding
6. (Optional) Enable Issues tracker — see the CTDF README for setup instructions
```

## Important Rules

1. **NEVER overwrite existing files** — only create files that are missing
2. **Use exact formatting** — separator lines must be exactly 80 `=` characters for section headers and 78 `-` characters for task separators
3. **All output in English**
