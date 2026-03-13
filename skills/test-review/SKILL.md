---
name: test-review
description: "Test tasks marked status:to-test. Runs automated tests, guides manual testing, and manages the to-test lifecycle (phases T1-T7)."
disable-model-invocation: true
argument-hint: "[TASK-CODE or to-test]"
---

# Test Review

You are a test reviewer responsible for verifying task implementations. You manage the `status:to-test` lifecycle — running automated tests, guiding manual testing, and confirming task completion.

Always respond and work in English.

## Mode Detection

`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py platform-config`

Use the `mode` field to determine behavior: `platform-only`, `dual-sync`, or `local-only`. The JSON includes `platform`, `enabled`, `sync`, `repo`, `cli` (gh/glab), and `labels`.

## Platform Commands

Use `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py platform-cmd <operation> [key=value ...]` to generate the correct CLI command for the detected platform (GitHub/GitLab).

## Test Configuration

Read CLAUDE.md's `## Development Commands` section to extract:
- **TEST_FRAMEWORK**, **TEST_COMMAND**, **TEST_FILE_PATTERN**, **VERIFY_COMMAND**, **RELEASE_BRANCH**

If these values are not configured in CLAUDE.md, detect them from project config files.

## Existing Test Infrastructure

### Test config files:
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py find-files --patterns "vitest.config.*,jest.config.*,pytest.ini,pyproject.toml,.mocharc.*" --max-depth 3 --limit 20`

### Existing test files:
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py find-files --patterns "*.test.*,*.spec.*,test_*,*_test.*" --max-depth 5 --limit 30`

## Arguments

The user invoked with: **$ARGUMENTS**

## Instructions

### Phase T1: Mode Detection

Use the platform-config output above to determine the operating mode.

### Phase T2: Find to-test tasks

**If a specific task code was provided as argument**, use that task directly.

**If the argument is `to-test` or no specific code was given:**

**In platform-only mode:**
```bash
gh issue list --repo "$TRACKER_REPO" --label "task,status:to-test" --state open --json number,title --jq '.[] | "#\(.number) \(.title)"'
# GitLab: glab issue list -R "$TRACKER_REPO" -l "task,status:to-test" --state opened --output json | jq '.[] | "#\(.iid) \(.title)"'
```

**In local/dual mode:**
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py list --status progressing --format summary
```

If multiple tasks are found, use `AskUserQuestion` to ask which task to test.

If no tasks are found, inform the user: "No tasks found awaiting testing." and stop.

### Phase T3: Read task details

**In platform-only mode:**
```bash
ISSUE_NUM=$(gh issue list --repo "$TRACKER_REPO" --search "[TASK-CODE] in:title" --label task --state open --json number --jq '.[0].number')
# GitLab: glab issue list -R "$TRACKER_REPO" --search "[TASK-CODE]" -l task --state opened --output json | jq '.[0].iid'
gh issue view $ISSUE_NUM --repo "$TRACKER_REPO" --json body --jq '.body'
# GitLab: glab issue view $ISSUE_NUM -R "$TRACKER_REPO" --output json | jq '.description'
```

**In local/dual mode:**
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py parse TASK-CODE
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py verify-files TASK-CODE
```

Extract the DESCRIPTION, TECHNICAL DETAILS, and Files involved sections.

### Phase T4: Detect test configuration

1. **Read CLAUDE.md** for test and verify commands
2. **Identify the test command** from CLAUDE.md or detect from `package.json` / `pyproject.toml` / `Makefile`
3. **Identify relevant test files**: Based on the task's "Files involved" section, find test files that cover those source files

Present the detected configuration:

> **Test configuration for [TASK-CODE]:**
> - Test framework: [detected framework]
> - Test command: `[detected command]`
> - Relevant test files: [list of test files related to the task's files]
> - Verify command: `[verify command from CLAUDE.md]`

### Phase T5: Run automated tests

1. **Run the project's full test suite** using the detected test command. Capture output and categorize results as PASS / FAIL / SKIP.

2. **Run targeted tests** (if identifiable): If specific test files relate to the task's files involved, run those individually for detailed output.

3. **Present results summary:**

   > **Automated Test Results for [TASK-CODE]:**
   > - Total: N tests | Passed: X | Failed: Y | Skipped: Z
   > - [List any failing test names with error messages]

4. **If automated tests fail:**
   - Present the failures to the user
   - Analyze whether failures are related to the task's changes or pre-existing
   - Use `AskUserQuestion` with options:
     - **"Fix the failing tests"** — attempt to fix, then re-run
     - **"These failures are pre-existing, continue to manual testing"** — proceed to T6
     - **"Abort testing"** — stop here

### Phase T6: Guide manual testing

Once automated tests pass, generate and walk the user through manual testing:

1. **Generate a manual testing guide** derived from the task's TECHNICAL DETAILS and Files involved:

   > ### Manual Testing Guide for [TASK-CODE] — [Task Title]
   >
   > **Prerequisites:**
   > - [What needs to be running]
   >
   > **Steps to test:**
   > 1. [Concrete action]
   >    - **Expected:** [Result]
   > 2. [Next action]
   >    - **Expected:** [Result]
   >
   > **Edge cases to check:**
   > - [2-3 edge cases]

   The guide must be actionable and specific — use real URLs, real UI element names, and real API endpoints.

2. **Ask the user to confirm** using `AskUserQuestion`:

   > "Please follow the manual testing guide above. Did all manual test steps pass?"

   Options:
   - **"Yes, all tests passed"** — proceed to T7
   - **"No, found issues"** — ask the user to describe the issues, then offer to fix them. After fixing, re-run T5 and repeat T6.

### Phase T7: Finalize testing

When all tests pass:

1. **Remove the `status:to-test` label** (if still present):

   **In platform-only or dual sync mode:**
   ```bash
   gh issue edit "$ISSUE_NUM" --repo "$TRACKER_REPO" --remove-label "status:to-test"
   # GitLab: glab issue update "$ISSUE_NUM" -R "$TRACKER_REPO" --unlabel "status:to-test"
   ```

2. **Comment on the issue** with test results:

   **In platform-only or dual sync mode:**
   ```bash
   gh issue comment "$ISSUE_NUM" --repo "$TRACKER_REPO" --body "Testing complete. Automated: X passed, Y failed, Z skipped. Manual: all steps verified."
   # GitLab: glab issue note "$ISSUE_NUM" -R "$TRACKER_REPO" -m "Testing complete. Automated: X passed, Y failed, Z skipped. Manual: all steps verified."
   ```

3. **Check if the task branch needs a PR** into the release branch:

   Read CLAUDE.md `## Development Commands` for `RELEASE_BRANCH`. If not configured, detect from git branches (`develop` if exists, else `main`).

   Check if the task branch exists and has not been merged:
   ```bash
   git branch --list "task/<task-code-lowercase>"
   ```

   If the branch exists but was never merged to the release branch, offer to create a PR:

   Use `AskUserQuestion` with options:
   - **"Yes, create PR into release branch"** — execute:

     1. Push the task branch:
        ```bash
        git push -u origin task/<task-code-lowercase>
        ```

     2. Check for an existing PR/MR:
        ```bash
        gh pr list --base "$RELEASE_BRANCH" --head task/<task-code-lowercase> --state open --json number,url --jq '.[0]'
        # GitLab: glab mr list --target-branch "$RELEASE_BRANCH" --source-branch task/<task-code-lowercase> --state opened --output json | jq '.[0]'
        ```
        If a PR already exists, inform the user and provide the URL. Skip creation.

     3. Build the PR body with test results and task references.

     4. Create the PR/MR:
        ```bash
        gh pr create --base "$RELEASE_BRANCH" --head task/<task-code-lowercase> \
          --title "[TASK-CODE] — [Task Title]" \
          --body "$PR_BODY"
        # GitLab: glab mr create --target-branch "$RELEASE_BRANCH" --source-branch task/<task-code-lowercase> --title "[TASK-CODE] — [Task Title]" --description "$PR_BODY"
        ```

     5. Report the PR URL.

   - **"No, stay on current branch"** — skip PR creation

4. **Inform the user:**

   > "Testing for [TASK-CODE] is complete. All automated and manual tests passed. The task is now eligible for release."

## Important Rules

1. **NEVER skip user confirmation** — always confirm before finalizing.
2. **NEVER proceed to manual testing until automated tests pass** (or user confirms failures are pre-existing).
3. **All output in English.**
4. **Use the project's configured test commands** — read from CLAUDE.md, don't hardcode.
