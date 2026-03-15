---
name: task
description: "Unified task management: pick up, create, continue, or check status of project tasks."
disable-model-invocation: true
argument-hint: "[pick [CODE]] [create [description]] [continue [CODE]] [status]"
---

# Task Manager

You are a task manager for this project. Manage the full task lifecycle: picking up tasks, creating new ones, continuing in-progress work, and reporting status. Always respond and work in English.

## Shorthand

| Alias | Expands to |
|-------|------------|
| `TM`  | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py` |
| `SH`  | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/skill_helper.py` |
| `RM`  | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/release_manager.py` |
| `PM`  | `TM platform-cmd` |

## Skill Context

`SH context` → platform config, worktree state, branch config, release config as JSON. Use throughout.

`PM <operation> [key=value ...]` — operations: `list-issues`, `search-issues`, `view-issue`, `edit-issue`, `close-issue`, `comment-issue`, `create-issue`, `create-pr`, `list-pr`, `merge-pr`, `create-release`, `edit-release`.

Task files (`to-do.txt`, `progressing.txt`, `done.txt`) always live in `main_root`. Source code lives in the worktree directory.

## Argument Dispatch

`SH dispatch --skill task --args "$ARGUMENTS"` → routes to: `pick`, `create`, `continue`, or `status` flow.

---

## Status Flow

Read-only report. Do NOT modify any files.

### Status Data

`SH status-report`

Returns pre-computed: `summary` counts, `in_progress` tasks, `blocked` tasks, `next_recommended` tasks, `worktrees`, and `release_plan`.

**Platform-only supplement:** Also query `platform-cmd list-issues labels="task,status:to-test" state="open"` for to-test tasks.

**Dual-sync supplement:** Run `TM sync-from-platform --dry-run --format text 2>/dev/null || echo "(sync check not available)"`.

### Status Report Presentation

1. **Summary** — Table with counts by status (completed, in-progress, to-test, todo, blocked) and progress percentage.
2. **In-Progress Tasks** — Task code, title, priority, what remains, files involved.
3. **To-Test Tasks** — Task code, title, testing pending. Suggest `/release-start test-only TASK-CODE`.
4. **Next Recommended** — Top 2-3 from `next_recommended`: code, title, priority, dependency status, brief scope.
5. **Blocked Tasks** — If any, list with blocking reason.
6. **Sync Discrepancies** — Dual-sync only. Task code, issue number, local vs platform status, suggested action.
7. **Active Worktrees** — Table from `worktrees` data. Cross-reference with in-progress tasks. Skip if none.
8. **Release Plan Overview** — From `release_plan`. If null/missing, skip. Show next release and upcoming releases summary.

---

## Pick Flow

Pick up the next todo task for implementation.

### Pick Flow — Current Task State

**Platform-only:** List todos by priority (HIGH/MEDIUM/LOW) with `platform-cmd list-issues labels="task,status:todo,priority:<level>" state="open"` for each level. List completed: `platform-cmd list-issues labels="task,status:done" state="closed" limit="20"`.

**Local/Dual:**
```bash
TM list --status todo --format summary
TM list --status done --format summary
TM sections --file to-do.txt
```

### Pick Flow Instructions

#### Step 1: Determine which task to pick

- **Task code provided:** Search for it in todos. If found in done, inform user and suggest next available.
- **No argument:** Select next by priority (HIGH > MEDIUM > LOW), lowest-numbered within same priority. Verify dependencies are satisfied.

Based on mode:
- **Platform-only:** Search via `platform-cmd search-issues`. Check dependency status via labels.
- **Local/dual:** Verify task exists in `to-do.txt` with `[ ]` status. Check dependencies are in `done.txt` as `[x]`.

#### Step 2: Mark task as in-progress

1. **Local/dual:** `TM move TASK-CODE --to progressing` — verify `"success": true`. If task appears in recommended order section of `to-do.txt`, update annotation to `[IN PROGRESS]`.
2. **Platform-only/dual sync:** Update labels (remove `status:todo`, add `status:in-progress`) and comment with branch name via `platform-cmd edit-issue` and `platform-cmd comment-issue`.
3. **Local only:** Skip platform sync.

#### Step 2.5: Create task worktree

```bash
SH setup-task-worktree --task-code <CODE> --base-branch <DEVELOPMENT_BRANCH>
```

If `reused_existing`, inform user. Change working directory to `worktree_dir`. Inform: worktree path, branch, base branch, main repo root. All subsequent steps operate within the worktree.

#### Step 3: Read the full task details

- **Platform-only:** `platform-cmd view-issue`. Parse DESCRIPTION, TECHNICAL DETAILS, Files involved.
- **Local/dual:** `TM parse TASK-CODE`.

#### Step 4: Explore the codebase

For each file in "Files involved":
- If exists, read to understand current state
- If marked CREATE, check target directory and similar files for patterns
- Identify relevant interfaces, types, and patterns

#### Step 5: Present the implementation briefing

1. **Task Selected**: Code, title, priority
2. **Status Update**: Confirm marked as in-progress
3. **Scope Summary**: What needs to be done
4. **Technical Approach**: Implementation steps based on task details and codebase exploration
5. **Files to Create/Modify**: Every file with what needs to happen
6. **Dependencies**: Status of all dependencies
7. **Risks**: Any concerns found during exploration
8. **Quality Gate**: Remind that verify command must pass before closing

Ask: "Ready to start implementation, or would you like to adjust the approach?"

---

#### Step 6: Post-Implementation — Confirm, Close & Commit

After full implementation and quality gate passes:

**6a. Generate the Testing Guide (do NOT present yet):**

Derive from TECHNICAL DETAILS and Files involved. Format:

> ### Testing Guide for [TASK-CODE] — [Task Title]
> **Prerequisites:** [What needs to be running]
> **Steps to test:**
> 1. [Concrete action] — **Expected:** [Result]
> **Edge cases to check:** [2-3 items]

Must be actionable — use real URLs, UI elements, API endpoints from the implementation.

**6a.5. Route testing guide and persist:**

| Mode | Deliver | `status:to-test` label | Platform comment | Local append |
|------|---------|----------------------|-----------------|-------------|
| Platform-only | Comment + notify | Yes | Yes | No |
| Dual sync | Comment + notify | Yes | Yes | Yes |
| Local-only | Show on screen | No | No | Yes |

Platform label: `platform-cmd edit-issue`. Platform comment: `platform-cmd comment-issue`. Local append: `TM add-test-procedure TASK-CODE --body "[guide text]"`.

**6b. Ask for user confirmation:**

Present summary of work done. Use `AskUserQuestion` with options:
- **"Yes, task is done (tests passed)"** — proceed to 6b.5 then 6c (full flow including merge option)
- **"Not yet, needs more work"** — proceed to 6b.5 then stop; task stays in-progress
- **"Skip testing, conclude task"** — proceed to 6b.5 then 6c (mark done, branch NOT merged)

**6b.5. Remove to-test label:**

Always remove `status:to-test` label after user responds (platform modes only, via `platform-cmd edit-issue`).

**6c. Mark task as done:**

- **Platform-only:** Remove `status:in-progress`, add `status:done` via `platform-cmd edit-issue`. Close via `platform-cmd close-issue`. Message: tests passed = "Task completed and verified." / testing skipped = "Task completed. Manual testing skipped. Branch not merged."
- **Local/dual:** `TM move TASK-CODE --to done --completed-summary "Brief summary"`. Update recommended order annotation to `[COMPLETED]` if present. Dual: also sync labels + close on platform.

Inform: "Task [TASK-CODE] has been closed."

**6c.5. Remove the task worktree:**

`TM remove-worktree --task-code <CODE>`

Inform: "Worktree removed. Branch preserved for PR. Use `/task continue [TASK-CODE]` to re-enter."

**6d. Ask to commit:**

Use `AskUserQuestion`: **"Yes, commit"** | **"No, skip commit"**

**6e. Ask to create PR (TESTS PASSED ONLY):**

Only when user chose "Yes, task is done (tests passed)" in 6b.

Use `AskUserQuestion`: **"Yes, create PR into <DEVELOPMENT_BRANCH>"** | **"No, stay on task branch"**

**PR creation:** Push with `-u`, check existing PR via `platform-cmd list-pr` (skip if exists). Build PR: title, summary, issue ref (platform modes). Create via `platform-cmd create-pr`. Report URL.

**If testing was skipped:** Do NOT offer PR. Inform: "Branch NOT submitted as PR. Run `/release-start test-only [TASK-CODE]` to complete testing."

---

## Create Flow

Generate properly formatted task blocks and add to the backlog. Task content MUST be in English.

### Create Flow — Current Task State

**Platform-only — Next ID:** Use `platform-cmd list-issues labels="task" state="all" limit="500"` to get titles, pipe to `TM next-id --type task --source platform-titles`.

**Local/dual:**
```bash
TM next-id --type task
TM sections --file to-do.txt
```

**Platform-only section info:** Derived from `labels.sections` mapping in tracker config.

### Create Flow Instructions

#### Step 1: Validate Input

If description after `create` is empty/unclear, use `AskUserQuestion` to ask for a task description. STOP. Do NOT proceed until the user responds.

#### Step 2: Determine Task Code Prefix

Check `prefixes` from next-id data. Reuse existing prefix if task fits that domain. Otherwise create a new 3-5 letter prefix (meaningful: AUTH, FEAT, DOCS, PERF, SEC, API, DATA, CFG).

#### Step 3: Compute Next Task Number

Use `next_number` from next-id JSON. Numbering is globally sequential across all prefixes.

#### Step 4: Explore the Codebase

1. Read relevant existing files based on task description.
2. Look at similar completed tasks for pattern reference.
3. Identify files to create/modify — verify paths with `Glob`.

#### Step 5: Draft the Task Block

**Platform-only** — Title: `[PREFIX-XXXX] Task Title`. Body: Code/Priority/Section/Dependencies/Release metadata line, then Description, Technical Details, Files Involved sections in markdown. Labels: `claude-code,task,PRIORITY_LABEL,status:todo,SECTION_LABEL`. Footer: `*Generated by Claude Code via /task create*`.

**Local/dual** — Text block with 78-dash separators, `[ ]` status, em dash in title, 2-space indent. Fields: Priority, Dependencies, Release, DESCRIPTION (4-10 lines), TECHNICAL DETAILS (structured by architecture), Files involved (CREATE/MODIFY). End with two blank lines.

#### Step 6: Present Draft and Confirm

Show the complete draft with task code, suggested section (with reasoning), and suggested priority (with reasoning).

`AskUserQuestion`: **"Looks good, create it"** | **"Needs changes"** | **"Cancel"**

STOP.

#### Step 7: Check for Duplicates

- **Platform-only:** Search via `platform-cmd search-issues` with key terms. Warn if similar found.
- **Local/dual:** `TM duplicates --keywords "keyword1,keyword2,keyword3"`. Warn if similar found.

#### Step 8: Insert into to-do.txt

- **Platform-only:** Skip.
- **Local/dual:** Use section data to find insertion point. Insert after last existing task in target section. Maintain whitespace. Use `Edit` tool.

#### Step 8.5: Sync to Platform

- **Platform-only:** Read label mappings, create issue via `platform-cmd create-issue`. On failure, hard fail.
- **Dual sync:** Create platform issue as above, extract issue number, add `GitHub: #NNN` to task block via `Edit`. On platform failure, warn but keep local task.
- **Local only:** Skip.

#### Step 9.5: Release Assignment

1. `RM release-plan-list`
2. If no releases, skip.
3. If releases exist, suggest assignment based on description vs release themes.
4. `AskUserQuestion`: **"Yes, assign to vX.Y.Z"** | **"Assign to different release"** | **"Create new release"** | **"Skip"**
5. If assigned: `task_manager.py set-release`, `release_manager.py release-plan-add-task`, platform: add label + milestone.

#### Step 10: Confirm and Report

Report: code, priority, dependencies, section, file counts. Platform modes: include issue URL.

### Section Selection Guide

Read section headers from `to-do.txt` (local/dual) or label mappings (platform-only). If no clear fit, suggest Section B (enhancements).

---

## Continue Flow

Resume work on an in-progress task. Does NOT close or commit — use Pick Flow for that.

### Continue Flow — Current Task State

- **Platform-only:** `platform-cmd list-issues labels="task,status:in-progress" state="open"`
- **Local/Dual:** `TM list --status progressing --format summary`

### Continue Flow Instructions

#### Step 1: Select the Task

- **No in-progress tasks:** Inform user, suggest `/task pick`. Stop.
- **Task code provided:** Find that task. If not found, list available.
- **No argument, one task:** Use it automatically.
- **No argument, multiple tasks:** `AskUserQuestion` to choose. STOP.

Platform: search via `platform-cmd search-issues` with `status:in-progress`. Local/dual: read `progressing.txt` for `[~]` tasks.

#### Step 1.5: Enter or create the task worktree

```bash
SH setup-task-worktree --task-code <CODE> --base-branch <DEVELOPMENT_BRANCH>
```

If `reused_existing`: "Entering existing worktree." If `created`: "Created fresh worktree from existing branch." If fails: suggest `/task pick <TASK-CODE>`. All subsequent steps operate within the worktree.

#### Step 2: Read the Full Task Block

- **Platform-only:** `platform-cmd view-issue`. Parse Description, Technical Details, Files Involved.
- **Local/dual:** `TM parse TASK-CODE` and `verify-files TASK-CODE`.

#### Step 3: Assess Current Implementation State

**CREATE files:** Check existence via `Glob`. Classify: missing, stub, or implemented.
**MODIFY files:** Read and `Grep` for key changes. Note: applied vs still needed.
Cross-check each technical requirement against code artifacts.

#### Step 4: Explore Related Code

Read all related files: those to be modified, similar files for patterns, related types/interfaces/imports.

#### Step 5: Present the Continuation Briefing

1. **Task**: Code, title, priority
2. **Description**: Brief summary
3. **Implementation Progress**: Done (with evidence) vs remaining
4. **Next Steps**: Ordered concrete actions for remaining work
5. **Files to Create/Modify**: What still needs to happen in each
6. **Quality Gate Reminder**: Verify command must pass before closing via `/task pick`

Ask: "Ready to continue implementation, or would you like to adjust the approach?"

---

## Important Rules

1. **Local/dual modes: NEVER modify `done.txt` directly** — use the `move` command.
2. **NEVER create duplicate tasks** — always cross-reference first.
3. **NEVER reuse a task number** — always use global max + 1.
4. **NEVER skip user confirmation** — always present drafts/briefings and wait for approval.
5. **English content** in all task blocks and field labels.
6. **Accurate file paths** — verify with `Glob` before listing.
7. **Follow exact formatting** — local: 78-dash separators, same indentation/field order. Platform: markdown format.
8. **Platform-only: NEVER modify local task files** — all operations via platform issues.
9. **Create Flow (local/dual): NEVER modify `progressing.txt` or `done.txt`** — only append to `to-do.txt`.
10. **Always ask** — never auto-commit, auto-close, or auto-create PRs.
11. **Quality gate must pass** before closing any task.
12. **Status Flow is read-only** — do NOT modify any files.
