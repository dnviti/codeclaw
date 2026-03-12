# claude-task-development-framework

A project-agnostic task and idea management framework for [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

claude-task-development-framework gives your AI-assisted development workflow a structured backbone: ideas are captured, evaluated, promoted to tasks, implemented with quality gates, and tracked to completion — all through plain-text files and Claude Code slash commands.

## Features

- **Two-pipeline workflow** — separate idea evaluation from task execution
- **20 built-in skills** — slash commands for every stage of the development lifecycle
- **Adaptive project initialization** — `/project-initialization` scaffolds your project and tailors all skills to your chosen stack, domain, and architecture
- **Plain-text tracking** — tasks and ideas live in simple `.txt` files, fully version-controllable
- **GitHub Issues integration** — optional tri-modal sync with GitHub Issues for task and idea tracking
- **Automated hooks** — file edits automatically surface related tasks and progress summaries
- **Quality gates** — verification, linting, and smoke tests run before tasks can be closed
- **Cross-platform** — works on Linux, macOS, and Windows with automatic OS detection
- **Project-agnostic** — works with any language, framework, or tech stack
- **Human-in-the-loop** — AI assists, but you make every decision

## Prerequisites

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and configured
- Python 3 (used by the bundled scripts)

## Getting Started

1. **Clone or copy claude-task-development-framework into your project root:**

   ```bash
   git clone https://github.com/dnviti/claude-task-development-framework.git my-project
   cd my-project
   ```

   Or copy the claude-task-development-framework files into an existing project:

   ```bash
   cp -r claude-task-development-framework/.claude your-project/
   cp claude-task-development-framework/to-do.txt claude-task-development-framework/progressing.txt claude-task-development-framework/done.txt your-project/
   cp claude-task-development-framework/ideas.txt claude-task-development-framework/idea-disapproved.txt your-project/
   cp -r claude-task-development-framework/scripts your-project/
   cp claude-task-development-framework/CLAUDE.md your-project/
   ```

2. **Initialize your project** — run `/project-initialization` to interactively choose a tech stack, scaffold the project, set up git with `main`/`develop` branches, and auto-configure all skills to match your project. Or manually customize `CLAUDE.md` — fill in the TODO sections with your project's development commands, environment setup, architecture, and file naming conventions.

3. **Customize `to-do.txt`** — update the project name in the header and define your section structure (e.g., SECTION A — Core Features, SECTION B — Enhancements).

4. **(Optional) Enable GitHub Issues integration** — see [GitHub Issues Integration](#github-issues-integration-optional) for setup instructions.

5. **Start Claude Code** in your project directory and use the slash commands:

   ```
   /idea-create Add user authentication with JWT
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

### Task Management

| Skill | Usage | Description |
|-------|-------|-------------|
| `/task-create` | `/task-create [description]` | Create a new task with auto-assigned ID and codebase-informed technical details |
| `/task-pick` | `/task-pick [TASK-CODE]` | Pick up the next task — verifies in-progress work first, runs quality gates |
| `/task-continue` | `/task-continue [TASK-CODE]` | Resume work on a specific in-progress task |
| `/task-status` | `/task-status` | Show current task summary and recommend next tasks |
| `/task-scout` | `/task-scout [focus-area]` | Research industry trends and suggest new features |

### Idea Management

| Skill | Usage | Description |
|-------|-------|-------------|
| `/idea-create` | `/idea-create [description]` | Add a lightweight idea to the backlog for future evaluation |
| `/idea-approve` | `/idea-approve [IDEA-NNN]` | Promote an idea to a full task with technical details |
| `/idea-disapprove` | `/idea-disapprove [IDEA-NNN]` | Reject an idea and archive it |
| `/idea-refactor` | `/idea-refactor [IDEA-NNN]` | Update an idea to reflect codebase changes |

### Project Setup

| Skill | Usage | Description |
|-------|-------|-------------|
| `/project-initialization` | `/project-initialization [purpose]` | Initialize a new project: choose stack, scaffold, configure git, and adapt all skills to your project |

### Development Operations

| Skill | Usage | Description |
|-------|-------|-------------|
| `/app-start` | `/app-start` | Start the development environment with error monitoring |
| `/app-stop` | `/app-stop` | Stop running development processes |
| `/app-restart` | `/app-restart` | Restart the development environment |

### Quality & Documentation

| Skill | Usage | Description |
|-------|-------|-------------|
| `/docs` | `/docs <operation> [category]` | Manage documentation (create, update, verify, sync, claude-md) |
| `/test-engineer` | `/test-engineer [scope] [target]` | Create, update, or optimize tests and CI/CD pipelines |
| `/security-audit` | `/security-audit [scope]` | Perform security audits and generate detailed reports |
| `/github-pages-updater` | `/github-pages-updater` | Create or update a GitHub Pages landing site for the project |

### Release & Publishing

| Skill | Usage | Description |
|-------|-------|-------------|
| `/code-optimize` | `/code-optimize` | Analyze codebase for optimization opportunities across 7 categories and apply selected fixes |
| `/git-publish` | `/git-publish` | Push development branch and open an auto-merging PR into main |
| `/release` | `/release [major\|minor\|patch\|stable]` | Bump version, update changelog, tag, and optionally publish with GitHub Release |

## Adaptive Skill Configuration

When you run `/project-initialization`, it doesn't just scaffold your project — it personalizes the entire skill ecosystem to match your chosen stack and domain. The following skills are adapted with project-specific values:

| Skill | What gets configured |
|-------|---------------------|
| **app-start / stop / restart** | Dev ports, start command, pre-dev setup command |
| **test-engineer** | Test framework, test command, file patterns, CI/CD runtime setup |
| **task-create / idea-approve** | Architecture layer names for task templates |
| **idea-create** | Domain-specific idea categories |
| **docs** | Project-specific documentation categories |
| **task-scout** | Project context (domain, stack, audience) and research categories |
| **release** | Tag prefix, release branch name, changelog path, package.json paths |
| **git-publish** | Development branch name, main branch name |
| **code-optimize** | Verify command reference |

Skills that are already dynamic (task-pick, task-continue, task-status, idea-refactor, idea-disapprove, github-pages-updater, security-audit) read from CLAUDE.md and the codebase at runtime, so they adapt automatically without needing placeholders.

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

Ideas are intentionally **high-level** — no technical details, no file lists. Those are added during `/idea-approve` when the idea becomes a task.

## Typical Workflow

```
0.  /project-initialization                    → Set up project, git, and all skills
1.  /idea-create "Add email notifications"     → Idea added to ideas.txt
2.  /idea-approve IDEA-001                     → Idea promoted to task in to-do.txt
3.  /task-pick                                 → Task moved to progressing.txt, briefing presented
4.  (implement the task)                       → Write code based on the briefing
5.  /task-pick                                 → Verifies implementation, runs quality gates
6.  (confirm completion)                       → Task moved to done.txt
7.  (optional: commit)                         → Changes committed with task code reference
```

You can also create tasks directly with `/task-create` if you don't need the idea evaluation step.

Use `/task-status` at any time to see your current progress and what to work on next.

## GitHub Issues Integration (Optional)

The framework supports an optional GitHub Issues integration that can operate in three modes:

| `enabled` | `sync` | Mode | Data Source |
|-----------|--------|------|-------------|
| `true` | `false` | **GitHub-only** | GitHub Issues only — no local text files |
| `true` | `true` | **Dual sync** | Local files first, then synced to GitHub Issues |
| `false` | — | **Local only** | Local `.txt` files only (default) |

### Setup

1. Copy the example config:
   ```bash
   cp .claude/github-issues.example.json .claude/github-issues.json
   ```

2. Edit `.claude/github-issues.json` — set `"enabled": true`, configure your `"repo"`, and choose `"sync"` mode.

3. Create the required labels on your GitHub repo:
   ```bash
   bash scripts/setup-github-labels.sh
   ```

4. Ensure `gh` CLI is authenticated: `gh auth status`

When GitHub Issues is enabled, all task and idea skills (`/task-create`, `/task-pick`, `/idea-create`, `/idea-approve`, etc.) automatically detect the mode and use the appropriate data source. In GitHub-only mode, tasks are managed entirely through GitHub Issues with status labels. In dual sync mode, local files are the source of truth with GitHub Issues kept in sync.

The framework works fully without GitHub Issues — local-only mode is the default and requires no additional setup.

## Scripts

The framework includes two Python scripts (zero external dependencies, stdlib only):

| Script | Purpose |
|--------|---------|
| `scripts/task_manager.py` | Task/idea file parsing, ID generation, duplicate checking, block movement, file-to-task correlation (used by the post-edit hook) |
| `scripts/app_manager.py` | Cross-platform port checking, process management for dev server lifecycle |

The post-edit hook in `.claude/settings.json` automatically runs `task_manager.py` whenever a file is edited, surfacing related in-progress tasks and a progress summary.

## Customization

### CLAUDE.md

Fill in the TODO sections to match your project (or let `/project-initialization` do it automatically):

- **Development Commands** — your `dev`, `build`, `test`, and `verify` commands, plus `DEV_PORTS`, `START_COMMAND`, `PREDEV_COMMAND`, `VERIFY_COMMAND`
- **Environment Setup** — how to install dependencies and configure env vars
- **Architecture** — your project's structure and key patterns
- **File Naming Conventions** — your naming rules by layer

### Adding New Skills

Create a new directory under `.claude/skills/` with a `SKILL.md` file:

```
.claude/skills/my-skill/SKILL.md
```

The SKILL.md frontmatter defines the skill metadata:

```yaml
---
name: my-skill
description: What this skill does
argument-hint: "[arguments]"
---
```

Then invoke it with `/my-skill` in Claude Code.

## Cross-Platform Notes

- **Python command:** All scripts and skills reference `python3`. On Windows where only `python` is available, substitute `python` for `python3` in all commands and update the reference in `.claude/settings.json`.
- **Port management:** `scripts/app_manager.py` automatically uses the correct OS tools — `lsof`/`ss` on Unix, `netstat`/`taskkill` on Windows.
- **File search:** `scripts/task_manager.py find-files` provides cross-platform file discovery.

## Project Structure

```
claude-task-development-framework/
├── CLAUDE.md                    # Project guidance for Claude Code (customize this)
├── README.md                    # This file
├── to-do.txt                    # Pending tasks [ ] and blocked tasks [!]
├── progressing.txt              # In-progress tasks [~]
├── done.txt                     # Completed tasks [x]
├── ideas.txt                    # Ideas awaiting evaluation
├── idea-disapproved.txt         # Rejected ideas archive
├── scripts/
│   ├── task_manager.py          # Task/idea management CLI and post-edit hook
│   ├── app_manager.py           # Cross-platform port and process management
│   └── setup-github-labels.sh   # Create GitHub labels for Issues integration
└── .claude/
    ├── settings.json            # Hook configuration
    ├── github-issues.example.json # GitHub Issues integration config template
    └── skills/                  # 20 Claude Code skills
        ├── task-create/         # Create tasks
        ├── task-pick/           # Pick up and close tasks
        ├── task-continue/       # Resume in-progress tasks
        ├── task-status/         # View task summary
        ├── task-scout/          # Research new features
        ├── idea-create/         # Add ideas
        ├── idea-approve/        # Promote ideas to tasks
        ├── idea-disapprove/     # Reject ideas
        ├── idea-refactor/       # Update ideas
        ├── project-initialization/ # Initialize and configure projects
        ├── app-start/           # Start dev environment
        ├── app-stop/            # Stop dev processes
        ├── app-restart/         # Restart dev environment
        ├── docs/                # Manage documentation
        ├── test-engineer/       # Manage tests and CI/CD
        ├── security-audit/      # Security audits
        ├── github-pages-updater/# GitHub Pages site management
        ├── code-optimize/       # Codebase optimization analysis
        ├── git-publish/         # PR-based publishing to main
        └── release/             # Version bumping and release management
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
