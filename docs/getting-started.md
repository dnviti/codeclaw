---
title: Getting Started
description: Installation, prerequisites, first run, and initial project setup
generated-by: ctdf-docs
generated-at: 2026-03-18T00:00:00Z
source-files:
  - README.md
  - .claude-plugin/plugin.json
  - .claude-plugin/marketplace.json
  - config/project-config.example.json
  - config/ollama-config.example.json
  - config/issues-tracker.example.json
---

## Overview

This guide walks you through installing CTDF, setting up your first project, and running your first workflow cycle from idea to release.

## Prerequisites

| Requirement | Purpose |
|-------------|---------|
| [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) | The host AI coding assistant that runs CTDF skills |
| Python 3 | Runtime for all CTDF automation scripts (stdlib only, no pip packages needed for core features) |
| Git | Version control; CTDF uses worktrees, branches, and tags |
| `gh` CLI (optional) | GitHub Issues integration, PR management, and branch protection setup |
| `glab` CLI (optional) | GitLab Issues integration |
| [Ollama](https://ollama.ai) (optional) | Local model integration for tool call offloading |

**Optional: Vector memory dependencies (for semantic search and MCP):**
```bash
pip install lancedb sentence-transformers mcp
```

## Installation

### From Marketplace

The recommended way to install CTDF:

```bash
/plugin marketplace add https://github.com/dnviti/claude-task-development-framework
/plugin install ctdf@dnviti-claude-task-development-framework
```

### Local Development

For contributing to CTDF or running from source:

```bash
git clone https://github.com/dnviti/claude-task-development-framework.git
claude --plugin-dir ./claude-task-development-framework
```

## First-Time Setup

### 1. Initialize Your Project

Run the setup skill in your project directory:

```
/setup My Project Name
```

This creates:
- **Task files** — `to-do.txt`, `progressing.txt`, `done.txt`
- **Idea files** — `ideas.txt`, `idea-disapproved.txt`
- **Branch strategy** — Configures `develop`, `staging`, `main` branches
- **CLAUDE.md** — Adds framework guidance with project-specific variables
- **`.claude/project-config.json`** — Project configuration including vector memory and social announce settings

The setup wizard guides you through:
1. Project name and context
2. Branch strategy configuration
3. Vector memory setup (enables semantic search via MCP)
4. Social media announcement configuration (for release announcements)
5. Ollama local model integration (optional)

### 2. Configure Issues Integration (Optional)

If you want GitHub or GitLab Issues integration:

```bash
# Copy the example config
cp <plugin-dir>/config/issues-tracker.example.json .claude/issues-tracker.json

# Edit with your repository details
# Set "enabled": true and "repo": "owner/repo"
```

Three modes are available:

| `enabled` | `sync` | Mode | Where data lives |
|-----------|--------|------|------------------|
| `false` | -- | **Local only** | `.txt` files (default) |
| `true` | `false` | **Platform only** | GitHub/GitLab Issues (+ release state in platform issue) |
| `true` | `true` | **Dual sync** | Local files synced to Issues |

> **Multi-user tip:** In platform-only mode, the release pipeline state is stored in a GitHub/GitLab issue (`ctdf-release-state` label), so all collaborators share the same state without needing a `git pull`.

### 3. Configure Ollama (Optional)

To route tool calls and tasks to a local language model:

```bash
# Auto-detect hardware and set up Ollama
python3 scripts/ollama_manager.py detect-hardware
python3 scripts/ollama_manager.py recommend-model

# Copy and edit the config
cp <plugin-dir>/config/ollama-config.example.json .claude/ollama-config.json
# Set "enabled": true and configure offloading.level (0-10)
```

### 4. Set Up Branch Protection (Optional)

```bash
python3 scripts/setup_protection.py --branch main --required-reviews 1
```

### 5. Create Platform Labels (Optional)

```bash
python3 scripts/setup_labels.py
```

## Your First Workflow

### Step 1: Capture an Idea

```
/idea create Add user authentication with JWT
```

This adds a lightweight proposal to `ideas.txt` with an auto-generated ID like `IDEA-AUTH-0001`.

### Step 2: Approve the Idea

```
/idea approve IDEA-AUTH-0001
```

The idea is promoted to a full task in `to-do.txt` with technical details, file lists, and dependencies.

### Step 3: Create a Release Milestone

```
/release create 1.0.0
```

### Step 4: Schedule the Task

```
/task schedule AUTH-0001 to 1.0.0
```

### Step 5: Pick Up the Task

```
/task pick AUTH-0001
```

This:
1. Creates an isolated git worktree at `.worktrees/task/AUTH-0001/`
2. Presents a technical briefing (description, approach, files to modify)
3. Moves the task from `to-do.txt` to `progressing.txt`

### Step 6: Implement and Close

After implementing the task, confirm completion via the `/task pick` gate to:
1. Post a testing guide to the platform issue
2. Mark the task done
3. Remove the worktree (merging the task branch back into local develop)
4. Create a PR into `develop`

### Step 7: Release

```
/release continue 1.0.0
```

The 9-stage release pipeline runs:
1. Create release branch
2. Verify all tasks are complete
3. Fetch open PRs
4. Analyze each PR with parallel sub-agents (optimize, security scan, fix, merge)
5. Merge to staging + local build gate + staging tag
6. Run integration tests
7. Merge to main + version bump + tag + CI monitoring + docs sync
8. Users testing
9. Cleanup (close milestone, clear state, GC vector memory)

## Quick Reference

| Command | What it does |
|---------|-------------|
| `/setup [name]` | Initialize project tracking |
| `/idea create [desc]` | Add a new idea |
| `/idea approve [ID]` | Promote idea to task |
| `/task pick` | Pick up next task |
| `/task status` | Show task summary |
| `/release continue X.X.X` | Run full release pipeline |
| `/release resume` | Resume interrupted release |
| `/docs generate` | Generate documentation |
| `/docs sync` | Update stale documentation |

## Yolo Mode

Append `yolo` to any command to auto-confirm all gates:

```
/release continue 1.0.0 yolo
/task pick all yolo
/docs generate yolo
```

Yolo mode never auto-confirms destructive operations (e.g., `/docs reset`) or "Abort release" options.

## Next Steps

- Read [Configuration](configuration.md) for detailed settings including Ollama, vector memory, and social announce
- Read [Architecture](architecture.md) for system design details including the PreToolUse hook and release state sync
- Read [Development](development.md) for contributing guidelines
