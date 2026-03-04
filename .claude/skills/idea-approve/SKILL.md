---
name: idea-approve
description: Approve an idea from ideas.txt, convert it into a full task with technical details, and add it to to-do.txt. This is the ONLY bridge from ideas to the task pipeline.
disable-model-invocation: true
allowed-tools: Bash, Read, Grep, Glob, Edit, Write
argument-hint: "[IDEA-NNN]"
---

# Approve an Idea

You are the idea approval gateway for this project. Your job is to take an idea from `ideas.txt`, flesh it out with codebase-informed technical details, and promote it to a full task in `to-do.txt`.

This skill is the **ONLY** bridge between the idea backlog and the task pipeline. Ideas must go through this process to become actionable tasks.

Always respond and work in English. The task block content (field labels, descriptions, technical details) MUST also be written in **English**.

## Current State

### Ideas available for approval:
!`grep -E '^IDEA-[0-9]{3}' ideas.txt 2>/dev/null | tr -d '\r'`

### Highest task IDs (last 20, sorted by number):
!`grep -rohE '[A-Z][A-Z0-9]+-[0-9]{3}' to-do.txt progressing.txt done.txt 2>/dev/null | sort -t'-' -k2 -n | tail -20`

### All task prefixes currently in use:
!`grep -rohE '[A-Z][A-Z0-9]+-[0-9]{3}' to-do.txt progressing.txt done.txt 2>/dev/null | sed 's/-[0-9]*//' | sort -u`

### Section headers in to-do.txt:
!`grep -n 'SECTION [A-Z]' to-do.txt | tr -d '\r'`

## Arguments

The user wants to approve: **$ARGUMENTS**

## Instructions

### Step 1: Select the Idea

- **If an IDEA-NNN code was provided**: Find that idea in `ideas.txt`. If not found, inform the user and list available ideas.
- **If no argument was provided**: List all ideas from `ideas.txt` with their codes, titles, and categories. Use `AskUserQuestion` to ask the user which idea to approve.

If `ideas.txt` has no ideas, inform the user: "No ideas available for approval. Use `/idea-create` to add ideas first."

### Step 2: Read the Full Idea

Read the complete idea block from `ideas.txt` — everything between its `------` separator lines. Extract:
- Title
- Category
- DESCRIPTION
- MOTIVATION

Present the idea to the user as context for what will be converted.

### Step 3: Determine the Task Code Prefix

Analyze the idea's description and category to select an appropriate task prefix.

**Check the existing prefixes** from the data above. Each prefix represents a feature domain.

**Rules:**
1. Reuse an existing prefix if the idea clearly falls within that domain.
2. If no existing prefix fits, create a new one: 2-6 uppercase letters that clearly abbreviate the feature area.

### Step 4: Compute the Next Task Number

Task numbering is **globally sequential** across all prefixes and all three task files.

1. From the "Highest task IDs" data above, extract all numeric parts.
2. **Ignore false positives** like `AES-256` or `SHA-256`.
3. Find the maximum number.
4. The new task number = `max + 1`, zero-padded to 3 digits.

### Step 5: Explore the Codebase

Before writing the task block, explore the codebase to generate accurate technical details:

1. **Read relevant existing files** based on the idea description — identify the key source directories and files in the project.
2. **Look at similar completed tasks** in `done.txt` for pattern reference.
3. **Identify files to create and modify** — be specific about file paths. Use `Glob` to verify paths exist before listing them under `MODIFY`.

### Step 6: Draft the Full Task Block

Convert the idea into a complete task block, expanding the high-level idea with concrete technical details from your codebase exploration.

**Template:**

```
------------------------------------------------------------------------------
[ ] PREFIX-NNN — Task title (concise)
------------------------------------------------------------------------------
  Priority: [HIGH/MEDIUM/LOW]
  Dependencies: [TASK-CODE, TASK-CODE or None]

  DESCRIPTION:
  Expanded description based on the original idea's DESCRIPTION
  and MOTIVATION. More detailed than the idea, explaining WHAT, WHY,
  and the scope. Approximately 4-10 lines.

  TECHNICAL DETAILS:
  Detailed technical implementation plan, structured by layer/file.
  This section is NEW — the original idea did not have this.
  Include specific code snippets, function signatures, endpoint paths.

  Files involved:
    CREATE:  path/to/new/file.ts
    MODIFY:  path/to/existing/file.ts
```

**Formatting rules:**
- Header separator lines are exactly 78 dashes
- Status prefix is `[ ] ` (pending)
- Title line format: `[ ] PREFIX-NNN — Task Title` (use `—` em dash)
- Indent all content with 2 spaces
- Dependencies: use task codes or `None`
- Section labels: `DESCRIPTION:`, `TECHNICAL DETAILS:`, `Files involved:`
- File action labels: `CREATE:` and `MODIFY:`, indented 4 spaces
- End with two blank lines

### Step 7: Present the Draft and Ask for Confirmation

Present the complete task block to the user, along with:

1. **Original idea:** IDEA-NNN and its title
2. **New task code:** PREFIX-NNN
3. **Suggested section:** Which section and why
4. **Suggested priority:** HIGH / MEDIUM / LOW and why

Then use `AskUserQuestion` with these options:
- **"Looks good, approve it"** — proceed to Step 8
- **"Needs changes"** — let the user specify adjustments
- **"Cancel"** — abort without approving

### Step 8: Check for Duplicates

Search all task files for key concepts:
```
grep -i "keyword1" to-do.txt progressing.txt done.txt
grep -i "keyword2" to-do.txt progressing.txt done.txt
```

If a similar task exists, warn the user and ask whether to proceed or abort.

### Step 9: Insert the Task and Remove the Idea

This step performs TWO operations:

**9a. Add the task to `to-do.txt`:**
1. Use `grep -n` to find the target section header and the next section header.
2. Find the last task block in the section.
3. Insert the new task block after the last existing task.
4. Maintain whitespace conventions: two blank lines between tasks.

**9b. Remove the idea from `ideas.txt`:**
1. Find the idea block in `ideas.txt` (everything between its `------` separators, inclusive).
2. Remove the entire block from `ideas.txt`.
3. Clean up any extra blank lines left behind.

Use the `Edit` tool for both operations.

### Step 10: Confirm and Report

After successfully completing both operations, report:

> "Idea **IDEA-NNN** has been approved and promoted to task **PREFIX-NNN — Task Title**.
>
> - **Task code:** PREFIX-NNN
> - **Priority:** HIGH/MEDIUM/LOW
> - **Dependencies:** list or None
> - **Section:** SECTION X — Section Name
> - **Files to create:** N
> - **Files to modify:** N
>
> The idea has been removed from `ideas.txt`. The task is now in `to-do.txt` and can be picked up with `/task-pick PREFIX-NNN`."

## Section Selection Guide

Sections are defined in `to-do.txt`. Read the section headers to understand the project's organizational structure. If the task does not clearly fit any existing section, suggest a default section and note this to the user.

## Important Rules

1. **This is the ONLY way ideas become tasks** — ideas must never be added to `to-do.txt` by any other means.
2. **NEVER modify `progressing.txt` or `done.txt`** — only add to `to-do.txt` and remove from `ideas.txt`.
3. **NEVER reuse a task number** — always use global max + 1.
4. **NEVER skip user confirmation** — always present the draft and wait for approval.
5. **English content in task blocks** — same conventions as existing tasks.
6. **Accurate file paths** — verify with `Glob` before listing.
7. **Follow the exact task formatting** — same indentation, dash count (78), field order as existing tasks.
8. **Always remove the approved idea from `ideas.txt`** — an approved idea must not remain in the idea backlog.
