---
name: update
description: Update CTDF-managed files (pipelines, scripts, prompts, skills, CLAUDE.md) to the latest plugin version. Detects outdated files and preserves user customizations.
disable-model-invocation: true
argument-hint: "[all | pipelines | agentic | scripts | prompts | skills | claude-md]"
---

# Update CTDF-Managed Files

You are an update assistant for the CTDF plugin. Detect which CTDF-managed files are outdated, show a summary, and selectively update them while preserving user customizations.

**Interaction rule (applies throughout):** At each `AskUserQuestion` call, STOP completely. Wait for the user's actual response before proceeding. Never assume answers, never batch questions, only use the exact options specified.

## Shorthand

| Alias | Expands to |
|-------|------------|
| `SH`  | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/skill_helper.py` |

## Step 1: Gather Context and Dispatch

```bash
SH context
```

Use the `platform.platform` field (`github` or `gitlab`). If no config exists, infer from `.github/` (github) or `.gitlab-ci.yml` (gitlab). Default to `github`.

```bash
SH dispatch --skill update --args "$ARGUMENTS"
```

The `flow` field determines scope: `all`, `pipelines`, `agentic`, `scripts`, `prompts`, `skills`, or `claude-md`.

## Step 2: Read Plugin Version

```bash
python3 -c "import json; print(json.load(open('${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json'))['version'])"
```

Display this as the source version in the summary.

## CTDF-Managed File Manifest

All source paths are relative to `${CLAUDE_PLUGIN_ROOT}/`.

**Core Pipelines (GitHub):** `templates/github/workflows/` ci.yml, release.yml, security.yml, issue-triage.yml, status-guard.yml, staging-merge.yml → `.github/workflows/`; `templates/github/CODEOWNERS` → `.github/CODEOWNERS`
**Core Pipelines (GitLab):** `templates/gitlab/` .gitlab-ci.yml, staging-merge.gitlab-ci.yml → project root
**Agentic Pipelines (GitHub):** `templates/github/workflows/` agentic-fleet.yml, agentic-task.yml, agentic-docs.yml → `.github/workflows/`
**Agentic Pipelines (GitLab):** `templates/gitlab/` agentic-fleet.gitlab-ci.yml, agentic-task.gitlab-ci.yml, agentic-docs.gitlab-ci.yml → project root
**Scripts:** `scripts/` memory_builder.py, codebase_analyzer.py, agent_runner.py → `.claude/scripts/`
**Prompts:** `templates/prompts/` agentic-task-prompt.md, agentic-docs-prompt.md → `.claude/prompts/`
**Skills:** `skills/` idea-scout/SKILL.md, docs/SKILL.md → `.claude/skills/`
**CLAUDE.md:** The `<!-- CTDF:START -->` to `<!-- CTDF:END -->` section. Canonical content is in `${CLAUDE_PLUGIN_ROOT}/skills/setup/SKILL.md`.

### Customizable Files

| File | Custom Value | Handling |
|------|-------------|----------|
| `agentic-task.yml` (GitHub) | `cron:` schedule | Extract before update, re-inject after |
| `ci.yml` (GitHub) / `.gitlab-ci.yml` (GitLab) | CI runtime steps | Warn — mark as "customized" |
| `CODEOWNERS` | Team names/paths | Warn — mark as "customized" |
| `CLAUDE.md` | Everything outside markers | Only replace between CTDF markers |

## Step 3: Scan and Compare Files

Filter pipeline categories by detected platform. For each file in scope, compare SHA-256 hashes:

```bash
python3 -c "
import hashlib; from pathlib import Path
pairs = [
    # ('source', 'target', 'name') — populate from manifest based on scope/platform
]
for s, t, n in pairs:
    sp, tp = Path(s), Path(t)
    if not tp.exists(): print(f'{n}|not_installed|'); continue
    if not sp.exists(): print(f'{n}|source_missing|'); continue
    sh = hashlib.sha256(sp.read_bytes()).hexdigest()
    th = hashlib.sha256(tp.read_bytes()).hexdigest()
    print(f'{n}|{\"current\" if sh == th else \"outdated\"}|')
"
```

**Override statuses for customizable files:**
- `ci.yml` (GitHub), `.gitlab-ci.yml` (GitLab), `CODEOWNERS`: if `outdated`, change to `customized`
- `agentic-task.yml`: keep `outdated` but flag for cron preservation

**For CLAUDE.md:**

```bash
python3 -c "
import re, hashlib; from pathlib import Path
p = Path('CLAUDE.md')
if not p.exists(): print('CLAUDE.md|not_installed|'); exit(0)
lm = re.search(r'<!-- CTDF:START -->(.+?)<!-- CTDF:END -->', p.read_text(), re.DOTALL)
if not lm: print('CLAUDE.md (CTDF section)|not_installed|'); exit(0)
setup = Path('${CLAUDE_PLUGIN_ROOT}/skills/setup/SKILL.md').read_text()
tm = re.search(r'<!-- CTDF:START -->(.+?)<!-- CTDF:END -->', setup, re.DOTALL)
if not tm: print('CLAUDE.md (CTDF section)|source_missing|'); exit(0)
lh = hashlib.sha256(lm.group(0).encode()).hexdigest()
th = hashlib.sha256(tm.group(0).encode()).hexdigest()
print(f'CLAUDE.md (CTDF section)|{\"current\" if lh == th else \"outdated\"}|')
"
```

## Step 4: Present Summary

Display results as a categorized table (only categories with installed files). Present results using the report format from Step 7, but with a **Status** column (Current / Outdated / Customized / Not installed) instead of an Action column.

**If all files are current**, report everything is up to date and stop.

**If `$ARGUMENTS` specifies a category**, skip Step 5 and go directly to Step 6 to update all outdated files in that category. Still warn about customized files.

## Step 5: User Choice

Use `AskUserQuestion` with these options:
- **"Update all outdated files"** — only files with status "outdated" (safe updates)
- **"Update all including customized (preserving custom values)"** — update everything that differs, preserving known custom values
- **"Choose by category"** — follow up with per-category selection
- **"Cancel"** — abort

**If "Choose by category"**, present a second `AskUserQuestion` listing each category with outdated/customized files, plus "All listed" and "Cancel".

## Step 6: Execute Updates

Three update strategies. Apply per file type:

| Strategy | Files | Method |
|----------|-------|--------|
| **Direct copy** | Scripts, prompts, skills, most workflows | `cp source target` |
| **Cron-preserve** | `agentic-task.yml` (GitHub) | Extract cron → copy template → re-inject cron |
| **CTDF-section** | `CLAUDE.md` | Regex replace between `<!-- CTDF:START -->` / `<!-- CTDF:END -->` markers |

**Cron-preserve implementation:**
```bash
python3 -c "
import re; from pathlib import Path
p = Path('.github/workflows/agentic-task.yml')
m = re.search(r\"cron:\s*'([^']+)'\", p.read_text())
cron = m.group(1) if m else '0 */6 * * *'
tmpl = Path('${CLAUDE_PLUGIN_ROOT}/templates/github/workflows/agentic-task.yml').read_text()
p.write_text(tmpl.replace(\"cron: '0 */6 * * *'\", f\"cron: '{cron}'\"))
print(f'Updated with cron: {cron}')
"
```

**CTDF-section implementation:**
```bash
python3 -c "
import re; from pathlib import Path
setup = Path('${CLAUDE_PLUGIN_ROOT}/skills/setup/SKILL.md').read_text()
tm = re.search(r'(<!-- CTDF:START -->.*?<!-- CTDF:END -->)', setup, re.DOTALL)
if not tm: print('ERROR: No CTDF section in setup template'); exit(1)
p = Path('CLAUDE.md')
p.write_text(re.sub(r'<!-- CTDF:START -->.*?<!-- CTDF:END -->', tm.group(1), p.read_text(), flags=re.DOTALL))
print('CLAUDE.md CTDF section updated')
"
```

**Customized files** (`ci.yml`, `CODEOWNERS`, `.gitlab-ci.yml`): Before updating, warn that user customizations will be overwritten and will need to be re-applied. Then direct-copy.

## Step 7: Verify and Report

Verify each updated file exists and is non-empty. For `agentic-task.yml`, verify cron expression is present. For `CLAUDE.md`, verify both CTDF markers are intact.

```
## CTDF Update Complete

**Plugin version:** [version]

### Files Updated
| File | Action |
|------|--------|
| [file path] | Updated to latest template |
| .github/workflows/agentic-task.yml | Updated (cron preserved: [cron]) |
| CLAUDE.md | CTDF section updated |

### Files Skipped
| File | Reason |
|------|--------|
| [file path] | Already current |

### Not Installed
These files are available but were never deployed:
| File | Install With |
|------|-------------|
| [file path] | `/setup` or `/setup agentic-fleet` |

### Next Steps
1. Review the changes: `git diff`
2. Commit the updates
3. Push to apply updated pipelines
```

---

## Important Rules

1. **Never create uninstalled files** — only update existing files. For new installations, suggest `/setup` or `/setup agentic-fleet`.
2. **Preserve cron expressions** in `agentic-task.yml` (GitHub) during updates.
3. **Only touch the CTDF:START/END section** in CLAUDE.md — never modify content outside those markers.
4. **Warn before overwriting customized files** (`ci.yml`, `CODEOWNERS`, `.gitlab-ci.yml`) — user must re-apply project-specific changes after update.
