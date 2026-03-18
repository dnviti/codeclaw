---
title: API Reference
description: CLI commands, skill interfaces, script subcommands, and hook specifications
generated-by: ctdf-docs
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
  - scripts/setup_labels.py
  - scripts/setup_protection.py
  - hooks/hooks.json
---

## Skills (Slash Commands)

### /task

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/task pick` | `[CODE]` | Pick up next (or specific) task; creates worktree, presents briefing |
| `/task pick all` | `[sequential]` | Pick up and implement all pending release tasks |
| `/task create` | `[description]` | Create a new task with auto-assigned ID |
| `/task create all` | `[sequential]` | Create tasks from all pending ideas |
| `/task continue` | `[CODE]` | Resume work on a specific in-progress task |
| `/task continue all` | `[sequential]` | Continue all in-progress tasks |
| `/task schedule` | `CODE [CODE2...] to X.X.X` | Assign task(s) to a release milestone |
| `/task status` | -- | Show current task summary |

### /idea

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/idea create` | `[description]` | Add a lightweight idea to the backlog |
| `/idea approve` | `[IDEA-CODE]` | Promote an idea to a full task |
| `/idea disapprove` | `[IDEA-CODE]` | Reject and archive an idea |
| `/idea refactor` | `[IDEA-CODE]` | Update ideas to reflect codebase changes |
| `/idea scout` | `[focus area]` | Research trends and suggest new ideas |

### /release

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/release create` | `X.X.X` | Create an empty release milestone |
| `/release generate` | -- | Analyze tasks and auto-generate release roadmap |
| `/release continue` | `X.X.X` | Full 9-stage release pipeline |
| `/release resume` | -- | Resume from last saved stage |
| `/release close` | `X.X.X` | Finalize: verify tasks, close milestone, cleanup |
| `/release security-only` | -- | Run security analysis alone |
| `/release test-only` | -- | Run integration tests alone |

### /docs

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/docs generate` | -- | Full documentation generation from codebase |
| `/docs sync` | -- | Incremental update of stale sections |
| `/docs reset` | -- | Remove all generated documentation |
| `/docs publish` | -- | Build and publish docs as static website |

### /setup

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/setup` | `[project name]` | Initialize task/idea tracking, branches, CI/CD, vector memory, social config |
| `/setup env` | `[section]` | Scan project to detect tech stack |
| `/setup init` | `[purpose]` | Full project scaffold |
| `/setup branch-strategy` | -- | Configure branch strategy |
| `/setup agentic-fleet` | -- | Set up AI-powered CI/CD pipelines |

### /tests

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/tests discover` | -- | Find all test files |
| `/tests analyze` | `[target]` | Analyze test coverage gaps |
| `/tests suggest` | -- | Recommend test targets |
| `/tests run` | `[target]` | Execute tests |
| `/tests coverage` | `[subcommand]` | Persistent coverage tracking |

### /update

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/update` | `[category]` | Update CTDF-managed files to latest plugin version |

### /help

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/help` | -- | Show available skills and usage |

---

## Script CLI Reference

All scripts output JSON by default and have zero external dependencies (stdlib only) unless noted.

### task_manager.py

```bash
python3 scripts/task_manager.py <subcommand> [options]
```

| Subcommand | Key Options | Description |
|------------|-------------|-------------|
| `list` | `--status STATUS`, `--format text\|json\|summary` | List tasks/ideas by status |
| `parse` | `CODE` | Parse a single task/idea block |
| `next-id` | `--type task\|idea`, `--source platform-titles` | Generate the next sequential task ID |
| `move` | `CODE --to progressing\|done\|todo`, `--completed-summary TEXT` | Move a task between statuses |
| `sections` | `--file FILE` | List sections in a task file |
| `duplicates` | `--keywords TEXT` | Detect duplicate tasks by keywords |
| `hook` | `FILE_PATH` | PostToolUse hook: correlate file edit to task |
| `platform-cmd` | `OPERATION [key=value...]` | Run a platform (GitHub/GitLab) operation |
| `setup-task-worktree` | `--task-code CODE`, `--base-branch BRANCH` | Create isolated git worktree for a task |
| `remove-worktree` | `--task-code CODE` | Remove a task's worktree (merges branch into develop first) |
| `list-release-tasks` | `--version VERSION` | List all tasks assigned to a release |
| `schedule-tasks` | `--codes "CODE1,CODE2"`, `--version VERSION` | Assign tasks to a release |
| `create-patch-task` | `--source SOURCE`, `--title TITLE`, `--release VERSION` | Create a release patch task (RPAT) |
| `sync-from-platform` | `--dry-run`, `--format text` | Sync task status from platform Issues |
| `deregister-agent` | `--session-id ID` | Deregister a completed agent session |
| `add-test-procedure` | `CODE --body TEXT` | Append testing instructions to a task |
| `set-release` | `CODE VERSION` | Set the release assignment for a task |

**platform-cmd operations:**

| Operation | Description |
|-----------|-------------|
| `list-issues` | List issues with label/state filters |
| `search-issues` | Search issues by query |
| `view-issue` | View a specific issue |
| `edit-issue` | Edit issue labels, assignees, milestone |
| `close-issue` | Close an issue |
| `comment-issue` | Post a comment on an issue |
| `create-issue` | Create a new issue |
| `create-pr` | Create a pull request |
| `list-pr` | List pull requests |
| `merge-pr` | Merge a pull request |
| `create-release` | Create a GitHub/GitLab release |
| `edit-release` | Edit an existing release |
| `close-milestone` | Close a milestone |
| `list-ci-runs` | List CI/CD workflow runs |

### release_manager.py

```bash
python3 scripts/release_manager.py <subcommand> [options]
```

| Subcommand | Key Options | Description |
|------------|-------------|-------------|
| `full-context` | -- | Return complete release context as JSON |
| `parse-commits` | `--since TAG` | Parse conventional commits since a tag |
| `generate-changelog` | `--version VERSION`, `--date DATE` | Generate changelog in Keep a Changelog format |
| `update-versions` | `--version VERSION`, `--package-paths PATHS` | Discover and update version in all manifests |
| `release-state-get` | -- | Read current release state (platform issue in platform-only mode) |
| `release-state-set` | `--version V`, `--stage N`, `--stage-name NAME`, `--branch B`, `--add-completed-task CODE`, `--add-issue JSON`, `--increment-loop`, `--mark-gate-approved N` | Persist release pipeline state |
| `release-state-clear` | -- | Clear saved release state (closes platform issue in platform-only mode) |
| `release-plan-list` | -- | List all releases in the release plan |
| `release-plan-create` | `--version VERSION`, `--theme TEXT`, `--target-date DATE` | Create a new release entry |
| `release-plan-add-task` | `--version VERSION`, `--task-code CODE` | Add a task to a release |
| `release-plan-mark-released` | `--version VERSION` | Mark a release as released |
| `release-plan-set-status` | `--version VERSION`, `--status STATUS` | Update a release status |
| `merge-check` | `--source BRANCH`, `--target BRANCH` | Check for merge conflicts without merging |
| `release-close` | `--version VERSION` | Check release readiness for closing |
| `list-release-tasks` | `--version VERSION` | List tasks for a release with platform status |

> **Release state in platform-only mode:** `release-state-get/set/clear` transparently read/write a GitHub/GitLab issue labeled `ctdf-release-state`, so all collaborators share the same pipeline state.

### skill_helper.py

```bash
python3 scripts/skill_helper.py <subcommand> [options]
```

| Subcommand | Key Options | Description |
|------------|-------------|-------------|
| `context` | -- | Return platform config, worktree state, branch config, submodules as JSON |
| `dispatch` | `--skill NAME`, `--args TEXT` | Parse skill arguments: flow, yolo, task code |
| `setup-task-worktree` | `--task-code CODE`, `--base-branch BRANCH` | Create isolated git worktree for a task |
| `list-submodules` | -- | List git submodules with paths |
| `status-report` | -- | Pre-computed status: task counts, in-progress, next recommended, worktrees |

### ollama_manager.py

```bash
python3 scripts/ollama_manager.py <subcommand> [options]
```

| Subcommand | Key Options | Description |
|------------|-------------|-------------|
| `detect-hardware` | -- | Detect RAM, VRAM, GPU vendor, CPU cores |
| `recommend-model` | `--ram-gb N`, `--vram-gb N` | Recommend the best model tier for the hardware |
| `score-task` | `--description TEXT` | Score a task description for offload suitability (0–10) |
| `should-offload` | `--tool NAME`, `--args TEXT`, `--level N` | Determine if a tool call should be routed to Ollama |
| `get-offload-level` | -- | Return the configured offloading level |
| `query` | `--prompt TEXT`, `--model MODEL` | Send a prompt to Ollama and return the response |
| `install` | -- | Install Ollama if not present |
| `pull-model` | `--model MODEL` | Pull a model into Ollama |

### scripts/hooks/pre_tool_offload.py

PreToolUse hook. Not intended for direct CLI use; invoked by Claude Code via `hooks.json`.

```bash
# For testing:
python3 scripts/hooks/pre_tool_offload.py <tool_name> <tool_args>
```

**Exit codes:**
- `0` with `{"action": "proceed"}` — Do not offload, Claude executes the tool normally
- `0` with `{"action": "offload", "provider": "ollama", "model": "...", ...}` — Offload to Ollama
- `2` — Hook blocked gracefully (fallback: proceed)

**Environment variables consumed:**
- `CLAUDE_TOOL_NAME` — Tool name (e.g., `"Bash"`)
- `CLAUDE_TOOL_INPUT` — Serialized tool arguments

### vector_memory.py

```bash
python3 scripts/vector_memory.py <subcommand> [options]
```

| Subcommand | Key Options | Description |
|------------|-------------|-------------|
| `index` | `--path PATH` | Index a file or directory |
| `search` | `--query TEXT`, `--limit N` | Semantic search the vector store |
| `hook` | `FILE_PATH` | PostToolUse hook: auto-index an edited file |
| `gc` | `--json` | Garbage-collect stale entries; compact index |
| `status` | -- | Report index size, entry count, last GC |
| `server` | -- | Start the MCP server (stdio transport) |

> **Prerequisites:** `pip install lancedb sentence-transformers mcp`

### docs_manager.py

```bash
python3 scripts/docs_manager.py <subcommand> [options]
```

| Subcommand | Key Options | Description |
|------------|-------------|-------------|
| `discover` | -- | Scan codebase: languages, frameworks, file roles |
| `check-staleness` | -- | Compare source hashes against `.docs-manifest.json` |
| `list-sections` | -- | List doc sections with existence status |
| `init-manifest` | `--sections-json JSON` | Create/update `.docs-manifest.json` |
| `clean` | -- | Remove all generated doc files |
| `detect-site-generator` | -- | Check for static site generators |
| `diff-since-tag` | `--tag TAG` | Return changed files since a git tag |

### agent_runner.py

```bash
python3 scripts/agent_runner.py run --pipeline <task|scout|docs> [options]
```

| Option | Description |
|--------|-------------|
| `--pipeline` | Pipeline type: `task`, `scout`, or `docs` (required) |
| `--provider` | AI provider: `claude`, `openai`, `ollama` |
| `--model` | Model override |
| `--budget` | Budget in USD (Claude only) |
| `--dry-run` | Print command without executing |

### app_manager.py

```bash
python3 scripts/app_manager.py <subcommand> [options]
```

| Subcommand | Key Options | Description |
|------------|-------------|-------------|
| `check-ports` | `PORT [PORT...]` | Check which ports are in use |
| `kill-ports` | `PORT [PORT...]` | Kill processes on specified ports |
| `verify-ports` | `--expect bound\|free PORT [PORT...]` | Verify port state |
| `sleep` | `SECONDS` | Cross-platform sleep |

### codebase_analyzer.py

```bash
python3 scripts/codebase_analyzer.py analyze [options]
```

| Option | Description |
|--------|-------------|
| `--root PATH` | Project root directory |
| `--focus AREAS` | Comma-separated: `infrastructure`, `features`, `quality` |
| `--output-dir DIR` | Directory for report files |
| `--output FILE` | Single output file (single focus only) |

### memory_builder.py

```bash
python3 scripts/memory_builder.py generate [options]
```

| Option | Description |
|--------|-------------|
| `--root PATH` | Project root directory |
| `--output FILE` | Output file path (default: stdout) |
| `--max-depth N` | Directory tree depth limit (default: 4) |
| `--max-size N` | Maximum output size in bytes (default: 40000) |

### test_manager.py

```bash
python3 scripts/test_manager.py <subcommand> [options]
```

| Subcommand | Key Options | Description |
|------------|-------------|-------------|
| `discover` | `--root PATH` | Find all test files |
| `analyze-gaps` | `--root PATH`, `--target FILE` | Compare source vs test coverage |
| `suggest` | `--root PATH` | Recommend test targets by priority |
| `run` | `--root PATH`, `--target FILE` | Execute tests via configured framework |
| `coverage snapshot` | `--root PATH` | Capture current coverage state |
| `coverage compare` | `--old FILE`, `--new FILE` | Diff two snapshots |
| `coverage report` | `--root PATH` | Generate human-readable coverage report |
| `coverage threshold-check` | `--min-coverage N` | Pass/fail against minimum |
| `coverage list-snapshots` | `--root PATH` | List available snapshots |

### setup_labels.py

```bash
python3 scripts/setup_labels.py
```

Creates all required labels (source, task, idea, priority, status, section) on the configured GitHub/GitLab repository. Idempotent.

### setup_protection.py

```bash
python3 scripts/setup_protection.py [options]
```

| Option | Description |
|--------|-------------|
| `--branch NAME` | Branch to protect (default: `main`) |
| `--required-reviews N` | Required approving reviews (default: 1) |
| `--status-checks NAME...` | Required CI check names |
| `--merge-queue` | Print merge queue setup instructions |

---

## Hook Specification

### PreToolUse Hook

**Trigger:** Before any `Bash`, `Read`, `Grep`, `Glob`, `Edit`, or `Write` tool call
**Handler:** `scripts/hooks/pre_tool_offload.py "$CLAUDE_TOOL_NAME" "$CLAUDE_TOOL_INPUT"`

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash|Read|Grep|Glob|Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/hooks/pre_tool_offload.py \"$CLAUDE_TOOL_NAME\" \"$CLAUDE_TOOL_INPUT\""
          }
        ]
      }
    ]
  }
}
```

**Behavior:**
1. Loads Ollama config from `.claude/ollama-config.json`
2. Checks whether tool call offloading is enabled and the tool is on the include list
3. Applies NFKC Unicode normalization to `tool_args` and checks exclude patterns (prevents fullwidth-space/homoglyph bypass)
4. If offload: emits `{"action": "offload", "provider": "ollama", "model": "...", "api_base": "...", "tool_name": "...", "offload_level": N}`
5. If pass-through: emits `{"action": "proceed"}`
6. Any exception → gracefully emits `{"action": "proceed"}` (never blocks Claude)

### PostToolUse Hooks

**Trigger:** After any `Edit` or `Write` tool call
**Handlers (both run):**
1. `task_manager.py hook "$CLAUDE_FILE_PATH"` — correlates file to in-progress task
2. `vector_memory.py hook "$CLAUDE_FILE_PATH"` — re-indexes the file in the vector store

```json
{
  "PostToolUse": [
    {
      "matcher": "Edit|Write",
      "hooks": [
        {
          "type": "command",
          "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py hook \"$CLAUDE_FILE_PATH\""
        },
        {
          "type": "command",
          "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/vector_memory.py hook \"$CLAUDE_FILE_PATH\""
        }
      ]
    }
  ]
}
```

**Task hook behavior:** Finds the in-progress task (from `progressing.txt` or platform) and logs the file path as modified by that task.

**Vector memory hook behavior:** Reads the modified file, re-embeds its content, and upserts into the LanceDB index at `.claude/memory/vectors`.
