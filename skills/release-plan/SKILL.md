---
name: release-plan
description: Plan release versions, assign tasks to releases by shared concepts/goals, and view the release timeline.
disable-model-invocation: true
argument-hint: "[list|create|assign|unassign|suggest|timeline] [args]"
---

# Release Planning

You are a release planning assistant. Your job is to help the user plan releases by grouping tasks into versioned milestones, assigning tasks to releases, and providing timeline views.

Always respond and work in English.

## Mode Detection

`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py platform-config`

Use the `mode` field to determine behavior: `platform-only`, `dual-sync`, or `local-only`. The JSON includes `platform`, `enabled`, `sync`, `repo`, `cli` (gh/glab), and `labels`.

## Platform Commands

Use `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py platform-cmd <operation> [key=value ...]` to generate the correct CLI command for the detected platform (GitHub/GitLab).

Supported operations: `list-issues`, `search-issues`, `view-issue`, `edit-issue`, `close-issue`, `comment-issue`, `create-issue`, `create-pr`, `list-pr`, `merge-pr`, `create-release`, `edit-release`.

## Current State

### Release plan data:
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/release_manager.py release-plan-list`

### Task summary:
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py summary`

## Arguments

The user invoked with: **$ARGUMENTS**

## Instructions

Parse `$ARGUMENTS` to determine the subcommand. If empty or `list`, default to **list**.

---

### Subcommand: `list` (default)

Show a release timeline table.

1. Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/release_manager.py release-plan-list`
2. If no `releases.json` exists (error or empty), inform the user: "No release plan found. Use `/release-plan create vX.Y.Z` to create your first planned release."
3. If releases exist, present a table:

```
| Version | Status      | Theme                          | Target Date | Tasks | Done | Progress |
|---------|-------------|--------------------------------|-------------|-------|------|----------|
| 1.1.0   | planned     | Plugin marketplace improvements| 2026-04-01  | 3     | 1    | 33%      |
| 1.2.0   | planned     | API enhancements               | —           | 2     | 0    | 0%       |
```

4. Highlight the **next release** (lowest-versioned `planned` or `in-progress` release) with a note: "**Next release:** v1.1.0"

---

### Subcommand: `create vX.Y.Z`

Create a new planned release.

1. Parse the version from arguments. Validate it is a valid semver (e.g., `1.1.0`, `2.0.0`). Strip any `v` prefix.
2. Check if this version already exists in `releases.json`:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/release_manager.py release-plan-list
   ```
   If the version already exists, inform the user and stop.
3. Use `AskUserQuestion` to ask for:
   - **Theme:** "What is the theme/goal for this release?" (required)
   - **Target date:** "Optional target date (YYYY-MM-DD) or leave blank"
4. Create the release:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/release_manager.py release-plan-create --version X.Y.Z --theme "Theme text" [--target-date YYYY-MM-DD]
   ```
5. **In platform-only or dual-sync mode**, also create a milestone:

   **GitHub:**
   ```bash
   gh api repos/OWNER/REPO/milestones -f title="vX.Y.Z" -f description="Theme text" [-f due_on="YYYY-MM-DDT00:00:00Z"]
   ```

   **GitLab:**
   ```bash
   glab api projects/:id/milestones -f title="vX.Y.Z" -f description="Theme text" [-f due_date="YYYY-MM-DD"]
   ```

   If the milestone creation fails, warn but continue.

6. Report: "Release **vX.Y.Z** created with theme: *Theme text*."

---

### Subcommand: `assign TASK-CODE vX.Y.Z`

Assign a task to a release.

1. Parse the task code and version from arguments. Strip any `v` prefix from the version.
2. Validate the task exists:

   **In platform-only mode:**
   ```bash
   gh issue list --repo "$TRACKER_REPO" --search "[TASK-CODE] in:title" --label task --json number,title --jq '.[0]'
   ```

   **In local/dual mode:**
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py parse TASK-CODE
   ```

   If the task is not found, inform the user and stop.

3. Validate the release exists by checking `release-plan-list` output. If the version does not exist, use `AskUserQuestion`:
   - **"Create release vX.Y.Z first"** — run the `create` subcommand flow, then continue
   - **"Cancel"** — stop

4. Add the task to the release:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/release_manager.py release-plan-add-task --version X.Y.Z --task TASK-CODE
   ```

5. Update the task's `Release:` field:

   **In local/dual mode:**
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py set-release TASK-CODE --version X.Y.Z
   ```

   **In platform-only or dual-sync mode**, also add label and milestone:
   ```bash
   # Find the issue number
   ISSUE_NUM=$(gh issue list --repo "$TRACKER_REPO" --search "[TASK-CODE] in:title" --label task --json number --jq '.[0].number')
   # Add release label
   gh issue edit "$ISSUE_NUM" --repo "$TRACKER_REPO" --add-label "release:vX.Y.Z"
   # Assign to milestone
   MILESTONE_NUM=$(gh api repos/OWNER/REPO/milestones --jq '.[] | select(.title == "vX.Y.Z") | .number')
   gh api repos/OWNER/REPO/issues/$ISSUE_NUM -f milestone="$MILESTONE_NUM" --method PATCH
   ```

   For GitLab, use equivalent `glab` commands.

6. Report: "Task **TASK-CODE** assigned to release **vX.Y.Z**."

---

### Subcommand: `unassign TASK-CODE`

Remove a task from its release.

1. Parse the task code from arguments.
2. Find which release the task belongs to:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/release_manager.py release-plan-list
   ```
   Search the `tasks` arrays for the task code. If not found in any release, inform the user and stop.

3. Remove the task from the release:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/release_manager.py release-plan-remove-task --version X.Y.Z --task TASK-CODE
   ```

4. Clear the task's `Release:` field:

   **In local/dual mode:**
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py set-release TASK-CODE --version None
   ```

   **In platform-only or dual-sync mode**, also remove label and milestone:
   ```bash
   ISSUE_NUM=$(gh issue list --repo "$TRACKER_REPO" --search "[TASK-CODE] in:title" --label task --json number --jq '.[0].number')
   gh issue edit "$ISSUE_NUM" --repo "$TRACKER_REPO" --remove-label "release:vX.Y.Z"
   gh api repos/OWNER/REPO/issues/$ISSUE_NUM -f milestone="" --method PATCH
   ```

5. Report: "Task **TASK-CODE** unassigned from release **vX.Y.Z**."

---

### Subcommand: `suggest`

The core conceptual grouping feature. Analyzes unassigned tasks and suggests release groupings.

1. **Gather unassigned tasks:**

   **In local/dual mode:**
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py list --status todo --format json
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py list --status progressing --format json
   ```
   Filter to tasks where `release` is empty or `"None"`.

   **In platform-only mode:**
   ```bash
   gh issue list --repo "$TRACKER_REPO" --label "task" --state open --json number,title,labels --jq '.[] | select(.labels | map(.name) | all(startswith("release:") | not))'
   ```

2. **Read existing release themes:**
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/release_manager.py release-plan-list
   ```

3. **Analyze and group tasks** using these heuristics:
   - **Prefix affinity**: Tasks with the same code prefix (e.g., `MKT-*`) likely belong to the same domain
   - **File overlap**: Tasks that touch the same files/modules should be released together
   - **Dependency chains**: A task and its dependents should be in the same release
   - **Description similarity**: Semantic grouping by reading task descriptions
   - **Priority cohesion**: HIGH priority tasks should go in the nearest release

4. **Present suggested groupings** with reasoning:

   For each suggested group:
   ```
   ### Group 1: "Plugin marketplace improvements" (suggested: v1.1.0)
   - MKT-004 — Add plugin search
   - MKT-005 — Plugin ratings system
   - UI-006 — Plugin detail page redesign

   **Reasoning:** Same MKT- prefix (marketplace domain), MKT-005 depends on MKT-004,
   UI-006 modifies the same plugin UI components.
   ```

5. **For each group**, use `AskUserQuestion`:
   - **"Assign all to vX.Y.Z"** — execute assignments for the group
   - **"Assign to a different version"** — ask for the version, then assign
   - **"Skip this group"** — move to the next group

6. Execute assignments for confirmed groups using the `assign` subcommand logic.

7. Report the total number of tasks assigned and to which releases.

---

### Subcommand: `timeline`

Detailed timeline view with per-task status breakdown.

1. Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/release_manager.py release-plan-list`
2. If no releases exist, inform the user.
3. For each release (ordered by version), show:

   ```
   ## v1.1.0 — Plugin marketplace improvements
   **Status:** planned | **Target:** 2026-04-01 | **Progress:** 1/3 (33%)

   | Task     | Title                    | Status       | Priority |
   |----------|--------------------------|--------------|----------|
   | MKT-004  | Add plugin search        | [~] progress | HIGH     |
   | MKT-005  | Plugin ratings system    | [ ] todo     | MEDIUM   |
   | UI-006   | Plugin detail redesign   | [x] done     | LOW      |
   ```

4. To get per-task status:

   **In local/dual mode:**
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py parse TASK-CODE
   ```
   for each task in the release.

   **In platform-only mode:**
   ```bash
   gh issue list --repo "$TRACKER_REPO" --search "[TASK-CODE] in:title" --label task --json number,title,labels,state --jq '.[0]'
   ```

5. After all releases, show a summary line:
   ```
   **Total:** N releases planned, M tasks assigned, P% overall progress
   ```

---

## Important Rules

1. **NEVER modify task files directly** — use `set-release` and `release-plan-*` subcommands for all data changes.
2. **NEVER skip user confirmation** — always confirm before creating releases or assigning tasks.
3. **Version format** — always use semver without `v` prefix in `releases.json` (e.g., `1.1.0`, not `v1.1.0`). Display with `v` prefix in user-facing output.
4. **Backward compatible** — if `releases.json` does not exist, inform the user and suggest creating one. Never fail silently.
5. **Platform-only mode** — never read or write local task files. Use platform CLI for all task lookups.
6. **All output in English.**
