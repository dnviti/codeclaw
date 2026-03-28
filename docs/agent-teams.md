# Agent Teams Mode (Claude Code Experimental)

Agent Teams is an experimental feature available in Claude Code when `$CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` is `"1"`. It provides coordinated multi-agent execution with dedicated quality and security reviewers.

## Detection

At each parallel execution point, check `$CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`:
- `"1"` -> **Agent Teams mode** (team composition specified per skill)
- Otherwise -> **Standard subagent mode** (default)

## Team Lifecycle

1. `TeamCreate` with descriptive `team_name` and `description`
2. `TaskCreate` for each unit of work (implementation, review, security scan)
3. `Agent` with `team_name` and `name` -- spawn teammates
4. Teammates claim tasks via `TaskUpdate`, communicate via `SendMessage`, complete via `TaskUpdate`
5. `SendMessage` with `{type: "shutdown_request"}` to all teammates
6. `TeamDelete` to clean up

## Standard Team Roles -- Implementation

Used by `/task pick all`, `/task continue all`, and `/crazy` for task implementation batches:

| Role | Purpose | Config |
|------|---------|--------|
| `backend-dev-{CODE}` | Server-side logic, API, data layer. Messages `frontend-dev` when done | `mode: "bypassPermissions"` |
| `frontend-dev-{CODE}` | UI, client-side, animations. Waits for `backend-dev` message before finalizing | `mode: "bypassPermissions"` |
| `qa-agent` | Reviews implementation, tests functionality, sends bugs back to devs for another pass | `mode: "bypassPermissions"` |
| `documenter` | Updates documentation while implementation is in progress | `mode: "bypassPermissions"` |
| `security-scanner` | Strict security testing, forces devs to fix critical issues before continuing | `mode: "bypassPermissions"` |

## Standard Team Roles -- Other Flows

| Role | Purpose | Config |
|------|---------|--------|
| `pr-analyst-{N}` | Analyzes a PR in release pipeline | `mode: "bypassPermissions"` |
| `security-auditor` | Cross-PR security validation | `mode: "bypassPermissions"` |
| `ci-monitor-{N}` | Monitors a CI workflow run | `mode: "bypassPermissions"` |
| `task-creator-{N}` | Converts an idea into a task spec | `mode: "bypassPermissions"` |
| `consistency-reviewer` | Reviews task specs for consistency | `mode: "bypassPermissions"` |

## Implementation Coordination Flow

1. **Backend dev** implements server-side logic for the task
2. When done -> `SendMessage` to frontend dev with API contracts and integration points
3. **Frontend dev** implements UI/client-side using backend APIs
4. **Documenter** works in parallel throughout, updating docs as code lands
5. **Security scanner** reviews changes from both devs; critical issues -> devs must fix before continuing
6. **QA agent** reviews final implementation from both devs, tests functionality; bugs -> sent back to responsible dev
7. QA + security approve -> task marked done

## Quality & Security Guarantees

Every implementation batch in Agent Teams mode includes:
- **QA agent** -- validates correctness, tests functionality, catches regressions, sends bugs back
- **Security scanner** -- validates OWASP Top 10, secrets, injection, auth, input validation, quality gate; blocks on critical
- **Documenter** -- ensures docs stay current with implementation
- QA + security must both approve before tasks complete
- Critical findings block completion and escalate to team lead

## Rules

1. **Always use Agent Teams** for any task when the feature is enabled. This is the default, not an option.
2. **Agents must commit and push** before `TeamDelete` -- uncommitted changes are lost forever.
3. **One task per agent.** Keep responsibilities focused and clear.
4. **Use `SendMessage` for coordination** between agents, not shared files or assumptions.
5. **QA and security agents are gate-keepers** -- their approval is required before closing a task.
