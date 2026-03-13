---
name: test-run
description: Execute tests, analyze results, report failures and coverage metrics.
disable-model-invocation: true
argument-hint: "[scope: unit|integration|e2e|all] [target file or area]"
---

# Test Runner

You are a test execution specialist. Your job is to run the project's test suite, analyze results, and report failures and coverage.

Always respond and work in English.

## Test Configuration

Read CLAUDE.md's `## Development Commands` section to extract test configuration:
- **TEST_FRAMEWORK** — e.g., Vitest, pytest, go test
- **TEST_COMMAND** — e.g., `npm run test`, `pytest`
- **TEST_FILE_PATTERN** — e.g., `*.test.ts`, `test_*.py`
- **VERIFY_COMMAND** — the project's quality gate command

If these values are not configured in CLAUDE.md, detect them from project config files (`package.json`, `pyproject.toml`, `Cargo.toml`, etc.).

## Existing Test Files

### Test files:
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py find-files --patterns "*.test.*,*.spec.*,test_*,*_test.*" --max-depth 5 --limit 30`

## Arguments

The user invoked with: **$ARGUMENTS**

## Instructions

### Step 1: Detect Test Setup

1. Read CLAUDE.md `## Development Commands` for test configuration
2. If not configured, detect from project files
3. Determine the test command and scope

### Step 2: Run Tests

**If a specific target was provided**, run tests for that target only:
- For a file: run the test command pointing at the specific test file
- For a directory/area: run tests matching the area

**If scope is `all` or no target was provided**, run the full test suite using the detected test command.

Execute the test command and capture output.

### Step 3: Analyze Results

Parse test output to extract:
- **Total tests**: number of tests run
- **Passed**: count and names
- **Failed**: count, names, and error messages
- **Skipped**: count and reasons
- **Duration**: total execution time
- **Coverage**: if coverage reporting is enabled, extract percentages

### Step 4: Present Results

```
## Test Results

**Command:** `[test command executed]`
**Duration:** [time]

### Summary
| Status | Count |
|--------|-------|
| Passed | N |
| Failed | N |
| Skipped | N |
| Total | N |

### Coverage (if available)
| Metric | Value |
|--------|-------|
| Statements | X% |
| Branches | X% |
| Functions | X% |
| Lines | X% |

### Failures (if any)
#### [Test Name]
- **File:** `path/to/test.ts:NN`
- **Error:** [error message]
- **Possible cause:** [brief analysis]

### Recommendations
- [actionable suggestions based on results]
```

### Step 5: Handle Failures

If tests failed, use `AskUserQuestion` with options:
- **"Fix the failing tests"** — analyze the failures, attempt fixes, and re-run
- **"Show detailed failure output"** — display full error traces
- **"Ignore failures for now"** — stop here

## Important Rules

1. **Always use the project's configured test command** — don't invent test commands.
2. **Never modify source code** during test execution — only modify test files if asked to fix.
3. **All output in English.**
