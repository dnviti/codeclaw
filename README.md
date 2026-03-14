# CTDF — Claude Task Development Framework

A project-agnostic task and idea management plugin for [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

CTDF gives your AI-assisted development workflow a structured backbone: ideas are captured, evaluated, promoted to tasks, implemented with quality gates, and tracked to completion — all through plain-text files and Claude Code slash commands.

## Features

- **Two-pipeline workflow** — separate idea evaluation from task execution
- **22 built-in skills** — slash commands for every stage of the development lifecycle
- **Claude Code plugin** — install via marketplace, uninstall cleanly, update easily
- **Adaptive project initialization** — `/project-initialization` scaffolds your project and tailors all skills to your chosen stack, domain, and architecture
- **Plain-text tracking** — tasks and ideas live in simple `.txt` files, fully version-controllable
- **GitHub/GitLab Issues integration** — optional tri-modal sync with GitHub or GitLab Issues
- **Automated hooks** — file edits automatically surface related tasks and progress summaries
- **Quality gates** — verification, linting, and smoke tests run before tasks can be closed
- **Cross-platform** — works on Linux, macOS, and Windows with automatic OS detection
- **Project-agnostic** — works with any language, framework, or tech stack
- **Human-in-the-loop** — AI assists, but you make every decision

## Prerequisites

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and configured
- Python 3 (used by the bundled scripts)

## Installation

### From Marketplace

```
/plugin marketplace add https://github.com/dnviti/claude-task-development-framework
/plugin install ctdf@dnviti-claude-task-development-framework
```

### Local Development

```bash
git clone https://github.com/dnviti/claude-task-development-framework.git
claude --plugin-dir ./claude-task-development-framework
```

## Getting Started

1. **Install the plugin** using one of the methods above.

2. **Set up task tracking** in your project:

   ```
   /setup My Project Name
   ```

   This creates the task/idea files (`to-do.txt`, `progressing.txt`, `done.txt`, `ideas.txt`, `idea-disapproved.txt`) and adds framework guidance to your `CLAUDE.md`.

3. **(Optional) Full project initialization** — if starting a new project from scratch:

   ```
   /project-initialization [project purpose or stack]
   ```

   This scaffolds your project, sets up git, and configures all skills for your specific tech stack.

4. **Start using skills:**

   ```
   /idea-create Add user authentication with JWT
   /idea-approve IDEA-AUTH-0001
   /task-pick
   /task-status
   ```

## Core Concepts

### Ideas Pipeline

Ideas are lightweight proposals — high-level descriptions without implementation details. They go through evaluation before entering the task pipeline.

```
ideas.txt  ──→  /idea-approve  ──→  to-do.txt (becomes a task)
    │
    └──→  /idea-disapprove  ──→  idea-disapproved.txt (archived)
```

### Task Pipeline

Tasks are actionable work items with technical details, file lists, and dependencies. They flow through three files:

```
to-do.txt [ ]  ──→  progressing.txt [~]  ──→  done.txt [x]
```

| File | Status | Symbol |
|------|--------|--------|
| `to-do.txt` | Pending | `[ ]` |
| `to-do.txt` | Blocked | `[!]` |
| `progressing.txt` | In progress | `[~]` |
| `done.txt` | Completed | `[x]` |

## Skills Reference

### Setup & Project

| Skill | Usage | Description |
|-------|-------|-------------|
| `/setup` | `/setup [project name]` | Initialize task/idea tracking files in an existing project |
| `/project-initialization` | `/project-initialization [purpose]` | Full project scaffold: choose stack, configure git, adapt all skills |
| `/env-setup` | `/env-setup` | Scan project to detect tech stack, dependencies, and commands; update CLAUDE.md |

### Task Management

| Skill | Usage | Description |
|-------|-------|-------------|
| `/task-create` | `/task-create [description]` | Create a new task with auto-assigned ID and codebase-informed technical details |
| `/task-pick` | `/task-pick [TASK-CODE]` | Pick up the next task — verifies in-progress work first, runs quality gates |
| `/task-continue` | `/task-continue [TASK-CODE]` | Resume work on a specific in-progress task |
| `/task-status` | `/task-status` | Show current task summary and recommend next tasks |

### Idea Management

| Skill | Usage | Description |
|-------|-------|-------------|
| `/idea-create` | `/idea-create [description]` | Add a lightweight idea to the backlog for future evaluation |
| `/idea-approve` | `/idea-approve [IDEA-PREFIX-XXXX]` | Promote an idea to a full task with technical details |
| `/idea-disapprove` | `/idea-disapprove [IDEA-PREFIX-XXXX]` | Reject an idea and archive it |
| `/idea-refactor` | `/idea-refactor [IDEA-PREFIX-XXXX]` | Update an idea to reflect codebase changes |
| `/idea-scout` | `/idea-scout [focus area or @local-file]` | Research trends and online sources to suggest new ideas for evaluation |

### Testing

| Skill | Usage | Description |
|-------|-------|-------------|
| `/test-scout` | `/test-scout` | Discover test infrastructure and coverage gaps |
| `/test-create` | `/test-create` | Generate test files (unit, integration, e2e) and CI config |
| `/test-run` | `/test-run` | Execute tests, analyze results, report coverage |
| `/test-review` | `/test-review` | Review tasks marked `status:to-test` with guided testing |

### Security

| Skill | Usage | Description |
|-------|-------|-------------|
| `/vulnerability-scout` | `/vulnerability-scout` | Scan codebase for security vulnerabilities |
| `/vulnerability-create` | `/vulnerability-create` | Create tasks from discovered vulnerabilities |
| `/vulnerability-report` | `/vulnerability-report` | Generate comprehensive security report |

### Documentation & Quality

| Skill | Usage | Description |
|-------|-------|-------------|
| `/docs` | `/docs <operation> [category]` | Manage documentation (create, update, verify, sync, claude-md) |
| `/code-optimize` | `/code-optimize` | Analyze codebase for optimization opportunities across 7 categories and apply selected fixes |

### Release

| Skill | Usage | Description |
|-------|-------|-------------|
| `/release` | `/release [major\|minor\|patch\|stable]` | Bump version, update changelog, tag, and optionally publish with GitHub Release |

## Typical Workflow

```
0.  /setup "My Project"                     → Create task/idea tracking files
1.  /idea-create "Add email notifications"   → Idea added to ideas.txt
2.  /idea-approve IDEA-AUTH-0001              → Idea promoted to task in to-do.txt
3.  /task-pick                               → Task moved to progressing.txt, briefing presented
4.  (implement the task)                           → Write code based on the briefing
5.  /task-pick                               → Verifies implementation, runs quality gates
6.  (confirm completion)                           → Task moved to done.txt
7.  (optional: commit)                             → Changes committed with task code reference
```

You can also create tasks directly with `/task-create` if you don't need the idea evaluation step.

Use `/task-status` at any time to see your current progress and what to work on next.

## Issues Tracker Integration (Optional)

The plugin supports optional GitHub/GitLab Issues integration that can operate in three modes:

| `enabled` | `sync` | Mode | Data Source |
|-----------|--------|------|-------------|
| `true` | `false` | **Platform-only** | GitHub/GitLab Issues only — no local text files |
| `true` | `true` | **Dual sync** | Local files first, then synced to platform issues |
| `false` | — | **Local only** | Local `.txt` files only (default) |

To enable, run `/project-initialization` and choose "Yes, enable issues tracker" when prompted, or manually copy and configure the example config:

```bash
cp <plugin-dir>/config/issues-tracker.example.json .claude/issues-tracker.json
# Edit .claude/issues-tracker.json with your repo and settings
```

## Agentic Fleet Pipelines

CTDF includes automated CI/CD pipelines that use Claude Code to perform idea scouting and task implementation without human intervention.

### Pipelines

| Pipeline | Trigger | What it does |
|----------|---------|--------------|
| **Idea Scout** | On release publish | Scans trends, documentation, and community sources to suggest new ideas |
| **Task Implementation** | Cron-based schedule | Picks up pending tasks, implements them in isolated worktrees, and opens PRs |

### Architecture

Each pipeline uses a **three-agent architecture**:

1. **Orchestrator** — coordinates the workflow and delegates to specialized agents
2. **Worker** — performs the actual scouting or implementation work
3. **Memory Builder** — persists learnings and context for future runs via `memory_builder.py`

### Setup

```bash
/setup agentic-fleet
```

This generates the workflow files under `.github/workflows/` (or `.gitlab-ci.yml` for GitLab). Requires an `ANTHROPIC_API_KEY` secret configured in your repository.

Supports both **GitHub Actions** and **GitLab CI/CD**.

## Task Format

Each task in `to-do.txt` (or `progressing.txt` / `done.txt`) follows this structure:

```
------------------------------------------------------------------------------
[ ] AUTH-0001 — User Authentication System
------------------------------------------------------------------------------
  Priority: HIGH
  Dependencies: None

  DESCRIPTION:
  Implement user registration, login, and token-based authentication
  using JWT. Users should be able to sign up with email/password,
  log in, and access protected routes.

  TECHNICAL DETAILS:
  Backend:
    - POST /api/auth/register — validate input, hash password, store user
    - POST /api/auth/login — verify credentials, return JWT
    - Auth middleware to protect routes
  Frontend:
    - Login and registration forms
    - Auth context for token storage and user state

  Files involved:
    CREATE:  src/services/auth.service.ts
    CREATE:  src/routes/auth.routes.ts
    MODIFY:  src/app.ts
```

Key formatting rules:
- Separator lines are exactly **78 dashes**
- Title uses an **em dash** (`—`), not a hyphen
- All content is **indented with 2 spaces**
- Task codes are **globally sequential** across all files and prefixes

## Idea Format

Each idea in `ideas.txt` follows this structure:

```
------------------------------------------------------------------------------
IDEA-UIX-0001 — Dark Mode Support
------------------------------------------------------------------------------
  Category: User Interface
  Date: 2026-03-04

  DESCRIPTION:
  Add dark mode theme support to the application, allowing users
  to switch between light and dark themes.

  MOTIVATION:
  Many users prefer dark mode for reduced eye strain in low-light
  environments. It is a widely expected feature in modern apps.
```

Ideas are intentionally **high-level** — no technical details, no file lists. Those are added during `/idea-approve` when the idea becomes a task.

## Plugin Structure

```
claude-task-development-framework/
├── .claude-plugin/
│   ├── plugin.json              # Plugin manifest
│   └── marketplace.json         # Marketplace definition
├── skills/                      # 22 Claude Code skills
│   ├── setup/                   # Initialize task tracking in a project
│   ├── project-initialization/  # Full project scaffolding
│   ├── env-setup/               # Detect tech stack and update CLAUDE.md
│   ├── task-create/             # Create tasks
│   ├── task-pick/               # Pick up and close tasks
│   ├── task-continue/           # Resume in-progress tasks
│   ├── task-status/             # View task summary
│   ├── idea-create/             # Add ideas
│   ├── idea-approve/            # Promote ideas to tasks
│   ├── idea-disapprove/         # Reject ideas
│   ├── idea-refactor/           # Update ideas
│   ├── idea-scout/              # Research and suggest new ideas
│   ├── test-scout/              # Discover test infrastructure and gaps
│   ├── test-create/             # Generate test files and CI config
│   ├── test-run/                # Execute tests and report coverage
│   ├── test-review/             # Review tasks awaiting test verification
│   ├── vulnerability-scout/     # Scan for security vulnerabilities
│   ├── vulnerability-create/    # Create tasks from vulnerabilities
│   ├── vulnerability-report/    # Generate security reports
│   ├── docs/                    # Manage documentation
│   ├── code-optimize/           # Codebase optimization analysis
│   └── release/                 # Version bumping and release management
├── scripts/                     # Python automation scripts (stdlib only)
│   ├── task_manager.py          # Task/idea management CLI and post-edit hook
│   ├── release_manager.py       # Release automation CLI (version, changelog)
│   ├── app_manager.py           # Cross-platform port and process management
│   ├── memory_builder.py        # Agentic fleet memory persistence
│   ├── setup_labels.py          # Create platform labels for Issues integration
│   └── setup_protection.py      # Branch protection setup
├── templates/                   # CI/CD workflow templates
│   ├── github/                  # GitHub templates
│   │   └── workflows/
│   │       ├── agentic-fleet.yml
│   │       ├── agentic-task.yml
│   │       ├── ci.yml
│   │       ├── issue-triage.yml
│   │       ├── release.yml
│   │       ├── security.yml
│   │       └── status-guard.yml
│   └── gitlab/                  # GitLab CI templates
│       ├── agentic-fleet.gitlab-ci.yml
│       └── agentic-task.gitlab-ci.yml
├── config/                      # Example configuration files
│   ├── issues-tracker.example.json
│   ├── github-issues.example.json
│   ├── project-config.example.json
│   └── releases.example.json
├── hooks/
│   └── hooks.json               # Plugin hooks (PostToolUse for task tracking)
├── CLAUDE.md                    # Framework guidance
├── VERSION                      # Plugin version
└── README.md                    # This file
```

## Cross-Platform Notes

- **Python command:** All scripts reference `python3`. On Windows where only `python` is available, substitute `python` for `python3`.
- **Port management:** `app_manager.py` automatically uses the correct OS tools — `lsof`/`ss` on Unix, `netstat`/`taskkill` on Windows.
- **File search:** `task_manager.py find-files` provides cross-platform file discovery.

## Managing the Plugin

```bash
# Update the plugin
/plugin update ctdf@dnviti-claude-task-development-framework

# Disable temporarily
/plugin disable ctdf@dnviti-claude-task-development-framework

# Re-enable
/plugin enable ctdf@dnviti-claude-task-development-framework

# Uninstall
/plugin uninstall ctdf@dnviti-claude-task-development-framework
```

## License

MIT License

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
