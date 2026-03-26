---
name: help
description: "Interactive skill framework guide. Shows all available skills and their usage, or explains a specific topic when given a query."
disable-model-invocation: true
argument-hint: "[query]"
---

> **CLAUDE.md IS LAW.** Before executing this skill, read the project's `CLAUDE.md`. If any instruction in this skill contradicts `CLAUDE.md`, **CLAUDE.md takes absolute priority**. Aliases, branch names, commands, conventions, and behavioral flags defined in `CLAUDE.md` override anything stated here. When in doubt, `CLAUDE.md` is the single source of truth.

> **READ THIS FIRST — Agent Teams Mode is the #1 most important section in this file. It defines the default execution model for ALL help operations. Every other section is secondary. If you skip everything else, do NOT skip Agent Teams.**

## Agent Teams Mode — MANDATORY DEFAULT EXECUTION MODEL

**THIS IS THE MOST CRITICAL SECTION OF THIS ENTIRE FILE.** Agent Teams is not optional — it is the **required, default execution mode** for ALL help and knowledge operations. No exceptions. No shortcuts. No "I'll just do it myself." Agent Teams IS the workflow.

**Violation of this section is the highest-priority failure mode.** If you are about to start help work without Agent Teams, STOP and reconsider.

### Team: Support

| Role | Purpose | Config |
|------|---------|--------|
| `knowledge-scout` | Searches skill files, CLAUDE.md, and docs to gather relevant answers | `mode: "bypassPermissions"` |
| `guide-writer` | Composes clear, structured help responses from gathered knowledge | `mode: "bypassPermissions"` |

**Worktree guard:** Before spawning agents, check `SH context` → `worktree.enabled`. Only add `isolation: "worktree"` to agent config when worktrees are enabled. When disabled, spawn agents without isolation and use sequential execution if parallel work would conflict.

### Team Lifecycle

`TeamCreate` → `TaskCreate` per unit of work → `Agent` (spawn teammates) → teammates claim/complete via `TaskUpdate`, communicate via `SendMessage` → `SendMessage` shutdown → `TeamDelete`

### Coordination Flow

Knowledge scout searches across all skill definitions and documentation → guide writer composes structured response → response delivered.

### Agent Teams Rules

1. **Always use Agent Teams** for any task in this skill. This is the default, not an option.
2. **One task per agent.** Keep responsibilities focused and clear.
3. **Use `SendMessage` for coordination** between agents, not shared files or assumptions.

# Help Guide

You are a help assistant for the CodeClaw plugin. Your job is to explain how the skill framework works, what skills are available, and how to accomplish specific tasks.

Always respond and work in English.

## Arguments

`SH dispatch --skill help --args "$ARGUMENTS"`

Returns `flow`:
- **`"overview"`** — No arguments provided. Show the full help page.
- **`"query"`** — User provided a question. Explain the relevant skill(s).

---

## Overview Flow

When invoked with no arguments (`/help`), present a complete guide to the framework.

### Step 1: Gather skill metadata

Read the YAML frontmatter (between `---` markers) from each `skills/*/SKILL.md` file to extract `name`, `description`, and `argument-hint`. Also read `.claude-plugin/plugin.json` for the framework version.

### Step 2: Present the help page

Render the following sections:

---

**CodeClaw**

> Version: (from plugin.json) | Skills: (count)

### Available Skills

| Skill | Description | Usage |
|-------|-------------|-------|
| `/task` | (description from frontmatter) | `/task [argument-hint]` |
| `/idea` | ... | ... |
| ... | ... | ... |

### Quick Start

1. **Set up your project:** `/setup` — Initialize task files, branch strategy, and platform integration
2. **Brainstorm ideas:** `/idea create [description]` — Capture ideas for later evaluation
3. **Approve ideas into tasks:** `/idea approve [IDEA-CODE]` — Promote an idea to a task with full technical details
4. **Create tasks directly:** `/task create [description]` — Create a fully specified task
5. **Pick up a task:** `/task pick [CODE]` — Start implementing a task in an isolated worktree
6. **Continue work:** `/task continue [CODE]` — Resume an in-progress task
7. **Check status:** `/task status` — See all tasks, progress, and recommendations
8. **Run tests:** `/tests scout` — Find coverage gaps; `/tests create [target]` — Generate tests
9. **Release:** `/release create X.X.X` then `/release continue X.X.X` — Run the 9-stage release pipeline
10. **Generate docs:** `/docs generate` — Produce technical documentation

### Task Lifecycle

```
/idea create → /idea approve → /task pick → implement → /task pick (close) → /release
```

Ideas flow through approval into tasks. Tasks are picked up, implemented in isolated worktrees, tested, and closed. The release pipeline collects completed tasks, merges through staging, and tags a production release.

### Modes

CodeClaw supports three operating modes for task tracking:
- **Local-only** — Tasks in text files (`to-do.txt`, `progressing.txt`, `done.txt`)
- **Platform-only** — Tasks as GitHub/GitLab issues (no local files)
- **Dual sync** — Local files synced with platform issues

Configure via `.claude/issues-tracker.json`.

### Tips

- Add `yolo` to any command to auto-approve all gates: `/task pick all yolo`
- Use `/task pick all` to implement all pending release tasks in parallel via subagents
- Use `/release resume` to continue a release pipeline from where it left off
- Run `/setup env` to regenerate CLAUDE.md after changing your project structure

---

## Query Flow

When invoked with a query (`/help how do I create a task`), provide a targeted explanation.

### Step 1: Parse the query

Extract the user's question from the dispatch `remaining_args`.

### Step 2: Semantic search (primary)

Attempt to find relevant skills and documentation using vector-based semantic search. This enables matching by meaning rather than exact keywords — e.g., "how do I check what needs to be done" would semantically match `/task status` even though "check" and "done" are not in a keyword list.

1. Call the `semantic_search` MCP tool with:
   - `query`: the user's question
   - `file_globs`: `["skills/*/SKILL.md", "docs/**/*.md", "CLAUDE.md"]`
   - `top_k`: 5
2. If the vector store is unavailable (error response or empty results), fall through to Step 2b (keyword fallback).
3. If results are returned, extract the matched skill names and relevant documentation sections. Rank semantic matches by score (lower `_distance` = better match).

**Staleness check:** After receiving semantic search results, check the index freshness. Run:
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/vector_memory.py status --root <project_root> --json
```
Parse the JSON output and check `last_indexed`. If the index is older than 30 minutes from the current time, append this note to your response:

> **Note:** The semantic index was last updated at `{last_indexed}`. Results may not reflect very recent changes. Run `/setup env` or `python3 scripts/vector_memory.py index` to refresh.

### Step 2b: Keyword fallback

If semantic search is unavailable or returned no results, fall back to keyword matching.

Compare the query keywords against:
- Skill names: task, idea, release, setup, docs, update, tests, help
- Flow names: pick, create, continue, status, scout, approve, generate, sync
- Concepts: worktree, submodule, yolo, pipeline, staging, branch, milestone

### Step 3: Merge and explain

If both semantic and keyword results are available, merge them with semantic matches ranked higher (they capture intent better). Deduplicate by skill name.

Provide a concise, actionable answer that includes:
1. **Which skill to use** — name and brief description
2. **Exact command syntax** — the specific `/skill subcommand [args]` to run
3. **What it does** — brief explanation of the flow that will execute
4. **Example** — one concrete usage example

If the query matches multiple skills, explain how they relate (e.g., ideas become tasks, tasks feed into releases).

If the query doesn't match any skill, suggest the closest match and offer to show the full overview with `/help`.

---

## Important Rules

1. **Read-only** — This skill never modifies any files.
2. **Dynamic** — Always read current skill frontmatter; never hardcode skill lists.
3. **Concise** — Keep explanations focused and actionable.
4. **Accurate** — Use exact command syntax from skill argument-hints.
