---
title: LLM Context
description: Consolidated single-file reference for LLM/bot consumption
generated-by: claw-docs
generated-at: 2026-03-29T00:00:00Z
source-files:
  - README.md
  - AGENTS.md
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
  - scripts/test_manager.py
  - scripts/build_ccpkg.py
  - scripts/build_portable.py
  - scripts/social_announcer.py
  - scripts/hooks/pre_tool_offload.py
  - .claude-plugin/plugin.json
  - config/project-config.example.json
  - config/ollama-config.example.json
---

<!-- MACHINE-READABLE METADATA
project: CodeClaw
version: 4.0.5
type: claude-code-plugin
language: python3
dependencies: stdlib-only for the supported core flow
platforms: linux, macos, windows
repository: https://github.com/dnviti/codeclaw
license: MIT
skills: task, idea, release, docs, setup, update, tests, help, crazy
hooks: PreToolUse(Bash|Read|Grep|Glob|Edit|Write), PostToolUse(Edit|Write)
-->

## Project Summary

CodeClaw is a project-agnostic Claude Code plugin that provides:
1. **Task and idea management** through plain-text files and slash commands
2. **GitHub/GitLab Issues integration** in local-only, platform-only, or dual-sync modes
3. **A gated 9-stage release pipeline** with staging and production promotion
4. **Manifest-based documentation sync** with hash-based staleness tracking
5. **Optional Ollama routing** for local tool-call offloading
6. **Cross-platform support** for Linux, macOS, and Windows
7. **[BETA] /crazy** for fully autonomous project building

## Architecture Overview

### Three Layers

```text
Skills (SKILL.md)  -> Declarative AI behavior
Scripts (*.py)     -> Deterministic logic
Hooks (hooks.json) -> Event-driven integration
```

### Key Scripts

| Script | Purpose |
|--------|---------|
| `scripts/task_manager.py` | Task/idea CRUD, platform sync, branch management |
| `scripts/release_manager.py` | Version detection, changelog, release state |
| `scripts/skill_helper.py` | Context gathering, argument dispatch, branch management |
| `scripts/config_lock.py` | Cross-platform file locking for atomic config writes |
| `scripts/ollama_manager.py` | Local model routing, hardware detection, tool-calling loop |
| `scripts/docs_manager.py` | Documentation lifecycle and hash-based staleness tracking |
| `scripts/test_manager.py` | Test discovery, gap analysis, coverage tracking |
| `scripts/build_ccpkg.py` | Package builder for distributable archives |
| `scripts/build_portable.py` | Portable ZIP builder for cross-tool installation |
| `scripts/social_announcer.py` | Release announcement generator and poster |
| `scripts/hooks/pre_tool_offload.py` | PreToolUse routing to Ollama |

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
      "scripts/task_manager.py hook $CLAUDE_FILE_PATH"
    ]
  }
}
```

### Branch Strategy

```text
develop -> staging -> main
```

- `develop` receives feature work
- `staging` is pre-release validation
- `main` contains production releases and tags

---

## Key APIs

### task_manager.py CLI

```bash
python3 scripts/task_manager.py <subcommand> [options]
```

Essential subcommands:
- `list --status todo|progressing|done|idea --format summary|json`
- `list-ideas --file ideas|disapproved|all --format json|summary`
- `parse CODE`
- `next-id --type task|idea --source local|platform-titles`
- `move CODE --to progressing|done|todo --completed-summary TEXT`
- `remove CODE --file FILE`
- `summary --format json|text`
- `platform-cmd OPERATION [key=value...]`
- `list-release-tasks --version X.X.X`
- `schedule-tasks --codes "CODE1,CODE2" --version X.X.X`
- `create-patch-task --source SOURCE --title TITLE --release X.X.X`
- `sync-from-platform --dry-run`
- `find-files --patterns GLOBS --max-depth N`
- `pr-body --task-code CODE --title TEXT --summary TEXT`

### release_manager.py CLI

```bash
python3 scripts/release_manager.py <subcommand> [options]
```

Essential subcommands:
- `full-context --tag-prefix PREFIX`
- `current-version --tag-prefix PREFIX`
- `release-state-get`
- `release-state-set --version V --stage N --stage-name NAME`
- `release-state-clear`
- `merge-check --source BRANCH --target BRANCH`
- `parse-commits --since TAG`
- `suggest-bump --current-version V --force TYPE`
- `generate-changelog --version V --date YYYY-MM-DD`
- `update-versions --version V --package-paths PATHS`
- `release-generate`
- `release-plan-list`
- `release-plan-create --version V --theme TEXT --target-date DATE`
- `release-plan-add-task --version V --task CODE`
- `release-plan-next`
- `release-close --version V`
- `coverage-gate --min-coverage N`

### skill_helper.py CLI

```bash
python3 scripts/skill_helper.py <subcommand> [options]
```

Essential subcommands:
- `context`
- `dispatch --skill NAME --args TEXT`
- `status-report`

### ollama_manager.py CLI

```bash
python3 scripts/ollama_manager.py <subcommand> [options]
```

Essential subcommands:
- `detect-hardware`
- `recommend-model --ram-gb N --vram-gb N`
- `score-task --description TEXT`
- `should-offload --tool NAME --args TEXT --level N`
- `get-offload-level`
- `query --prompt TEXT --model MODEL`
- `install`
- `pull-model --model MODEL`

### test_manager.py CLI

```bash
python3 scripts/test_manager.py <subcommand> [options]
```

Essential subcommands:
- `discover --root PATH`
- `analyze-gaps --root PATH --target FILE`
- `suggest --root PATH`
- `run --root PATH --target FILE`
- `coverage snapshot --root PATH`
- `coverage compare --old FILE --new FILE`
- `coverage threshold-check --min-coverage N`

### docs_manager.py CLI

```bash
python3 scripts/docs_manager.py <subcommand> [options]
```

Essential subcommands:
- `discover`
- `check-staleness`
- `list-sections`
- `init-manifest --sections-json JSON --visual-richness TIER`
- `clean`
- `get-visual-richness`
- `detect-site-generator`
- `diff-since-tag --tag TAG`

---

## Configuration Reference

### `.claude/issues-tracker.json`

```json
{
  "platform": "github",
  "enabled": true,
  "sync": false,
  "repo": "owner/repo"
}
```

When `enabled: true` and `sync: false`, release state is stored in a `claw-release-state` platform issue.

### `.claude/project-config.json`

Key fields:
- `verify_command`
- `tag_prefix`
- `changelog_file`
- `development_branch`
- `staging_branch`
- `production_branch`
- `show_generated_footer`
- `project_context`
- `social_announce`
- `ollama`

Legacy provider blocks are not part of the supported configuration surface.

### `.claude/ollama-config.json`

```json
{
  "enabled": false,
  "model": "",
  "api_base": "http://localhost:11434",
  "offloading": {
    "level": 5,
    "tool_calls": {
      "enabled": false,
      "exclude_patterns": ["git push", "git reset", "rm -rf", "sudo"]
    }
  },
  "tool_calling": {
    "enabled": true,
    "max_tool_rounds": 10
  }
}
```

---

## Quick-Start Commands

```bash
/plugin marketplace add https://github.com/dnviti/codeclaw
/plugin install claw@dnviti-plugins
/setup "My Project"
/idea create "Feature description"
/idea approve IDEA-FEAT-0001
/task pick FEAT-0001
/release continue 1.0.0
/docs sync
```

---

## Release State Machine

| Stage | Name | Key Action |
|-------|------|------------|
| 1 | Create Branch | `git checkout -b release/X.X.X develop` |
| 2 | Task Readiness Gate | Verify all release tasks are `done` |
| 3 | Fetch Open PRs | List PRs on the release branch |
| 4 | Per-PR Analysis | Parallel review and fix cycle |
| 5 | Merge to Staging | `develop -> staging` with local build gate |
| 6 | Integration Tests | Run the configured test command |
| 7 | Merge to Main + Tag | `staging -> main` with version bump gate |
| 7h | Docs Sync | `/docs sync` |
| 8 | Users Testing | Release is live |
| 9 | End | Close the milestone and clear state |
