---
name: idea-create
description: Create a new idea in the idea backlog (ideas.txt or platform issues) for future evaluation. Ideas are lightweight proposals that must be approved before becoming tasks.
disable-model-invocation: true
argument-hint: "[idea description]"
# Idea IDs use IDEA-PREFIX-XXXX format (e.g., IDEA-AUTH-0001)
---

# Create a New Idea

You are an idea creation assistant for this project. Your job is to generate properly formatted idea blocks and add them to the idea backlog.

Ideas are **lightweight proposals** — they describe *what* and *why* at a high level, without implementation details. Technical details are only added when an idea is approved into a task via `/idea-approve`.

Always respond and work in English. The idea block content (field labels, descriptions) MUST also be written in **English**.

## Mode Detection

`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py platform-config`

Use the `mode` field to determine behavior: `platform-only`, `dual-sync`, or `local-only`. The JSON includes `platform`, `enabled`, `sync`, `repo`, `cli` (gh/glab), and `labels`.

## Platform Commands

Use `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py platform-cmd <operation> [key=value ...]` to generate the correct CLI command for the detected platform (GitHub/GitLab).

Supported operations: `list-issues`, `search-issues`, `view-issue`, `edit-issue`, `close-issue`, `comment-issue`, `create-issue`, `create-pr`, `list-pr`, `merge-pr`, `create-release`, `edit-release`.

Example: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py platform-cmd create-issue title="[CODE] Title" body="Description" labels="task,status:todo"`

## Current Idea State

### Platform-only mode — next idea ID:

In platform-only mode, pipe platform issue titles into:
```bash
gh issue list --repo "$TRACKER_REPO" --label idea --state all --limit 500 --json title --jq '.[].title' | python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py next-id --type idea --source platform-titles
```

### Local/Dual mode:

#### Next available idea ID:
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py next-id --type idea`

#### Current ideas:
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py list-ideas --file ideas --format summary`

## Arguments

The user wants to create an idea for: **$ARGUMENTS**

## Instructions

### Step 1: Validate Input

If `$ARGUMENTS` is empty or unclear, ask the user to describe the idea they want to add using `AskUserQuestion`:

> "Please describe the idea you want to add. Include what the feature/improvement should do and why it would be valuable."

Do NOT proceed without a clear idea description.

### Step 2: Determine the Category

Analyze the idea description and select an appropriate category.

**Suggested categories:**

Read CLAUDE.md's `## Architecture` section to understand the project's domain and derive appropriate categories. Combine universal categories with project-specific ones.

Universal categories: Core Features, Security, Performance, Infrastructure.
Add 2-3 project-domain categories based on the project's architecture and purpose (e.g., for an e-commerce app: Product Catalog, Checkout, User Accounts).

If no existing category fits well, create a concise new one.

### Step 2.5: Determine the Idea Code Prefix

Analyze the idea description and category to select an appropriate code prefix.

**Check the existing prefixes** from the next-id JSON output (`prefixes` array). Each prefix represents a feature domain in this project.

**Rules:**
1. Reuse an existing prefix if the idea clearly falls within that domain.
2. If no existing prefix fits, create a new one: 3-5 uppercase letters forming a meaningful English word or common acronym that categorizes the idea's domain (e.g., AUTH, FEAT, DOCS, PERF, SEC, API, DATA, CFG).

The idea code will be `IDEA-PREFIX-XXXX` (e.g., `IDEA-AUTH-0001`). When this idea is later approved via `/idea-approve`, the `IDEA-` prefix is simply dropped, so `IDEA-AUTH-0001` becomes task `AUTH-0001`.

### Step 3: Compute the Next Idea Number

Idea and task numbering share a **single global sequence** — an idea's number IS its future task number.

**In Platform-only mode:**
1. Pipe platform issue titles into the next-id command (see "Current Idea State" above).
2. Use the `next_number` from the JSON output.
3. If no ideas or tasks exist yet, start at `IDEA-PREFIX-0001`.

**In local/dual mode:**
Use the `next_number` field from the "Next available idea ID" JSON above. The script scans both task and idea files to compute the global max, ensuring no number collisions.

### Step 4: Draft the Idea

**In Platform-only mode**, draft the idea as a platform issue:

**Title:** `[IDEA-PREFIX-XXXX] Idea Title (concise)`

**Body:**
```
**Category:** CATEGORY | **Date:** YYYY-MM-DD

## Description
Description of the idea in English. Explain WHAT the idea proposes and the
general context. Keep it high-level, without implementation details.
Approximately 2-6 lines.

## Motivation
Why this idea could be useful. What problem it solves or what value it
adds to the project. Approximately 2-4 lines.

---
*Generated by Claude Code via `/idea-create`*
```

**In local/dual mode**, draft the idea block in English:

```
------------------------------------------------------------------------------
IDEA-PREFIX-XXXX — Idea title (concise)
------------------------------------------------------------------------------
  Category: [from Step 2]
  Date: YYYY-MM-DD

  DESCRIPTION:
  Description of the idea. Explain WHAT it proposes and the
  general context. Keep it high-level, without implementation details.
  Approximately 2-6 lines.

  MOTIVATION:
  Why this idea could be useful. What problem it solves or
  what value it adds to the project. Approximately 2-4 lines.
```

**Formatting rules for local/dual mode:**
- Header separator lines are exactly 78 dashes: `------------------------------------------------------------------------------`
- Title line format: `IDEA-PREFIX-XXXX — Title` (use `—` em dash, not `-` hyphen)
- Indent all content with 2 spaces
- Date format: `YYYY-MM-DD` (today's date)
- Section labels in order: `DESCRIPTION:`, `MOTIVATION:`
- End with two blank lines after the last line

### Step 5: Present the Draft and Ask for Confirmation

Present the complete idea to the user, along with:

1. **Idea code:** The generated IDEA-PREFIX-XXXX
2. **Category:** The selected category

Then use `AskUserQuestion` with these options:
- **"Looks good, create it"** — proceed to Step 6
- **"Needs changes"** — let the user specify what to adjust
- **"Cancel"** — abort without creating

### Step 6: Check for Duplicates

Before writing, perform a duplicate check:

**In Platform-only mode:**
```bash
gh issue list --repo "$TRACKER_REPO" --search "keyword1" --label idea --json number,title --jq '.[] | "#\(.number) \(.title)"'
# GitLab: glab issue list -R "$TRACKER_REPO" --search "keyword1" -l idea --output json | jq '.[] | "#\(.iid) \(.title)"'
gh issue list --repo "$TRACKER_REPO" --search "keyword2" --label task --json number,title --jq '.[] | "#\(.number) \(.title)"'
# GitLab: glab issue list -R "$TRACKER_REPO" --search "keyword2" -l task --output json | jq '.[] | "#\(.iid) \(.title)"'
```

**In local/dual mode:**
1. Run: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py duplicates --keywords "keyword1,keyword2,keyword3"`
   Use 2-3 key terms from the idea title and description as keywords.
2. If the JSON output contains matches that look like a similar idea or task, warn the user and ask whether to proceed or abort.
3. If no duplicates found, continue to Step 7.

### Step 7: Create the Idea

**In Platform-only mode:**

Create the platform issue directly:
```bash
ISSUE_URL=$(gh issue create --repo "$TRACKER_REPO" \
  --title "[IDEA-PREFIX-XXXX] Idea Title" \
  --body "$IDEA_BODY" \
  --label "claude-code,idea")
# GitLab: glab issue create -R "$TRACKER_REPO" --title "[IDEA-PREFIX-XXXX] Idea Title" --description "$IDEA_BODY" -l "claude-code,idea"
```

**In dual sync mode:**

1. Append the idea block to `ideas.txt` using the `Edit` tool.
2. Then create the platform issue (same as above).
3. Extract the issue number: `ISSUE_NUM=$(echo "$ISSUE_URL" | grep -oE '[0-9]+$')`
4. Write `GitHub: #NNN` back to the idea block in `ideas.txt` after the `Date:` line using the `Edit` tool.
5. If the platform command fails, warn the user that platform sync failed but do NOT fail the idea creation — the idea is already in `ideas.txt`.

**In local only mode:**

Append the idea block to `ideas.txt` using the `Edit` tool.

### Step 8: Confirm and Report

After successfully creating the idea, report:

> "Idea **IDEA-PREFIX-XXXX — Idea Title** has been created.
>
> - **Code:** IDEA-PREFIX-XXXX
> - **Category:** Category
> - **Date:** YYYY-MM-DD
> - **GitHub Issue:** #NNN (URL) *(only if GitHub issue was created)*
>
> Use `/idea-approve IDEA-PREFIX-XXXX` to promote this idea to a task, or `/idea-disapprove IDEA-PREFIX-XXXX` to reject it."

## Important Rules

1. **NEVER modify task files** (`to-do.txt`, `progressing.txt`, `done.txt`) — only create ideas.
2. **NEVER create duplicate ideas** — always cross-reference all idea and task sources first.
3. **NEVER reuse an idea number** — always use global max + 1.
4. **NEVER skip user confirmation** — always present the draft and wait for approval.
5. **English content** — all labels, descriptions, and content in English across all modes.
6. **Keep ideas high-level** — no implementation details, no file lists, no technical specifications. Those are added during `/idea-approve`.
7. **Follow the exact formatting** — same indentation, same dash count (78), same field order for local mode.
8. **In Platform-only mode, NEVER modify local idea files** — all operations go through platform issues exclusively.
