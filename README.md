# CTDF — Claude Task Development Framework

A project-agnostic task and idea management plugin for [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

CTDF gives your AI-assisted development workflow a structured backbone: ideas are captured, evaluated, promoted to tasks, implemented with quality gates, and tracked to completion — all through plain-text files and Claude Code slash commands.

## Features

- **Two-pipeline workflow** — separate idea evaluation from task execution
- **21 built-in skills** — slash commands for every stage of the development lifecycle
- **Claude Code plugin** — install via marketplace, uninstall cleanly, update easily
- **Adaptive project initialization** — `/ctdf:project-initialization` scaffolds your project and tailors all skills to your chosen stack, domain, and architecture
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
/plugin marketplace add dnviti/claude-task-development-framework
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
   /ctdf:setup My Project Name
   ```

   This creates the task/idea files (`to-do.txt`, `progressing.txt`, `done.txt`, `ideas.txt`, `idea-disapproved.txt`) and adds framework guidance to your `CLAUDE.md`.

3. **(Optional) Full project initialization** — if starting a new project from scratch:

   ```
   /ctdf:project-initialization [project purpose or stack]
   ```

   This scaffolds your project, sets up git, and configures all skills for your specific tech stack.

4. **Start using skills:**

   ```
   /ctdf:idea-create Add user authentication with JWT
   /ctdf:idea-approve IDEA-001
   /ctdf:task-pick
   /ctdf:task-status
   ```

## Core Concepts

### Ideas Pipeline

Ideas are lightweight proposals — high-level descriptions without implementation details. They go through evaluation before entering the task pipeline.

```
ideas.txt  ──→  /ctdf:idea-approve  ──→  to-do.txt (becomes a task)
    │
    └──→  /ctdf:idea-disapprove  ──→  idea-disapproved.txt (archived)
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

All skills are namespaced under `ctdf:`. Use `/ctdf:skill-name` to invoke.

### Setup & Project

| Skill | Usage | Description |
|-------|-------|-------------|
| `/ctdf:setup` | `/ctdf:setup [project name]` | Initialize task/idea tracking files in an existing project |
| `/ctdf:project-initialization` | `/ctdf:project-initialization [purpose]` | Full project scaffold: choose stack, configure git, adapt all skills |

### Task Management

| Skill | Usage | Description |
|-------|-------|-------------|
| `/ctdf:task-create` | `/ctdf:task-create [description]` | Create a new task with auto-assigned ID and codebase-informed technical details |
| `/ctdf:task-pick` | `/ctdf:task-pick [TASK-CODE]` | Pick up the next task — verifies in-progress work first, runs quality gates |
| `/ctdf:task-continue` | `/ctdf:task-continue [TASK-CODE]` | Resume work on a specific in-progress task |
| `/ctdf:task-status` | `/ctdf:task-status` | Show current task summary and recommend next tasks |
| `/ctdf:task-scout` | `/ctdf:task-scout [focus-area]` | Research industry trends and suggest new features |

### Idea Management

| Skill | Usage | Description |
|-------|-------|-------------|
| `/ctdf:idea-create` | `/ctdf:idea-create [description]` | Add a lightweight idea to the backlog for future evaluation |
| `/ctdf:idea-approve` | `/ctdf:idea-approve [IDEA-NNN]` | Promote an idea to a full task with technical details |
| `/ctdf:idea-disapprove` | `/ctdf:idea-disapprove [IDEA-NNN]` | Reject an idea and archive it |
| `/ctdf:idea-refactor` | `/ctdf:idea-refactor [IDEA-NNN]` | Update an idea to reflect codebase changes |

### Development Operations

| Skill | Usage | Description |
|-------|-------|-------------|
| `/ctdf:app-start` | `/ctdf:app-start` | Start the development environment with error monitoring |
| `/ctdf:app-stop` | `/ctdf:app-stop` | Stop running development processes |
| `/ctdf:app-restart` | `/ctdf:app-restart` | Restart the development environment |

### Quality & Documentation

| Skill | Usage | Description |
|-------|-------|-------------|
| `/ctdf:docs` | `/ctdf:docs <operation> [category]` | Manage documentation (create, update, verify, sync, claude-md) |
| `/ctdf:test-engineer` | `/ctdf:test-engineer [scope] [target]` | Create, update, or optimize tests and CI/CD pipelines |
| `/ctdf:security-audit` | `/ctdf:security-audit [scope]` | Perform security audits and generate detailed reports |
| `/ctdf:github-pages-updater` | `/ctdf:github-pages-updater` | Create or update a GitHub Pages landing site for the project |

### Release & Publishing

| Skill | Usage | Description |
|-------|-------|-------------|
| `/ctdf:code-optimize` | `/ctdf:code-optimize` | Analyze codebase for optimization opportunities across 7 categories and apply selected fixes |
| `/ctdf:git-publish` | `/ctdf:git-publish` | Push development branch and open an auto-merging PR into main |
| `/ctdf:release` | `/ctdf:release [major\|minor\|patch\|stable]` | Bump version, update changelog, tag, and optionally publish with GitHub Release |

## Typical Workflow

```
0.  /ctdf:setup "My Project"                     → Create task/idea tracking files
1.  /ctdf:idea-create "Add email notifications"   → Idea added to ideas.txt
2.  /ctdf:idea-approve IDEA-001                   → Idea promoted to task in to-do.txt
3.  /ctdf:task-pick                               → Task moved to progressing.txt, briefing presented
4.  (implement the task)                           → Write code based on the briefing
5.  /ctdf:task-pick                               → Verifies implementation, runs quality gates
6.  (confirm completion)                           → Task moved to done.txt
7.  (optional: commit)                             → Changes committed with task code reference
```

You can also create tasks directly with `/ctdf:task-create` if you don't need the idea evaluation step.

Use `/ctdf:task-status` at any time to see your current progress and what to work on next.

## Issues Tracker Integration (Optional)

The plugin supports optional GitHub/GitLab Issues integration that can operate in three modes:

| `enabled` | `sync` | Mode | Data Source |
|-----------|--------|------|-------------|
| `true` | `false` | **Platform-only** | GitHub/GitLab Issues only — no local text files |
| `true` | `true` | **Dual sync** | Local files first, then synced to platform issues |
| `false` | — | **Local only** | Local `.txt` files only (default) |

To enable, run `/ctdf:project-initialization` and choose "Yes, enable issues tracker" when prompted, or manually copy and configure the example config:

```bash
cp <plugin-dir>/config/issues-tracker.example.json .claude/issues-tracker.json
# Edit .claude/issues-tracker.json with your repo and settings
```

## Task Format

Each task in `to-do.txt` (or `progressing.txt` / `done.txt`) follows this structure:

```
------------------------------------------------------------------------------
[ ] AUTH-001 — User Authentication System
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
IDEA-001 — Dark Mode Support
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

Ideas are intentionally **high-level** — no technical details, no file lists. Those are added during `/ctdf:idea-approve` when the idea becomes a task.

## Plugin Structure

```
claude-task-development-framework/
├── .claude-plugin/
│   ├── plugin.json              # Plugin manifest
│   └── marketplace.json         # Marketplace definition
├── skills/                      # 21 Claude Code skills
│   ├── setup/                   # Initialize task tracking in a project
│   ├── task-create/             # Create tasks
│   ├── task-pick/               # Pick up and close tasks
│   ├── task-continue/           # Resume in-progress tasks
│   ├── task-status/             # View task summary
│   ├── task-scout/              # Research new features
│   ├── idea-create/             # Add ideas
│   ├── idea-approve/            # Promote ideas to tasks
│   ├── idea-disapprove/         # Reject ideas
│   ├── idea-refactor/           # Update ideas
│   ├── project-initialization/  # Full project scaffolding
│   ├── app-start/               # Start dev environment
│   ├── app-stop/                # Stop dev processes
│   ├── app-restart/             # Restart dev environment
│   ├── docs/                    # Manage documentation
│   ├── test-engineer/           # Manage tests and CI/CD
│   ├── security-audit/          # Security audits
│   ├── github-pages-updater/    # GitHub Pages site management
│   ├── code-optimize/           # Codebase optimization analysis
│   ├── git-publish/             # PR-based publishing to main
│   └── release/                 # Version bumping and release management
├── scripts/                     # Python automation scripts (stdlib only)
│   ├── task_manager.py          # Task/idea management CLI and post-edit hook
│   ├── release_manager.py       # Release automation CLI (version, changelog)
│   ├── app_manager.py           # Cross-platform port and process management
│   ├── setup_labels.py          # Create platform labels for Issues integration
│   └── setup_protection.py      # Branch protection setup
├── templates/                   # CI/CD workflow templates
│   ├── github/workflows/        # GitHub Actions workflows
│   └── gitlab/                  # GitLab CI templates
├── config/                      # Example configuration files
│   ├── issues-tracker.example.json
│   ├── github-issues.example.json
│   └── project-config.example.json
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
