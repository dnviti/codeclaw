---
title: Deployment
description: CI/CD pipelines, GitHub Actions workflows, GitLab CI templates, Docker tagging strategy, and production setup
generated-by: ctdf-docs
generated-at: 2026-03-17T10:00:00Z
source-files:
  - .github/workflows/ci.yml
  - .github/workflows/release.yml
  - templates/github/workflows/ci.yml
  - templates/github/workflows/release.yml
  - templates/github/workflows/staging-merge.yml
  - templates/github/workflows/security.yml
  - templates/github/workflows/agentic-fleet.yml
  - templates/github/workflows/agentic-task.yml
  - templates/github/workflows/agentic-docs.yml
  - templates/github/workflows/issue-triage.yml
  - templates/github/workflows/status-guard.yml
  - templates/gitlab/agentic-fleet.gitlab-ci.yml
  - templates/gitlab/agentic-task.gitlab-ci.yml
  - templates/gitlab/agentic-docs.gitlab-ci.yml
  - templates/gitlab/staging-merge.gitlab-ci.yml
  - scripts/agent_runner.py
---

## Overview

CTDF provides CI/CD pipeline templates for both GitHub Actions and GitLab CI/CD. These templates are copied into your project during `/setup init` or `/setup agentic-fleet` and can be customized for your stack.

## CTDF's Own CI/CD

The CTDF plugin itself uses two GitHub Actions workflows:

### CI Pipeline (`.github/workflows/ci.yml`)

Runs on pull requests to `main`, `develop`, and `staging` branches. Template-based with placeholder sections for project-specific lint, test, and build commands.

### Release Pipeline (`.github/workflows/release.yml`)

Triggers on pushes to `main` that modify plugin-relevant paths (`skills/`, `scripts/`, `config/`, `templates/`, `hooks/`, `CLAUDE.md`). Automatically:

1. Reads version from `.claude-plugin/plugin.json`
2. Checks if the tag already exists
3. Generates release notes from commit history
4. Creates a zip archive of the repository
5. Tags and creates a GitHub Release with the archive

## Template Workflows for Your Project

### GitHub Actions Templates

Located in `templates/github/workflows/`:

| Template | Trigger | Purpose |
|----------|---------|---------|
| `ci.yml` | PR to main/develop/staging | Lint, test, build (placeholder-based) |
| `release.yml` | Workflow dispatch or main push | Create tagged release with notes |
| `staging-merge.yml` | Push to staging | Build and push `latest` Docker image |
| `security.yml` | Schedule or manual | Security scanning |
| `agentic-fleet.yml` | Release publish | Orchestrates scout and docs pipelines |
| `agentic-task.yml` | Cron schedule | Autonomous task implementation |
| `agentic-docs.yml` | Release publish | Autonomous documentation sync |
| `issue-triage.yml` | Issue/PR events | Auto-label and triage |
| `status-guard.yml` | Status events | Guard branch protections |

### GitLab CI Templates

Located in `templates/gitlab/`:

| Template | Trigger | Purpose |
|----------|---------|---------|
| `agentic-fleet.gitlab-ci.yml` | Release | Orchestrates scout and docs pipelines |
| `agentic-task.gitlab-ci.yml` | Schedule | Autonomous task implementation |
| `agentic-docs.gitlab-ci.yml` | Release | Autonomous documentation sync |
| `staging-merge.gitlab-ci.yml` | Merge to staging | Build and push Docker images |

## Agentic Fleet Pipelines

The agentic fleet uses AI agents in CI/CD to automate development tasks.

```mermaid
flowchart TD
    subgraph "Triggers"
        CRON["Cron Schedule"]
        REL["Release Published"]
    end

    subgraph "Pipeline Types"
        TASK["Task Pipeline<br>Pick task → implement →<br>create PR"]
        SCOUT["Scout Pipeline<br>Research trends →<br>create ideas"]
        DOCS["Docs Pipeline<br>Sync documentation →<br>commit changes"]
    end

    subgraph "Three-Agent Architecture"
        ORCH["Orchestrator<br>codebase_analyzer.py"]
        WORK["Worker<br>agent_runner.py"]
        MEM["Memory Builder<br>memory_builder.py"]
    end

    CRON --> TASK
    REL --> SCOUT & DOCS

    ORCH -->|"analysis reports"| WORK
    MEM -->|"project memory"| WORK
    WORK --> TASK & SCOUT & DOCS
```

### Provider Support

| Provider | CLI | Task Model | Scout/Docs Model | Budget |
|----------|-----|------------|-------------------|--------|
| Claude | `claude` | `claude-opus-4-6` | `claude-sonnet-4-6` | Configurable USD |
| OpenAI | `codex` | `o3` | `o3-mini` | N/A |
| OpenClaw | `openclaw` | Default | Default | N/A |

### Required Secrets

| Secret | Provider | Purpose |
|--------|----------|---------|
| `ANTHROPIC_API_KEY` | Claude | API authentication |
| `OPENAI_API_KEY` | OpenAI | API authentication |
| `OPENCLAW_API_KEY` | OpenClaw | API authentication |
| `GH_TOKEN` / `GITHUB_TOKEN` | All | Repository access |

## Docker Tagging Strategy

```mermaid
flowchart LR
    subgraph "Staging Push"
        STG_PUSH["Push to staging branch"]
        STG_BUILD["Build Docker image"]
        STG_TAG["Tag: latest"]
    end

    subgraph "Production Tag"
        PROD_TAG["Push tag v*"]
        PROD_BUILD["Build Docker image"]
        PROD_TAGS["Tags: stable, vX.X.X"]
    end

    STG_PUSH --> STG_BUILD --> STG_TAG
    PROD_TAG --> PROD_BUILD --> PROD_TAGS
```

| Branch | Trigger | Docker Tags |
|--------|---------|-------------|
| `staging` | Push to staging | `latest` |
| `main` | Release tag push (`v*`) | `stable`, `vX.X.X` |

## Release Pipeline Deployment Flow

The `/release continue` command executes a 9-stage pipeline with built-in deployment steps:

```mermaid
flowchart TD
    S5["Stage 5: Merge to Staging"]
    S5_BUILD["Local Build Gate<br>verify_command"]
    S5_PUSH["Push to staging"]
    S5_DOCKER["CI builds 'latest' Docker"]

    S7["Stage 7: Merge to Main"]
    S7_BUMP["Version Bump Gate"]
    S7_BUILD["Local Build Gate"]
    S7_TAG["Tag vX.X.X"]
    S7_PUSH["Push to main + tags"]
    S7_CI["CI Monitor Agents<br>(parallel, one per workflow)"]
    S7_DOCKER["CI builds 'stable' +<br>'vX.X.X' Docker"]
    S7_RELEASE["Create GitHub/GitLab Release"]

    S5 --> S5_BUILD --> S5_PUSH --> S5_DOCKER
    S7 --> S7_BUMP --> S7_BUILD --> S7_TAG --> S7_PUSH --> S7_CI --> S7_DOCKER --> S7_RELEASE
```

### Local Build Gate

Before any push (staging or production), the release pipeline runs the configured `verify_command` locally. This catches:
- Version bump regressions
- Post-merge compilation errors
- Missing dependency issues

### CI Monitoring (Platform-Only)

After tagging, parallel monitor agents watch each CI workflow:
1. Detect workflow runs triggered by the tag push
2. Poll for completion
3. If a workflow fails: analyze the failure, create a fix PR, merge it
4. Move the tag: delete old tag → pull fix → rebuild locally → re-tag → recreate release

## Setup Commands

### Install Templates

```
/setup init
```

Copies CI/CD templates to your project and replaces placeholders with detected stack values.

### Configure Agentic Fleet

```
/setup agentic-fleet
```

Guides you through:
1. Selecting an AI provider
2. Configuring models and budgets
3. Copying workflow files
4. Setting up prompt templates
5. Configuring repository secrets
