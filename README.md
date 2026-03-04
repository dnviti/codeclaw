# claude-task-development-framework

A project-agnostic task and idea management framework for [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

claude-task-development-framework gives your AI-assisted development workflow a structured backbone: ideas are captured, evaluated, promoted to tasks, implemented with quality gates, and tracked to completion — all through plain-text files and Claude Code slash commands.

## Features

- **Two-pipeline workflow** — separate idea evaluation from task execution
- **17 built-in skills** — slash commands for every stage of the development lifecycle
- **Plain-text tracking** — tasks and ideas live in simple `.txt` files, fully version-controllable
- **Automated hooks** — file edits automatically surface related tasks and progress summaries
- **Quality gates** — verification, linting, and smoke tests run before tasks can be closed
- **Project-agnostic** — works with any language, framework, or tech stack
- **Human-in-the-loop** — AI assists, but you make every decision

## Prerequisites

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) installed and configured

## Getting Started

1. **Clone or copy claude-task-development-framework into your project root:**

   ```bash
   git clone https://github.com/YOUR_USERNAME/claude-task-development-framework.git my-project
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

2. **Initialize your project** — run `/project-initialization` to interactively choose a tech stack, scaffold the project, set up git with `main`/`develop` branches, and auto-configure all skills. Or manually customize `CLAUDE.md` — fill in the TODO sections with your project's development commands, environment setup, architecture, and file naming conventions.

3. **Customize `to-do.txt`** — update the project name in the header and define your section structure (e.g., SECTION A — Core Features, SECTION B — Enhancements).

4. **Customize `scripts/task-manager.sh`** — populate the `FILE_TASK_MAP` and `TASK_NAMES` associative arrays as you create tasks.

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
| `/project-initialization` | `/project-initialization [purpose]` | Initialize a new project: choose stack, scaffold, configure git (main + develop branches), set up `.gitignore`, and wire up all skills |

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
| `/github-pages-updater` | `/github-pages-updater` | Update GitHub Pages documentation |

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

## Customization

### CLAUDE.md

Fill in the TODO sections to match your project:

- **Development Commands** — your `dev`, `build`, `test`, and `verify` commands
- **Environment Setup** — how to install dependencies and configure env vars
- **Architecture** — your project's structure and key patterns
- **File Naming Conventions** — your naming rules by layer

### task-manager.sh

Populate the two maps in `scripts/task-manager.sh` as you create tasks:

```bash
declare -A FILE_TASK_MAP=(
  ["auth.service.ts"]="AUTH-001"
  ["LoginPage.tsx"]="AUTH-001"
)

declare -A TASK_NAMES=(
  ["AUTH-001"]="User authentication"
)
```

This enables the post-edit hook to surface related tasks automatically.

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
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
argument-hint: "[arguments]"
---
```

Then invoke it with `/my-skill` in Claude Code.

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
│   └── task-manager.sh          # Post-edit hook: surfaces related tasks
└── .claude/
    ├── settings.json            # Hook configuration
    └── skills/                  # 17 Claude Code skills
        ├── task-create/         # Create tasks
        ├── task-pick/           # Pick up and close tasks
        ├── task-continue/       # Resume in-progress tasks
        ├── task-status/         # View task summary
        ├── task-scout/          # Research new features
        ├── idea-create/         # Add ideas
        ├── idea-approve/        # Promote ideas to tasks
        ├── idea-disapprove/     # Reject ideas
        ├── idea-refactor/       # Update ideas
        ├── project-initialization/ # Initialize new projects
        ├── app-start/           # Start dev environment
        ├── app-stop/            # Stop dev processes
        ├── app-restart/         # Restart dev environment
        ├── docs/                # Manage documentation
        ├── test-engineer/       # Manage tests and CI/CD
        ├── security-audit/      # Security audits
        └── github-pages-updater/# Update GitHub Pages
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
