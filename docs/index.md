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

A project-agnostic task and idea management plugin for Claude Code with 8 streamlined skills: `/task`, `/idea`, `/release`, `/docs`, `/setup`, `/update`, `/tests`, `/help`. Features a gated release pipeline with automatic subagent orchestration — all through plain-text files and slash commands.

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
| [MCP Vector Memory](mcp-vector-memory.md) | Semantic search, MCP server, embedding providers, multi-agent coordination |
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
| MCP Server | Vector memory semantic search (stdio transport) |
| Data Format | Plain-text files (`.txt`) + JSON configs |
| Vector Memory | LanceDB + sentence-transformers (optional) |

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
| `/setup` | Project initialization, configuration, scaffolding, branch strategy, agentic fleet |
| `/update` | Update CodeClaw-managed files |
| `/tests` | Test discovery, gaps, coverage, execution |
| `/help` | Semantic search over skills and documentation |
| `/crazy` | **[BETA]** Fully autonomous project builder |

## Feature Highlights (v4.0.0)

- **Unified memory orchestrator** — Tandem multi-backend coordination (LanceDB + SQLite FTS5 + RLM)
- **Semantic intelligence** — `/task`, `/idea`, `/docs`, `/tests`, `/help` skills powered by vector search
- **[BETA] /crazy skill** — Fully autonomous end-to-end project builder
- **Image generation** — On-demand with 4 provider backends (DALL-E, Replicate, Stability AI, local)
- **Frontend design wizard** — Template search, theme selection, color palette picker
- **Security hardened** — 209 findings analyzed, 133 fixes applied across 20 PRs by parallel sub-agents
- **Rebranded** — CTDF to CodeClaw with plugin id `claw`
- **Gated release pipeline** — 9 sequential stages with parallel sub-agent PR analysis, CI monitoring, and mandatory local build verification

## Key Design Principles

1. **Project-agnostic** — Works with any language, framework, or tech stack
2. **Zero dependencies** — All scripts use Python 3 stdlib only (vector memory and MCP are optional)
3. **Human-in-the-loop** — AI assists, but users decide at every gate
4. **Plain-text first** — Tasks and ideas in simple `.txt` files
5. **Cross-platform** — Linux, macOS, Windows with auto OS detection

## Version

Current plugin version: **4.0.0**

Repository: [github.com/dnviti/codeclaw](https://github.com/dnviti/codeclaw)

License: MIT
