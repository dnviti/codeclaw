---
title: Configuration
description: Environment variables, configuration files, feature flags, and project settings
generated-by: claw-docs
generated-at: 2026-03-29T00:00:00Z
source-files:
  - config/issues-tracker.example.json
  - config/project-config.example.json
  - config/releases.example.json
  - config/ollama-config.example.json
  - scripts/skill_helper.py
  - scripts/release_manager.py
  - scripts/task_manager.py
  - scripts/ollama_manager.py
  - skills/setup/SKILL.md
  - skills/release/SKILL.md
---

## Overview

CodeClaw uses JSON files in `.claude/` for project-specific settings. The supported configuration surface is intentionally small: issues tracking, release metadata, Ollama routing, and a few project-level hints for task, docs, and testing workflows.

## Configuration Files

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
| `platform` | `github` or `gitlab` | Which platform CLI to use (`gh` or `glab`) |
| `enabled` | `boolean` | Enable platform Issues integration |
| `sync` | `boolean` | Enable bidirectional sync between local files and platform Issues |
| `repo` | `string` | Repository identifier such as `owner/repo` |
| `labels.*` | `object` | Label names used by CodeClaw workflows |

> Platform-only mode stores release state in a `claw-release-state` platform issue so collaborators share the same pipeline state.

### project-config.json

Project-specific settings used by skills and release commands.

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
  "development_branch": "develop",
  "staging_branch": "staging",
  "production_branch": "main",
  "release_branch": "",
  "show_generated_footer": true,
  "python_command": "",
  "social_announce": {
    "platforms": {
      "bluesky": { "enabled": false },
      "mastodon": { "enabled": false },
      "discord": { "enabled": false },
      "slack": { "enabled": false }
    }
  },
  "ollama": {
    "enabled": false,
    "model": "",
    "offloading_level": 5
  }
}
```

| Field | Description |
|-------|-------------|
| `dev_ports` | Development server ports for status and helper commands |
| `start_command` | Command to start the app locally |
| `predev_command` | Command to run before local startup |
| `verify_command` | Build/verify command for release gates |
| `test_framework` | Test framework name |
| `test_command` | Command used for tests |
| `test_file_pattern` | Glob used to discover test files |
| `project_context` | Project summary used by task and docs skills |
| `tag_prefix` | Git tag prefix used in releases |
| `development_branch` | Branch name for active development |
| `staging_branch` | Branch name for pre-release validation |
| `production_branch` | Branch name for tagged releases |
| `show_generated_footer` | Append a generated footer to task output |
| `social_announce` | Optional announcement platform toggles |
| `ollama` | Simple quick-enable for local model routing |

**Legacy note:** the removed provider blocks are no longer part of the supported config surface.

### releases.json

Release roadmap with planned milestones.

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
      "tasks": ["MKT-004", "MKT-005", "UI-006"]
    }
  ]
}
```

### ollama-config.json

Full configuration for Ollama routing and tool calling.

**Location:** `.claude/ollama-config.json`
**Example:** `config/ollama-config.example.json`

```json
{
  "enabled": false,
  "model": "",
  "api_base": "http://localhost:11434",
  "offloading": {
    "level": 5,
    "tool_calls": {
      "enabled": false,
      "include_tools": ["Bash", "Read", "Grep", "Glob", "Edit", "Write"],
      "exclude_patterns": ["git push", "git reset", "rm -rf", "sudo", "chmod", "chown"]
    }
  },
  "tool_calling": {
    "enabled": true,
    "max_tool_rounds": 10
  }
}
```

## Project Context Variables

The `/setup` skill records project variables in `project-context.md` so the rest of the CodeClaw docs and skills can stay platform-agnostic:

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

These variables are read by `skill_helper.py` and `test_manager.py` when present. Current docs and skills rely on `project-context.md`.

## Environment Variables

| Variable | Purpose | Used by |
|----------|---------|---------|
| `GH_TOKEN` | GitHub API authentication for CI | GitHub Actions workflows |
| `CLAUDE_TOOL_NAME` | Tool name for PreToolUse hook | `pre_tool_offload.py` |
| `CLAUDE_TOOL_INPUT` | Tool input for PreToolUse hook | `pre_tool_offload.py` |
| `CLAUDE_FILE_PATH` | File path for PostToolUse hook | `task_manager.py` |

## Feature Flags

| Flag | Config location | Effect |
|------|-----------------|--------|
| Issues integration | `issues-tracker.json → enabled` | Enables platform Issues sync |
| Dual sync | `issues-tracker.json → sync` | Enables bidirectional file/Issues sync |
| Platform release state | `issues-tracker.json → enabled=true, sync=false` | Stores release state as a platform issue |
| Ollama routing | `ollama-config.json → enabled` | Routes selected tool calls to a local model |
| Social announce | `project-config.json → social_announce.platforms.<name>.enabled` | Enables release announcements |
| Yolo mode | Appended to any command | Auto-confirms non-destructive gates |
