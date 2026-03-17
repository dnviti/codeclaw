---
title: Configuration
description: Environment variables, configuration files, feature flags, and project settings
generated-by: ctdf-docs
generated-at: 2026-03-17T10:00:00Z
source-files:
  - config/project-config.example.json
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

CTDF uses JSON configuration files stored in the `.claude/` directory of your project and a `CLAUDE.md` file for project-specific variables. Configuration is layered: CLI flags override environment variables, which override config files, which override defaults.

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
| `labels.source` | `string` | Label applied to all CTDF-created issues |
| `labels.task` | `string` | Label for task issues |
| `labels.idea` | `string` | Label for idea issues |
| `labels.priority` | `object` | Maps priority levels to label names |
| `labels.status` | `object` | Maps task statuses to label names |
| `labels.sections` | `object` | Custom section labels for task organization |
| `labels.release_prefix` | `string` | Prefix for release milestone labels |

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
  "release_branch": ""
}
```

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
| `tech_detail_layers` | Technology layers for task technical details (e.g., `"Backend, Frontend, Database"`) |
| `idea_categories` | Categories for idea classification |
| `doc_categories` | Categories for documentation sections |
| `project_context` | Free-text project description for AI context |
| `scout_categories` | Focus areas for the idea scout pipeline |
| `package_json_paths` | Comma-separated paths to `package.json` files (monorepo support) |
| `changelog_file` | Changelog file path (default: `CHANGELOG.md`) |
| `tag_prefix` | Git tag prefix (default: `v`) |
| `github_repo_url` | Repository URL for changelog links |
| `release_branch` | Branch to release from (default: `develop`) |

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
| `provider` | AI provider: `"claude"`, `"openai"`, or `"openclaw"` |
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
| `OPENCLAW_API_KEY` | OpenClaw API authentication | `agent_runner.py` |
| `AGENTIC_PROVIDER` | Override provider selection | `agent_runner.py` |
| `AGENTIC_AUTO_PR` | Override auto-PR creation (`true`/`false`) | `agent_runner.py` |
| `GITLAB_CI` | GitLab CI detection | `agent_runner.py` |
| `GH_TOKEN` | GitHub API authentication for CI | GitHub Actions workflows |

## Feature Flags

CTDF uses configuration-driven feature flags rather than compile-time flags:

| Flag | Config location | Effect |
|------|-----------------|--------|
| Issues integration | `issues-tracker.json → enabled` | Enables platform Issues sync |
| Dual sync | `issues-tracker.json → sync` | Enables bidirectional file/Issues sync |
| Auto-PR | `agentic-provider.json → auto_pr` | Auto-creates PRs in task pipeline |
| Yolo mode | Appended to any command | Auto-confirms all non-destructive gates |
| Merge queue | `setup_protection.py --merge-queue` | Prints merge queue setup instructions |
