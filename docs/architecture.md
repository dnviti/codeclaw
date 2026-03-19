---
title: Architecture
description: System architecture, component interactions, data flow, and design decisions
generated-by: claw-docs
generated-at: 2026-03-18T00:00:00Z
source-files:
  - scripts/task_manager.py
  - scripts/release_manager.py
  - scripts/skill_helper.py
  - scripts/docs_manager.py
  - scripts/agent_runner.py
  - scripts/app_manager.py
  - scripts/codebase_analyzer.py
  - scripts/memory_builder.py
  - scripts/test_manager.py
  - scripts/ollama_manager.py
  - scripts/vector_memory.py
  - scripts/hooks/pre_tool_offload.py
  - scripts/analyzers/__init__.py
  - hooks/hooks.json
  - .claude-plugin/plugin.json
  - skills/task/SKILL.md
  - skills/idea/SKILL.md
  - skills/release/SKILL.md
  - skills/docs/SKILL.md
  - skills/setup/SKILL.md
  - skills/update/SKILL.md
  - skills/tests/SKILL.md
  - skills/help/SKILL.md
---

## Overview

CodeClaw is a project-agnostic plugin for Claude Code that provides structured task management, idea evaluation, gated release pipelines, documentation generation, and automated CI/CD via agentic fleet pipelines. It is built entirely in Python 3 using only the standard library (zero external dependencies for core functionality; optional packages for vector memory and MCP).

## Why This Architecture

CodeClaw is designed to be a **zero-dependency, cross-platform plugin** that works with any language, framework, or tech stack. The architecture separates concerns into three layers:

1. **Skills** (natural language interface) — Claude Code slash commands that define the AI's behavior
2. **Scripts** (deterministic logic) — Python CLIs that handle file I/O, parsing, and state management
3. **Hooks** (event-driven integration) — PreToolUse and PostToolUse hooks for real-time tool call routing and file tracking

This separation ensures that AI behavior is defined declaratively in Markdown skills, while all deterministic operations (file parsing, ID generation, version bumping, Ollama routing) are handled by reliable Python scripts.

## Component Architecture

```mermaid
flowchart TD
    subgraph "Claude Code Plugin"
        PLUGIN["plugin.json<br>Plugin manifest"]
        HOOKS["hooks.json<br>PreToolUse + PostToolUse"]
    end

    subgraph "Skills Layer"
        S_TASK["/task"]
        S_IDEA["/idea"]
        S_REL["/release"]
        S_DOCS["/docs"]
        S_SETUP["/setup"]
        S_UPDATE["/update"]
        S_TESTS["/tests"]
        S_HELP["/help"]
    end

    subgraph "Scripts Layer"
        TM["task_manager.py<br>Task/idea CRUD, hooks"]
        RM["release_manager.py<br>Version, changelog, state"]
        SH["skill_helper.py<br>Context, dispatch, worktrees"]
        DM["docs_manager.py<br>Discover, staleness, manifest"]
        AR["agent_runner.py<br>Multi-provider fleet runner"]
        AM["app_manager.py<br>Port/process management"]
        CA["codebase_analyzer.py<br>Static analysis reports"]
        MB["memory_builder.py<br>Codebase summary generator"]
        TT["test_manager.py<br>Test discovery, gaps, coverage"]
        OM["ollama_manager.py<br>Local model routing + tool calling"]
        VM["vector_memory.py<br>Always-on semantic indexing + MCP"]
    end

    subgraph "Hooks"
        PRE["pre_tool_offload.py<br>PreToolUse: Ollama routing"]
        POST_TM["task_manager.py hook<br>PostToolUse: file tracking"]
        POST_VM["vector_memory.py hook<br>PostToolUse: auto-index"]
    end

    subgraph "Analyzers Subpackage"
        AI["__init__.py<br>File walking, classification"]
        AF["features.py<br>Feature analysis"]
        AQ["quality.py<br>Code quality analysis"]
        AINF["infrastructure.py<br>Infrastructure analysis"]
        AC["coverage.py<br>Coverage snapshots"]
    end

    subgraph "Templates"
        GH["GitHub Actions workflows"]
        GL["GitLab CI templates"]
        PR["Agentic prompts"]
        CMD["CLAUDE.md template"]
    end

    subgraph "Configuration"
        CFG_IT["issues-tracker.json"]
        CFG_PC["project-config.json"]
        CFG_RL["releases.json"]
        CFG_AP["agentic-provider.json"]
        CFG_OL["ollama-config.json"]
    end

    PLUGIN --> S_TASK & S_IDEA & S_REL & S_DOCS & S_SETUP & S_UPDATE & S_TESTS & S_HELP
    HOOKS --> PRE & POST_TM & POST_VM

    PRE --> OM
    POST_TM --> TM
    POST_VM --> VM

    S_TASK --> TM & SH
    S_IDEA --> TM & SH
    S_REL --> RM & TM & SH & DM
    S_DOCS --> DM & SH
    S_SETUP --> SH & TM
    S_TESTS --> TT

    CA --> AI & AF & AQ & AINF
    TT --> AI & AQ & AC
    DM --> AI
    AR --> PR

    OM --> CFG_OL

    S_SETUP --> GH & GL & CMD
    S_SETUP --> CFG_IT & CFG_PC & CFG_RL & CFG_AP & CFG_OL
```

## Script Responsibilities

### task_manager.py

The largest script (~2,100 lines). Manages the full lifecycle of tasks and ideas through plain-text files.

**Key responsibilities:**
- Parse and manipulate task/idea blocks in `to-do.txt`, `progressing.txt`, `done.txt`, `ideas.txt`, `idea-disapproved.txt`
- Generate globally sequential task codes (e.g., `AUTH-0001`) and idea codes (e.g., `IDEA-AUTH-0001`)
- Move blocks between files (pick, close, approve, disapprove)
- PostToolUse hook: correlates edited files to in-progress tasks
- Duplicate detection, file verification, section support
- GitHub/GitLab Issues integration (tri-modal: local-only, platform-only, dual-sync)
- Worktree setup: on teardown, merges task branch into local develop before removing worktree

**CLI subcommands:** `list`, `parse`, `next-id`, `move`, `sections`, `duplicates`, `hook`, `platform-cmd`, `setup-task-worktree`, `remove-worktree`, `list-release-tasks`, `schedule-tasks`, `create-patch-task`, `sync-from-platform`, `deregister-agent`

### release_manager.py

Manages the release lifecycle including version detection, changelog generation, and release state persistence.

**Key responsibilities:**
- Detect current version from manifest files (`package.json`, `pyproject.toml`, `Cargo.toml`, `.claude-plugin/plugin.json`, etc.)
- Parse conventional commits and classify them into changelog categories
- Calculate semantic version bumps (major/minor/patch)
- Generate changelogs in Keep a Changelog format
- Persist release state across pipeline stages — stored locally as `.claude/release-state.json` in local/dual mode, or as a `claw-release-state` GitHub/GitLab issue in platform-only mode (shared across all collaborators)
- Discover and bump version fields in all manifest files
- Platform milestone management (close with verification)

**CLI subcommands:** `full-context`, `parse-commits`, `generate-changelog`, `update-versions`, `release-state-get`, `release-state-set`, `release-state-clear`, `release-plan-list`, `release-plan-create`, `release-plan-add-task`, `release-plan-mark-released`, `merge-check`, `list-release-tasks`, `release-close`

### skill_helper.py

Consolidated helper that eliminates repeated logic across all skills.

**Key responsibilities:**
- Gather platform context (GitHub/GitLab config, worktree state, branch config, submodule list)
- Dispatch skill arguments (parse flow, yolo mode, task codes)
- Manage git worktrees for isolated task development
- Parse project config for skill behavior
- Branch strategy detection and enforcement
- Status reports (task counts, in-progress tasks, recommended next tasks)

**CLI subcommands:** `context`, `dispatch`, `setup-task-worktree`, `list-submodules`, `status-report`

### ollama_manager.py

Local model manager for Ollama-powered task offloading and tool calling.

**Key responsibilities:**
- Detect hardware (RAM, VRAM, GPU vendor, CPU cores) and recommend an appropriate model tier
- Manage Ollama installation and model pulling
- Score tasks to determine offload suitability (0–10 scale)
- Route tool calls by level: level ≥ 3 for simple Bash, ≥ 4 for simple edits, ≥ 6 for search/read, ≥ 8 for structural edits, ≥ 10 for everything
- Execute full `/api/chat` tool-calling loop: send tool call to Ollama, parse `tool_calls` response, invoke the tool, feed result back, repeat until a text response is returned
- NFKC normalization of command strings before exclude-pattern matching to prevent Unicode homoglyph bypass

**CLI subcommands:** `detect-hardware`, `recommend-model`, `score-task`, `should-offload`, `query`, `install`, `pull-model`, `get-offload-level`

### scripts/hooks/pre_tool_offload.py

**PreToolUse hook** — evaluates each tool call against the Ollama offloading policy before Claude executes it.

**Key responsibilities:**
- Load Ollama config from `.claude/ollama-config.json`
- Check whether tool call offloading is enabled and the tool is in the include list
- Apply NFKC normalization to `tool_args` before matching against exclude patterns
- If the call should be offloaded: emit a JSON `{"action": "offload", ...}` payload; otherwise emit `{"action": "proceed"}`
- Graceful degradation: any error returns `{"action": "proceed"}` so Claude is never blocked

### vector_memory.py

Always-on semantic memory layer for the project codebase.

**Key responsibilities:**
- Index project files into a LanceDB vector store (`LanceDB` + `sentence-transformers`, installed via pip)
- PostToolUse hook: automatically re-indexes files on every edit/write
- MCP server: exposes semantic search and memory storage tools via stdio transport
- Garbage collection: prune stale entries, compact the index
- Embedding providers: local `all-MiniLM-L6-v2` (default), or remote via API key

### docs_manager.py

Manages the documentation lifecycle with hash-based staleness tracking.

**Key responsibilities:**
- Discover codebase structure (languages, frameworks, file roles)
- Track documentation staleness via SHA-256 hashes in `.docs-manifest.json`
- List documentation sections and their status
- Detect static site generators for publishing
- Diff changed files since a git tag for release-triggered sync

**CLI subcommands:** `discover`, `check-staleness`, `list-sections`, `init-manifest`, `clean`, `detect-site-generator`, `diff-since-tag`

### agent_runner.py

Multi-provider agent runner for automated CI/CD pipelines.

**Key responsibilities:**
- Abstract provider-specific CLI details (Claude, OpenAI, Ollama)
- Build pipeline-specific prompts with platform placeholders
- Manage provider configuration with layered precedence (CLI > env > config > defaults)
- Install provider CLIs and set up the CodeClaw plugin
- Support three pipelines: task implementation, idea scouting, documentation sync

### test_manager.py

Test lifecycle management with persistent coverage tracking.

**Key responsibilities:**
- Discover test files across any project structure
- Analyze coverage gaps by matching source files to their tests
- Suggest test targets ranked by complexity, role, and recency
- Execute tests via auto-detected or configured frameworks
- Persistent coverage snapshots with regression detection and threshold checking

### Analyzers Subpackage

Deterministic static analysis replacing expensive LLM-based reader agents.

| Module | Purpose |
|--------|---------|
| `__init__.py` | File walking, gitignore handling, language/framework detection, role classification |
| `infrastructure.py` | Infrastructure analysis (Docker, CI/CD, deployment, environment) |
| `features.py` | Feature analysis (API endpoints, routes, components, services) |
| `quality.py` | Code quality analysis (test coverage, complexity, patterns) |
| `coverage.py` | Persistent coverage snapshot management and regression detection |

## Data Flow

### Task Lifecycle

```mermaid
flowchart LR
    subgraph "Idea Pipeline"
        I1["ideas.txt"] -->|"/idea approve"| I2["to-do.txt"]
        I1 -->|"/idea disapprove"| I3["idea-disapproved.txt"]
    end

    subgraph "Task Pipeline"
        T1["to-do.txt<br>[ ] TASK-0001"] -->|"/task pick"| T2["progressing.txt<br>[~] TASK-0001"]
        T2 -->|"verify + close"| T3["done.txt<br>[x] TASK-0001"]
    end

    subgraph "Worktree"
        T2 -.->|"creates"| W[".worktrees/task/<br>TASK-0001/"]
        T3 -.->|"merge branch → develop<br>then remove"| W
    end

    subgraph "Vector Memory"
        T2 -.->|"PostToolUse hook"| VM["vector_memory.py<br>auto-index on edit"]
    end
```

### Release Pipeline

```mermaid
flowchart TD
    S1["1. Create release branch"]
    S2["2. Task readiness gate"]
    S3["3. Fetch open PRs"]
    S4["4. Per-PR sub-agents<br>(parallel analysis)"]
    S5["5. Merge to staging<br>+ local build gate"]
    S6["6. Integration tests"]
    S7["7. Merge to main + tag<br>+ version bump gate<br>+ CI monitoring"]
    S7H["7h. Docs sync"]
    S8["8. Users testing"]
    S85["8.5. Social announce"]
    S9["9. End + cleanup"]

    S1 --> S2 --> S3 --> S4 --> S5 --> S6 --> S7 --> S7H --> S8 --> S85 --> S9

    S4 -.->|"RPAT"| S2
    S5 -.->|"RPAT"| S2
    S6 -.->|"RPAT"| S2
    S7 -.->|"CI fix loop"| S7
```

### Ollama Tool Call Routing

```mermaid
sequenceDiagram
    participant C as Claude Code
    participant H as pre_tool_offload.py
    participant OM as ollama_manager.py
    participant O as Ollama API

    C->>H: PreToolUse (tool_name, tool_args)
    H->>H: NFKC normalize + exclude check
    H->>OM: should_offload_tool_call(tool, args, level)
    alt Offload
        OM-->>H: true
        H->>C: {"action": "offload", "model": "..."}
        C->>O: POST /api/chat (tool_calls enabled)
        O-->>C: tool_calls response
        C->>C: Execute tool locally
        C->>O: Feed result back
        O-->>C: Final text response
    else Proceed locally
        OM-->>H: false
        H->>C: {"action": "proceed"}
    end
```

### Release State Persistence

```mermaid
stateDiagram-v2
    [*] --> Local: local-only / dual-sync mode
    [*] --> Platform: platform-only mode

    Local: .claude/release-state.json
    Platform: GitHub/GitLab issue (label: claw-release-state)

    Local --> Shared: git commit & push
    Platform --> Shared: All collaborators read via gh/glab
```

### Agentic Fleet Pipeline

```mermaid
flowchart LR
    subgraph "CI/CD Trigger"
        CRON["Cron schedule"]
        RELEASE["Release publish"]
    end

    subgraph "Agent Runner"
        CONFIG["Load config<br>(provider, model, budget)"]
        INSTALL["Install CLI"]
        PLUGIN["Setup plugin"]
        PROMPT["Build prompt"]
        INVOKE["Invoke agent"]
    end

    subgraph "Pipelines"
        P_TASK["Task Pipeline<br>Pick + implement tasks"]
        P_SCOUT["Scout Pipeline<br>Research + create ideas"]
        P_DOCS["Docs Pipeline<br>Sync documentation"]
    end

    CRON --> CONFIG
    RELEASE --> CONFIG
    CONFIG --> INSTALL --> PLUGIN --> PROMPT --> INVOKE
    INVOKE --> P_TASK & P_SCOUT & P_DOCS
```

## Plugin System

CodeClaw integrates with Claude Code via the plugin system:

- **`plugin.json`** — Declares the plugin name (`claw`), version (`3.5.1`), and skills directory
- **`marketplace.json`** — Marketplace listing for discovery and installation
- **`hooks.json`** — Registers:
  - `PreToolUse` on `Bash|Read|Grep|Glob|Edit|Write` → `pre_tool_offload.py` (Ollama routing)
  - `PostToolUse` on `Edit|Write` → `task_manager.py hook` (file-task correlation)
  - `PostToolUse` on `Edit|Write` → `vector_memory.py hook` (auto-indexing)
- **Skills** — Each skill is a `SKILL.md` file in `skills/<name>/` that defines the AI's behavior as a Markdown document with structured instructions

## Branch Strategy

```mermaid
flowchart LR
    DEV["develop<br>Active development"]
    STG["staging<br>Pre-release validation<br>'latest' Docker tag"]
    MAIN["main<br>Production releases<br>'stable' + 'vX.X.X' Docker tags"]

    DEV -->|"merge"| STG -->|"merge + tag"| MAIN
```

The three-branch strategy enforces a strict promotion path:
- **develop** — All feature branches merge here via PRs; on task worktree teardown, the task branch is merged into local develop
- **staging** — Pre-release validation; builds the `latest` Docker image; tagged `vX.X.X-staging`
- **main** — Production; tagged releases build `stable` + versioned Docker images

## Issues Integration Architecture

```mermaid
stateDiagram-v2
    [*] --> LocalOnly: sync=false, enabled=false
    [*] --> PlatformOnly: sync=false, enabled=true
    [*] --> DualSync: sync=true, enabled=true

    LocalOnly: .txt files only
    PlatformOnly: GitHub/GitLab Issues only
    DualSync: Local files + synced to Issues

    state PlatformOnly {
        GH: GitHub Issues (gh CLI)
        GL: GitLab Issues (glab CLI)
    }
```

Three operational modes controlled by `issues-tracker.json`:
- **Local only** (default) — Tasks/ideas in plain `.txt` files
- **Platform only** — GitHub/GitLab Issues as the sole data source; release state stored in a platform issue
- **Dual sync** — Local files as primary, synced to platform Issues

## Cross-Platform Design

All scripts use `platform.system()` detection and dispatch to platform-specific implementations:
- **Port management** — `lsof`/`ss` on Unix, `netstat`/`taskkill` on Windows
- **File paths** — Forward-slash normalization throughout
- **Python command** — Scripts reference `python3`; Windows users substitute `python`
- **CLI tools** — `gh` (GitHub) or `glab` (GitLab) based on configuration
