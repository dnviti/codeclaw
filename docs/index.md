---
title: CodeClaw Documentation
description: Complete technical documentation for the CodeClaw
generated-by: claw-docs
generated-at: 2026-03-19T00:00:00Z
source-files:
  - README.md
  - .claude-plugin/plugin.json
  - .claude-plugin/marketplace.json
---

# CodeClaw

A project-agnostic task and idea management plugin for Claude Code with 9 streamlined skills: `/task`, `/idea`, `/release`, `/docs`, `/setup`, `/update`, `/tests`, `/help`, and `/crazy`. It features a gated release pipeline and keeps the workflow rooted in plain-text files and slash commands.

## Table of Contents

| Section | Description |
|---------|-------------|
| [Architecture](architecture.md) | System architecture, component diagrams, data flow |
| [Getting Started](getting-started.md) | Installation, prerequisites, first run |
| [Configuration](configuration.md) | Config files, environment variables, feature flags |
| [API Reference](api-reference.md) | Skills, script CLIs, hooks |
| [Deployment](deployment.md) | CI/CD pipelines, Docker, release automation |
| [Development](development.md) | Contributing, local dev, testing, conventions |
| [Troubleshooting](troubleshooting.md) | Common errors, debugging, FAQ |
| [LLM Context](llm-context.md) | Consolidated reference for LLM/bot consumption |

## Quick Start

```bash
# Install the plugin
/plugin marketplace add https://github.com/dnviti/codeclaw
/plugin install claw@dnviti-plugins

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
| Runtime | Python 3.12+ (stdlib only, zero dependencies) |
| Host | Claude Code CLI |
| Version Control | Git (branches, tags) |
| Platform | GitHub Actions / GitLab CI/CD |
| AI Providers | Claude, OpenAI Codex, OpenClaw |
| Data Format | Plain-text files (`.txt`) + JSON configs |

## Supported Platforms

| Platform | Status |
|----------|--------|
| Claude Code | Supported |
| OpenCode | Supported |
| OpenClaw | Supported |
| Cursor | Supported |
| Windsurf | Supported |
| Continue.dev | Supported |
| GitHub Copilot | Supported |
| Aider | Supported |

## Skills Overview

| Skill | Purpose |
|-------|---------|
| `/task` | Task lifecycle: pick, create, continue, schedule, status, edit |
| `/idea` | Idea lifecycle: create, approve, disapprove, refactor, scout, edit |
| `/release` | Release pipeline: create, generate, continue, close, security-only, test-only, edit |
| `/docs` | Documentation: generate, sync, reset, publish |
| `/setup` | Project initialization, configuration, scaffolding, branch strategy |
| `/update` | Update CodeClaw-managed files |
| `/tests` | Test discovery, gaps, coverage, execution |
| `/help` | Search over skills and documentation |
| `/crazy` | **[BETA]** Fully autonomous project builder |

## Feature Highlights (v4.0.5)

- **Release cleanup** — 4.0.4 documentation and changelog corrections are carried through the release line
- **Branch alignment** — `develop`, `staging`, and `main` share the same release history and tree
- **Docs simplification** — Public docs no longer advertise retired legacy flows
- **[BETA] /crazy skill** — Fully autonomous end-to-end project builder
- **Frontend design wizard** — Template search, theme selection, color palette picker
- **Security hardened** — release cleanup and validation checks continue to catch issues across the pipeline
- **Rebranded** — CTDF to CodeClaw with plugin id `claw`
- **Gated release pipeline** — 9 sequential stages with mandatory local build verification

## Key Design Principles

1. **Project-agnostic** — Works with any language, framework, or tech stack
2. **Zero dependencies** — All supported core scripts use Python 3 stdlib only
3. **Human-in-the-loop** — AI assists, but users decide at every gate
4. **Plain-text first** — Tasks and ideas in simple `.txt` files
5. **Cross-platform** — Linux, macOS, Windows with auto OS detection

## Version

Current plugin version: **4.0.5**

Repository: [github.com/dnviti/codeclaw](https://github.com/dnviti/codeclaw)

License: MIT
