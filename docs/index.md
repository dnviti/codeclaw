---
title: CodeClaw Documentation
description: Complete technical documentation for the CodeClaw
generated-by: claw-docs
generated-at: 2026-03-18T18:00:00Z
source-files:
  - README.md
  - .claude-plugin/plugin.json
  - .claude-plugin/marketplace.json
---

# CodeClaw

A project-agnostic task and release management framework with 8 streamlined skills: `/task`, `/idea`, `/release`, `/docs`, `/setup`, `/update`, `/tests`, `/help`. Features a gated release pipeline with automatic subagent orchestration — all through plain-text files and slash commands.

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
| Runtime | Python 3 (stdlib only, zero dependencies) |
| Host | Claude Code CLI |
| Version Control | Git (worktrees, branches, tags) |
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
| `/task` | Task lifecycle: pick, create, continue, schedule, status |
| `/idea` | Idea lifecycle: create, approve, disapprove, refactor, scout |
| `/release` | Release pipeline: create, generate, continue, close |
| `/docs` | Documentation: generate, sync, reset, publish |
| `/setup` | Project initialization and configuration |
| `/update` | Update CodeClaw-managed files |
| `/tests` | Test discovery, gaps, coverage, execution |
| `/help` | Usage guide |

## Feature Highlights (v3.5.1)

- **Ollama local model integration** — Route tool calls and tasks to local LLMs with configurable offloading level (0–10) and full `/api/chat` tool-calling loop
- **Mandatory vector memory** — Always-on semantic indexing of project files; MCP server for agent retrieval
- **Platform release state sync** — `release-state.json` persisted as a GitHub/GitLab issue in platform-only mode, shared across all collaborators
- **NFKC Unicode normalization** — Exclude patterns are NFKC-normalized to prevent fullwidth-space/homoglyph bypass
- **PreToolUse hook** — Evaluate every tool call against the Ollama offloading policy before execution
- **Gated release pipeline** — 9 sequential stages with parallel sub-agent PR analysis, CI monitoring, and mandatory local build verification

## Key Design Principles

1. **Project-agnostic** — Works with any language, framework, or tech stack
2. **Zero dependencies** — All scripts use Python 3 stdlib only (vector memory and MCP are optional)
3. **Human-in-the-loop** — AI assists, but users decide at every gate
4. **Plain-text first** — Tasks and ideas in simple `.txt` files
5. **Cross-platform** — Linux, macOS, Windows with auto OS detection

## Version

Current plugin version: **3.5.2**

Repository: [github.com/dnviti/codeclaw](https://github.com/dnviti/codeclaw)

License: MIT
