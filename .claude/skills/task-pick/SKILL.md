---
name: task-pick
description: Pick up the next task for implementation. Prioritizes verifying and closing in-progress tasks before picking new ones.
disable-model-invocation: true
argument-hint: "[TASK-CODE]"
---

# Pick Up a Task

You are a task manager for this project. Your job is to:
1. **First**: verify and close any in-progress tasks that have already been implemented
2. **Then**: pick up a new task only when all in-progress tasks are resolved

## Mode Detection

Determine the operating mode first:

```bash
GH_ENABLED="$(jq -r '.enabled // false' .claude/github-issues.json 2>/dev/null)"
GH_SYNC="$(jq -r '.sync // false' .claude/github-issues.json 2>/dev/null)"
GH_REPO="$(jq -r '.repo' .claude/github-issues.json 2>/dev/null)"
```

- **GitHub-only mode** (`GH_ENABLED=true` AND `GH_SYNC != true`): Read/write task state via GitHub Issues. No local file operations.
- **Dual sync mode** (`GH_ENABLED=true` AND `GH_SYNC=true`): Use local files as primary, then sync to GitHub.
- **Local only mode** (`GH_ENABLED=false` or config missing): Use local files only.

## Current Task State

### GitHub-only mode:

```bash
# In-progress tasks
gh issue list --repo "$GH_REPO" --label "task,status:in-progress" --state open --json number,title --jq '.[] | "\(.title)"' 2>/dev/null
# Pending tasks (by priority)
gh issue list --repo "$GH_REPO" --label "task,status:todo,priority:high" --state open --json number,title --jq '.[] | "\(.title)"' 2>/dev/null
gh issue list --repo "$GH_REPO" --label "task,status:todo,priority:medium" --state open --json number,title --jq '.[] | "\(.title)"' 2>/dev/null
gh issue list --repo "$GH_REPO" --label "task,status:todo,priority:low" --state open --json number,title --jq '.[] | "\(.title)"' 2>/dev/null
# Completed tasks
gh issue list --repo "$GH_REPO" --label "task,status:done" --state closed --limit 20 --json number,title --jq '.[] | "\(.title)"' 2>/dev/null
```

### Local/Dual mode:

#### In-progress tasks:
!`python3 scripts/task_manager.py list --status progressing --format summary`

#### Pending tasks:
!`python3 scripts/task_manager.py list --status todo --format summary`

#### Completed tasks:
!`python3 scripts/task_manager.py list --status done --format summary`

#### Recommended implementation order:
!`python3 scripts/task_manager.py sections --file to-do.txt`

## Instructions

The user wants to pick up a task. The argument provided is: **$ARGUMENTS**

---

### Step 0: Verify and Close In-Progress Tasks (PRIORITY)

Before picking any new task, you MUST process in-progress tasks.

**In GitHub-only mode:**
- Query in-progress tasks: `gh issue list --repo "$GH_REPO" --label "task,status:in-progress" --state open --json number,title`
- If a specific task code was provided AND that task has `status:in-progress` label: jump directly to Step 0b for that task only.
- Otherwise, process ALL in-progress tasks sequentially.

**In local/dual mode:**
- Read `progressing.txt` and identify all tasks marked `[~]`.
- If a specific task code was provided AND found in progressing.txt: jump to Step 0b for that task only.
- Otherwise, process ALL in-progress tasks.

If there are no in-progress tasks, skip to Step 1.

**0a. Read the in-progress task list** (as described above).

**0b. For each in-progress task, switch to the task branch and verify implementation:**

First, check if a task branch exists:
```bash
git branch --list "task/<task-code-lowercase>"
```

- **If the branch exists:** Switch to it: `git checkout task/<task-code-lowercase>`
- **If it does not exist:** Continue on the current branch.

**Read the full task details:**

**In GitHub-only mode:**
- Find the issue: `ISSUE_NUM=$(gh issue list --repo "$GH_REPO" --search "[TASK-CODE] in:title" --label task --state open --json number --jq '.[0].number')`
- Read the body: `gh issue view $ISSUE_NUM --repo "$GH_REPO" --json body --jq '.body'`
- Parse the body to extract **Files Involved** (CREATE / MODIFY) and **Technical Details** sections.

**In local/dual mode:**
```
python3 scripts/task_manager.py parse TASK-CODE
python3 scripts/task_manager.py verify-files TASK-CODE
```

The `parse` command returns all task fields as JSON (description, technical_details, files_create, files_modify).
The `verify-files` command checks whether each file in "Files involved" exists and returns a JSON report with `all_exist` boolean.

Perform these verification checks:

1. **File existence checks:**
   - For files marked **CREATE**: Use `Glob` to check if the file exists. If not found at the exact path, search nearby directories.
   - For files marked **MODIFY**: Verify the file exists.

2. **Implementation content checks:**
   - For files marked **CREATE**: Read the file and verify meaningful implementation (not empty or stub-only). Check for key exports, components, or functions described in TECHNICAL DETAILS.
   - For files marked **MODIFY**: Use `Grep` to verify key changes described in TECHNICAL DETAILS are present. Look for new imports, function names, route paths, component names, API endpoints, store fields, and UI elements described in the task.
   - Cross-check against TECHNICAL DETAILS: for each numbered technical requirement, verify at least one code artifact proves it was implemented.

3. **Build a verification report:**
   ```
   VERIFICATION: [TASK-CODE] — [Task Title]
   OK [file path] — [what was found]
   MISSING [file path] — MISSING: [what was expected]

   Technical checks:
   OK [requirement] — verified in [file]
   MISSING [requirement] — NOT FOUND
   ```

**0c. Decision based on verification result:**

- **ALL checks pass (task fully implemented):**
  1. **Quality Gate (MANDATORY):** Before closing the task, run your project's verify command (see CLAUDE.md). If it fails:
     - Fix ALL errors and warnings reported
     - Re-run the verify command until it passes with zero errors
     - Only proceed to step 2 when the quality gate passes
  2. **Smoke-Test (MANDATORY):** After the quality gate passes, verify the app starts without runtime errors:

     **2a. Start the application:**
     Run your project's start command using the Bash tool with `run_in_background: true`.

     **2b. Wait for startup and check ports:**
     Wait for startup and verify dev ports are listening:
     ```bash
     python3 scripts/app_manager.py verify-ports --wait 8 --expect bound DEV_PORTS
     ```

     **2c. Check for startup errors:**
     Read the background process output using `TaskOutput`. Scan for common error indicators:
     - Port conflicts: `EADDRINUSE`, `Address already in use`, `port is already allocated`
     - Missing dependencies: `Cannot find module`, `ModuleNotFoundError`, `no required module`, `package not found`
     - Connection failures: `ECONNREFUSED`, `Connection refused`, `connection error`
     - Generic errors: `Error`, `FATAL`, `panic`, `traceback`, stack traces or crash dumps

     **Note on false positives:** Ignore occurrences of "error" that appear in variable names, file paths, log format strings, or middleware names (e.g., `errorHandler`, `error.middleware.ts`). Only flag actual runtime errors.

     **2d. Decision:**
     - **If startup errors are found:** Fix all errors, then re-run the verify command and repeat the smoke-test from 2a (max 2 retries total). If still failing after retries, present the errors to the user and stop.
     - **If no errors (or only false positives):** Proceed to 2e.

     **2e. Stop the application (MANDATORY — no processes must remain):**
     Kill all processes on dev ports and verify:
     ```bash
     python3 scripts/app_manager.py kill-ports DEV_PORTS
     python3 scripts/app_manager.py verify-ports --wait 2 --expect free DEV_PORTS
     ```

  3. Present the verification report to the user (including quality gate result and smoke-test result)
  4. **Run the Step 6 completion flow** (Testing Guide -> Confirm -> Close -> Commit) for this task
  5. **Continue to the next in-progress task** — repeat Step 0b

- **Some checks fail (task partially implemented or not implemented):**
  1. Present the verification report showing what is implemented and what is missing
  2. **Do NOT close the task** — leave it in-progress
  3. Read all existing files related to the task to understand current state
  4. Proceed to Step 4 (Explore codebase) and Step 5 (Present briefing) for this task, focusing the briefing on **what remains to be done**
  5. **Stop processing further in-progress tasks** — the user should finish this one first

**0d. When all in-progress tasks have been verified and closed:**
Inform the user how many tasks were closed, then continue to Step 1 to pick a new task.

---

### Step 1: Determine which task to pick

This step is only reached when there are NO in-progress tasks remaining.

**In GitHub-only mode:**
- **If a task code was provided** (e.g., `AUTH-001`): Search for it: `gh issue list --repo "$GH_REPO" --search "[TASK-CODE] in:title" --label "task,status:todo" --state open --json number,title`
  - If not found in todo, check if already done: `gh issue list --repo "$GH_REPO" --search "[TASK-CODE] in:title" --label "task,status:done" --state closed --json number,title`
  - If done, inform the user and suggest the next available task.
- **If no argument was provided**: Select the next task by priority label ordering: `priority:high` first, then `priority:medium`, then `priority:low`. Within same priority, pick the lowest-numbered task. Check dependencies by reading the task body — dependency task codes should have `status:done` label.

**In local/dual mode:**
- **If a task code was provided**: Use that specific task. Verify it exists in `to-do.txt` and is in `[ ]` (todo) status. If found in `done.txt` as `[x]` (completed), inform the user and suggest the next available task.
- **If no argument was provided**: Select the next task from the recommended implementation order that is still `[ ]` (todo) in `to-do.txt`. Skip tasks found in `done.txt` (completed) or `progressing.txt` (in-progress). Also verify that the task's dependencies are satisfied (dependency tasks should be in `done.txt` as `[x]`). If a task has unsatisfied dependencies, skip it and pick the next one.

### Step 2: Mark task as in-progress

**In GitHub-only mode:**

Update the GitHub Issue labels:
```bash
ISSUE_NUM=$(gh issue list --repo "$GH_REPO" --search "[TASK-CODE] in:title" --label "task,status:todo" --state open --json number --jq '.[0].number')
gh issue edit "$ISSUE_NUM" --repo "$GH_REPO" --remove-label "status:todo" --add-label "status:in-progress"
gh issue comment "$ISSUE_NUM" --repo "$GH_REPO" --body "Task picked up. Branch: \`task/<task-code-lowercase>\`"
```

**In dual sync mode:**

1. Run the move command:
   ```bash
   python3 scripts/task_manager.py move TASK-CODE --to progressing
   ```
   This automatically removes the block from `to-do.txt`, inserts it into `progressing.txt`, and updates the status symbol from `[ ]` to `[~]`. Verify the JSON output shows `"success": true`.
2. If the task appears in the recommended order section of `to-do.txt`, update its status annotation to `[IN PROGRESS]`.
3. Sync to GitHub (update labels as above).

**In local only mode:**

Same as dual sync steps 1-2, skip GitHub sync.

### Step 2.5: Create a task branch

Create a dedicated git branch for this task, branching from `[RELEASE_BRANCH]`.

**2.5a. Check the working tree:**
```bash
git status --porcelain
```
If dirty, inform the user and stop.

**2.5b. Switch to the release branch and pull latest:**
```bash
git checkout [RELEASE_BRANCH]
git pull origin [RELEASE_BRANCH]
```

**2.5c. Create the task branch:**
```bash
git branch --list "task/<task-code-lowercase>"
```
- If exists: `git checkout task/<task-code-lowercase>`
- If not: `git checkout -b task/<task-code-lowercase>`

### Step 3: Read the full task details

**In GitHub-only mode:**
- `gh issue view $ISSUE_NUM --repo "$GH_REPO" --json body --jq '.body'`
- Parse the structured body: DESCRIPTION, TECHNICAL DETAILS, Files involved (CREATE / MODIFY) sections.

**In local/dual mode:**

Get the full parsed task data:
```bash
python3 scripts/task_manager.py parse TASK-CODE
```
This returns all fields as structured JSON: priority, dependencies, description, technical_details, files_create, files_modify.

### Step 4: Explore the codebase

For each file listed in the "Files involved" section:
- If the file exists, read it to understand the current state
- If marked "CREATE", check the target directory and look at similar files for patterns to follow
- Identify relevant interfaces, types, and patterns

### Step 5: Present the implementation briefing

Present a clear English-language briefing:

1. **Task Selected**: Code, title, and priority
2. **Status Update**: Confirm the task was marked as in-progress
3. **Scope Summary**: What needs to be done
4. **Technical Approach**: Implementation steps based on task details and codebase exploration
5. **Files to Create/Modify**: Every file with what needs to happen in each
6. **Dependencies**: Status of all dependencies
7. **Risks**: Any concerns found during exploration
8. **Quality Gate**: Remind that the project's verify command must pass before the task can be closed

After presenting the briefing, ask the user: "Ready to start implementation, or would you like to adjust the approach?"

---

### Step 6: Post-Implementation — Confirm, Close & Commit

After a task has been **fully implemented and the quality gate passes**, execute this completion flow:

**6a. Present a Testing Guide:**

Before asking the user to confirm, generate and present a **manual testing guide** specific to the task that was just implemented. Derive the guide from the task's TECHNICAL DETAILS and Files involved sections.

Present it in this format:

> ### Testing Guide for [TASK-CODE] — [Task Title]
>
> **Prerequisites:**
> - [What needs to be running — e.g., dev server, Docker containers, specific env vars]
>
> **Steps to test:**
> 1. [Concrete action the user can perform in the browser or terminal]
>    - **Expected:** [What they should see or what should happen]
> 2. [Next action]
>    - **Expected:** [Result]
> 3. [Continue as needed...]
>
> **Edge cases to check:**
> - [2-3 edge cases worth verifying — e.g., empty states, error handling, permissions, invalid input]

The guide must be actionable and specific — use real URLs, real UI element names, and real API endpoints from the implementation. Do not use generic placeholders.

**6b. Ask for user confirmation:**

Present a summary of what was done and ask the user to confirm:

> "Implementation of **[TASK-CODE] — [Task Title]** is complete and the quality gate passed.
>
> **Summary of work done:**
> - [brief list of what was created/modified]
>
> Can you confirm this task is done?"

Use `AskUserQuestion` with options:
- **"Yes, task is done"** — proceed to 6c
- **"Not yet, needs more work"** — stop the completion flow; the task stays in-progress

**6c. Mark task as done:**

Once the user confirms the work is done:

**In GitHub-only mode:**
```bash
ISSUE_NUM=$(gh issue list --repo "$GH_REPO" --search "[TASK-CODE] in:title" --label task --state open --json number --jq '.[0].number')
gh issue edit "$ISSUE_NUM" --repo "$GH_REPO" --remove-label "status:in-progress" --add-label "status:done"
gh issue close "$ISSUE_NUM" --repo "$GH_REPO" --comment "Task completed and verified. Quality gate passed."
```

**In dual sync mode:**
1. Run the move command with a completion summary:
   ```bash
   python3 scripts/task_manager.py move TASK-CODE --to done --completed-summary "Brief summary of what was implemented"
   ```
   This automatically removes from `progressing.txt`, inserts into `done.txt`, updates `[~]` to `[x]`, and adds the `COMPLETED:` line.
2. If the task appears in the recommended order section of `to-do.txt`, update its status annotation to `[COMPLETED]`.
3. Sync to GitHub (update labels and close issue as above).

**In local only mode:**
Same as dual sync steps 1-2, skip GitHub sync.

Inform the user: "Task [TASK-CODE] has been closed."

**6d. Ask to commit:**

After closing the task, ask the user:

> "Would you like me to commit these changes?"

Use `AskUserQuestion` with options:
- **"Yes, commit"** — create a commit using the `/commit` skill (or follow the standard git commit workflow). The commit message should reference the task code and briefly describe what was implemented.
- **"No, skip commit"** — skip the commit; done.

**6e. Ask to merge into the release branch:**

Use `AskUserQuestion` with options:
- **"Yes, merge into [RELEASE_BRANCH]"** — execute:
  ```bash
  git checkout [RELEASE_BRANCH]
  git merge task/<task-code-lowercase> --no-ff -m "Merge task/<task-code-lowercase> into [RELEASE_BRANCH]"
  ```
  Use `--no-ff` to preserve branch history.

- **"No, stay on task branch"** — skip the merge

**Important:** Always ask — never auto-commit, auto-close, or auto-merge without user confirmation.
