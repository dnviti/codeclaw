---
name: task
description: "Unified task management: pick up, create, continue, or check status of project tasks."
disable-model-invocation: true
argument-hint: "[pick [CODE | all [sequential]]] [create [description | all [sequential]]] [continue [CODE | all [sequential]]] [schedule CODE [CODE2...] to X.X.X] [status] [yolo]"
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

`SH context` → platform config, worktree state (including `submodules` list), branch config, release config as JSON. Use throughout.

`PM <operation> [key=value ...]` — operations: `list-issues`, `search-issues`, `view-issue`, `edit-issue`, `close-issue`, `comment-issue`, `create-issue`, `create-pr`, `list-pr`, `merge-pr`, `create-release`, `edit-release`.

Task files (`to-do.txt`, `progressing.txt`, `done.txt`) always live in `main_root`. Source code lives in the worktree directory.

### Submodule Awareness

When `SH context` returns `worktree.submodules` with one or more entries, the project uses git submodules. Before creating a worktree or exploring the codebase:

1. Run `SH list-submodules` to get available submodules
2. Present an `AskUserQuestion` with options: each submodule name + "Root repository (parent)"
3. If a submodule is selected, all codebase exploration and implementation operates within `<worktree_dir>/<submodule_path>` — never on the parent repo directly
4. After task completion (Step 6), if a submodule was selected: `git add <submodule_path> && git commit -m "chore: update submodule <name> pointer"` in the parent repo to align the submodule reference

Submodules are automatically initialized (`git submodule update --init --recursive`) when worktrees are created.

## Argument Dispatch

`SH dispatch --skill task --args "$ARGUMENTS"` → routes to: `pick`, `pick-all`, `create`, `create-all`, `continue`, `continue-all`, `schedule`, or `status` flow.

Also returns `yolo: true/false`. When `yolo` is `true`, **auto-select the recommended (first) option at every GATE** without waiting for user input. Log each auto-selected choice. Yolo never auto-selects destructive or cancel options.

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
3. **To-Test Tasks** — Task code, title, testing pending. Suggest `/release test-only TASK-CODE`.
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

**Release check (after task selection, before proceeding):**

Once the task is identified, verify it has a release/milestone assigned:
- **Platform-only:** Check for a `release:vX.Y.Z` label or milestone on the issue.
- **Local/dual:** Check for a `Release:` field in the task block.

If the task has **no release assigned**:
1. Run `RM release-plan-list` to get available releases.
2. **Yolo mode:** Auto-assign to the current active release (from `RM release-state-get`). If no active release, use the next upcoming release. Log the auto-selection and proceed.
3. **Normal mode:** Warn: "Task {CODE} has no release assigned. Every task must be tied to a release milestone." Present a GATE via `AskUserQuestion`: **"Assign to vX.Y.Z (recommended)"** | **"Assign to different release"** | **"Cancel"**. STOP until user responds.
4. Apply the assignment: `TM set-release`, `RM release-plan-add-task`, platform: add label + milestone.
5. If no releases exist at all, proceed without assignment (but warn).

#### Step 2: Mark task as in-progress

1. **Local/dual:** `TM move TASK-CODE --to progressing` — verify `"success": true`. If task appears in recommended order section of `to-do.txt`, update annotation to `[IN PROGRESS]`.
2. **Platform-only/dual sync:** Update labels (remove `status:todo`, add `status:in-progress`) and comment with branch name via `platform-cmd edit-issue` and `platform-cmd comment-issue`. Also auto-assign: `PM edit-issue number=ISSUE_NUM add-assignee="@me"`.
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

**6e. Ask to create PR (always offered):**

Always offer PR creation after task completion, regardless of whether testing passed or was skipped.

**Yolo mode:** Auto-create the PR without asking. Log the auto-selection.

**Normal mode:** Use `AskUserQuestion`: **"Yes, create PR into <DEVELOPMENT_BRANCH>"** | **"No, stay on task branch"**

**PR creation:** Push with `-u`, check existing PR via `platform-cmd list-pr` (skip if exists). Build PR: title, summary, issue ref (platform modes). Include `milestone` parameter from the task's release assignment. Create via `platform-cmd create-pr` with `assignee="@me"`. Report URL.

**When testing was skipped:** Still create the PR, but:
- Add a `needs-testing` label to the PR
- Prepend a note in the PR body: "**Warning:** Testing was skipped for this task. Manual testing is required before merge."
- Inform: "PR created with `needs-testing` label. Run `/release test-only [TASK-CODE]` to complete testing before merge."

---

## Pick All Flow

Pick up and implement **all pending tasks for the current active release**. By default, tasks are implemented **in parallel** using subagents (one agent per task). Use `/task pick all sequential` to implement tasks one at a time instead.

This flow is triggered by `/task pick all` or `/task pick all sequential`.

### Pick All — Release Detection

Detect the active release:

```bash
RM release-state-get
```

- If **no active release:** inform user: "No active release found. Run `/release X.X.X` first to create a release, then re-run `/task pick all`." **STOP.**
- Extract version from `release_state.version`.

### Pick All — Task Discovery

```bash
TM list-release-tasks --version X.X.X
```

Filter to only `todo` and `progressing` tasks. If none pending → "All tasks for release X.X.X are already complete. You can resume the release with `/release resume`." **STOP.**

### Pick All Instructions

#### Step 1: Build dependency graph

Parse `Dependencies:` fields from each pending task. Group independent tasks (no unmet dependencies) into parallel batches. Tasks whose dependencies are not yet done go into later batches.

#### Step 2: Present the plan

Present: "Found **N pending tasks** for release X.X.X. **M can run in parallel** in batch 1."

| Batch | Tasks | Notes |
|-------|-------|-------|
| 1 | CODE1, CODE2 | Independent |
| 2 | CODE3 | Depends on CODE1 |

**Default (parallel):** GATE: "Spawn agents to implement all tasks" / "Cancel"

**Sequential mode (`/task pick all sequential`):** GATE: "Implement tasks one by one" / "Cancel"

#### Step 3a: Parallel execution (default)

For each batch, spawn Agent subagents with `isolation: "worktree"` and `mode: "bypassPermissions"`:

```
prompt: "You are a task implementation agent. Implement task {CODE} for release {VERSION}.

1. Mark task as in-progress: `TM move {CODE} --to progressing`
2. Auto-assign (platform-only/dual): `PM edit-issue number=ISSUE_NUM add-assignee="@me"`
3. Create worktree: `SH setup-task-worktree --task-code {CODE} --base-branch {DEVELOPMENT_BRANCH}`
4. Read full task details: `TM parse {CODE}`
5. Explore the codebase: read all files listed in Files involved and related code
6. Implement the task according to DESCRIPTION and TECHNICAL DETAILS
7. Create/modify files as specified in Files involved
8. Run {VERIFY_COMMAND} — on failure, fix and retry (max 3 attempts)
9. Commit: `git add <changed files> && git commit -m 'feat: {description} ({CODE})'`
10. Push branch: `git push -u origin task/{CODE}`
11. Create PR: `PM create-pr title='feat: {description} ({CODE})' head='task/{CODE}' base='{DEVELOPMENT_BRANCH}' body='Implements {CODE} for release {VERSION}' milestone='{VERSION}' assignee='@me'`
    - If verify command failed or was skipped, append to body: '**Note:** Testing was skipped or incomplete. Needs manual testing.' and add label `needs-testing`.
12. Mark task as done: `TM move {CODE} --to done --completed-summary 'Implemented: {title}'`
13. Remove worktree: `TM remove-worktree --task-code {CODE}`

Report: {{ code, success, summary, files_changed[], pr_url, error_if_any }}"
```

Wait for **all agents in the current batch** to complete before proceeding to the next batch.

#### Step 3b: Sequential execution (`/task pick all sequential`)

For each task in dependency order, execute the standard **Pick Flow** (from Step 1 through Step 6) one at a time. Wait for user confirmation at each task's closing gate before moving to the next.

#### Step 4: Present batch results

| Code | Title | Result |
|------|-------|--------|
| CODE1 | Title | Success |
| CODE2 | Title | Failed (reason) |

Update completed tasks. Move to next batch if any remain (repeat from Step 3a/3b).

#### Step 5: Handle failures

On failures → GATE: "Retry failed tasks" / "Skip failed tasks" / "Cancel"

#### Step 6: Final summary

When all batches complete, present:

> **All N tasks for release X.X.X have been implemented.**
> Successful: M | Failed: K | Skipped: J
>
> You can now resume the release pipeline with `/release resume`.

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

**Platform-only** — Title: `[PREFIX-XXXX] Task Title`. Body: Code/Priority/Section/Dependencies/Release metadata line, then Description, Technical Details, Files Involved sections in markdown. Labels: `claude-code,task,PRIORITY_LABEL,status:todo,SECTION_LABEL`. If `show_generated_footer` is `true` (or absent) in `.claude/project-config.json`, append footer: `*Generated by Claude Code via /task create*`.

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

- **Platform-only:** Read label mappings, create issue via `platform-cmd create-issue` with `assignee="@me"`. On failure, hard fail.
- **Dual sync:** Create platform issue as above (with `assignee="@me"`), extract issue number, add `GitHub: #NNN` to task block via `Edit`. On platform failure, warn but keep local task.
- **Local only:** Skip.

#### Step 9.5: Release Assignment

1. `RM release-plan-list`
2. If **no releases exist at all**, skip this step entirely.
3. **Determine the default "next version":**
   1. List all releases from the release-plan-list output.
   2. Filter to only open/planned releases (exclude status "released").
   3. Sort by semver ascending.
   4. Skip any with status "in-progress" — the first remaining release with status "planned" is the **next version**.
   5. If no "planned" releases remain, fall back to the active "in-progress" release.
   6. **Platform-only:** Query milestones via GitHub API (`gh api repos/{owner}/{repo}/milestones --jq '.[] | select(.state=="open")'`), sort by semver ascending, and select the next open milestone as the default.
4. **Yolo mode:** Auto-assign to the next version without prompting. Log: "Auto-assigned to vX.Y.Z (next release)." Skip the GATE. Proceed to step 6.
5. **Normal mode:** `AskUserQuestion` with the next version as the recommended first option:
   - **"Yes, assign to vX.Y.Z (next release)"** *(default/recommended)*
   - **"Assign to different release"**
   - **"Create new release"**
   - Note: "Skip" is **NOT** offered when releases exist — every task must be tied to a release milestone.
6. If assigned: `TM set-release`, `RM release-plan-add-task`, platform: add label + milestone.

#### Step 10: Confirm and Report

Report: code, priority, dependencies, section, file counts. Platform modes: include issue URL.

### Section Selection Guide

Read section headers from `to-do.txt` (local/dual) or label mappings (platform-only). If no clear fit, suggest Section B (enhancements).

---

## Create All Flow

Create tasks from **all pending ideas** in `ideas.txt` in one batch. By default, tasks are created **in parallel** using subagents (one agent per idea). Use `/task create all sequential` to process ideas one at a time instead.

### Create All — Idea Discovery

```bash
TM list --status idea --format summary
TM sections --file ideas.txt
```

**Platform-only:** `platform-cmd list-issues labels="idea,status:pending" state="open"`

If no pending ideas → "No pending ideas found in ideas.txt. Use `/idea create` to add ideas first." **STOP.**

### Create All Instructions

#### Step 1: Present the plan

Present: "Found **N pending ideas** to convert into tasks."

| # | Idea Code | Title |
|---|-----------|-------|
| 1 | IDEA-XXX-0001 | Title |
| 2 | IDEA-YYY-0002 | Title |

GATE: "Create tasks from all ideas" / "Cancel"

#### Step 2a: Parallel execution (default)

For each idea, spawn Agent subagents with `isolation: "worktree"` and `mode: "bypassPermissions"`:

```
prompt: "You are a task creation agent. Convert idea {IDEA_CODE} into a fully specified task.

1. Read the idea details: `TM parse {IDEA_CODE}`
2. Explore the codebase to understand scope, existing patterns, and relevant files
3. Determine task code prefix and next number: `TM next-id --type task`
4. Draft a task block with: Priority, Dependencies, DESCRIPTION (4-10 lines), TECHNICAL DETAILS (structured by architecture), Files involved (CREATE/MODIFY)
5. Insert the task into to-do.txt: use the Edit tool at the correct section
6. Move the idea from ideas.txt to idea-disapproved.txt (approved): `TM move {IDEA_CODE} --to approved`
7. Report: {{ idea_code, task_code, title, priority, files_count }}"
```

#### Step 2b: Sequential execution (`/task create all sequential`)

For each idea in order, execute the standard **Create Flow** one at a time. Wait for user confirmation at each task's draft gate before moving to the next.

#### Step 3: Present results

| Idea Code | Task Code | Title | Result |
|-----------|-----------|-------|--------|
| IDEA-XXX-0001 | AUTH-0005 | Title | Created |
| IDEA-YYY-0002 | — | Title | Failed (reason) |

On failures → GATE: "Retry failed" / "Skip failed" / "Cancel"

#### Step 4: Final summary

> **Created N tasks from M ideas.**
> Successful: K | Failed: J | Skipped: L

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

**Auto-assign (platform-only/dual sync):** `PM edit-issue number=ISSUE_NUM add-assignee="@me"` to track collaboration.

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

## Continue All Flow

Resume work on **all in-progress tasks** simultaneously. By default, tasks are continued **in parallel** using subagents (one agent per task). Use `/task continue all sequential` to process tasks one at a time instead.

### Continue All — Task Discovery

```bash
TM list --status progressing --format summary
```

**Platform-only:** `platform-cmd list-issues labels="task,status:in-progress" state="open"`

If no in-progress tasks → "No in-progress tasks found. Use `/task pick` to pick up a task first." **STOP.**

### Continue All Instructions

#### Step 1: Present the plan

Present: "Found **N in-progress tasks** to continue."

| # | Code | Title | Priority |
|---|------|-------|----------|
| 1 | CODE1 | Title | HIGH |
| 2 | CODE2 | Title | MEDIUM |

GATE: "Spawn agents to continue all tasks" / "Cancel"

#### Step 2a: Parallel execution (default)

For each in-progress task, spawn Agent subagents with `isolation: "worktree"` and `mode: "bypassPermissions"`:

```
prompt: "You are a task continuation agent. Continue implementing task {CODE}.

1. Create or enter worktree: `SH setup-task-worktree --task-code {CODE} --base-branch {DEVELOPMENT_BRANCH}`
2. Read full task details: `TM parse {CODE}`
3. Assess current implementation state: check which files exist, what's done vs remaining
4. Explore related code for patterns and context
5. Implement remaining work according to DESCRIPTION and TECHNICAL DETAILS
6. Run {VERIFY_COMMAND} — on failure, fix and retry (max 3 attempts)
7. Commit: `git add <changed files> && git commit -m 'feat: {description} ({CODE})'`
8. Mark task as done: `TM move {CODE} --to done --completed-summary 'Completed: {title}'`
9. Remove worktree: `TM remove-worktree --task-code {CODE}`

Report: {{ code, success, summary, files_changed[], error_if_any }}"
```

#### Step 2b: Sequential execution (`/task continue all sequential`)

For each task in priority order, execute the standard **Continue Flow** one at a time. Wait for user direction before moving to the next.

#### Step 3: Present results

| Code | Title | Result |
|------|-------|--------|
| CODE1 | Title | Completed |
| CODE2 | Title | Failed (reason) |

On failures → GATE: "Retry failed tasks" / "Skip failed tasks" / "Cancel"

#### Step 4: Final summary

> **Continued N in-progress tasks.**
> Completed: M | Failed: K | Skipped: J

---

## Schedule Flow

Assign one or more tasks to a release milestone.

### Schedule Flow Instructions

#### Step 1: Parse arguments

From dispatch: `task_code` contains comma-separated codes, `remaining_args` contains version.

- If task codes missing → GATE: "Which task(s) to schedule? Enter codes separated by spaces."
- If version missing → list available releases with `RM release-plan-list` and ask. If no releases exist → suggest `/release create X.X.X` first. Stop.

#### Step 2: Validate release exists

```bash
RM release-plan-list
```

If version not found → GATE: "Release X.X.X does not exist. Create it with `/release create X.X.X`?" / "Cancel"

#### Step 3: Schedule tasks

```bash
TM schedule-tasks --codes "CODE1,CODE2" --version X.X.X
```

In platform modes, also add `release:vX.X.X` label and milestone via `PM edit-issue`.

#### Step 4: Report

Present results table:

| Code | Title | Result |
|------|-------|--------|
| CODE1 | Title | Scheduled to X.X.X |
| CODE2 | Title | Failed (reason) |

Suggest: "Start the release with `/release continue X.X.X`" or "Schedule more tasks with `/task schedule`."

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
10. **Always ask** — never auto-commit, auto-close, or auto-create PRs (except in yolo mode, where auto-selection of recommended options is permitted as defined in Argument Dispatch).
11. **Quality gate must pass** before closing any task.
12. **Status Flow is read-only** — do NOT modify any files.
