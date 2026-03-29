---
title: API Reference
description: CLI commands, skill interfaces, script subcommands, and hook specifications
generated-by: claw-docs
generated-at: 2026-03-29T00:00:00Z
source-files:
  - scripts/task_manager.py
  - scripts/release_manager.py
  - scripts/skill_helper.py
  - scripts/docs_manager.py
  - scripts/test_manager.py
  - scripts/ollama_manager.py
  - scripts/build_ccpkg.py
  - scripts/build_portable.py
  - scripts/social_announcer.py
  - scripts/hooks/pre_tool_offload.py
  - hooks/hooks.json
---

## Skills

### /task

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/task pick` | `[CODE]` | Pick up the next or a specific task |
| `/task pick all` | `[sequential]` | Pick up and implement all pending release tasks |
| `/task create` | `[description]` | Create a new task with an auto-assigned ID |
| `/task create all` | `[sequential]` | Create tasks from all pending ideas |
| `/task continue` | `[CODE]` | Resume work on an in-progress task |
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
| `/release generate` | -- | Analyze tasks and auto-generate a roadmap |
| `/release continue` | `X.X.X` | Run the 9-stage release pipeline |
| `/release resume` | -- | Resume from the saved stage |
| `/release close` | `X.X.X` | Finalize and close a release |
| `/release security-only` | -- | Run security analysis alone |
| `/release test-only` | -- | Run integration tests alone |

### /docs

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/docs generate` | -- | Full documentation generation from codebase analysis |
| `/docs sync` | -- | Incremental update of stale sections |
| `/docs reset` | -- | Remove all generated documentation |
| `/docs publish` | -- | Build and publish docs as a static website |

### /setup

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/setup` | `[project name]` | Initialize task tracking, branches, CI/CD, and config |
| `/setup env` | `[section]` | Scan the project and detect the tech stack |
| `/setup init` | `[purpose]` | Full project scaffold |
| `/setup branch-strategy` | -- | Configure branch strategy |

### /tests

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/tests discover` | -- | Find all test files |
| `/tests analyze` | `[target]` | Analyze coverage gaps |
| `/tests suggest` | -- | Recommend test targets |
| `/tests run` | `[target]` | Execute tests |
| `/tests coverage` | `[subcommand]` | Persistent coverage tracking |

### /update

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/update` | `[category]` | Update CodeClaw-managed files to the latest plugin version |

### /help

| Command | Arguments | Description |
|---------|-----------|-------------|
| `/help` | -- | Show available skills and usage |

## Script CLI Reference

All scripts output JSON by default and use the Python standard library for the supported core flow.

### task_manager.py

```bash
python3 scripts/task_manager.py <subcommand> [options]
```

| Subcommand | Key Options | Description |
|------------|-------------|-------------|
| `list` | `--status STATUS`, `--format json\|summary` | List tasks by status |
| `list-ideas` | `--file ideas\|disapproved\|all`, `--format json\|summary` | List ideas |
| `parse` | `CODE` | Parse a single task or idea block |
| `next-id` | `--type task\|idea`, `--source local\|platform-titles` | Generate the next sequential ID |
| `move` | `CODE --to progressing\|done\|todo`, `--completed-summary TEXT` | Move a task between statuses |
| `remove` | `CODE --file FILE` | Remove a block from a file |
| `sections` | `--file FILE` | List sections in a task file |
| `duplicates` | `--keywords TEXT`, `--files FILES` | Detect duplicate tasks by keywords |
| `summary` | `--format json\|text` | Task counts and progress |
| `prefixes` | -- | List all task code prefixes |
| `verify-files` | `CODE` | Check file existence for a task |
| `is-frontend-task` | `CODE`, `--json-body JSON` | Check if a task involves frontend work |
| `hook` | `FILE_PATH` | PostToolUse hook: correlate file edit to task |
| `platform-cmd` | `OPERATION [key=value...]` | Run a platform operation |
| `platform-config` | -- | Return platform tracker configuration |
| `list-release-tasks` | `--version VERSION`, `--format json\|text` | List tasks assigned to a release |
| `schedule-tasks` | `--codes "CODE1,CODE2"`, `--version VERSION` | Assign tasks to a release |
| `create-patch-task` | `--source SOURCE`, `--title TITLE`, `--release VERSION`, `--priority PRIORITY`, `--description TEXT` | Create a release patch task |
| `sync-from-platform` | `--dry-run`, `--format json\|text` | Sync task status from platform Issues |
| `pr-body` | `--task-code CODE`, `--title TEXT`, `--summary TEXT`, `--issue-num NUM`, `--source SOURCE` | Generate a PR body from the template |
| `find-files` | `--patterns GLOBS`, `--max-depth N`, `--limit N`, `--format json\|text` | Cross-platform file search |
| `add-test-procedure` | `CODE --body TEXT` | Append testing instructions to a task |
| `set-release` | `CODE --version VERSION` | Set the release assignment for a task |

### release_manager.py

```bash
python3 scripts/release_manager.py <subcommand> [options]
```

| Subcommand | Key Options | Description |
|------------|-------------|-------------|
| `full-context` | `--tag-prefix PREFIX` | Return complete release context as JSON |
| `current-version` | `--tag-prefix PREFIX` | Detect version from manifest files |
| `parse-commits` | `--since TAG` | Parse conventional commits since a tag |
| `suggest-bump` | `--current-version V`, `--suggested-bump TYPE`, `--force TYPE` | Calculate a version bump |
| `generate-changelog` | `--version VERSION`, `--date DATE` | Generate a Keep a Changelog entry |
| `update-versions` | `--version VERSION`, `--package-paths PATHS` | Discover and update version in all manifests |
| `release-state-get` | -- | Read the current release state |
| `release-state-set` | `--version V`, `--stage N`, `--stage-name NAME`, `--increment-loop` | Persist release pipeline state |
| `release-state-clear` | -- | Clear saved release state |
| `release-generate` | -- | Analyze pending tasks for roadmap generation |
| `release-plan-list` | -- | List all releases in the release plan |
| `release-plan-create` | `--version VERSION`, `--theme TEXT`, `--target-date DATE` | Create a new release entry |
| `release-plan-add-task` | `--version VERSION`, `--task CODE` | Add a task to a release |
| `release-plan-remove-task` | `--version VERSION`, `--task CODE` | Remove a task from a release |
| `release-plan-next` | -- | Get the next planned or in-progress release |
| `release-plan-mark-released` | `--version VERSION` | Mark a release as released |
| `release-plan-set-status` | `--version VERSION`, `--status STATUS` | Update a release status |
| `merge-check` | `--source BRANCH`, `--target BRANCH` | Check for merge conflicts without merging |
| `release-close` | `--version VERSION` | Check release readiness for closing |
| `coverage-gate` | `--min-coverage N` | Run coverage threshold check as a release gate |

### skill_helper.py

```bash
python3 scripts/skill_helper.py <subcommand> [options]
```

| Subcommand | Key Options | Description |
|------------|-------------|-------------|
| `context` | -- | Return platform config, branch config, and submodules as JSON |
| `dispatch` | `--skill NAME`, `--args TEXT` | Parse skill arguments and return the flow |
| `check-project-state` | -- | Return project file existence and project-context.md status |
| `create-project-files` | `--project-name NAME` | Create missing task/idea files |
| `detect-branch-strategy` | -- | Return branch state and needs |
| `status-report` | -- | Pre-computed task counts and next recommendations |
| `list-submodules` | -- | List git submodules with paths |
| `detect-release-config` | -- | Return release configuration |
| `detect-platform` | -- | Detect the AI coding platform and adapter info |
| `refresh-branch-config` | -- | Refresh branch config cache |
| `adapter-invoke` | `--platform PLATFORM`, `--tool TOOL`, `--tool-args ARGS` | Invoke a tool through the platform adapter |

### ollama_manager.py

```bash
python3 scripts/ollama_manager.py <subcommand> [options]
```

| Subcommand | Key Options | Description |
|------------|-------------|-------------|
| `detect-hardware` | -- | Detect RAM, VRAM, GPU vendor, CPU cores |
| `recommend-model` | `--ram-gb N`, `--vram-gb N` | Recommend a model tier for the hardware |
| `score-task` | `--description TEXT` | Score a task description for offload suitability (0–10) |
| `should-offload` | `--tool NAME`, `--args TEXT`, `--level N` | Determine if a tool call should be routed to Ollama |
| `get-offload-level` | -- | Return the configured offloading level |
| `query` | `--prompt TEXT`, `--model MODEL` | Send a prompt to Ollama and return the response |
| `install` | -- | Install Ollama if not present |
| `pull-model` | `--model MODEL` | Pull a model into Ollama |

### docs_manager.py

```bash
python3 scripts/docs_manager.py <subcommand> [options]
```

| Subcommand | Key Options | Description |
|------------|-------------|-------------|
| `discover` | -- | Scan the codebase and classify files |
| `check-staleness` | -- | Compare source hashes against `.docs-manifest.json` |
| `list-sections` | -- | List doc sections with existence status |
| `init-manifest` | `--sections-json JSON`, `--visual-richness TIER` | Create or update `.docs-manifest.json` |
| `clean` | -- | Remove all generated doc files |
| `get-visual-richness` | -- | Return the visual richness tier from the manifest |
| `detect-site-generator` | -- | Check for static site generators |
| `diff-since-tag` | `--tag TAG` | Return changed files since a git tag |

Documentation sync now uses manifest-based discovery and hash-based staleness only.

### test_manager.py

```bash
python3 scripts/test_manager.py <subcommand> [options]
```

| Subcommand | Key Options | Description |
|------------|-------------|-------------|
| `discover` | `--root PATH` | Find all test files |
| `analyze-gaps` | `--root PATH`, `--target FILE` | Compare source vs test coverage |
| `suggest` | `--root PATH` | Recommend test targets by priority |
| `run` | `--root PATH`, `--target FILE` | Execute tests via the configured framework |
| `coverage snapshot` | `--root PATH` | Capture current coverage state |
| `coverage compare` | `--old FILE`, `--new FILE` | Diff two snapshots |
| `coverage report` | `--root PATH` | Generate a human-readable coverage report |
| `coverage threshold-check` | `--min-coverage N` | Pass or fail against a minimum threshold |
| `coverage list-snapshots` | `--root PATH` | List available snapshots |

## Hook Specification

### PreToolUse

**Trigger:** Before any `Bash`, `Read`, `Grep`, `Glob`, `Edit`, or `Write` tool call
**Handler:** `scripts/hooks/pre_tool_offload.py "$CLAUDE_TOOL_NAME" "$CLAUDE_TOOL_INPUT"`

**Behavior:**
1. Loads Ollama config from `.claude/ollama-config.json`
2. Checks whether tool call offloading is enabled
3. Applies NFKC normalization to the tool arguments before matching exclude patterns
4. Emits either `{"action": "offload", ...}` or `{"action": "proceed"}`
5. Falls back to `{"action": "proceed"}` on any error

### PostToolUse

**Trigger:** After any `Edit` or `Write` tool call
**Handler:** `scripts/task_manager.py hook "$CLAUDE_FILE_PATH"`

```json
{
  "PostToolUse": [
    {
      "matcher": "Edit|Write",
      "hooks": [
        {
          "type": "command",
          "command": "python3 ${CLAW_ROOT}/scripts/task_manager.py hook \"$CLAUDE_FILE_PATH\""
        }
      ]
    }
  ]
}
```

The retired hook is no longer part of the supported configuration.
