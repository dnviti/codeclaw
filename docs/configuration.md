---
title: Configuration
description: Environment variables, configuration files, feature flags, and project settings
generated-by: claw-docs
generated-at: 2026-03-20T00:25:00Z
source-files:
  - config/project-config.example.json
  - config/mcp-server.example.json
  - config/ollama-config.example.json
  - config/issues-tracker.example.json
  - config/releases.example.json
  - config/agentic-provider.example.json
  - config/github-issues.example.json
  - scripts/skill_helper.py
  - scripts/agent_runner.py
  - scripts/task_manager.py
  - scripts/release_manager.py
---

## Overview

CodeClaw uses JSON configuration files stored in the `.claude/` directory of your project and a `CLAUDE.md` file for project-specific variables. Configuration is layered: CLI flags override environment variables, which override config files, which override defaults.

## Configuration Files

All configuration files live in `.claude/` at your project root. Example files are provided in the plugin's `config/` directory.

### issues-tracker.json

Controls GitHub/GitLab Issues integration.

**Location:** `.claude/issues-tracker.json`
**Example:** `config/issues-tracker.example.json`

```json
{
  "platform": "github",
  "enabled": false,
  "sync": false,
  "repo": "owner/repo",
  "labels": {
    "source": "claude-code",
    "task": "task",
    "idea": "idea",
    "priority": {
      "HIGH": "priority:high",
      "MEDIUM": "priority:medium",
      "LOW": "priority:low"
    },
    "status": {
      "todo": "status:todo",
      "in-progress": "status:in-progress",
      "to-test": "status:to-test",
      "done": "status:done"
    },
    "sections": {},
    "release_prefix": "release:"
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `platform` | `"github"` or `"gitlab"` | Which platform CLI to use (`gh` or `glab`) |
| `enabled` | `boolean` | Enable platform Issues integration |
| `sync` | `boolean` | Enable bidirectional sync between local files and platform Issues |
| `repo` | `string` | Repository identifier (e.g., `"owner/repo"`) |
| `labels.source` | `string` | Label applied to all CodeClaw-created issues |
| `labels.task` | `string` | Label for task issues |
| `labels.idea` | `string` | Label for idea issues |
| `labels.priority` | `object` | Maps priority levels to label names |
| `labels.status` | `object` | Maps task statuses to label names |
| `labels.sections` | `object` | Custom section labels for task organization |
| `labels.release_prefix` | `string` | Prefix for release milestone labels |

> **Platform-only mode note:** When `enabled: true` and `sync: false`, the release pipeline also stores `release-state.json` content in a `claw-release-state` platform issue so all collaborators share the same pipeline state without needing a `git pull`.

### project-config.json

Project-specific settings used by skills during task creation and releases.

**Location:** `.claude/project-config.json`
**Example:** `config/project-config.example.json`

```json
{
  "dev_ports": "",
  "start_command": "",
  "predev_command": "",
  "verify_command": "",
  "test_framework": "",
  "test_command": "",
  "test_file_pattern": "",
  "ci_runtime_setup": "",
  "tech_detail_layers": "",
  "idea_categories": "",
  "doc_categories": "",
  "project_context": "",
  "scout_categories": "",
  "package_json_paths": "",
  "changelog_file": "",
  "tag_prefix": "",
  "github_repo_url": "",
  "release_branch": "",
  "show_generated_footer": true,
  "python_command": "",
  "memory_consistency": {
    "gc_ttl_days": 30,
    "max_index_size_mb": 500,
    "conflict_strategy": "auto",
    "enable_versioned_reads": false,
    "auto_resolve": {
      "enabled": false,
      "strategy": "single-judge",
      "provider": "ollama",
      "confidence_threshold": 0.8,
      "num_votes": 3,
      "max_auto_resolve_per_run": 10,
      "model": ""
    }
  },
  "vector_memory": {
    "enabled": false,
    "auto_index": false,
    "embedding_provider": "local",
    "embedding_model": "all-MiniLM-L6-v2",
    "embedding_api_key_env": "",
    "chunk_size": 2000,
    "index_path": ".claude/memory/vectors",
    "batch_size": 64,
    "include_patterns": [],
    "exclude_patterns": [],
    "lock_backend": {
      "type": "file",
      "sqlite_path": ".claude/memory/locks/lock.db",
      "redis_url": "redis://localhost:6379",
      "redis_key_prefix": "claw:",
      "timeout": 30,
      "auto_renew_interval": 10
    },
    "backend": "lancedb",
    "sqlite": {
      "enabled": false,
      "hybrid_weight_vector": 0.7,
      "hybrid_weight_text": 0.3,
      "db_path": ".claude/memory/sqlite/memory.db"
    },
    "gpu_acceleration": {
      "mode": "auto",
      "log_provider": true,
      "lib_paths": [],
      "gpu_path_allowlist": []
    },
    "search_log": {
      "enabled": false,
      "path": ".claude/memory/search_log.jsonl",
      "include_content": false,
      "max_size_mb": 10,
      "retention_days": 30
    },
    "event_sourcing": {
      "enabled": false,
      "compact_interval_seconds": 300,
      "max_segment_size_mb": 10,
      "auto_compact_on_search": true
    },
    "rlm": {
      "enabled": false,
      "provider": "ollama",
      "max_depth": 3,
      "max_context_mb": 10,
      "aggregation": "map-reduce",
      "timeout_seconds": 120
    },
    "orchestrator": {
      "backends": ["lancedb"],
      "routing_weights": { "lancedb": 1.0, "sqlite": 0.8, "rlm": 0.6 },
      "fallback_chain": ["lancedb", "sqlite", "rlm"],
      "query_routing": { "exact": "sqlite", "semantic": "lancedb", "deep": "rlm" },
      "rrf_k": 60
    }
  },
  "mcp_server": {
    "enabled": false,
    "transport": "stdio",
    "auto_start": false
  },
  "social_announce": {
    "platforms": {
      "bluesky": { "enabled": false },
      "mastodon": { "enabled": false },
      "discord": { "enabled": false },
      "slack": { "enabled": false }
    },
    "clipboard_platforms": [
      { "name": "twitter", "enabled": false, "max_length": 280, "post_url": "https://twitter.com/compose/tweet" },
      { "name": "linkedin", "enabled": false, "max_length": 3000, "post_url": "https://www.linkedin.com/feed/" },
      { "name": "reddit", "enabled": false, "max_length": 10000, "post_url": "" },
      { "name": "hackernews", "enabled": false, "max_length": 2000, "post_url": "https://news.ycombinator.com/submit" }
    ]
  },
  "image_generation": {
    "enabled": false,
    "provider": "local",
    "api_key_env": "",
    "default_size": "1024x1024",
    "default_style": "natural",
    "output_dir": "assets/generated"
  },
  "ollama": {
    "enabled": false,
    "model": "",
    "offloading_level": 5
  },
}
```

**Core fields:**

| Field | Description |
|-------|-------------|
| `dev_ports` | Ports used by the development server (e.g., `"3000,5173"`) |
| `start_command` | Command to start the dev server (e.g., `"npm run dev"`) |
| `predev_command` | Command to run before starting dev (e.g., `"npm install"`) |
| `verify_command` | Build/verify command for release gates (e.g., `"npm run build"`) |
| `test_framework` | Test framework name (e.g., `"vitest"`, `"pytest"`) |
| `test_command` | Command to run tests (e.g., `"npm test"`) |
| `test_file_pattern` | Glob for test files (e.g., `"**/*.test.ts"`) |
| `ci_runtime_setup` | CI/CD runtime setup snippet (e.g., Node.js version) |
| `tech_detail_layers` | Technology layers for task technical details |
| `idea_categories` | Categories for idea classification |
| `doc_categories` | Categories for documentation sections |
| `project_context` | Free-text project description for AI context |
| `scout_categories` | Focus areas for the idea scout pipeline |
| `package_json_paths` | Comma-separated paths to `package.json` files (monorepo support) |
| `changelog_file` | Changelog file path (default: `CHANGELOG.md`) |
| `tag_prefix` | Git tag prefix (default: `v`) |
| `github_repo_url` | Repository URL for changelog links |
| `release_branch` | Branch to release from (default: `develop`) |
| `show_generated_footer` | Append `*Generated by Claude Code via /task create*` to task bodies |
| `python_command` | Python command override (default: `python3`) |

**`memory_consistency` section:**

| Field | Description |
|-------|-------------|
| `gc_ttl_days` | Days before stale memory entries are garbage-collected (default: 30) |
| `max_index_size_mb` | Maximum vector index size in MB (default: 500) |
| `conflict_strategy` | How to resolve multi-agent write conflicts: `"auto"` or `"manual"` |
| `enable_versioned_reads` | Enable versioned reads for concurrent agent safety |

**`memory_consistency.auto_resolve` section:**

| Field | Description |
|-------|-------------|
| `enabled` | Enable automatic conflict resolution (default: `false`) |
| `strategy` | Resolution strategy: `"single-judge"` or `"majority-vote"` |
| `provider` | LLM provider for conflict resolution (default: `"ollama"`) |
| `confidence_threshold` | Minimum confidence to accept auto-resolution (default: 0.8) |
| `num_votes` | Number of votes for majority-vote strategy (default: 3) |
| `max_auto_resolve_per_run` | Maximum conflicts to auto-resolve per run (default: 10) |
| `model` | Model name for conflict resolution (auto-detected if empty) |

**`vector_memory` section:**

| Field | Description |
|-------|-------------|
| `enabled` | Enable vector memory (default: `false`; opt-in via `/setup`) |
| `auto_index` | Automatically re-index files on PostToolUse events (default: `false`) |
| `embedding_provider` | `"local"` (all-MiniLM-L6-v2) or `"remote"` |
| `embedding_model` | Model name for embeddings |
| `embedding_api_key_env` | Environment variable holding remote API key |
| `chunk_size` | Characters per index chunk (default: 2000) |
| `index_path` | LanceDB index directory (default: `.claude/memory/vectors`) |
| `batch_size` | Embedding batch size for indexing (default: 64) |
| `include_patterns` | Glob patterns of files to always index |
| `exclude_patterns` | Glob patterns of files to never index |
| `backend` | Primary backend engine: `"lancedb"` (default) |

**`vector_memory.lock_backend` section:**

Configures distributed locking for multi-agent coordination.

| Field | Description |
|-------|-------------|
| `type` | Lock backend type: `"file"` (default, single-machine), `"sqlite"` (networked filesystems), or `"redis"` (distributed, requires `pip install redis`) |
| `sqlite_path` | SQLite lock database path (default: `.claude/memory/locks/lock.db`) |
| `redis_url` | Redis connection URL (default: `redis://localhost:6379`) |
| `redis_key_prefix` | Key prefix for Redis locks (default: `"claw:"`) |
| `timeout` | Lock acquisition timeout in seconds (default: 30) |
| `auto_renew_interval` | Interval in seconds to auto-renew held locks (default: 10) |

**`vector_memory.sqlite` section:**

SQLite FTS5 hybrid search backend (alternative/complement to LanceDB).

| Field | Description |
|-------|-------------|
| `enabled` | Enable SQLite FTS5 backend (default: `false`) |
| `hybrid_weight_vector` | Weight for vector similarity in hybrid search (default: 0.7) |
| `hybrid_weight_text` | Weight for text search in hybrid search (default: 0.3) |
| `db_path` | SQLite database path (default: `.claude/memory/sqlite/memory.db`) |

**`vector_memory.gpu_acceleration` section:**

| Field | Description |
|-------|-------------|
| `mode` | GPU acceleration mode: `"auto"` (default), `"cpu"`, or `"gpu"` |
| `log_provider` | Log which execution provider is selected (default: `true`) |
| `lib_paths` | Auto-discovered GPU library directories injected into `LD_LIBRARY_PATH`/`PATH` at runtime (default: `[]`) |
| `gpu_path_allowlist` | Restrict which directories may be added to `LD_LIBRARY_PATH` from config. Empty list = use built-in defaults (system lib dirs, CUDA, ROCm, pip site-packages). Set explicit paths/globs to override (default: `[]`) |

**`vector_memory.search_log` section:**

Search query logging for debugging and analysis. Disabled by default for privacy.

| Field | Description |
|-------|-------------|
| `enabled` | Enable search query logging (default: `false`). Opt-in only |
| `path` | Log file path (default: `.claude/memory/search_log.jsonl`) |
| `include_content` | Include matched chunk content in log entries (default: `false`) |
| `max_size_mb` | Maximum log file size before rotation (default: 10) |
| `retention_days` | Auto-purge log entries older than N days (default: 30) |

> **Privacy notice:** When enabled, search queries and result metadata are written to disk in plaintext. This may include sensitive data such as code patterns, file paths, and search terms. Logs are created with `0o600` permissions (owner-only read/write) and auto-purged after `retention_days`.

**`vector_memory.event_sourcing` section:**

Event-sourced memory for concurrent write safety.

| Field | Description |
|-------|-------------|
| `enabled` | Enable event sourcing (default: `false`) |
| `compact_interval_seconds` | Interval between automatic compactions (default: 300) |
| `max_segment_size_mb` | Maximum segment file size before compaction (default: 10) |
| `auto_compact_on_search` | Compact before search if stale (default: `true`) |

**`vector_memory.rlm` section:**

Recursive Language Model (RLM) backend for deep context processing.

| Field | Description |
|-------|-------------|
| `enabled` | Enable RLM backend (default: `false`) |
| `provider` | LLM provider for RLM processing (default: `"ollama"`) |
| `max_depth` | Maximum recursion depth (default: 3) |
| `max_context_mb` | Maximum context size in MB (default: 10) |
| `aggregation` | Aggregation strategy: `"map-reduce"` (default) |
| `timeout_seconds` | Timeout for RLM processing (default: 120) |

**`vector_memory.orchestrator` section:**

Multi-backend search orchestration with routing and fusion.

| Field | Description |
|-------|-------------|
| `backends` | List of active backends (default: `["lancedb"]`) |
| `routing_weights` | Relevance weights per backend for result ranking |
| `fallback_chain` | Ordered fallback sequence if primary backend fails |
| `query_routing` | Maps query types to backends: `exact` → sqlite, `semantic` → lancedb, `deep` → rlm |
| `rrf_k` | Reciprocal Rank Fusion constant (default: 60) |

> **Prerequisites for vector memory:** `pip install "mcp>=1.0" "lancedb>=0.5.0,<1.0" "sentence-transformers>=2.7.0,<3.0"`

**`mcp_server` section:**

| Field | Description |
|-------|-------------|
| `enabled` | Enable the MCP server for vector memory tool access (default: `false`; opt-in via `/setup`) |
| `transport` | Transport protocol (`"stdio"` for Claude Code) |
| `auto_start` | Start the MCP server automatically on Claude Code launch (default: `false`) |

The standalone MCP server configuration file (`config/mcp-server.example.json`) provides additional options for Claude Code integration, including `restart_on_crash`, available tools (`index_repository`, `semantic_search`, `store_memory`, `get_task_context`), and a `memory://status` resource endpoint.

**`social_announce` section:**

Configures release announcement platforms. All platforms are disabled by default.

- **Direct posting** (Bluesky, Mastodon, Discord, Slack) — post via API
- **Clipboard platforms** (Twitter/X, LinkedIn, Reddit, Hacker News) — format and copy to clipboard

**`image_generation` section:**

Configures on-demand image generation with multiple provider backends.

| Field | Description |
|-------|-------------|
| `enabled` | Enable image generation (default: `false`) |
| `provider` | Provider backend: `"local"`, `"dalle"`, `"replicate"`, or `"stability"` (default: `"local"`) |
| `api_key_env` | Environment variable holding the provider API key |
| `default_size` | Default image dimensions (default: `"1024x1024"`) |
| `default_style` | Default style: `"natural"` or `"vivid"` (default: `"natural"`) |
| `output_dir` | Directory for generated images (default: `"assets/generated"`) |

**`ollama` section (in project-config.json):**

Quick-enable for Ollama. For full Ollama configuration, use `ollama-config.json`.

| Field | Description |
|-------|-------------|
| `enabled` | Enable Ollama local model routing |
| `model` | Model name to use (auto-detected if empty) |
| `offloading_level` | Default offloading level 0–10 (default: 5) |

### ollama-config.json

Full configuration for Ollama local model integration.

**Location:** `.claude/ollama-config.json`
**Example:** `config/ollama-config.example.json`

```json
{
  "enabled": false,
  "model": "",
  "api_base": "http://localhost:11434",
  "hardware": {
    "ram_gb": 0,
    "vram_gb": 0,
    "gpu_vendor": "none",
    "cpu_cores": 0
  },
  "offloading": {
    "level": 5,
    "auto_route": true,
    "offloadable_tasks": ["generate-boilerplate", "format-code", "write-docstrings", "simple-refactor"],
    "tool_calls": {
      "enabled": false,
      "include_tools": ["Bash", "Read", "Grep", "Glob", "Edit", "Write"],
      "exclude_patterns": ["git push", "git reset", "rm -rf", "sudo", "chmod", "chown"]
    },
    "max_tokens": 2048,
    "temperature": 0.1
  },
  "tool_calling": {
    "enabled": true,
    "allowed_tools": ["bash_execute", "read_file", "write_file", "edit_file", "grep_search", "glob_search", "web_fetch", "web_search"],
    "max_tool_rounds": 10
  },
  "installation": {
    "auto_start": false,
    "pull_on_setup": true
  }
}
```

| Field | Description |
|-------|-------------|
| `enabled` | Enable Ollama integration |
| `model` | Ollama model name (auto-recommended from hardware if empty) |
| `api_base` | Ollama API URL (default: `http://localhost:11434`); must start with `http://` or `https://` |
| `hardware` | Hardware spec for model recommendation; 0 = auto-detect |
| `offloading.level` | Offloading level 0–10 (0 = off, 10 = route everything) |
| `offloading.tool_calls.enabled` | Enable PreToolUse hook routing |
| `offloading.tool_calls.include_tools` | Tool names eligible for offloading |
| `offloading.tool_calls.exclude_patterns` | Command substrings that are NEVER offloaded (NFKC-normalized) |
| `tool_calling.enabled` | Enable Ollama's own tool-calling capability (`/api/chat` loop) |
| `tool_calling.max_tool_rounds` | Maximum tool invocation rounds per chat turn |

**Offloading levels:**

| Level | What gets routed to Ollama |
|-------|--------------------------|
| 0 | Nothing (disabled) |
| 1–2 | Reserved |
| 3 | Simple Bash commands (ls, cat, git status) |
| 4 | Simple edits (formatting, whitespace) |
| 6 | Search/read operations (Grep, Glob, Read) |
| 7 | Complex Bash (piped commands) |
| 8 | Structural edits (class/function changes) |
| 10 | All tool calls except always-excluded patterns |

### releases.json

Release roadmap with planned milestones. Used in local/dual-sync mode only (platform-only uses GitHub/GitLab milestones).

**Location:** `.claude/releases.json`
**Example:** `config/releases.example.json`

```json
{
  "releases": [
    {
      "version": "1.1.0",
      "status": "planned",
      "target_date": "2026-04-01",
      "theme": "Plugin marketplace improvements",
      "tasks": ["MKT-004", "MKT-005", "UI-006"],
      "created_at": "2026-03-13",
      "released_at": null
    }
  ]
}
```

### agentic-provider.json

Configuration for the agentic fleet pipelines.

**Location:** `.claude/agentic-provider.json`
**Example:** `config/agentic-provider.example.json`

```json
{
  "provider": "claude",
  "model": {
    "task": "claude-opus-4-6",
    "scout": "claude-sonnet-4-6",
    "docs": "claude-sonnet-4-6"
  },
  "budget": {
    "task": 15,
    "scout": 5,
    "docs": 5
  },
  "auto_pr": true
}
```

| Field | Description |
|-------|-------------|
| `provider` | AI provider: `"claude"`, `"openai"`, or `"ollama"` |
| `model.task` | Model for task implementation pipeline |
| `model.scout` | Model for idea scouting pipeline |
| `model.docs` | Model for documentation pipeline |
| `budget.task` | Budget in USD for task pipeline (Claude only) |
| `budget.scout` | Budget in USD for scout pipeline (Claude only) |
| `budget.docs` | Budget in USD for docs pipeline (Claude only) |
| `auto_pr` | Whether to auto-create PRs after task implementation |

**Configuration precedence:**
1. CLI flags (`--provider`, `--model`, `--budget`)
2. Environment variable (`AGENTIC_PROVIDER`)
3. Config file (`.claude/agentic-provider.json`)
4. Defaults (Claude with default models)

## CLAUDE.md Variables

The `/setup` skill generates a `CLAUDE.md` file with a bash code block containing project variables:

```bash
PROJECT_NAME="My Project"
VERIFY_COMMAND="npm run build"
TEST_FRAMEWORK="vitest"
TEST_COMMAND="npm test"
DEV_PORTS="3000"
START_COMMAND="npm run dev"
TAG_PREFIX="v"
CHANGELOG_FILE="CHANGELOG.md"
```

These variables are parsed by `skill_helper.py` and `test_manager.py` at runtime to configure skill behavior.

## Environment Variables

| Variable | Purpose | Used by |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | Claude API authentication | `agent_runner.py` |
| `OPENAI_API_KEY` | OpenAI API authentication | `agent_runner.py` |
| `AGENTIC_PROVIDER` | Override provider selection | `agent_runner.py` |
| `AGENTIC_AUTO_PR` | Override auto-PR creation (`true`/`false`) | `agent_runner.py` |
| `GITLAB_CI` | GitLab CI detection | `agent_runner.py` |
| `GH_TOKEN` | GitHub API authentication for CI | GitHub Actions workflows |
| `CLAUDE_TOOL_NAME` | Tool name for PreToolUse hook | `pre_tool_offload.py` |
| `CLAUDE_TOOL_INPUT` | Tool input for PreToolUse hook | `pre_tool_offload.py` |
| `CLAUDE_FILE_PATH` | File path for PostToolUse hook | `task_manager.py`, `vector_memory.py` |

## Feature Flags

CodeClaw uses configuration-driven feature flags rather than compile-time flags:

| Flag | Config location | Effect |
|------|-----------------|--------|
| Issues integration | `issues-tracker.json → enabled` | Enables platform Issues sync |
| Dual sync | `issues-tracker.json → sync` | Enables bidirectional file/Issues sync |
| Platform release state | `issues-tracker.json → enabled=true, sync=false` | Stores release state as platform issue |
| Auto-PR | `agentic-provider.json → auto_pr` | Auto-creates PRs in task pipeline |
| Yolo mode | Appended to any command | Auto-confirms all non-destructive gates |
| Vector memory | `project-config.json → vector_memory.enabled` | Opt-in semantic indexing (enable via `/setup`) |
| MCP server | `project-config.json → mcp_server.enabled` | Exposes vector memory via MCP protocol |
| Ollama routing | `ollama-config.json → enabled` | Routes tool calls/tasks to local model |
| Social announce | `project-config.json → social_announce.platforms.<name>.enabled` | Enables release announcements |
| Search logging | `project-config.json → vector_memory.search_log.enabled` | Opt-in search query logging with privacy controls |
