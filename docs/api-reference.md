---
title: API Reference
description: CLI commands, skill interfaces, script subcommands, and hook specifications
generated-by: ctdf-docs
generated-at: 2026-03-17T10:00:00Z
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
| `/release continue resume` | -- | Resume from last saved stage |
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
| `/setup` | `[project name]` | Initialize task/idea tracking, branches, CI/CD |
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

All scripts output JSON by default and have zero external dependencies (stdlib only).

### task_manager.py

```bash
python3 scripts/task_manager.py <subcommand> [options]
```

| Subcommand | Key Options | Description |
|------------|-------------|-------------|
| `list` | `--file FILE`, `--format text\|json` | List tasks/ideas from a file |
| `parse-block` | `--code CODE`, `--file FILE` | Parse a single task/idea block |
| `next-id` | `--prefix PREFIX` | Generate the next sequential task ID |
| `move-block` | `--code CODE`, `--from FILE`, `--to FILE` | Move a block between files |
| `remove-block` | `--code CODE`, `--file FILE` | Remove a block from a file |
| `add-block` | `--file FILE`, `--block TEXT` | Add a block to a file |
| `verify-files` | -- | Check all task/idea files for consistency |
| `find-duplicates` | -- | Detect duplicate task codes |
| `hook` | `FILE_PATH` | PostToolUse hook: correlate file edit to task |
| `find-files` | `--pattern GLOB` | Cross-platform file discovery |
| `issue-create` | `--code CODE`, `--title TITLE`, ... | Create a platform issue |
| `issue-update` | `--code CODE`, `--status STATUS` | Update issue status labels |
| `issue-close` | `--code CODE` | Close a platform issue |
| `issue-list` | `--filter FILTER` | List platform issues |
| `milestone-create` | `--version VERSION` | Create a platform milestone |
| `milestone-close` | `--version VERSION` | Close a milestone with verification |
| `milestone-list` | -- | List platform milestones |
| `close-milestone` | `--version VERSION` | Close milestone (alias) |

### release_manager.py

```bash
python3 scripts/release_manager.py <subcommand> [options]
```

| Subcommand | Key Options | Description |
|------------|-------------|-------------|
| `current-version` | `--manifest PATH` | Detect current version from manifests |
| `classify-commits` | `--since TAG`, `--until REF` | Parse and classify commits |
| `next-version` | `--current VERSION`, `--bump TYPE` | Calculate next semantic version |
| `generate-changelog` | `--version VERSION`, `--since TAG` | Generate changelog in Keep a Changelog format |
| `update-changelog` | `--version VERSION`, `--content TEXT` | Insert new version into existing changelog |
| `release-state-save` | `--version VERSION`, `--stage N`, ... | Persist release pipeline state |
| `release-state-get` | -- | Read current release state |
| `release-state-clear` | -- | Clear saved release state |
| `discover-manifests` | -- | Find all version-bearing manifest files |
| `bump-version` | `--file PATH`, `--version VERSION` | Update version in a manifest file |
| `close-milestone` | `--version VERSION` | Close a milestone with open-item verification |

### skill_helper.py

```bash
python3 scripts/skill_helper.py <subcommand> [options]
```

| Subcommand | Key Options | Description |
|------------|-------------|-------------|
| `context` | -- | Return platform config, worktree state, branch config as JSON |
| `dispatch` | `--skill NAME`, `--args TEXT` | Parse skill arguments: flow, yolo, task code |
| `worktree-create` | `--task CODE`, `--branch BRANCH` | Create isolated git worktree for a task |
| `worktree-cleanup` | `--task CODE` | Remove a task's worktree |
| `worktree-list` | -- | List all active worktrees |

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
| `--provider` | AI provider: `claude`, `openai`, `openclaw` |
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

### PostToolUse Hook

**Trigger:** After any `Edit` or `Write` tool call
**Handler:** `task_manager.py hook "$CLAUDE_FILE_PATH"`

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py hook \"$CLAUDE_FILE_PATH\""
          }
        ]
      }
    ]
  }
}
```

**Behavior:** When a file is edited or written, the hook finds the in-progress task (from `progressing.txt`) and logs the file path as a modified file for that task. This enables automatic tracking of which files were changed during task implementation.
