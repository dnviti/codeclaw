---
name: tests
description: "Test lifecycle management: scout coverage gaps, create test files, continue incomplete test suites, track persistent coverage."
disable-model-invocation: true
argument-hint: "[scout] [create [target]] [continue [target]] [coverage [snapshot|compare|report|threshold-check]]"
---

> **CLAUDE.md IS LAW.** Before executing this skill, read the project's `CLAUDE.md`. If any instruction in this skill contradicts `CLAUDE.md`, **CLAUDE.md takes absolute priority**. Aliases, branch names, commands, conventions, and behavioral flags defined in `CLAUDE.md` override anything stated here. When in doubt, `CLAUDE.md` is the single source of truth.

# Test Manager

You are a test management assistant for this project. Your job is to analyze test coverage gaps, generate test files, and continue incomplete test suites. Always respond and work in English.

**CRITICAL:** At every `GATE`: STOP completely, wait for the user's response, never assume an answer, never batch questions.

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
- `coverage` -> [Coverage Flow](#coverage-flow)

---

## Scout Flow

Analyze the codebase to identify coverage gaps, untested critical paths, high-complexity functions without tests, and recently changed files lacking test updates. When vector memory is available, perform semantic gap analysis to discover high-risk untested code paths.

### Scout Step 1: Gather Context

```bash
SH context
TESTS discover --root .
TESTS analyze-gaps --root .
TESTS suggest --root .
```

### Scout Step 2: Semantic Gap Analysis

After structural gap analysis, run semantic search to find high-risk untested code paths (validation, authentication, error handling, payment processing, etc.):

```bash
TESTS semantic-gaps --root .
```

If `vector_memory_available` is `false` in the result, skip this step silently and rely on structural analysis only. If available, merge the `semantic_risks` results into the coverage report (Step 3).

### Scout Step 3: Analyze Recent Changes

```bash
git log --oneline --name-only -20 2>/dev/null | head -60
```

Cross-reference changed source files against test file mappings from `analyze-gaps`. Identify source files that were recently modified but have no corresponding test file or no recent test updates.

### Scout Step 4: Present Coverage Report

Present:

1. **Test Framework** — Detected framework, test command, file pattern.
2. **Coverage Summary** — Total source files, total test files, test-to-source ratio. Per-directory breakdown table (directory, source count, test count, ratio).
3. **Per-File Gap Analysis** — Table of source files with no matching test file. Sorted by complexity (lines, functions) descending. Limit to top 20.
4. **Semantic Risk Analysis** *(if vector memory available)* — Table of high-risk untested code paths from `semantic-gaps`, grouped by risk category (validation, auth, error handling, etc.). Highlight that these are critical paths discovered via semantic search that go beyond structural coverage mapping.
5. **High-Priority Targets** — From `suggest` output: files recommended for testing based on complexity, recent changes, and missing coverage. Include rationale. When semantic risks are available, boost priority for files appearing in both structural gaps and semantic risks.
6. **Recently Changed Without Tests** — Source files changed in last 20 commits that lack test coverage.

### Scout Step 5: GATE — Next Action

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

### Create Step 2b: Discover Test Patterns

Before generating tests, search for existing test files that cover similar domains to replicate established patterns:

```bash
TESTS similar-tests --root . --target <target_file>
```

If `vector_memory_available` is `true` and results are returned:
- Note the **assertion styles** from `patterns.assertion_styles` (e.g., plain assert, unittest methods, expect())
- Note the **mocking strategies** from `patterns.mocking_libraries` (e.g., unittest.mock, pytest-mock)
- Note the **naming conventions** from `patterns.naming_conventions`
- Review the top 2-3 `similar_tests` content previews for structural patterns (setup/teardown, fixtures, parametrized tests)

Use these patterns in Step 4 when generating the test file. If vector memory is not available, proceed using framework defaults and project config.

### Create Step 3: GATE — Test Plan

Present the test plan:
- **Target file** and its role (service, controller, utility, etc.)
- **Test file path** to be created
- **Test cases** — bulleted list of functions/methods to test with brief description of what each test verifies
- **Test framework** and any imports needed
- **Patterns adopted** *(if similar tests were found)* — mention which existing test patterns will be followed (assertion style, mocking approach, naming convention)

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
   - When similar test patterns were discovered in Step 2b, replicate the established assertion styles, mocking strategies, and structural conventions
4. Ensure the file is syntactically valid.

### Create Step 5: Verify

Run the test command to verify the new tests:

```bash
TESTS run --root . --target <test_file>
```

If tests fail, analyze the output and fix issues. Re-run until tests pass or present failures to the user.

### Create Step 6: Reindex

After the test file passes verification, update the vector index so subsequent scout or create runs reflect the new coverage:

```bash
TESTS reindex-test --root . --target <test_file>
```

If reindexing fails or vector memory is unavailable, warn but do not block — this is a best-effort step.

### Create Step 7: Report

Present: test file created (path), number of test cases, pass/fail status, vector index updated (yes/no), and any warnings.

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

## Coverage Flow

Persistent coverage tracking across sessions. Takes snapshots of which source files have tests, detects regressions when source changes without test updates, and gates releases on minimum coverage thresholds.

Coverage manifests are stored in `.claude/coverage/` with timestamped snapshots for trend analysis.

### Coverage Step 1: Determine Sub-command

Parse `remaining_args` from the dispatcher. Expected sub-commands:
- `snapshot` -> [Coverage: Snapshot](#coverage-snapshot)
- `compare` -> [Coverage: Compare](#coverage-compare)
- `report` -> [Coverage: Report](#coverage-report)
- `threshold-check` -> [Coverage: Threshold Check](#coverage-threshold-check)
- *(empty)* -> default to **snapshot** then **report**

### Coverage: Snapshot

Capture the current state of test coverage and persist it.

```bash
TESTS coverage snapshot --root .
```

Present:
- Total source files, test files, covered, uncovered
- Coverage percentage
- Timestamp of snapshot
- Mention that the snapshot is saved for future comparisons

### Coverage: Compare

Compare two snapshots to detect regressions and improvements.

```bash
TESTS coverage list-snapshots --root .
```

If two or more snapshots exist, compare latest two automatically:

```bash
TESTS coverage compare --root .
```

If the user provides specific snapshots via arguments:

```bash
TESTS coverage compare --root . --old <old_snapshot> --new <new_snapshot>
```

Present:
1. **Coverage change** -- percentage point difference
2. **Regressions** -- source files that changed but their tests did not (table)
3. **Improvements** -- new test coverage added since last snapshot
4. **New files** -- source files added since last snapshot (with/without tests)
5. **Removed files** -- source files deleted since last snapshot

### Coverage: Report

Generate a human-readable Markdown report from the current manifest.

```bash
TESTS coverage report --root .
```

If no manifest exists yet, take a snapshot first:

```bash
TESTS coverage snapshot --root .
TESTS coverage report --root .
```

Present the report content directly.

### Coverage: Threshold Check

Verify coverage meets a minimum percentage. Used as a release gate.

```bash
TESTS coverage threshold-check --root . --min-coverage <N>
```

If the user does not specify a threshold, ask:

Use `AskUserQuestion`:
- **"Use default (0%)"** -> run with `--min-coverage 0`
- **"I will specify a minimum"** -> wait for input

STOP.

Present: pass/fail status, actual coverage %, required %, deficit (if any).

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
