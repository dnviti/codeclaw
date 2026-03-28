---
title: LLM Context
description: Consolidated single-file reference for LLM/bot consumption — architecture, APIs, configuration, and quick-start
generated-by: claw-docs
generated-at: 2026-03-20T00:25:00Z
source-files:
  - README.md
  - CLAUDE.md
  - docs/index.md
  - docs/architecture.md
  - docs/getting-started.md
  - docs/configuration.md
  - docs/api-reference.md
  - docs/development.md
  - scripts/task_manager.py
  - scripts/release_manager.py
  - scripts/skill_helper.py
  - scripts/ollama_manager.py
  - scripts/vector_memory.py
  - scripts/mcp_server.py
  - scripts/memory_protocol.py
  - scripts/memory_lock.py
  - scripts/memory_orchestrator.py
  - scripts/test_manager.py
  - scripts/hooks/pre_tool_offload.py
  - .claude-plugin/plugin.json
  - config/project-config.example.json
  - config/ollama-config.example.json
---

<!-- MACHINE-READABLE METADATA
project: CodeClaw
version: 4.0.2
type: claude-code-plugin
language: python3
dependencies: stdlib-only (lancedb+onnxruntime+tokenizers+mcp optional for vector memory)
platforms: linux, macos, windows
repository: https://github.com/dnviti/codeclaw
license: MIT
skills: task, idea, release, docs, setup, update, tests, help, crazy
hooks: PreToolUse(Bash|Read|Grep|Glob|Edit|Write), PostToolUse(Edit|Write)
-->

## Project Summary

CodeClaw is a project-agnostic Claude Code plugin (v4.0.2) that provides:
1. **Task and idea management** — Structured plain-text files (`to-do.txt`, `progressing.txt`, `done.txt`, `ideas.txt`)
2. **GitHub/GitLab Issues integration** — Local-only, platform-only, or dual-sync modes
3. **Gated 9-stage release pipeline** — Branch creation → task verification → PR analysis → staging → testing → production tagging → announcement → cleanup
4. **Ollama local model offloading** — Route tool calls and tasks to a local LLM with configurable offloading level (0–10) and full tool-calling loop
5. **Unified memory orchestrator** — Tandem multi-backend coordination (LanceDB + SQLite FTS5 + RLM) with semantic indexing, auto-updated on file edits, accessible via MCP
6. **Semantic intelligence** — `/task`, `/idea`, `/docs`, `/tests`, `/help` skills powered by vector search
7. **Platform release state sync** — In platform-only mode, release state is stored in a `claw-release-state` GitHub/GitLab issue shared by all collaborators
8. **Agentic CI/CD fleet** — Autonomous task implementation, idea scouting, and documentation sync via GitHub Actions / GitLab CI
9. **[BETA] /crazy skill** — Fully autonomous end-to-end project builder
10. **Image generation** — On-demand with 4 provider backends (DALL-E, Replicate, Stability AI, local)
11. **Frontend design wizard** — Template search, theme selection, color palette picker
12. **Multi-platform support** — Claude Code, OpenCode, OpenClaw, Cursor, Windsurf, Continue.dev, GitHub Copilot, Aider

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
| `scripts/task_manager.py` | Task/idea CRUD, platform sync, branch management (~2,700 lines) |
| `scripts/release_manager.py` | Version detection, changelog, release state (local + platform) |
| `scripts/skill_helper.py` | Context gathering, argument dispatch, branch management |
| `scripts/config_lock.py` | Cross-platform file locking for atomic config writes (fcntl/msvcrt) |
| `scripts/deps_check.py` | Dependency checking with GPU path allowlist security |
| `scripts/ollama_manager.py` | Local model routing, hardware detection, tool-calling loop |
| `scripts/vector_memory.py` | LanceDB indexing, semantic search, GC, agent sessions |
| `scripts/mcp_server.py` | MCP stdio server exposing vector memory tools via FastMCP |
| `scripts/memory_orchestrator.py` | Multi-backend memory coordination (LanceDB + SQLite FTS5 + RLM) |
| `scripts/memory_protocol.py` | Multi-agent consistency protocol, conflict detection, session registry |
| `scripts/memory_lock.py` | Cross-platform advisory locking (file/SQLite/Redis backends) |
| `scripts/test_manager.py` | Test discovery, gaps, coverage tracking, execution |
| `scripts/docs_manager.py` | Documentation lifecycle, hash-based staleness tracking |
| `scripts/agent_runner.py` | Multi-provider agentic fleet runner (Claude/OpenAI/Ollama) |
| `scripts/image_generator.py` | Multi-provider image generation (DALL-E/Replicate/Stability AI/local) |
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

- `develop` — All feature PRs; task branches merge here
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
- `list-ideas --file ideas|disapproved|all --format json|summary`
- `parse CODE` — parse a task block
- `next-id --type task|idea --source local|platform-titles` — next sequential ID
- `move CODE --to progressing|done|todo --completed-summary TEXT`
- `remove CODE --file FILE` — remove a block from a file
- `summary --format json|text` — task counts and progress
- `semantic-explore CODE` — explore codebase semantically via vector search
- `platform-cmd OPERATION [key=value...]` — GitHub/GitLab operations
- `list-release-tasks --version X.X.X`
- `schedule-tasks --codes "CODE1,CODE2" --version X.X.X`
- `create-patch-task --source SOURCE --title TITLE --release X.X.X`
- `sync-from-platform --dry-run` — sync task status from platform Issues
- `find-files --patterns GLOBS --max-depth N` — cross-platform file search
- `register-agent --task-code CODE --agent-type TYPE` — memory consistency protocol
- `pr-body --task-code CODE --title TEXT --summary TEXT` — generate PR body

### release_manager.py CLI

```bash
python3 scripts/release_manager.py <subcommand> [options]
```

Essential subcommands:
- `full-context --tag-prefix PREFIX` — complete release context as JSON
- `current-version --tag-prefix PREFIX` — detect version from manifest files
- `release-state-get` — read pipeline state (local file OR platform issue)
- `release-state-set --version V --stage N --stage-name NAME [--increment-loop] [--mark-gate-approved N]`
- `release-state-clear` — clear state (close platform issue in platform-only mode)
- `merge-check --source BRANCH --target BRANCH`
- `parse-commits --since TAG`
- `suggest-bump --current-version V --force TYPE` — calculate new version
- `generate-changelog --version V --date YYYY-MM-DD`
- `update-versions --version V --package-paths PATHS` — auto-discover and bump all manifests
- `release-generate` — analyze tasks and return grouped data for roadmap
- `release-plan-list` — list all releases in the release plan
- `release-plan-create --version V --theme TEXT --target-date DATE`
- `release-plan-add-task --version V --task CODE`
- `release-plan-next` — get the next planned/in-progress release
- `release-close --version V` — check release readiness for closing
- `coverage-gate --min-coverage N` — run coverage threshold check

### skill_helper.py CLI

```bash
python3 scripts/skill_helper.py <subcommand> [options]
```

Essential subcommands:
- `context` — platform config, branches, submodules as JSON
- `dispatch --skill NAME --args TEXT` — parse flow, yolo, task code
- `status-report` — task counts, in-progress, next recommended

### ollama_manager.py CLI

```bash
python3 scripts/ollama_manager.py <subcommand> [options]
```

Essential subcommands:
- `detect-hardware` — RAM, VRAM, GPU, CPU
- `recommend-model --ram-gb N --vram-gb N` — best model tier for hardware
- `score-task --description TEXT` — score task for offload suitability (0–10)
- `should-offload --tool NAME --args TEXT --level N` → true/false
- `get-offload-level` → integer 0–10
- `query --prompt TEXT --model MODEL` → Ollama response
- `install` — install Ollama if not present
- `pull-model --model MODEL` — pull a model into Ollama

### test_manager.py CLI

```bash
python3 scripts/test_manager.py <subcommand> [options]
```

Essential subcommands:
- `discover --root PATH` — find all test files
- `analyze-gaps --root PATH --target FILE` — compare source vs test coverage
- `suggest --root PATH` — recommend test targets by priority
- `run --root PATH --target FILE` — execute tests via configured framework
- `coverage snapshot --root PATH` — capture current coverage state
- `coverage compare --old FILE --new FILE` — diff two snapshots
- `coverage threshold-check --min-coverage N` — pass/fail against minimum

### vector_memory.py CLI

```bash
python3 scripts/vector_memory.py <subcommand> [options]
```

Essential subcommands:
- `index --root PATH --full --force-init` — index a file or directory
- `search QUERY --top-k N --file-filter F --type-filter T --json --version N` — semantic search
- `status --root PATH --json` — report index health, chunk counts, staleness
- `clear --root PATH --force` — reset the vector index
- `gc --root PATH --ttl-days N --deep --json` — garbage-collect stale entries
- `agents --root PATH --status STATUS` — list active/historical agent sessions
- `conflicts --root PATH --resolve ID` — show/resolve contradictions between agents
- `validate-model --root PATH --model MODEL` — validate embedding model files
- `hook FILE_PATH` — PostToolUse hook: auto-index an edited file

### mcp_server.py

```bash
python3 scripts/mcp_server.py [--root PATH] [--check]
```

MCP Tools (when `vector_memory.enabled` is `true`): `index_repository`, `semantic_search`, `store_memory`, `get_task_context`, `list_backends`, `backend_health`
MCP Resources: `memory://status`, `memory://backends`

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
  "python_command": "",        // override: "python3" (default) or "python"
  "memory_consistency": {
    "gc_ttl_days": 30,
    "max_index_size_mb": 500,
    "conflict_strategy": "auto",   // "auto" or "manual"
    "enable_versioned_reads": false,
    "auto_resolve": {
      "enabled": false,
      "strategy": "single-judge",  // or "majority-vote"
      "provider": "ollama"
    }
  },
  "vector_memory": {
    "enabled": false,          // opt-in semantic indexing (enable via /setup)
    "auto_index": false,       // auto-reindex on PostToolUse events
    "embedding_provider": "local",
    "embedding_model": "all-MiniLM-L6-v2",
    "chunk_size": 2000,
    "index_path": ".claude/memory/vectors",
    "backend": "lancedb",
    "lock_backend": {
      "type": "file",         // "file", "sqlite", or "redis"
      "timeout": 30
    },
    "sqlite": {
      "enabled": false,       // SQLite FTS5 hybrid search backend
      "hybrid_weight_vector": 0.7,
      "hybrid_weight_text": 0.3
    },
    "gpu_acceleration": { "mode": "auto", "gpu_path_allowlist": [] },
    "search_log": { "enabled": false, "retention_days": 30 },
    "event_sourcing": { "enabled": false },
    "rlm": { "enabled": false, "provider": "ollama", "max_depth": 3 },
    "orchestrator": {
      "backends": ["lancedb"],
      "fallback_chain": ["lancedb", "sqlite", "rlm"],
      "query_routing": { "exact": "sqlite", "semantic": "lancedb", "deep": "rlm" }
    }
  },
  "mcp_server": {
    "enabled": false,          // MCP server for vector search (opt-in via /setup)
    "transport": "stdio",
    "auto_start": false
  },
  "social_announce": {
    "platforms": {             // direct posting: bluesky, mastodon, discord, slack
      "bluesky": { "enabled": false }
    },
    "clipboard_platforms": [   // format + copy: twitter, linkedin, reddit, hackernews
      { "name": "twitter", "enabled": false, "max_length": 280 }
    ]
  },
  "image_generation": {
    "enabled": false,
    "provider": "local",       // "local", "dalle", "replicate", "stability"
    "output_dir": "assets/generated"
  },
  "ollama": {
    "enabled": false,
    "offloading_level": 5      // 0-10
  },
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

# Fully autonomous mode (append yolo to auto-confirm gates)
/task pick all yolo
/release continue 1.0.0 yolo

# [BETA] Autonomous project builder
/crazy "Build a REST API with user auth"
```

---

## Release State Machine

The 9-stage release pipeline persists state via `release-state-get/set`:

| Stage | Name | Key Action |
|-------|------|------------|
| 1 | Create Branch | `git checkout -b release/X.X.X develop` |
| 2 | Task Readiness Gate | Verify all release tasks are `done` |
| 3 | Fetch Open PRs | `gh pr list --base develop --state open` |
| 4 | Per-PR Sub-Agent Analysis | Parallel: analyze → optimize → security → fix → merge each PR |
| 5 | Merge to Staging | develop → staging; local build gate; tag `vX.X.X-staging`; push |
| 6 | Integration Tests | Run `verify_command` or auto-detected test suite |
| 7 | Merge to Main + Tag | staging → main; changelog; version bump gate; local build gate; tag `vX.X.X`; push; CI monitoring (platform-only) |
| 7h | Docs Sync | `/docs sync` auto-runs |
| 8 | Users Testing | Release is live |
| 8.5 | Announce | Social media via configured platforms (direct + clipboard) |
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
├── project-config.json     # Project settings (vector memory, social announce, image gen, ollama)
├── ollama-config.json      # Ollama offloading config
├── releases.json           # Release plan (local/dual mode)
├── release-state.json      # Pipeline state (local/dual mode)
├── agentic-provider.json   # CI/CD fleet config
└── memory/
    ├── vectors/            # LanceDB vector index (gitignored)
    ├── sqlite/             # SQLite FTS5 backend (optional)
    └── locks/              # Lock files for multi-agent coordination

scripts/
├── task_manager.py         # Task/idea CRUD, platform sync
├── release_manager.py      # Version, changelog, release state
├── skill_helper.py         # Context, dispatch
├── ollama_manager.py       # Local model routing + tool calling
├── vector_memory.py        # Semantic indexing and search
├── mcp_server.py           # MCP stdio server for vector memory
├── memory_orchestrator.py  # Multi-backend coordination (LanceDB + SQLite + RLM)
├── memory_protocol.py      # Multi-agent consistency protocol
├── config_lock.py          # Cross-platform file locking for config writes
├── deps_check.py           # Dependency checking with GPU path allowlist
├── memory_lock.py          # Distributed lock backends (file/SQLite/Redis)
├── sqlite_backend.py       # SQLite FTS5 + vec hybrid backend
├── memory_event_log.py     # Event-sourced memory for concurrent writes
├── conflict_judge.py       # LLM-as-judge conflict resolution
├── rlm_backend.py          # Recursive context processing
├── docs_manager.py         # Documentation lifecycle
├── agent_runner.py         # Multi-provider fleet runner
├── test_manager.py         # Test discovery, gaps, coverage
├── app_manager.py          # Port/process management (cross-platform)
├── codebase_analyzer.py    # Static analysis reports
├── memory_builder.py       # Codebase summary generator
├── image_generator.py      # Multi-provider image generation
├── frontend_wizard.py      # Frontend design wizard
├── setup_labels.py         # Platform label creation
├── setup_protection.py     # Branch protection rules
├── adapters/               # Platform adapters (claude_code, opencode, openclaw)
├── chunkers/               # Text chunking for vector memory
├── embeddings/             # Embedding providers (local ONNX, API)
├── mcp_tools/              # MCP server tool definitions
├── social_platforms/       # Social media posting adapters
├── hooks/
│   └── pre_tool_offload.py
└── analyzers/              # Static analysis (features, quality, infrastructure, coverage)

skills/
├── task/SKILL.md
├── idea/SKILL.md
├── release/SKILL.md
├── docs/SKILL.md
├── setup/SKILL.md
├── update/SKILL.md
├── tests/SKILL.md
├── help/SKILL.md
└── crazy/SKILL.md          # [BETA] Autonomous project builder

hooks/hooks.json            # PreToolUse + PostToolUse definitions
.claude-plugin/plugin.json  # Plugin manifest (version: 4.0.2)
```
