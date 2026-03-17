---
title: CTDF Documentation
description: Complete technical documentation for the Claude Task Development Framework
generated-by: ctdf-docs
generated-at: 2026-03-17T10:00:00Z
source-files:
  - README.md
  - .claude-plugin/plugin.json
---

# CTDF — Claude Task Development Framework

A project-agnostic task and idea management plugin for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). CTDF gives your AI-assisted development workflow a structured backbone: ideas are captured, evaluated, promoted to tasks, implemented with quality gates, and tracked to completion — all through plain-text files and Claude Code slash commands.

## Table of Contents

| Section | Description |
|---------|-------------|
| [Architecture](architecture.md) | System architecture, component diagrams, data flow |
| [Getting Started](getting-started.md) | Installation, prerequisites, first run |
| [Configuration](configuration.md) | Config files, environment variables, feature flags |
| [API Reference](api-reference.md) | Skills, script CLIs, hooks |
| [Deployment](deployment.md) | CI/CD pipelines, Docker, agentic fleet |
| [Development](development.md) | Contributing, local dev, testing, conventions |
| [Troubleshooting](troubleshooting.md) | Common errors, debugging, FAQ |
| [LLM Context](llm-context.md) | Consolidated reference for LLM/bot consumption |

## Quick Start

```bash
# Install the plugin
/plugin marketplace add https://github.com/dnviti/claude-task-development-framework
/plugin install ctdf@dnviti-claude-task-development-framework

# Set up your project
/setup "My Project"

# Start working
/idea create "Add user authentication"
/idea approve IDEA-AUTH-0001
/task pick AUTH-0001
```

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Runtime | Python 3 (stdlib only, zero dependencies) |
| Host | Claude Code CLI |
| Version Control | Git (worktrees, branches, tags) |
| Platform | GitHub Actions / GitLab CI/CD |
| AI Providers | Claude, OpenAI Codex, OpenClaw |
| Data Format | Plain-text files (`.txt`) + JSON configs |

## Skills Overview

| Skill | Purpose |
|-------|---------|
| `/task` | Task lifecycle: pick, create, continue, schedule, status |
| `/idea` | Idea lifecycle: create, approve, disapprove, refactor, scout |
| `/release` | Release pipeline: create, generate, continue, close |
| `/docs` | Documentation: generate, sync, reset, publish |
| `/setup` | Project initialization and configuration |
| `/update` | Update CTDF-managed files |
| `/tests` | Test discovery, gaps, coverage, execution |
| `/help` | Usage guide |

## Key Design Principles

1. **Project-agnostic** — Works with any language, framework, or tech stack
2. **Zero dependencies** — All scripts use Python 3 stdlib only
3. **Human-in-the-loop** — AI assists, but users decide at every gate
4. **Plain-text first** — Tasks and ideas in simple `.txt` files
5. **Cross-platform** — Linux, macOS, Windows with auto OS detection

## Version

Current plugin version: **3.2.1**

Repository: [github.com/dnviti/claude-task-development-framework](https://github.com/dnviti/claude-task-development-framework)

License: MIT
