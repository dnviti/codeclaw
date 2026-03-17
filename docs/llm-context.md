---
title: LLM Context
description: Consolidated single-file reference for LLM and bot consumption
generated-by: ctdf-docs
generated-at: 2026-03-17T10:00:00Z
source-files:
  - README.md
  - scripts/task_manager.py
  - scripts/release_manager.py
  - scripts/skill_helper.py
  - scripts/docs_manager.py
  - scripts/agent_runner.py
  - scripts/test_manager.py
  - .claude-plugin/plugin.json
  - config/issues-tracker.example.json
  - config/agentic-provider.example.json
---

# CTDF — LLM Context File

## Project Summary

**Name:** CTDF (Claude Task Development Framework)
**Type:** Claude Code plugin
**Language:** Python 3 (stdlib only, zero external dependencies)
**Version:** 3.2.1
**Repository:** github.com/dnviti/claude-task-development-framework
**License:** MIT

CTDF is a project-agnostic plugin for Claude Code that provides structured task management, idea evaluation, gated release pipelines, documentation generation, test management, and automated CI/CD through agentic fleet pipelines.

---

## Architecture Overview

### Three-Layer Design

1. **Skills** — 8 Claude Code slash commands defined as Markdown files in `skills/<name>/SKILL.md`
2. **Scripts** — 11 Python CLIs in `scripts/` handling all deterministic operations
3. **Templates** — CI/CD workflows, prompts, and configuration templates in `templates/`

### Key Scripts

| Script | Purpose | Subcommands |
|--------|---------|-------------|
| `task_manager.py` | Task/idea CRUD, hooks, Issues integration | `list`, `parse-block`, `next-id`, `move-block`, `add-block`, `hook`, `issue-create`, `milestone-create` |
| `release_manager.py` | Version detection, changelog, release state | `current-version`, `classify-commits`, `next-version`, `generate-changelog`, `release-state-save`, `discover-manifests`, `bump-version` |
| `skill_helper.py` | Context gathering, argument dispatch, worktrees | `context`, `dispatch`, `worktree-create`, `worktree-cleanup` |
| `docs_manager.py` | Documentation lifecycle, staleness tracking | `discover`, `check-staleness`, `list-sections`, `init-manifest`, `clean` |
| `agent_runner.py` | Multi-provider agentic fleet runner | `run --pipeline task\|scout\|docs` |
| `test_manager.py` | Test discovery, gaps, coverage | `discover`, `analyze-gaps`, `suggest`, `run`, `coverage` |
| `app_manager.py` | Cross-platform port/process management | `check-ports`, `kill-ports`, `verify-ports` |
| `codebase_analyzer.py` | Static analysis reports | `analyze --focus infrastructure,features,quality` |
| `memory_builder.py` | Codebase summary for agent context | `generate` |

### Data Files

| File | Format | Purpose |
|------|--------|---------|
| `to-do.txt` | Plain text | Pending tasks |
| `progressing.txt` | Plain text | In-progress tasks |
| `done.txt` | Plain text | Completed tasks |
| `ideas.txt` | Plain text | Pending ideas |
| `idea-disapproved.txt` | Plain text | Rejected ideas |
| `.claude/issues-tracker.json` | JSON | GitHub/GitLab Issues config |
| `.claude/project-config.json` | JSON | Project settings |
| `.claude/releases.json` | JSON | Release roadmap |
| `.claude/agentic-provider.json` | JSON | AI provider config |

---

## Skills Reference

### /task
- `pick [CODE]` — Pick up next task, create worktree, present briefing
- `pick all [sequential]` — Implement all pending tasks
- `create [description]` — Create new task with auto-ID
- `continue [CODE]` — Resume in-progress task
- `schedule CODE to X.X.X` — Assign to release milestone
- `status` — Show task summary

### /idea
- `create [description]` — Add idea to backlog
- `approve [IDEA-CODE]` — Promote to task
- `disapprove [IDEA-CODE]` — Reject and archive
- `refactor [IDEA-CODE]` — Update for codebase changes
- `scout [focus]` — Research and suggest new ideas

### /release
- `create X.X.X` — Create empty milestone
- `generate` — Auto-generate release roadmap
- `continue X.X.X` — 9-stage gated pipeline
- `continue resume` — Resume from last stage
- `close X.X.X` — Finalize release
- `security-only` — Security analysis only
- `test-only` — Integration tests only

### /docs
- `generate` — Full documentation from codebase analysis
- `sync` — Update stale sections only
- `reset` — Remove all generated docs
- `publish` — Build as static website

### /setup
- `[project name]` — Initialize tracking files and branches
- `env [section]` — Detect tech stack
- `init [purpose]` — Full project scaffold
- `branch-strategy` — Configure branches
- `agentic-fleet` — Set up AI CI/CD pipelines

### /tests
- `discover` — Find all test files
- `analyze [target]` — Coverage gap analysis
- `suggest` — Recommend test targets
- `run [target]` — Execute tests
- `coverage [snapshot|compare|report|threshold-check]` — Persistent tracking

---

## Configuration Quick Reference

### Issues Tracker Modes

| `enabled` | `sync` | Mode | Data Source |
|-----------|--------|------|-------------|
| `false` | -- | Local only | `.txt` files |
| `true` | `false` | Platform only | GitHub/GitLab Issues |
| `true` | `true` | Dual sync | Local + Issues |

### Agentic Provider Config

```json
{
  "provider": "claude|openai|openclaw",
  "model": {"task": "model-id", "scout": "model-id", "docs": "model-id"},
  "budget": {"task": 15, "scout": 5, "docs": 5},
  "auto_pr": true
}
```

### Branch Strategy

`develop` → `staging` → `main`

- develop: active development, feature branches merge here
- staging: pre-release validation, builds `latest` Docker tag
- main: production, tagged releases, builds `stable` + `vX.X.X` Docker tags

---

## Task Format

```
------------------------------------------------------------------------------
[ ] AUTH-0001 — User Authentication System
------------------------------------------------------------------------------
  Priority: HIGH
  Dependencies: None

  DESCRIPTION:
  Implementation details here.

  TECHNICAL DETAILS:
  Backend:
    - POST /api/auth/register
    - POST /api/auth/login

  Files involved:
    CREATE:  src/services/auth.service.ts
    MODIFY:  src/app.ts
```

- Status markers: `[ ]` todo, `[~]` progressing, `[x]` done, `[!]` blocked
- 78-dash separators, em dash in title, 2-space indent
- Globally sequential codes: 3-5 uppercase letters + 4-digit number

---

## Release Pipeline Stages

1. Create release branch from develop
2. Task readiness gate (blocks if tasks pending)
3. Fetch open PRs on release branch
4. Per-PR sub-agents (parallel: analyze, optimize, security, fix, merge)
5. Merge to staging + local build gate + push
6. Integration tests on staging
7. Merge to main + version bump + tag + CI monitoring
8. Users testing (release is live)
9. End: cleanup and final report

Feedback loops: stages 4-6 create RPAT (Release Patch) tasks that loop back to stage 2. Stage 7 CI failures trigger fix → tag move → re-monitor.

---

## Quick Start Commands

```bash
# Install
/plugin marketplace add https://github.com/dnviti/claude-task-development-framework
/plugin install ctdf@dnviti-claude-task-development-framework

# Setup
/setup "My Project"

# Workflow
/idea create "Description"
/idea approve IDEA-CODE
/task pick
/release continue 1.0.0

# Yolo (auto-confirm all gates)
/release continue 1.0.0 yolo
```
