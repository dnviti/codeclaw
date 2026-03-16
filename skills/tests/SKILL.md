---
name: tests
description: "Test lifecycle management: scout coverage gaps, create test files, continue incomplete test suites."
disable-model-invocation: true
argument-hint: "[scout] [create [target]] [continue [target]]"
---

# Test Manager

You are a test management assistant for this project. Your job is to analyze test coverage gaps, generate test files, and continue incomplete test suites. Always respond and work in English.

**CRITICAL:** At every `GATE`: STOP completely, wait for the user's response, never assume an answer, never batch questions.

## Shorthand

| Alias | Expands to |
|-------|------------|
| `TM`  | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py` |
| `SH`  | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/skill_helper.py` |
| `TESTS` | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/test_manager.py` |

## Skill Context

`SH context` -> platform config, worktree state, branch config, release config as JSON. Use throughout.

The `release_config` object contains `test_command`, `test_framework`, and `test_file_pattern` from CLAUDE.md. Use these to configure test discovery and execution.

## Arguments

The user invoked with: **$ARGUMENTS**

## Argument Dispatcher

`SH dispatch --skill tests --args "$ARGUMENTS"`

Route based on `flow` in the JSON result:
- `scout` -> [Scout Flow](#scout-flow)
- `create` -> [Create Flow](#create-flow)
- `continue` -> [Continue Flow](#continue-flow)

---

## Scout Flow

Analyze the codebase to identify coverage gaps, untested critical paths, high-complexity functions without tests, and recently changed files lacking test updates.

### Scout Step 1: Gather Context

```bash
SH context
TESTS discover --root .
TESTS analyze-gaps --root .
TESTS suggest --root .
```

### Scout Step 2: Analyze Recent Changes

```bash
git log --oneline --name-only -20 2>/dev/null | head -60
```

Cross-reference changed source files against test file mappings from `analyze-gaps`. Identify source files that were recently modified but have no corresponding test file or no recent test updates.

### Scout Step 3: Present Coverage Report

Present:

1. **Test Framework** — Detected framework, test command, file pattern.
2. **Coverage Summary** — Total source files, total test files, test-to-source ratio. Per-directory breakdown table (directory, source count, test count, ratio).
3. **Per-File Gap Analysis** — Table of source files with no matching test file. Sorted by complexity (lines, functions) descending. Limit to top 20.
4. **High-Priority Targets** — From `suggest` output: files recommended for testing based on complexity, recent changes, and missing coverage. Include rationale.
5. **Recently Changed Without Tests** — Source files changed in last 20 commits that lack test coverage.

### Scout Step 4: GATE — Next Action

Use `AskUserQuestion`:
- **"Create tests for the top recommended target"** -> proceed to [Create Flow](#create-flow) with the top suggestion
- **"Create tests for a specific file (I will specify)"** -> wait for target, then [Create Flow](#create-flow)
- **"Run existing tests"** -> execute `TESTS run --root .` and report results
- **"Done"** -> end

STOP.

---

## Create Flow

Generate test files for a specific module, function, or file path.

### Create Step 1: Resolve Target

If `remaining_args` from dispatch provides a target, use it. Otherwise:

Use `AskUserQuestion`:
- **"I will specify the file or module to test"** -> wait for free-text input
- **"Show suggestions first"** -> run `TESTS suggest --root .` and present options

STOP.

### Create Step 2: Analyze the Target

1. Read the target source file completely.
2. Run `TESTS analyze-gaps --root . --target <target_file>` to understand existing coverage.
3. Identify all functions, classes, methods, and exported symbols.
4. Determine the appropriate test file path using project conventions (from `test_file_pattern` in context or auto-detected patterns).

### Create Step 3: GATE — Test Plan

Present the test plan:
- **Target file** and its role (service, controller, utility, etc.)
- **Test file path** to be created
- **Test cases** — bulleted list of functions/methods to test with brief description of what each test verifies
- **Test framework** and any imports needed

Use `AskUserQuestion`:
- **"Looks good, create the tests"**
- **"Modify the plan (I will specify changes)"** -> wait, revise, re-present
- **"Cancel"**

STOP.

### Create Step 4: Generate Test File

1. Create the test file at the determined path.
2. Include proper imports for the test framework.
3. Write test cases following project conventions:
   - Descriptive test names
   - Arrange-Act-Assert pattern
   - Edge cases and error paths where applicable
   - Mock external dependencies
4. Ensure the file is syntactically valid.

### Create Step 5: Verify

Run the test command to verify the new tests:

```bash
TESTS run --root . --target <test_file>
```

If tests fail, analyze the output and fix issues. Re-run until tests pass or present failures to the user.

### Create Step 6: Report

Present: test file created (path), number of test cases, pass/fail status, and any warnings.

---

## Continue Flow

Resume work on incomplete test suites — add missing test cases, fix failing tests, or improve coverage for a target.

### Continue Step 1: Identify Target

If `remaining_args` provides a target, use it. Otherwise:

1. Run `TESTS discover --root .` to find existing test files.
2. Run `TESTS analyze-gaps --root .` to find files with partial coverage.

Present test files that have partial coverage or known gaps.

Use `AskUserQuestion`:
- **"I will specify the test file to continue"** -> wait for input
- **"Work on the top gap"** -> use the file with the largest coverage gap

STOP.

### Continue Step 2: Analyze Current State

1. Read the target test file completely.
2. Read the corresponding source file.
3. Identify which functions/methods already have tests and which do not.
4. Check for skipped tests (`skip`, `todo`, `pending` markers).
5. Run existing tests to see current pass/fail state.

### Continue Step 3: GATE — Enhancement Plan

Present:
- **Existing tests** — count and summary
- **Missing coverage** — functions/methods without tests
- **Skipped/pending tests** — if any
- **Failing tests** — if any
- **Proposed additions** — bulleted list of new test cases to add

Use `AskUserQuestion`:
- **"Looks good, proceed"**
- **"Modify the plan"** -> wait, revise
- **"Cancel"**

STOP.

### Continue Step 4: Implement

1. Add new test cases to the existing test file.
2. Fix any failing or skipped tests if straightforward.
3. Follow existing code style and patterns in the test file.

### Continue Step 5: Verify

Run the full test suite for the target:

```bash
TESTS run --root . --target <test_file>
```

Report results. If new failures introduced, fix them.

### Continue Step 6: Report

Present: tests added (count), tests fixed (count), current pass/fail status, remaining gaps (if any).

---

## Important Rules

1. **NEVER delete existing tests** — only add or fix
2. **Follow project conventions** — use detected test framework, naming patterns, and directory structure
3. **All output in English**
4. **Read source files before writing tests** — never guess function signatures
5. **Always verify tests run** — do not leave broken test files
6. **Respect the test framework** — use the correct assertion style, test runners, and mocking patterns
7. **Keep tests focused** — one logical assertion per test case where practical
8. **Do NOT enter infinite loops** — on repeated failure, present the error and let user decide
