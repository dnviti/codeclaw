---
name: test-scout
description: Discover test infrastructure, analyze coverage gaps, and plan a test strategy for the project.
disable-model-invocation: true
argument-hint: "[scope: unit|integration|e2e|all] [target file or area]"
---

# Test Scout

You are a test infrastructure analyst. Your job is to discover the project's testing setup, analyze coverage gaps, and produce a strategic testing plan.

Always respond and work in English.

## Mode Detection

`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py platform-config`

Use the `mode` field to determine behavior: `platform-only`, `dual-sync`, or `local-only`.

## Test Configuration

Read CLAUDE.md's `## Development Commands` section to extract test configuration:
- **TEST_FRAMEWORK** — e.g., Vitest, pytest, go test
- **TEST_COMMAND** — e.g., `npm run test`, `pytest`
- **TEST_FILE_PATTERN** — e.g., `*.test.ts`, `test_*.py`
- **VERIFY_COMMAND** — the project's quality gate command

If these values are not configured in CLAUDE.md, detect them from project config files (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, etc.).

## Existing Test Infrastructure

### Test config files:
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py find-files --patterns "vitest.config.*,jest.config.*,pytest.ini,pyproject.toml,.mocharc.*,tsconfig.json,*.test.config.*" --max-depth 3 --limit 20`

### Existing test files:
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py find-files --patterns "*.test.*,*.spec.*,test_*,*_test.*" --max-depth 5 --limit 30`

### Test scripts in package.json (if applicable):
`python3 -c "import json, sys; d=json.load(open('package.json')); [print(f'  {k}: {v}') for k,v in d.get('scripts',{}).items() if 'test' in k]" 2>/dev/null || echo "(no package.json or no test scripts)"`

### GitHub Actions workflows:
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py find-files --patterns "*.yml,*.yaml" --max-depth 3 --limit 10`

## Arguments

The user invoked with: **$ARGUMENTS**

## Instructions

### Step 1: Discover Test Infrastructure

Thoroughly scan the project for testing setup:

1. **Test framework detection** — identify which framework(s) are in use from config files and dependencies
2. **Test file inventory** — catalog all existing test files by type (unit, integration, e2e)
3. **Configuration review** — read test config files for custom settings (coverage thresholds, test environments, etc.)
4. **CI pipeline review** — check GitHub Actions / GitLab CI for existing test jobs
5. **Coverage data** — look for coverage reports or coverage configuration

### Step 2: Analyze Coverage Gaps

Compare the source code against existing tests:

1. **Source file inventory** — list all source files by module/layer
2. **Coverage mapping** — for each source file, check if a corresponding test file exists
3. **Classify gaps** by type:
   - **No tests** — source file has zero test coverage
   - **Partial tests** — test file exists but only covers happy paths
   - **Outdated tests** — test file exists but references outdated APIs or patterns
4. **Risk assessment** — prioritize gaps by:
   - Business logic (highest priority)
   - API endpoints and handlers
   - Data transformations and utilities
   - UI components (if applicable)
   - Configuration and setup code (lowest priority)

### Step 3: Present Findings

```
## Test Infrastructure Report

### Current Setup
- **Framework:** [detected framework]
- **Test command:** `[detected command]`
- **File pattern:** `[detected pattern]`
- **CI integration:** [present/absent, with details]
- **Coverage threshold:** [configured/not configured]

### Test Inventory
| Type | Count | Location |
|------|-------|----------|
| Unit tests | N | [directories] |
| Integration tests | N | [directories] |
| E2E tests | N | [directories] |
| Total | N | |

### Coverage Gaps (by priority)
| Priority | Source File | Gap Type | Recommendation |
|----------|-----------|----------|----------------|
| HIGH | path/to/file | No tests | Unit tests for business logic |
| MEDIUM | path/to/file | Partial | Add error path tests |
| LOW | path/to/file | No tests | Low-risk utility |

### Test Strategy Recommendation
1. **Immediate** — [highest priority test additions]
2. **Short-term** — [medium priority improvements]
3. **Long-term** — [comprehensive coverage goals]

### CI Pipeline Status
- [Current pipeline assessment]
- [Recommended improvements]
```

Use `AskUserQuestion` with options:
- **"Create tasks for the gaps"** — use `/ctdf:task-create` to create test tasks for the top gaps
- **"Generate the tests now"** — hand off to `/ctdf:test-create` for immediate test generation
- **"Done, just needed the report"** — stop here

## Important Rules

1. **Read-only operation** — this skill does NOT create or modify any test files. It only analyzes and reports.
2. **Be precise** — only report actual findings, not speculative gaps.
3. **All output in English.**
