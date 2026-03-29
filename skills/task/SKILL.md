---
name: task
description: "Unified task management: pick up, create, continue, or check status of project tasks."
disable-model-invocation: true
argument-hint: "[pick [CODE | all [sequential]]] [create [description | all [sequential]]] [continue [CODE | all [sequential]]] [edit CODE] [schedule CODE [CODE2...] to X.X.X] [status] [yolo]"
---

> **Project configuration is authoritative.** Before executing, run `SH context` to load project configuration. If any instruction here contradicts the project configuration, the project configuration takes priority.

# Task Manager

You are a task manager for this project. Manage the full task lifecycle: picking up tasks, creating new ones, continuing in-progress work, and reporting status. Always respond and work in English.

## Skill Context

`SH context` → platform config, branch config, release config as JSON. Use throughout.

`PM <operation> [key=value ...]` — operations: `list-issues`, `search-issues`, `view-issue`, `edit-issue`, `close-issue`, `comment-issue`, `create-issue`, `create-pr`, `list-pr`, `merge-pr`, `create-release`, `edit-release`.

Task files (`to-do.txt`, `progressing.txt`, `done.txt`) always live in the main repository root.

### Submodule Awareness

When the project uses git submodules:

1. Run `SH list-submodules` to get available submodules
2. Present an `AskUserQuestion` with options: each submodule name + "Root repository (parent)"
3. If a submodule is selected, all codebase exploration and implementation operates within `<submodule_path>` — never on the parent repo directly
4. After task completion (Step 6), if a submodule was selected: `git add <submodule_path> && git commit -m "chore: update submodule <name> pointer"` in the parent repo to align the submodule reference

## Argument Dispatch

`SH dispatch --skill task --args "$ARGUMENTS"` → routes to: `pick`, `pick-all`, `create`, `create-all`, `continue`, `continue-all`, `edit`, `schedule`, or `status` flow.

Also returns `yolo: true/false` (see **Yolo Mode** in project configuration).

---

## Status Flow

Read-only report. Do NOT modify any files.

### Status Data

`SH status-report`

Returns pre-computed: `summary` counts, `in_progress` tasks, `blocked` tasks, `next_recommended` tasks, and `release_plan`.

**Platform-only supplement:** Also query `platform-cmd list-issues labels="task,status:to-test" state="open"` for to-test tasks.

**Dual-sync supplement:** Run `TM sync-from-platform --dry-run --format text 2>/dev/null || echo "(sync check not available)"`.

### Status Report Presentation

1. **Summary** — Table with counts by status (completed, in-progress, to-test, todo, blocked) and progress percentage.
2. **In-Progress Tasks** — Task code, title, priority, what remains, files involved.
3. **To-Test Tasks** — Task code, title, testing pending. Suggest `/release test-only TASK-CODE`.
4. **Next Recommended** — Top 2-3 from `next_recommended`: code, title, priority, dependency status, brief scope.
5. **Blocked Tasks** — If any, list with blocking reason.
6. **Sync Discrepancies** — Dual-sync only. Task code, issue number, local vs platform status, suggested action.
7. **Release Plan Overview** — From `release_plan`. If null/missing, skip. Show next release and upcoming releases summary.

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

#### Step 2.5: Create task branch

Create a dedicated `task/<code>` branch from `{DEVELOPMENT_BRANCH}` and check it out:

```bash
git checkout -b task/<code> {DEVELOPMENT_BRANCH}
```

If the branch already exists, check it out instead:

```bash
git checkout task/<code>
```

Inform: branch name, base branch. All subsequent steps operate on the checked-out task branch.

#### Step 3: Read the full task details

- **Platform-only:** `platform-cmd view-issue`. Parse DESCRIPTION, TECHNICAL DETAILS, Files involved.
- **Local/dual:** `TM parse TASK-CODE`.

#### Step 4: Explore the codebase

For each file in "Files involved":
- If exists, read to understand current state
- If marked CREATE, check target directory and similar files for patterns
- Identify relevant interfaces, types, and patterns

**Related code heuristics:** After the above file exploration, use local heuristics to find related code not listed in "Files involved":
- Run `TM duplicates --keywords "<task keywords>"` to surface similar tasks.
- Run `TM find-files "<keywords>"` to locate likely source files.
- Read the top 3-5 most relevant files to discover hidden dependencies, shared patterns, or code that should be updated alongside the task.
- Include these as "Additional related files" in the implementation briefing (Step 5).

#### Step 4.5: Frontend Design Wizard (conditional)

After codebase exploration, check if the task involves frontend code:

```bash
TM is-frontend-task TASK-CODE
```

**Platform-only alternative:** Pass issue body as JSON: `TM is-frontend-task TASK-CODE --json-body '{"title":"...","description":"...","files_create":[...],"files_modify":[...]}'`

If `is_frontend` is `true`, run the frontend design wizard:

```bash
python3 ${CLAW_ROOT}/scripts/frontend_wizard.py detect-framework --root <PROJECT_ROOT>
python3 ${CLAW_ROOT}/scripts/frontend_wizard.py search-templates --framework <DETECTED> --query "<task keywords>"
python3 ${CLAW_ROOT}/scripts/frontend_wizard.py list-palettes
```

1. **Present 3 template options** from `search-templates` results. In **yolo mode**, auto-select the first template.
2. **Ask palette selection**: show bundled palettes (Open Color, Radix Colors, Tailwind, Material Design) plus "Generate from seed color". In **yolo mode**, auto-select the recommended palette.
3. **Apply constraints**: `python3 ${CLAW_ROOT}/scripts/frontend_wizard.py apply-constraints --template <SELECTED> --palette <SELECTED> --typography modern`
4. Include the generated CSS variables, typography, and motion settings as **design constraints** in the implementation briefing.

**Skip conditions:** Skip this step if `is_frontend` is `false` or if the wizard has already been run for this task (check `.claude/frontend-config.json`).

#### Step 5: Present the implementation briefing

1. **Task Selected**: Code, title, priority
2. **Status Update**: Confirm marked as in-progress
3. **Scope Summary**: What needs to be done
4. **Technical Approach**: Implementation steps based on task details and codebase exploration
5. **Files to Create/Modify**: Every file with what needs to happen
6. **Additional Related Files** (from local exploration): Nearby modules, shared utilities, or follow-up files discovered during code analysis. Omit if none found.
7. **Dependencies**: Status of all dependencies
8. **Risks**: Any concerns found during exploration
9. **Quality Gate**: Remind that verify command must pass before closing

Ask: "Ready to start implementation, or would you like to adjust the approach?"

#### Step 5.5: Visual Assets

If the task needs a visual asset, ask the user to provide it or use the frontend design wizard when the task is frontend-related. CodeClaw no longer ships a standalone image-generation workflow in this flow.

---

#### Step 6: Post-Implementation — Confirm, Close & Commit

After full implementation and quality gate passes:

**6-pre. No extra index refresh is required.**

The current workflow relies on normal task tracking and docs sync. PostToolUse already records the edited files against the active task.

**6-review. Run quality gate:**

Run the local quality gate on changed files:

```bash
python3 ${CLAW_ROOT}/scripts/quality_gate.py --root <PROJECT_ROOT> --files <changed_files> --verify-command "<CTX.config.verify_command>" --json
```

Parse the JSON result. If `passed` is `false`:

1. Present the dashboard from `result.dashboard`.
2. Attempt iterative auto-fix: the quality gate runs up to `max_fix_iterations` (default 3) internally, applying auto-fixes between iterations.
3. After the loop, if blocking findings remain (critical/high severity), present them grouped by tool.

**GATE (blocking findings remain):** "Fix remaining issues manually and re-run" / "Proceed despite findings (not recommended)" / "Cancel task closure"

If `passed` is `true`, or user chooses to proceed: continue to 6a.

This step is non-blocking and silent on failure (e.g., if the quality gate script is unavailable or errors out, log a warning and proceed).

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

Inform: "Task closed. Branch `task/<code>` preserved for PR."

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

Pick up and implement **all pending tasks for the current active release**. By default, tasks are implemented sequentially in dependency order so the review trail stays on the task itself.

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

Parse `Dependencies:` fields from each pending task. Group tasks into dependency batches so the next task is always clear.

#### Step 2: Present the plan

Present: "Found **N pending tasks** for release X.X.X. **M are ready** in batch 1."

| Batch | Tasks | Notes |
|-------|-------|-------|
| 1 | CODE1, CODE2 | Independent |
| 2 | CODE3 | Depends on CODE1 |

**Default:** GATE: "Implement tasks sequentially" / "Cancel"

#### Step 3a: Sequential execution (default)

For each batch, process the tasks one by one in dependency order:

1. Move the task to progressing and assign it if needed.
2. Checkout the task branch.
3. Read the task details and related code.
4. Implement the task according to DESCRIPTION and TECHNICAL DETAILS.
5. Run `{VERIFY_COMMAND}` and fix any failures, up to 3 attempts.
6. Commit, push, create the PR, and move the task to done.

Wait for the current batch to finish before moving to the next batch.

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
4. Use local heuristics to discover related code patterns:
   - Read similar completed tasks and nearby source files
   - Look for matching module names, imports, and keywords
   - Use those findings to inform the "Files involved" section and identify dependencies

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

Create tasks from **all pending ideas** in `ideas.txt` in one batch. Process ideas sequentially by default so each draft can be reviewed before the next one starts.

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

#### Step 2a: Sequential execution (default)

For each idea in order, execute the standard Create Flow one at a time:

1. Parse the idea details.
2. Explore the codebase to understand scope, patterns, and relevant files.
3. Determine the next task code.
4. Draft the task block with Priority, Dependencies, DESCRIPTION, TECHNICAL DETAILS, and Files involved.
5. Insert the task into `to-do.txt`.
6. Move the idea to approved.
7. Record the created task.

Wait for user confirmation at each task's draft gate before moving to the next idea.

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

#### Step 1.5: Checkout the task branch

```bash
git checkout task/<code>
```

If the branch does not exist, suggest `/task pick <TASK-CODE>` to create it. All subsequent steps operate on the checked-out task branch.

**Auto-assign (platform-only/dual sync):** `PM edit-issue number=ISSUE_NUM add-assignee="@me"` to track collaboration.

#### Step 2: Read the Full Task Block

- **Platform-only:** `platform-cmd view-issue`. Parse Description, Technical Details, Files Involved.
- **Local/dual:** `TM parse TASK-CODE` and `verify-files TASK-CODE`.

#### Step 3: Assess Current Implementation State

**CREATE files:** Check existence via `Glob`. Classify: missing, stub, or implemented.
**MODIFY files:** Read and `Grep` for key changes. Note: applied vs still needed.
Cross-check each technical requirement against code artifacts.

**Related code heuristics:** Run `TM duplicates --keywords "<task keywords>"` and `TM find-files "<keywords>"` to discover any new or modified files across the project that are conceptually related to this task. This catches changes made by other work since the task was last active, revealing integration points that may need attention.

#### Step 4: Explore Related Code

Read all related files: those to be modified, similar files for patterns, related types/interfaces/imports. Include any high-relevance files surfaced by the semantic exploration in Step 3.

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

Resume work on **all in-progress tasks** sequentially by default so each update can be reviewed before the next task starts.

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

GATE: "Implement tasks sequentially" / "Cancel"

#### Step 2a: Sequential execution (default)

For each task in priority order, execute the standard Continue Flow one at a time:

1. Checkout the task branch.
2. Read the full task details.
3. Assess the current implementation state.
4. Explore related code for patterns and context.
5. Implement the remaining work according to DESCRIPTION and TECHNICAL DETAILS.
6. Run `{VERIFY_COMMAND}` and fix failures, up to 3 attempts.
7. Commit the changes.
8. Mark the task as done.

Wait for user direction before moving to the next task.

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

## Edit Flow

Modify fields of an existing task in-place without changing its status.

### Edit Flow — Locate Task

- **Task code from dispatch:** `task_code` field. If empty, ask: "Which task do you want to edit? Enter the task code." STOP.
- **Platform-only:** `PM view-issue` using the task code to search. Parse current fields (title, priority, dependencies, description, technical details, files involved).
- **Local/dual:** `TM parse TASK-CODE`. Parse current fields from the task block.

### Edit Flow Instructions

#### Step 1: Present Current Fields

Display the task's current values:

| # | Field | Current Value |
|---|-------|---------------|
| 1 | Title | [current title] |
| 2 | Priority | [HIGH/MEDIUM/LOW] |
| 3 | Dependencies | [deps or None] |
| 4 | Release | [version or None] |
| 5 | Description | [first line or summary] |
| 6 | Technical Details | [first line or summary] |
| 7 | Files Involved | [count of files] |

#### Step 2: Select Fields to Edit

`AskUserQuestion` multiSelect: "Which fields do you want to edit?" with options:
- **"Title"**
- **"Priority"**
- **"Dependencies"**
- **"Release"**
- **"Description"**
- **"Technical Details"**
- **"Files Involved"**
- **"Cancel"**

STOP.

#### Step 3: Accept New Values

For each selected field, present the current value and ask for the new value. Validate inputs before proceeding:
- **Priority:** Must be one of `HIGH`, `MEDIUM`, or `LOW` (case-insensitive). Reject other values and re-prompt.
- **Release:** Must match semver format `X.X.X` and exist in `RM release-plan-list`. If not found, warn and re-prompt.
- **Multi-line fields** (Description, Technical Details): Accept the full replacement text.

#### Step 4: Confirm Changes

Present a diff-style summary of old vs new values for each modified field.

`AskUserQuestion`: **"Apply these changes"** | **"Needs adjustments"** | **"Cancel"**

STOP.

#### Step 5: Apply Changes

Based on mode:
- **Platform-only:** `PM edit-issue` to update the issue title, body, and labels as needed. For priority changes, swap priority labels (remove old, add new). For release changes, update milestone and `release:` label.
- **Local/dual:** Use `Edit` tool to modify the task block in the appropriate file (`to-do.txt`, `progressing.txt`, or `done.txt`). Preserve exact formatting: 78-dash separators, 2-space indent, field order.
- **Dual sync:** Apply both local edit and platform update. If platform fails, warn but keep local changes.

#### Step 6: Confirm

Report: "Task [TASK-CODE] updated. Fields changed: [list]." Include platform issue URL if applicable.

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
