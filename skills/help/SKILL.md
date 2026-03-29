---
name: help
description: "Interactive skill framework guide. Shows all available skills and their usage, or explains a specific topic when given a query."
disable-model-invocation: true
argument-hint: "[query]"
---

> **Project configuration is authoritative.** Before executing, run `SH context` to load project configuration. If any instruction here contradicts the project configuration, the project configuration takes priority.

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
5. **Pick up a task:** `/task pick [CODE]` — Start implementing a task on a dedicated branch
6. **Continue work:** `/task continue [CODE]` — Resume an in-progress task
7. **Check status:** `/task status` — See all tasks, progress, and recommendations
8. **Run tests:** `/tests scout` — Find coverage gaps; `/tests create [target]` — Generate tests
9. **Release:** `/release create X.X.X` then `/release continue X.X.X` — Run the 9-stage release pipeline
10. **Generate docs:** `/docs generate` — Produce technical documentation

### Task Lifecycle

```
/idea create → /idea approve → /task pick → implement → /task pick (close) → /release
```

Ideas flow through approval into tasks. Tasks are picked up, implemented on dedicated branches, tested, and closed. The release pipeline collects completed tasks, merges through staging, and tags a production release.

### Modes

CodeClaw supports three operating modes for task tracking:
- **Local-only** — Tasks in text files (`to-do.txt`, `progressing.txt`, `done.txt`)
- **Platform-only** — Tasks as GitHub/GitLab issues (no local files)
- **Dual sync** — Local files synced with platform issues

Configure via `.claude/issues-tracker.json`.

### Tips

- Add `yolo` to any command to auto-approve all gates: `/task pick all yolo`
- Use `/task pick all` to implement all pending release tasks sequentially in dependency order
- Use `/release resume` to continue a release pipeline from where it left off
- Run `/setup env` to regenerate the platform instructions file after changing your project structure

---

## Query Flow

When invoked with a query (`/help how do I create a task`), provide a targeted explanation.

### Step 1: Parse the query

Extract the user's question from the dispatch `remaining_args`.

### Step 2: Keyword search

Search the available skills and docs using keyword matching. This keeps the flow deterministic and works without any external index.

1. Look for direct matches in:
   - Skill names: task, idea, release, setup, docs, update, tests, help, crazy
   - Flow names: pick, create, continue, status, scout, approve, generate, sync
   - Concepts: branch, milestone, yolo, docs, release, testing
2. Check the current docs pages for matching terms and exact command names.
3. Prefer the most specific skill or docs section over a generic match.

### Step 2b: Fallback expansion

If no direct keyword match is found, broaden the search to neighboring concepts and explain the closest relevant command.

Compare the query keywords against:
- Skill names: task, idea, release, setup, docs, update, tests, help
- Flow names: pick, create, continue, status, scout, approve, generate, sync
- Concepts: submodule, yolo, pipeline, staging, branch, milestone

### Step 3: Merge and explain

If multiple keyword matches are available, merge them by relevance and deduplicate by skill name.

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
