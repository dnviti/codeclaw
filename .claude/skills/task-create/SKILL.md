---
name: task-create
description: Create a new task in the project backlog with auto-assigned ID, codebase-informed technical details, and proper formatting.
disable-model-invocation: true
argument-hint: "[task description]"
---

# Create a New Task

You are a task creation assistant for this project. Your job is to generate properly formatted task blocks and add them to the project backlog.

Always respond and work in English. The task block content (field labels, descriptions, technical details) MUST also be written in **English**.

## Mode Detection

Determine the operating mode first:

```bash
GH_ENABLED="$(jq -r '.enabled // false' .claude/github-issues.json 2>/dev/null)"
GH_SYNC="$(jq -r '.sync // false' .claude/github-issues.json 2>/dev/null)"
GH_REPO="$(jq -r '.repo' .claude/github-issues.json 2>/dev/null)"
```

- **GitHub-only mode** (`GH_ENABLED=true` AND `GH_SYNC != true`): Use GitHub Issues exclusively. No local file operations.
- **Dual sync mode** (`GH_ENABLED=true` AND `GH_SYNC=true`): Write local files first, then sync to GitHub.
- **Local only mode** (`GH_ENABLED=false` or config missing): Use local files only.

## Current Task State

### In GitHub-only mode:

#### Highest task IDs (last 20, sorted by number):
!`GH_REPO="$(jq -r '.repo' .claude/github-issues.json 2>/dev/null)"; gh issue list --repo "$GH_REPO" --label task --state all --limit 500 --json title --jq '.[].title' | grep -oE '[A-Z][A-Z0-9]+-[0-9]{3}' | sort -t'-' -k2 -n | tail -20`

#### All prefixes currently in use:
!`GH_REPO="$(jq -r '.repo' .claude/github-issues.json 2>/dev/null)"; gh issue list --repo "$GH_REPO" --label task --state all --limit 500 --json title --jq '.[].title' | grep -oE '[A-Z][A-Z0-9]+-[0-9]{3}' | sed 's/-[0-9]*//' | sort -u`

### In local only and dual sync modes:

#### Next available task ID and existing prefixes:
!`python3 scripts/task_manager.py next-id --type task`

#### Section headers in to-do.txt:
!`python3 scripts/task_manager.py sections --file to-do.txt`

### Section info (GitHub-only mode):

In GitHub-only mode, section information is derived from the label mappings in `.claude/github-issues.json` rather than from `to-do.txt`. Read the `labels.sections` mapping from the config to determine available sections and their labels.

## Arguments

The user wants to create a task for: **$ARGUMENTS**

## Instructions

### Step 1: Validate Input

If `$ARGUMENTS` is empty or unclear, ask the user to describe the task they want to create using `AskUserQuestion`:

> "Please describe the task you want to create. Include what the feature/fix should do and any known technical requirements."

Do NOT proceed without a clear task description.

### Step 2: Determine the Task Code Prefix

Analyze the task description and select an appropriate code prefix.

**Check the existing prefixes** from the data above. Each prefix represents a feature domain in this project.

**Rules:**
1. Reuse an existing prefix if the task clearly falls within that domain.
2. If no existing prefix fits, create a new one: 2-6 uppercase letters that clearly abbreviate the feature area.
3. Document the new prefix's domain when presenting the draft.

### Step 3: Compute the Next Task Number

Task numbering is **globally sequential** across all prefixes.

**In GitHub-only mode:**
1. From the GitHub-sourced "Highest task IDs" data above, extract all numeric parts (e.g., `ORCH-065` -> 65).
2. **Ignore false positives** like `AES-256` or `SHA-256` — these are not task codes but algorithm references. Only consider IDs where the prefix is a known task prefix or matches the pattern of a short alphabetical prefix.
3. Find the maximum number.
4. The new task number = `max + 1`, zero-padded to 3 digits.

**In local only and dual sync modes:**
Use the `next_number` field from the "Next available task ID" JSON above. The `prefixes` array shows all existing domain prefixes. No manual computation needed — the script handles global sequencing and false-positive filtering.

### Step 4: Explore the Codebase

Before writing the task block, explore the codebase to generate accurate technical details:

1. **Read relevant existing files** based on the task description — identify the key source directories and files in the project.
2. **Look at similar completed tasks** for pattern reference:
   - In local only / dual sync mode: check `done.txt` for a task with similar scope and mirror its structure.
   - In GitHub-only mode: search closed issues with `gh issue list --repo "$GH_REPO" --label task --state closed --limit 10 --json title,body` for reference.
3. **Identify files to create and modify** — be specific about file paths based on the actual directory structure. Use `Glob` to verify paths exist before listing them under `MODIFY`.

### Step 5: Draft the Task Block

**In GitHub-only mode:** Draft the task as a GitHub Issue in **English**.

GitHub Issue format:
- **Title:** `[PREFIX-NNN] Task Title`
- **Body:**

```markdown
**Code:** PREFIX-NNN | **Priority:** PRIORITY | **Section:** SECTION_NAME | **Dependencies:** DEPS

## Description
Multi-line description in English. Explain WHAT the task does, WHY it is
needed, and its scope. Technical but readable, roughly 4-10 lines.

## Technical Details
Detailed technical implementation plan in English. Structure by layer/file:
[TECH_DETAIL_LAYERS]
Use indented sub-sections with specific code snippets, type definitions,
function signatures, and endpoint paths where appropriate.

## Files Involved
**CREATE:** path/to/new/file.ts
**MODIFY:** path/to/existing/file.ts

---
*Generated by Claude Code via `/task-create`*
```

- **Labels:** `claude-code,task,PRIORITY_LABEL,status:todo,SECTION_LABEL`

**In local only and dual sync modes:** Draft the task block in **English** using the existing format.

Template:

```
------------------------------------------------------------------------------
[ ] PREFIX-NNN — Task title (concise)
------------------------------------------------------------------------------
  Priority: [HIGH/MEDIUM/LOW]
  Dependencies: [TASK-CODE, TASK-CODE or None]

  DESCRIPTION:
  Multi-line description. Explain WHAT the task does, WHY it is
  needed, and its scope. Technical but readable, approximately
  4-10 lines.

  TECHNICAL DETAILS:
  Detailed technical implementation plan. Structure by layer/file:
[TECH_DETAIL_LAYERS]
  Use indented sub-sections with specific code snippets, type
  definitions, function signatures, and endpoint paths where appropriate.

  Files involved:
    CREATE:  path/to/new/file.ts
    MODIFY:  path/to/existing/file.ts
```

**Formatting rules (local only and dual sync):**
- Header separator lines are exactly 78 dashes: `------------------------------------------------------------------------------`
- Status prefix is `[ ] ` (pending)
- Title line format: `[ ] PREFIX-NNN — Task Title` (use `—` em dash, not `-` hyphen)
- Indent all content with 2 spaces
- Dependencies: use task codes like `AUTH-001, DB-002` or `None` if none
- Section labels in order: `DESCRIPTION:`, `TECHNICAL DETAILS:`, `Files involved:`
- File action labels: `CREATE:` (new files) and `MODIFY:` (existing files), indented 4 spaces
- End with two blank lines after the last file entry

### Step 6: Present the Draft and Ask for Confirmation

Present the complete task block (or GitHub Issue draft) to the user, along with:

1. **Task code:** The generated PREFIX-NNN
2. **Suggested section:** Which section it should be placed in, with reasoning
3. **Suggested priority:** HIGH / MEDIUM / LOW, with reasoning

Then use `AskUserQuestion` with these options:
- **"Looks good, create it"** — proceed to Step 7
- **"Needs changes"** — let the user specify what to adjust (section, priority, description, etc.)
- **"Cancel"** — abort without creating

### Step 7: Check for Duplicates

Before writing, perform a final duplicate check:

**In GitHub-only mode:**
1. Search GitHub issues for key concepts:
   ```bash
   gh issue list --repo "$GH_REPO" --label task --state all --search "keyword1 keyword2" --json title,number,state --jq '.[] | "#\(.number) [\(.state)] \(.title)"'
   ```
2. If a potentially similar task is found, warn the user and ask whether to proceed or abort.
3. If no duplicates found, continue to Step 8.

**In local only and dual sync modes:**
1. Run: `python3 scripts/task_manager.py duplicates --keywords "keyword1,keyword2,keyword3"`
   Use 2-3 key terms from the task title and description as keywords.
2. If the JSON output contains matches that look like a similar task, warn the user and ask whether to proceed or abort.
3. If no duplicates found, continue to Step 8.

### Step 8: Insert the Task into to-do.txt

**In GitHub-only mode:** Skip this step entirely.

**In local only and dual sync modes:**

Determine the correct insertion point based on the confirmed section.

**Insertion rules:**
1. Use the section data from the "Section headers" JSON above to find the target section's line number.
2. Read that range of lines to find the last task block in the section.
3. Insert the new task block **after the last existing task** in the section (or after the section header + blank lines if the section is empty).
4. Maintain whitespace conventions: two blank lines between tasks, two blank lines before the next section header.

Use the `Edit` tool to insert the task block at the correct position.

### Step 8.5: Sync to GitHub Issues

**In GitHub-only mode:** This is the **primary write** step. Create the GitHub Issue:

1. Read the label mappings from config:
   ```bash
   GH_REPO="$(jq -r '.repo' .claude/github-issues.json)"
   PRIORITY_LABEL="$(jq -r ".labels.priority.\"$PRIORITY\"" .claude/github-issues.json)"
   SECTION_LABEL="$(jq -r ".labels.sections.\"$SECTION_LETTER\"" .claude/github-issues.json)"
   ```

2. Create the GitHub Issue:
   ```bash
   ISSUE_URL=$(gh issue create --repo "$GH_REPO" \
     --title "[PREFIX-NNN] Task Title" \
     --body "$(cat <<'EOF'
   **Code:** PREFIX-NNN | **Priority:** PRIORITY | **Section:** SECTION_NAME | **Dependencies:** DEPS

   ## Description
   [Description content in English]

   ## Technical Details
   [Technical details content in English]

   ## Files Involved
   **CREATE:** list of files
   **MODIFY:** list of files

   ---
   *Generated by Claude Code via `/task-create`*
   EOF
   )" \
     --label "claude-code,task,$PRIORITY_LABEL,status:todo,$SECTION_LABEL")
   ```

3. If the `gh` command fails, report the error to the user. In GitHub-only mode this is a hard failure since there is no local fallback.

**In dual sync mode:**

1. Read the label mappings from config:
   ```bash
   GH_REPO="$(jq -r '.repo' .claude/github-issues.json)"
   PRIORITY_LABEL="$(jq -r ".labels.priority.\"$PRIORITY\"" .claude/github-issues.json)"
   SECTION_LABEL="$(jq -r ".labels.sections.\"$SECTION_LETTER\"" .claude/github-issues.json)"
   ```

2. Create the GitHub Issue:
   ```bash
   ISSUE_URL=$(gh issue create --repo "$GH_REPO" \
     --title "[PREFIX-NNN] Task Title" \
     --body "$(cat <<'EOF'
   **Code:** PREFIX-NNN | **Priority:** PRIORITY | **Section:** SECTION_NAME | **Dependencies:** DEPS

   ## Description
   [DESCRIPTION content from the task block]

   ## Technical Details
   [TECHNICAL DETAILS content from the task block]

   ## Files Involved
   **CREATE:** list of files
   **MODIFY:** list of files

   ---
   *Generated by Claude Code via `/task-create`*
   EOF
   )" \
     --label "claude-code,task,$PRIORITY_LABEL,status:todo,$SECTION_LABEL")
   ```

3. Extract the issue number from the URL:
   ```bash
   ISSUE_NUM=$(echo "$ISSUE_URL" | grep -oE '[0-9]+$')
   ```

4. Write the issue reference back to the task block in `to-do.txt`. Add a `GitHub: #NNN` line after the `Dependencies:` line using the `Edit` tool.

5. If the `gh` command fails, warn the user that GitHub sync failed but do NOT fail the task creation — the task is already in `to-do.txt`.

**In local only mode:** Skip this step entirely.

### Step 9: Confirm and Report

After successfully creating the task, report:

**In GitHub-only mode:**

> "Task **PREFIX-NNN — Task Title** has been created as GitHub Issue.
>
> - **Code:** PREFIX-NNN
> - **Priority:** HIGH/MEDIUM/LOW
> - **Dependencies:** list or None
> - **Section:** SECTION_NAME
> - **Files to create:** N
> - **Files to modify:** N
> - **GitHub Issue:** #NNN (URL)"

**In dual sync mode:**

> "Task **PREFIX-NNN — Task Title** has been created in `to-do.txt`, SECTION X.
>
> - **Code:** PREFIX-NNN
> - **Priority:** HIGH/MEDIUM/LOW
> - **Dependencies:** list or None
> - **Section:** SECTION X — Section Name
> - **Files to create:** N
> - **Files to modify:** N
> - **GitHub Issue:** #NNN (URL) *(only if GitHub sync succeeded)*"

**In local only mode:**

> "Task **PREFIX-NNN — Task Title** has been created in `to-do.txt`, SECTION X.
>
> - **Code:** PREFIX-NNN
> - **Priority:** HIGH/MEDIUM/LOW
> - **Dependencies:** list or None
> - **Section:** SECTION X — Section Name
> - **Files to create:** N
> - **Files to modify:** N"

## Section Selection Guide

Sections are defined in `to-do.txt`. Read the section headers to understand the project's organizational structure. If the task does not clearly fit any existing section, suggest Section B (enhancements) and note this to the user. If needed, propose a new section.

## Important Rules

1. **In local only and dual sync modes, NEVER modify `progressing.txt` or `done.txt`** — only append to `to-do.txt`.
2. **NEVER create duplicate tasks** — always cross-reference existing tasks first (GitHub issues in GitHub-only mode, local files in local/dual mode).
3. **NEVER reuse a task number that already exists** — always use global max + 1.
4. **NEVER skip user confirmation** — always present the draft and wait for approval.
5. **English content in task blocks** — field labels (`Priority`, `Dependencies`, `DESCRIPTION`, `TECHNICAL DETAILS`, `Files involved`, `CREATE`, `MODIFY`) and descriptions are always in English.
6. **Accurate file paths** — only reference files that actually exist (for `MODIFY`) or directories that exist (for `CREATE`). Verify with `Glob` before listing.
7. **Follow the exact formatting** — in local/dual mode: same indentation, same dash count (78), same field order as existing tasks. In GitHub-only mode: use the GitHub Issue markdown format specified in Step 5.
8. **In GitHub-only mode, NEVER modify local task files** (`to-do.txt`, `progressing.txt`, `done.txt`) — all operations go through GitHub Issues exclusively.
