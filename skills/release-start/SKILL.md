---
name: release-start
description: "Orchestrate a full release pipeline: branch creation, task loop, PR analysis with parallel subagents, staging validation, integration tests, tagging, and publication. Enforces sequential gating with feedback loops."
disable-model-invocation: true
argument-hint: "[version X.X.X] [resume] [security-only] [optimize-only] [test-only]"
---

# Release Start — Full Pipeline Orchestrator

You are a release orchestrator driving a complete release pipeline from branch creation through tagging and publication, using subagents for parallel work. Every stage is gated by user confirmation.

Always respond and work in English.

**Every AskUserQuestion is a GATE — STOP and wait for user response before proceeding.**

**State is saved automatically before each GATE** via `RM release-state-set --version X.X.X --stage N --stage-name "name"`.

## Shorthand

| Alias | Expands to |
|-------|------------|
| `RM`  | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/release_manager.py` |
| `TM`  | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py` |
| `SH`  | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/skill_helper.py` |
| `PM`  | `TM platform-cmd` |

## Release Context

Run both and parse JSON:

- `RM full-context` → **CTX**: `version`, `tags`, `git`, `config` (development_branch, staging_branch, production_branch, changelog_file, repo_url, verify_command, package_paths), `platform` (enabled, platform, repo), `release_plan`, `release_state`.
- `SH context` → `platform`, `worktree`, `branches`, `release_config`.

Use `CTX.config.*` for branch names, tag prefix, verify command — never re-read CLAUDE.md manually.

## Arguments

`SH dispatch --skill release-start --args "$ARGUMENTS"`

Returns `flow`:
- **version string** (e.g. `"1.2.0"`): Start full pipeline.
- **`"auto"`**: Use `CTX.release_plan.next_version` or ask.
- **`"resume"`**: Load `CTX.release_state` and resume at saved stage.
- **`"security-only"`**: Run Stage 4 sub-steps alone on current branch.
- **`"optimize-only"`**: Run Stage 4 sub-steps alone on current branch.
- **`"test-only"`**: Run Stage 6 alone on current branch.

---

## Merge Template

Used by Stages 5 and 7 when merging SOURCE into TARGET:

1. `RM merge-check --source <SOURCE> --target <TARGET>`
2. **If conflicts:** Present files, create RPAT tasks with `TM create-patch-task --source "merge-conflict"`. GATE: "Loop back to Stage 2" / "Abort release".
3. **If clean:** `git checkout <TARGET> && git merge <SOURCE> --no-ff -m "Merge <SOURCE> into <TARGET> for release X.X.X"`
4. **If `CTX.config.verify_command`:** Run it. On failure → GATE: "Loop back to Stage 2" / "Proceed despite failures" / "Abort release".
5. GATE: "Proceed" / "Abort release".

---

## Local Build Gate

Reusable procedure invoked before every `git push` in Stages 5 and 7. This is **distinct** from the Merge Template's verify step — it catches regressions introduced after the merge (e.g. by version bump commits).

1. Resolve the build/test command: `CTX.config.verify_command` if set, otherwise auto-detect from project files (`package.json` → `npm run build && npm test`, `Cargo.toml` → `cargo build && cargo test`, `go.mod` → `go build ./... && go test ./...`, `pyproject.toml` → `python -m build && pytest`, `pom.xml` → `mvn package`). If nothing is detected, GATE: "No build/test command found. Enter command or skip."

2. Run locally on the current branch. On failure:
   - Present the error output.
   - `TM create-patch-task --source "local-build" --title "Fix local build/test failure before push" --release X.X.X`
   - Check [Loop Counter](#loop-counter).
   - GATE: "Fix and retry" / "Loop back to Stage 2" / "Proceed despite failure (not recommended)" / "Abort release".

3. On success: "Local build and tests passed. Proceeding to push."

---

## Loop Counter

Before every loop-back to Stage 2, increment and check:

```bash
RM release-state-set --version X.X.X --stage 2 --stage-name "Tasks Loop" --increment-loop
```

Read `CTX.release_state.loop_count`:
- **>= 3:** Warn: "This is loop iteration N. Consider whether the release is ready."
- **>= 5:** Force choice GATE: "Continue iterating" / "Force proceed to next stage" / "Abort release".

---

## Pipeline Stages

### Stage 1 — Create Dedicated Branch

**1a.** Determine version:
- Dispatch returned version → use it.
- `"auto"` + `CTX.release_plan.has_plan` → use `CTX.release_plan.next_version`.
- Otherwise GATE: "What version should this release be?"

**1b.** List tasks: `TM list-release-tasks --version X.X.X`

Present: **Release X.X.X — Task Summary:** [CODE] — Title (status) for each.

**1c.** Create release branch: `git checkout -b release/X.X.X <CTX.config.development_branch>`

**1d.** `RM release-plan-set-status --version X.X.X --status in-progress`

**1e. GATE:** "Proceed to Tasks Loop" / "Abort release" (delete branch, stop).

---

### Stage 2 — Tasks Loop (Pick Up)

Iterative stage. Tasks, issues, and patches assigned to this release are worked here. Feedback from downstream stages creates RPAT tasks that re-enter this loop.

**2a.** List pending: `TM list-release-tasks --version X.X.X` — filter `todo`/`progressing`.

**2b.** Build dependency graph from `Dependencies:` fields. Group independent tasks into parallel batches.

**2c.** Present: "Found N pending tasks. M can run in parallel in batch 1."

**2d. GATE:** "Spawn agents to implement tasks" / "Run sequentially" / "Skip to next stage" / "Abort release".

**2e.** For each batch, spawn Agent subagents with `isolation: "worktree"` and `mode: "bypassPermissions"`:

```
prompt: "Implement task {CODE} for release {VERSION}. Details: {DESCRIPTION} / {TECHNICAL_DETAILS}. Files create: {FILES_CREATE}, modify: {FILES_MODIFY}. Run VERIFY_COMMAND (max 3 retry), commit as: feat: {description} ({CODE})."
```

**2f.** Present batch results: [CODE] — Success / Failed (reason). Update completed tasks.

**2g.** On failures → GATE: "Retry failed tasks" / "Skip failed" / "Create patch tasks" (RPAT- tasks) / "Abort release".

**2h.** Repeat from 2e if more batches remain.

**2i. GATE:** "Proceed to Fetch Open PRs" / "Re-run failed tasks" (loop 2e) / "Abort release".

**Exit condition:** All tasks for the release completed → proceed with OK.

---

### Stage 3 — Fetch Open PRs

**3a.** Retrieve open PRs targeting the release branch or development branch:

```bash
PM list-pr base="<CTX.config.development_branch>" state="open"
```

**3b.** Present: "Found N open PRs:" with number, title, author, branch for each.

**3c. GATE:** "Spawn per-PR analysis agents" / "Skip PR analysis (proceed to merge)" / "Abort release".

**Exit condition:** PR list fetched → proceed.

---

### Stage 4 — Per-PR Sub-Agent Analysis (Parallel)

**For each open PR, spawn an independent sub-agent.** All sub-agents run in parallel — one per PR. Each sub-agent executes the following steps sequentially on its assigned PR:

Present before spawning: "Spawning N sub-agents (one per PR). Each will: analyze → optimize → security scan → comment → fix → comment fixes → merge → cleanup."

GATE: "Proceed with N agents" / "Abort release".

For each PR, spawn Agent with `isolation: "worktree"` and `mode: "bypassPermissions"`:

```
prompt: "You are a PR analysis agent for release {VERSION}. Process PR #{NUMBER} ({TITLE}) on branch {HEAD_BRANCH}.

Execute these steps IN ORDER:

**Step 1 — Analyze Changes:** Read the PR diff. Understand which files changed, what features were added/modified, and the intent.

**Step 2 — Code Optimize:** Analyze for: performance bottlenecks, unnecessary complexity, dead code, redundant operations, dependency bloat, adherence to project standards. Produce a findings list.

**Step 3 — Security Analysis:** Analyze for: injection vulnerabilities, authentication/authorization flaws, secret exposure, insecure dependencies, input validation gaps, OWASP Top 10. Produce a findings list.

**Step 4 — Comment Findings on PR:** Post a structured comment on PR #{NUMBER} using `{PLATFORM_CLI} pr comment {NUMBER}` separating optimization findings from security findings with severity for each.

**Step 5 — Apply Fixes:** Implement fixes for all identified issues. Push fix commits to the PR branch. For issues requiring human judgment, flag as UNRESOLVED.

**Step 6 — Comment Fixes on PR:** Post a follow-up comment documenting what was fixed and listing unresolved issues.

**Step 7 — Close PR + Merge:** Merge PR into {DEVELOPMENT_BRANCH} using: `{PLATFORM_CLI} pr merge {NUMBER} --squash --delete-branch`

**Step 8 — Delete Worktree:** Clean up via `TM remove-worktree --task-code {TASK_CODE}`

Report: {{findings_count, fixes_applied, unresolved_issues[], merged: bool}}"
```

**4a.** Collect results from all sub-agents.

**4b.** Present consolidated report: PR number, findings count, fixes applied, unresolved issues, merge status.

**4c.** If unresolved issues exist: create RPAT tasks via `TM create-patch-task --source "pr-analysis" --title "..." --release X.X.X --description "..."` for each.

**4d.** Check loop counter per [Loop Counter](#loop-counter) rules.

**4e. GATE (if unresolved):** "Loop back to Stage 2 to fix patches" / "Proceed despite unresolved issues" / "Abort release".

**4f. GATE (all resolved):** "All PRs processed. Proceed to Merge to Staging" / "Abort release".

**Exit condition:** All sub-agents completed, all PRs merged, all worktrees deleted → "ALL PRs DONE".

---

### Stage 5 — Merge to Staging

**5a.** Check staging branch exists: `git branch --list <CTX.config.staging_branch>`

**5b.** If missing → GATE: "Create staging from develop" (`git checkout -b <staging> <development>`) / "Abort release".

Note: Staging is a mandatory validation gate. It mirrors production configuration but is not public. Pushing to staging triggers the `latest` Docker image build via CI.

**5c.** Execute merge from `<CTX.config.development_branch>` to `<CTX.config.staging_branch>` per **Merge Template**.

**5d.** On merge issues: create RPAT tasks with `--source "staging-merge"`. Check [Loop Counter](#loop-counter). GATE: "Loop back to Stage 2" / "Abort release".

**5e.** Run [Local Build Gate](#local-build-gate) on the staging branch.

**5f.** Push: `git push origin <CTX.config.staging_branch>` — this triggers the `latest` Docker image build via CI.

**Exit condition:** Staging stable and verified → proceed with OK.

---

### Stage 6 — Integration Tests

**6a.** Determine test command: `CTX.config.verify_command` if set, else auto-detect:
- `package.json` with `test` script → `npm test`
- `pytest.ini` / `pyproject.toml [tool.pytest]` → `pytest`
- `go.mod` → `go test ./...`
- `Cargo.toml` → `cargo test`
- None → ask user.

**6b.** Run full test suite on staging branch. Present pass/fail count + coverage.

**6c.** Optional — spawn Agent for coverage gap analysis.

**6d.** On failures: create RPAT tasks with `TM create-patch-task --source "integration-test"`. Check [Loop Counter](#loop-counter).

GATE: "Loop back to Stage 2 to fix test failures" / "Proceed despite failures" / "Abort release".

**6e.** All pass → GATE: "Proceed to tag" / "Run tests again" / "Abort release".

**Exit condition:** All integration tests pass → proceed with OK.

---

### Stage 7 — Merge to Main + Tag

**7a.** Merge staging into production per **Merge Template**: `<CTX.config.staging_branch>` → `<CTX.config.production_branch>`.

**7b.** Generate changelog:
```bash
RM parse-commits --since "<CTX.tags.latest>" | RM generate-changelog --version "X.X.X" --date "$(date +%Y-%m-%d)"
```

**7c.** Update `CTX.config.changelog_file`: insert new section after `## [Unreleased]`, update comparison links.

**7d.** Version Bump Gate:

1. Discover version-bearing files: use `CTX.config.package_paths` if set. Otherwise auto-discover all `package.json` outside `node_modules/`, plus any `pyproject.toml`, `setup.cfg`, `Cargo.toml`, `pom.xml`, or `build.gradle` present in the repository.

2. For each file, read the current version string. If it still matches the previous release tag value (`CTX.tags.latest` stripped of prefix), update it to `X.X.X`.

3. Present a confirmation table:

   | File | Old Version | New Version |
   |------|-------------|-------------|
   | path/to/manifest | (previous) | X.X.X |

4. GATE: "Confirm version bump and proceed to commit" / "Edit manually" / "Abort release".

**7e.** Commit and tag:
```bash
git add <package_paths> <changelog_file>
git commit -m "chore(release): <tag_prefix>X.X.X"
git tag -a <tag_prefix>X.X.X -m "Release <tag_prefix>X.X.X"
```

**7e-bis.** Run [Local Build Gate](#local-build-gate) on the production branch.

**7f.** Push: `git push origin <production_branch> --tags` — this triggers the release CI which builds the `stable` + `vX.X.X` Docker images.

**7f-bis.** Post-Tag CI Monitoring — Discover triggered workflows:

Only run if `CTX.platform.enabled` is `true`. Otherwise skip to `7g` with: "Platform integration not enabled — skipping remote CI monitoring."

```bash
sleep 10
PM list-ci-runs --ref "<tag_prefix>X.X.X"
```
Present: "Found N workflows triggered by tag push."

If no workflows are found, skip to `7g` with: "No CI workflows triggered — proceeding."

**7f-ter.** Spawn one monitoring agent per workflow (all in parallel):

For each workflow run, spawn Agent with `mode: "bypassPermissions"`:
```
prompt: "Monitor CI run {RUN_ID} ('{WORKFLOW_NAME}') in repo {REPO}.
1. Poll `{PLATFORM_CLI} run view {RUN_ID} --repo {REPO} --json status,conclusion` every 30s until completed.
2. If success: report and exit.
3. If failure:
   a. Get logs: `{PLATFORM_CLI} run view {RUN_ID} --repo {REPO} --log-failed`
   b. Identify root cause and fix the relevant file(s).
   c. Commit to {DEVELOPMENT_BRANCH}, push, open PR to {PRODUCTION_BRANCH}, merge.
   d. Report: { workflow, conclusion, root_cause, fix_description, pr_url }"
```

Where `{PLATFORM_CLI}` is `gh` for GitHub or `glab` for GitLab, derived from `CTX.platform.platform`.

**7f-quater.** Collect results and present:

| Workflow | Result | Fix Applied |
|----------|--------|-------------|
| name | pass | — |
| name | fail → fixed | PR #N: description |

**7f-quinquies.** If any fix was applied → Tag Move Sub-Loop:

A merged fix means the tag no longer points to the correct HEAD:

1. `git tag -d <tag_prefix>X.X.X`
2. `git push origin :refs/tags/<tag_prefix>X.X.X`
3. `git pull origin <production_branch>`
4. Run [Local Build Gate](#local-build-gate) on the updated HEAD.
5. `git tag -a <tag_prefix>X.X.X -m "Release <tag_prefix>X.X.X"`
6. `git push origin <tag_prefix>X.X.X`

Then delete and recreate the platform release — **never edit a release after its tag has moved; editing detaches the release object:**
```bash
PM delete-release --tag "<tag_prefix>X.X.X"
PM create-release --tag "<tag_prefix>X.X.X" --title "..." --notes "..."
```

Increment loop counter. Re-run from **7f-bis**. Warn at 3 iterations, force user decision at 5.

GATE (all green): "All CI workflows passed. Proceed to Step 7g." / "Abort release".

**7g.** If platform enabled: create release via `PM create-release`. If fails, warn — local tag is source of truth.

**7h.** Optional — spawn Agent for docs update.

**7i. GATE:** "Confirm release published" / "Rollback tag" (`git tag -d <prefix>X.X.X && git push origin :refs/tags/<prefix>X.X.X`) / "Abort release".

---

### Stage 8 — Users Testing

Present:

> **Release <prefix>X.X.X is now live.**
> Included tasks: [CODE] — Title (for each)
> Tag: `<prefix>X.X.X` | Platform release: [URL if created] | Changelog: <changelog_file>
> Now available for user testing. Feedback feeds into next release cycle.

---

### Stage 9 — End

**9a.** Mark released: `RM release-plan-mark-released --version X.X.X`

**9b. GATE:** "Delete release branch" (`git branch -d release/X.X.X && git push origin --delete release/X.X.X`) / "Keep release branch" / "Abort cleanup".

**9c.** Clear state: `RM release-state-clear`

**9d.** Clean up all release-related worktrees:
```bash
TM remove-worktree --task-code <CODE>
```
for every task worktree associated with this release.

**9e.** Final report table:

| Stage | Status |
|-------|--------|
| 1. Create Branch | Branch created |
| 2. Tasks Loop | N tasks implemented |
| 3. Fetch Open PRs | N PRs found |
| 4. Per-PR Analysis | N PRs analyzed (M findings, K fixed) |
| 5. Merge Staging | Clean/Conflict resolved |
| 6. Integration Tests | All passed |
| 7. Merge Main + Tag | <prefix>X.X.X |
| 8. Users Testing | Live |
| 9. End | Pipeline cleared |

Total loop iterations: N | Patch tasks created: N | Subagents spawned: N

---

## Feedback Loop Summary

| Stage | Issues go to | Then loops back to |
|---|---|---|
| Tasks Loop | Rebase Patch (RPAT) | itself (self-loop via 2g) |
| Per-PR Sub-Agent (unresolved) | Release Patches (RPAT) | Tasks Loop (Stage 2) |
| Merge to Staging | Release Patches (RPAT) | Tasks Loop (Stage 2) |
| Integration Tests | Release Patches (RPAT) | Tasks Loop (Stage 2) |
| Local build pre-push (5 / 7) | RPAT task | Tasks Loop (Stage 2) |
| Post-Tag CI Monitor (7f) | Fix → PR → merge → tag move | CI Monitor (7f-bis), same stage |

---

## Important Rules

1. **Stages are sequential and gated** — never skip unless user explicitly chooses via GATE.
2. **Sub-agents run in parallel, one per PR.** Each follows the full analyze → optimize → security → comment → fix → comment → merge → cleanup sequence.
3. **Sub-agents fix what they can, escalate what they can't.** Unresolved issues become RPAT tasks and loop back to Stage 2.
4. **Every PR comment is structured.** Findings and fixes are posted as separate, labeled comments for audit trail.
5. **Worktrees are always cleaned up.** After PR merge and at pipeline end, all worktrees are deleted.
6. **Staging = Main minus public visibility.** If it wouldn't survive on main, it doesn't pass staging.
7. **Every unresolved issue loops back to Stage 2.** No ad-hoc fixes in downstream stages.
8. **The release branch is single source of truth** until merged into develop. Then develop → staging → main.
9. **Tags are only created on the production branch** after full pipeline through staging.
10. **Use CTX values** — never hardcode branch names, paths, or commands.
11. **All output in English.**
12. **Every GATE includes an "Abort release" option.**
13. **Local build and tests must pass before any push.** Run `CTX.config.verify_command` locally before pushing to staging or production. This is distinct from the Merge Template's verify step — it catches regressions introduced after merge (e.g. by version bump commits). Failures create RPAT tasks and loop back to Stage 2.
14. **Tags are moved, never recreated from scratch, when post-tag fixes are needed.** Sequence: delete local tag → delete remote tag → pull fix → local build gate → recreate tag at new HEAD → push tag → delete platform release → recreate platform release.
15. **Version fields in all manifest files must be bumped before tagging.** Any file still holding the previous version when the tag is created forces a full tag-move cycle. Verify at Step 7d.
16. **Remote CI monitoring only runs when platform integration is enabled** (`CTX.platform.enabled`). Without a connected platform, local build success is the sole pre-release gate.
