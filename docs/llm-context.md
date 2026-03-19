---
title: LLM Context
description: Consolidated single-file reference for LLM/bot consumption — architecture, APIs, configuration, and quick-start
generated-by: claw-docs
generated-at: 2026-03-18T00:00:00Z
source-files:
  - README.md
  - scripts/task_manager.py
  - scripts/release_manager.py
  - scripts/skill_helper.py
  - scripts/ollama_manager.py
  - scripts/vector_memory.py
  - scripts/hooks/pre_tool_offload.py
  - .claude-plugin/plugin.json
  - config/project-config.example.json
  - config/ollama-config.example.json
---

<!-- MACHINE-READABLE METADATA
project: CodeClaw
version: 3.5.1
type: claude-code-plugin
language: python3
dependencies: stdlib-only (lancedb+sentence-transformers+mcp optional for vector memory)
platforms: linux, macos, windows
repository: https://github.com/dnviti/codeclaw
license: MIT
skills: task, idea, release, docs, setup, update, tests, help
hooks: PreToolUse(Bash|Read|Grep|Glob|Edit|Write), PostToolUse(Edit|Write)
-->

## Project Summary

CodeClaw is a project-agnostic Claude Code plugin that provides:
1. **Task and idea management** — Structured plain-text files (`to-do.txt`, `progressing.txt`, `done.txt`, `ideas.txt`)
2. **GitHub/GitLab Issues integration** — Local-only, platform-only, or dual-sync modes
3. **Gated 9-stage release pipeline** — Branch creation → task verification → PR analysis → staging → testing → production tagging → announcement → cleanup
4. **Ollama local model offloading** — Route tool calls and tasks to a local LLM with configurable offloading level (0–10) and full tool-calling loop
5. **Always-on vector memory** — Semantic indexing via LanceDB, auto-updated on file edits, accessible via MCP
6. **Platform release state sync** — In platform-only mode, release state is stored in a `claw-release-state` GitHub/GitLab issue shared by all collaborators
7. **Agentic CI/CD fleet** — Autonomous task implementation, idea scouting, and documentation sync via GitHub Actions / GitLab CI

---

## Architecture Overview

### Three Layers

```
Skills (SKILL.md)     → Declarative AI behavior (Markdown)
Scripts (*.py)        → Deterministic logic (Python 3 stdlib)
Hooks (hooks.json)    → Event-driven integration (PreToolUse + PostToolUse)
```

### Key Scripts

| Script | Purpose |
|--------|---------|
| `scripts/task_manager.py` | Task/idea CRUD, platform sync, worktree management |
| `scripts/release_manager.py` | Version detection, changelog, release state (local + platform) |
| `scripts/skill_helper.py` | Context gathering, argument dispatch, worktree setup |
| `scripts/ollama_manager.py` | Local model routing, hardware detection, tool-calling loop |
| `scripts/vector_memory.py` | LanceDB indexing, MCP server, GC |
| `scripts/hooks/pre_tool_offload.py` | PreToolUse: evaluate tool calls for Ollama offloading |

### Hooks

```json
{
  "PreToolUse": {
    "matcher": "Bash|Read|Grep|Glob|Edit|Write",
    "handler": "scripts/hooks/pre_tool_offload.py $CLAUDE_TOOL_NAME $CLAUDE_TOOL_INPUT"
  },
  "PostToolUse": {
    "matcher": "Edit|Write",
    "handlers": [
      "scripts/task_manager.py hook $CLAUDE_FILE_PATH",
      "scripts/vector_memory.py hook $CLAUDE_FILE_PATH"
    ]
  }
}
```

### Branch Strategy

```
develop → staging → main
```

- `develop` — All feature PRs; worktree task branches merge here on teardown
- `staging` — Pre-release validation; tagged `vX.X.X-staging`
- `main` — Production; tagged `vX.X.X`

---

## Key APIs

### task_manager.py CLI

```bash
python3 scripts/task_manager.py <subcommand> [options]
```

Essential subcommands:
- `list --status todo|progressing|done|idea --format summary|json`
- `parse CODE` — parse a task block
- `next-id --type task|idea` — next sequential ID
- `move CODE --to progressing|done|todo`
- `platform-cmd OPERATION [key=value...]` — GitHub/GitLab operations
- `setup-task-worktree --task-code CODE --base-branch develop`
- `remove-worktree --task-code CODE` — merges branch into develop, then removes
- `list-release-tasks --version X.X.X`
- `create-patch-task --source SOURCE --title TITLE --release X.X.X`

### release_manager.py CLI

```bash
python3 scripts/release_manager.py <subcommand> [options]
```

Essential subcommands:
- `full-context` — complete release context as JSON
- `release-state-get` — read pipeline state (local file OR platform issue)
- `release-state-set --version V --stage N --stage-name NAME [--increment-loop] [--mark-gate-approved N]`
- `release-state-clear` — clear state (close platform issue in platform-only mode)
- `merge-check --source BRANCH --target BRANCH`
- `parse-commits --since TAG`
- `generate-changelog --version V --date YYYY-MM-DD`
- `update-versions --version V` — auto-discover and bump all manifests

### skill_helper.py CLI

```bash
python3 scripts/skill_helper.py <subcommand> [options]
```

Essential subcommands:
- `context` — platform config, branches, worktrees, submodules as JSON
- `dispatch --skill NAME --args TEXT` — parse flow, yolo, task code
- `setup-task-worktree --task-code CODE --base-branch BRANCH`
- `status-report` — task counts, in-progress, next recommended, worktrees

### ollama_manager.py CLI

```bash
python3 scripts/ollama_manager.py <subcommand> [options]
```

Essential subcommands:
- `detect-hardware` — RAM, VRAM, GPU, CPU
- `recommend-model` — best model tier for hardware
- `should-offload --tool NAME --args TEXT --level N` → true/false
- `get-offload-level` → integer 0–10
- `query --prompt TEXT` → Ollama response

### pre_tool_offload.py (Hook)

**Input:** `CLAUDE_TOOL_NAME`, `CLAUDE_TOOL_INPUT` (env vars or positional args)

**Output (stdout):**
```json
{"action": "proceed"}
// or
{"action": "offload", "provider": "ollama", "model": "qwen2.5-coder:7b", "api_base": "http://localhost:11434", "tool_name": "Bash", "offload_level": 5}
```

Always exits 0. Never blocks Claude. Applies NFKC normalization to prevent Unicode homoglyph bypass of exclude patterns.

---

## Configuration Reference

### `.claude/issues-tracker.json`

```json
{
  "platform": "github",   // "github" | "gitlab"
  "enabled": true,        // enable platform Issues
  "sync": false,          // true = dual-sync, false = platform-only
  "repo": "owner/repo"
}
```

> When `enabled: true, sync: false` (platform-only): release state is stored in a `claw-release-state` platform issue.

### `.claude/project-config.json` (key fields)

```json
{
  "verify_command": "",        // run before staging/production push
  "tag_prefix": "v",
  "changelog_file": "CHANGELOG.md",
  "vector_memory": {
    "enabled": true,           // always-on semantic indexing
    "embedding_provider": "local",
    "index_path": ".claude/memory/vectors"
  },
  "mcp_server": {
    "enabled": true,           // MCP server for vector search
    "auto_start": true
  },
  "ollama": {
    "enabled": false,
    "offloading_level": 5      // 0-10
  }
}
```

### `.claude/ollama-config.json` (key fields)

```json
{
  "enabled": false,
  "model": "",                 // auto-recommended if empty
  "api_base": "http://localhost:11434",
  "offloading": {
    "level": 5,                // 0=off, 10=route everything
    "tool_calls": {
      "enabled": false,        // enable PreToolUse hook routing
      "exclude_patterns": ["git push", "git reset", "rm -rf", "sudo"]
    }
  },
  "tool_calling": {
    "enabled": true,           // Ollama's own tool-calling loop
    "max_tool_rounds": 10
  }
}
```

---

## Quick-Start Commands

```bash
# Install
/plugin marketplace add https://github.com/dnviti/codeclaw
/plugin install claw@dnviti-plugins

# Initialize project
/setup "My Project"

# Idea → Task → Release cycle
/idea create "Feature description"
/idea approve IDEA-FEAT-0001
/task pick FEAT-0001
# ... implement ...
# (confirm task done via gate)
/release continue 1.0.0

# Resume interrupted release
/release resume

# Update documentation
/docs sync
```

---

## Release State Machine

The 9-stage release pipeline persists state via `release-state-get/set`:

| Stage | Name | Key Action |
|-------|------|------------|
| 1 | Create Branch | `git checkout -b release/X.X.X develop` |
| 2 | Task Readiness Gate | Verify all release tasks are `done` |
| 3 | Fetch Open PRs | `gh pr list --base develop --state open` |
| 4 | Per-PR Sub-Agent Analysis | Parallel: analyze → fix → merge each PR |
| 5 | Merge to Staging | develop → staging; tag `vX.X.X-staging`; push |
| 6 | Integration Tests | Run `verify_command` or auto-detected test suite |
| 7 | Merge to Main + Tag | staging → main; bump versions; tag `vX.X.X`; push; CI monitor |
| 7h | Docs Sync | `/docs sync` auto-runs |
| 8 | Users Testing | Release is live |
| 8.5 | Announce | Social media via configured platforms |
| 9 | End | Close milestone; clear state; GC vector memory |

---

## Offloading Level Guide

| Level | What routes to Ollama |
|-------|-----------------------|
| 0 | Nothing |
| 3 | Simple Bash (ls, cat, git status) |
| 4 | Simple edits (formatting, whitespace) |
| 6 | Search/read (Grep, Glob, Read pattern ops) |
| 7 | Complex Bash (piped commands) |
| 8 | Structural edits (class, function changes) |
| 10 | All tools except always-excluded patterns |

Always-excluded (regardless of level): `git push`, `git reset`, `rm -rf`, `sudo`, `chmod`, `chown`

---

## File Structure

```
.claude/
├── issues-tracker.json     # Platform integration config
├── project-config.json     # Project settings
├── ollama-config.json      # Ollama offloading config
├── releases.json           # Release plan (local/dual mode)
├── release-state.json      # Pipeline state (local/dual mode)
├── agentic-provider.json   # CI/CD fleet config
└── memory/vectors/         # LanceDB vector index (gitignored)

scripts/
├── task_manager.py
├── release_manager.py
├── skill_helper.py
├── ollama_manager.py
├── vector_memory.py
├── docs_manager.py
├── agent_runner.py
├── hooks/
│   └── pre_tool_offload.py
└── analyzers/

skills/
├── task/SKILL.md
├── idea/SKILL.md
├── release/SKILL.md
├── docs/SKILL.md
├── setup/SKILL.md
├── update/SKILL.md
├── tests/SKILL.md
└── help/SKILL.md

hooks/hooks.json            # PreToolUse + PostToolUse definitions
.claude-plugin/plugin.json  # Plugin manifest (version: 3.5.1)
```
