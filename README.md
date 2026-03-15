# CTDF — Claude Task Development Framework

A project-agnostic task and idea management plugin for [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

CTDF gives your AI-assisted development workflow a structured backbone: ideas are captured, evaluated, promoted to tasks, implemented with quality gates, and tracked to completion — all through plain-text files and Claude Code slash commands. A gated release pipeline with parallel sub-agent orchestration enforces strict development rules from branch creation to production tagging.

## Features

- **Two-pipeline workflow** — separate idea evaluation from task execution
- **5 streamlined skills** — unified slash commands (`/task`, `/idea`, `/release-start`, `/setup`, `/update`)
- **Gated release pipeline** — 9 sequential stages with user-confirmed gates, feedback loops, parallel sub-agents, and mandatory local build verification before every push
- **Per-PR sub-agent analysis** — each PR gets an independent agent for code optimization, security scanning, fix application, and automated merge
- **Post-tag CI monitoring** — parallel agents monitor remote CI after tagging, auto-fix failures, and move tags when needed (platform-only)
- **Explicit version bump gate** — all manifest files are discovered, verified, and updated with user confirmation before tagging
- **Three-branch strategy** — enforced `develop` → `staging` → `main` promotion path with mandatory staging validation
- **Docker tagging** — staging builds the `latest` tag, production builds `stable` + versioned tags
- **Claude Code plugin** — install via marketplace, uninstall cleanly, update easily
- **Plain-text tracking** — tasks and ideas live in simple `.txt` files, fully version-controllable
- **GitHub/GitLab Issues integration** — optional tri-modal sync with GitHub or GitLab Issues
- **Quality gates** — verification, linting, and smoke tests run before tasks can be closed
- **Cross-platform** — works on Linux, macOS, and Windows with automatic OS detection
- **Project-agnostic** — works with any language, framework, or tech stack
- **Human-in-the-loop** — AI assists, but you make every decision at every gate

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

   This creates the task/idea files (`to-do.txt`, `progressing.txt`, `done.txt`, `ideas.txt`, `idea-disapproved.txt`), configures the three-branch strategy, and adds framework guidance to your `CLAUDE.md`.

3. **Start using skills:**

   ```
   /idea create Add user authentication with JWT
   /idea approve IDEA-AUTH-0001
   /task pick
   /task status
   ```

4. **When ready to release:**

   ```
   /release-start 1.0.0
   ```

## How It Works

CTDF enforces strict development rules through two connected pipelines and a gated release process.

### Idea Pipeline

Ideas are lightweight proposals — *what* and *why* only. They must be explicitly approved before entering the task pipeline.

```mermaid
flowchart LR
    A[ideas.txt] -->|/idea approve| B[to-do.txt<br>becomes a task]
    A -->|/idea disapprove| C[idea-disapproved.txt<br>archived]
```

### Task Pipeline

Tasks are actionable work items with technical details, file lists, and dependencies. Each task gets an isolated git worktree for parallel development.

```mermaid
flowchart LR
    A["to-do.txt [ ]"] -->|"/task pick"| B["progressing.txt [~]"]
    B -->|"verify + close"| C["done.txt [x]"]
    B -.->|worktree created| D[".worktrees/task/code/"]
    C -.->|worktree removed| D
```

### Release Pipeline — Flow Diagram

The release pipeline enforces a strict sequential process with built-in feedback loops. Every stage is gated — the release advances only when the stage passes ("OK"). Issues found at any stage create patch tasks (RPAT) that loop back to Stage 2.

```mermaid
flowchart TD
    S1["1. CREATE BRANCH<br>release/X.X.X from develop"]
    S2["2. TASKS LOOP<br>Pick up & implement tasks<br>(parallel subagents)"]
    S3["3. FETCH OPEN PRs<br>List PRs on release branch"]
    S4["4. PER-PR SUB-AGENTS<br>(one agent per PR, parallel)<br>analyze → optimize → security →<br>comment → fix → merge → cleanup"]
    S5["5. MERGE TO STAGING<br>develop → staging<br>Local build gate → push<br>Builds 'latest' Docker tag"]
    S6["6. INTEGRATION TESTS<br>Full test suite on staging"]
    S7["7. MERGE TO MAIN + TAG<br>staging → main | Version bump gate |<br>Local build gate | Tag: vX.X.X |<br>CI monitoring (platform-only) |<br>Builds 'stable' + 'vX.X.X' Docker tags"]
    S8["8. USERS TESTING<br>Release is live"]
    S9["9. END<br>Cleanup, final report"]

    S1 -->|OK| S2
    S2 -->|OK| S3
    S3 --> S4
    S4 -->|ALL PRs DONE| S5
    S5 -->|OK| S6
    S6 -->|OK| S7
    S7 --> S8
    S8 --> S9

    S2 -. "self-loop<br>(RPAT)" .-> S2
    S4 -. "unresolved issues<br>create RPAT" .-> S2
    S5 -. "merge/build issues<br>create RPAT" .-> S2
    S6 -. "test failures<br>create RPAT" .-> S2
    S7 -. "CI failure<br>fix → tag move" .-> S7
```

### Stage 7 — Internal Flow Detail

Stage 7 contains multiple sub-gates including version bumping, local build verification, and conditional CI monitoring with a tag-move self-healing loop.

```mermaid
flowchart TD
    M["7a. Merge staging → main<br>(Merge Template)"]
    CL["7b-c. Generate + update changelog"]
    VB["7d. VERSION BUMP GATE<br>Discover manifests → diff table →<br>user confirmation"]
    CT["7e. Commit + tag"]
    LB["7e-bis. LOCAL BUILD GATE<br>verify_command before push"]
    P["7f. Push production + tags"]
    CI{"7f-bis. Platform<br>enabled?"}
    SKIP["Skip to 7g"]
    DISC{"CI workflows<br>found?"}
    MON["7f-ter. Spawn monitor agents<br>(parallel, one per workflow)"]
    RES["7f-quater. Collect results"]
    FIX{"Any fix<br>applied?"}
    TM["7f-quinquies. TAG MOVE<br>delete tag → pull fix →<br>local build gate → re-tag →<br>delete + recreate release"]
    REL["7g. Create platform release"]

    M --> CL --> VB --> CT --> LB --> P --> CI
    CI -->|"no / not enabled"| SKIP --> REL
    CI -->|yes| DISC
    DISC -->|"no workflows"| REL
    DISC -->|"workflows found"| MON --> RES --> FIX
    FIX -->|no| REL
    FIX -->|"yes (loop)"| TM --> CI
```

### Feedback Loop Summary

| Stage | Issues go to | Then loops back to |
|---|---|---|
| Tasks Loop | Rebase Patch (RPAT) | itself (self-loop) |
| Per-PR Sub-Agent (unresolved) | Release Patches (RPAT) | Tasks Loop |
| Merge to Staging | Release Patches (RPAT) | Tasks Loop |
| Integration Tests | Release Patches (RPAT) | Tasks Loop |
| Local build pre-push (5 / 7) | RPAT task | Tasks Loop |
| Post-Tag CI Monitor (7f) | Fix → PR → merge → tag move | CI Monitor (7f-bis), same stage |

### Key Rules Enforced

1. **Stages are sequential and gated** — never skip a stage without explicit user override at a GATE.
2. **Sub-agents run in parallel, one per PR** — each follows the full analyze → optimize → security → comment → fix → merge → cleanup sequence.
3. **Sub-agents fix what they can, escalate what they can't** — unresolved issues become RPAT tasks and loop back.
4. **Every PR comment is structured** — findings and fixes are posted as separate, labeled comments for audit trail.
5. **Worktrees are always cleaned up** — after PR merge and at pipeline end, no stale worktrees survive.
6. **Staging = Main minus public visibility** — if it wouldn't survive on main, it doesn't pass staging.
7. **Tags are only created on the production branch** — after full pipeline through staging.
8. **Loop counter enforced** — warnings at 3 iterations, forced choice at 5. Prevents infinite loops.
9. **Local build and tests must pass before any push** — catches regressions from version bump commits or post-merge changes.
10. **Tags are moved, never recreated** — when post-tag CI fixes are needed: delete tag → pull fix → rebuild → re-tag → delete and recreate platform release.
11. **Version fields in all manifests must be bumped before tagging** — explicit gate with user confirmation at Step 7d.
12. **Remote CI monitoring is platform-only** — without a connected platform, local build success is the sole pre-release gate.

### Branch Strategy

```mermaid
flowchart LR
    DEV["develop<br><i>Active development<br>feature merges, task branches</i>"]
    STG["staging<br><i>Pre-release validation<br>'latest' Docker image</i>"]
    MAIN["main<br><i>Production: tagged releases<br>'stable' + 'vX.X.X' Docker images</i>"]

    DEV -->|merge| STG -->|merge + tag| MAIN
```

### Docker Tagging Strategy

| Branch | Trigger | Docker Tags Built |
|--------|---------|-------------------|
| `staging` | Push to staging | `latest` |
| `main` | Release tag push (`v*`) | `stable`, `vX.X.X` |

## Skills Reference

### Setup & Project

| Skill | Usage | Description |
|-------|-------|-------------|
| `/setup` | `/setup [project name]` | Initialize task/idea tracking, branches, CI/CD, and issues integration |
| `/setup env` | `/setup env [section]` | Scan project to detect tech stack, dependencies, and commands; update CLAUDE.md |
| `/setup init` | `/setup init [purpose]` | Full project scaffold: choose stack, configure git, adapt all skills |
| `/setup branch-strategy` | `/setup branch-strategy` | Configure develop/staging/main branch strategy |
| `/setup agentic-fleet` | `/setup agentic-fleet` | Set up AI-powered CI/CD pipelines for idea scouting and task implementation |
| `/update` | `/update [category]` | Update CTDF-managed files (pipelines, scripts, prompts, skills, CLAUDE.md) to the latest plugin version |

### Task Management

| Skill | Usage | Description |
|-------|-------|-------------|
| `/task pick` | `/task pick [CODE]` | Pick up the next task — creates worktree, presents briefing, runs quality gates |
| `/task create` | `/task create [description]` | Create a new task with auto-assigned ID and codebase-informed technical details |
| `/task continue` | `/task continue [CODE]` | Resume work on a specific in-progress task |
| `/task status` | `/task status` | Show current task summary and recommend next tasks |

### Idea Management

| Skill | Usage | Description |
|-------|-------|-------------|
| `/idea create` | `/idea create [description]` | Add a lightweight idea to the backlog for future evaluation |
| `/idea approve` | `/idea approve [IDEA-CODE]` | Promote an idea to a full task with technical details |
| `/idea disapprove` | `/idea disapprove [IDEA-CODE]` | Reject an idea and archive it |
| `/idea refactor` | `/idea refactor [IDEA-CODE]` | Update ideas to reflect codebase changes |
| `/idea scout` | `/idea scout [focus area]` | Research trends and online sources to suggest new ideas |

### Release

| Skill | Usage | Description |
|-------|-------|-------------|
| `/release-start` | `/release-start [X.X.X]` | Full 9-stage release pipeline with parallel sub-agents, local build gates, version bump verification, staging validation, post-tag CI monitoring, and production tagging |
| `/release-start resume` | `/release-start resume` | Resume a release pipeline from the last saved stage |
| `/release-start security-only` | `/release-start security-only` | Run security analysis alone on the current branch |
| `/release-start test-only` | `/release-start test-only` | Run integration tests alone on the current branch |

## Typical Workflow

```
0.  /setup "My Project"                     → Create tracking files + branches
1.  /idea create "Add email notifications"  → Idea added to ideas.txt
2.  /idea approve IDEA-NOTIF-0001           → Idea promoted to task in to-do.txt
3.  /task pick                              → Worktree created, briefing presented
4.  (implement the task)                    → Write code in isolated worktree
5.  /task pick                              → Verify, close task, create PR
6.  /release-start 1.0.0                    → Full pipeline: tasks → PRs → staging → main
```

## Issues Tracker Integration (Optional)

The plugin supports optional GitHub/GitLab Issues integration that can operate in three modes:

| `enabled` | `sync` | Mode | Data Source |
|-----------|--------|------|-------------|
| `true` | `false` | **Platform-only** | GitHub/GitLab Issues only — no local text files |
| `true` | `true` | **Dual sync** | Local files first, then synced to platform issues |
| `false` | — | **Local only** | Local `.txt` files only (default) |

To enable, run `/setup` and choose your platform when prompted, or manually configure:

```bash
cp <plugin-dir>/config/issues-tracker.example.json .claude/issues-tracker.json
# Edit .claude/issues-tracker.json with your repo and settings
```

## Agentic Fleet Pipelines

CTDF includes automated CI/CD pipelines that use Claude Code to perform idea scouting and task implementation without human intervention.

| Pipeline | Trigger | What it does |
|----------|---------|--------------|
| **Idea Scout** | On release publish | Scans trends, documentation, and community sources to suggest new ideas |
| **Task Implementation** | Cron-based schedule | Picks up pending tasks, implements them in isolated worktrees, and opens PRs |
| **Docs** | On release publish | Updates documentation based on code changes |

Each pipeline uses a **three-agent architecture**: Orchestrator, Worker, and Memory Builder. Supports both **GitHub Actions** and **GitLab CI/CD** with multiple AI providers (Claude, OpenAI Codex, OpenClaw).

```bash
/setup agentic-fleet
```

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
  using JWT.

  TECHNICAL DETAILS:
  Backend:
    - POST /api/auth/register — validate input, hash password, store user
    - POST /api/auth/login — verify credentials, return JWT

  Files involved:
    CREATE:  src/services/auth.service.ts
    MODIFY:  src/app.ts
```

Key formatting rules: 78-dash separators, em dash (`—`) in title, 2-space indent, globally sequential task codes.

## Plugin Structure

```
claude-task-development-framework/
├── .claude-plugin/
│   ├── plugin.json              # Plugin manifest
│   └── marketplace.json         # Marketplace definition
├── skills/                      # 5 unified Claude Code skills
│   ├── setup/                   # Initialize, configure, scaffold projects
│   ├── update/                  # Update CTDF-managed files
│   ├── task/                    # Pick, create, continue, status
│   ├── idea/                    # Create, approve, disapprove, refactor, scout
│   └── release-start/           # 9-stage gated release pipeline
├── scripts/                     # Python automation scripts (stdlib only)
│   ├── task_manager.py          # Task/idea management CLI and post-edit hook
│   ├── release_manager.py       # Release automation CLI (version, changelog)
│   ├── skill_helper.py          # Consolidated skill helper (context, dispatch, worktrees)
│   ├── agent_runner.py          # Multi-provider agentic fleet runner
│   ├── app_manager.py           # Cross-platform port and process management
│   ├── codebase_analyzer.py     # Agentic fleet codebase analysis
│   ├── memory_builder.py        # Agentic fleet memory persistence
│   ├── setup_labels.py          # Create platform labels for Issues integration
│   └── setup_protection.py      # Branch protection setup
├── templates/                   # CI/CD workflow templates
│   ├── github/workflows/        # GitHub Actions (ci, release, staging, security, agentic)
│   ├── gitlab/                  # GitLab CI templates
│   └── prompts/                 # Agentic fleet prompt templates
├── config/                      # Example configuration files
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

# After updating the plugin, refresh CTDF-managed files in your project
/update
```

```bash
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
