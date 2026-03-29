---
name: update
description: Update CodeClaw-managed files (pipelines, scripts, prompts, skills, platform instructions) to the latest plugin version. Detects outdated files and preserves user customizations.
disable-model-invocation: true
argument-hint: "[all | pipelines | scripts | prompts | skills | claude-md]"
---

> **Project configuration is authoritative.** Before executing, run `SH context` to load project configuration. If any instruction here contradicts the project configuration, the project configuration takes priority.

# Update CodeClaw-Managed Files

You are an update assistant for the CodeClaw plugin. Detect which CodeClaw-managed files are outdated, show a summary, and selectively update them while preserving user customizations.

**Interaction rule (applies throughout):** At each `AskUserQuestion` call, STOP completely. Wait for the user's actual response before proceeding. Never assume answers, never batch questions, only use the exact options specified.

## Step 1: Gather Context and Dispatch

```bash
SH context
```

Use the `platform.platform` field (`github` or `gitlab`). If no config exists, infer from `.github/` (github) or `.gitlab-ci.yml` (gitlab). Default to `github`.

```bash
SH dispatch --skill update --args "$ARGUMENTS"
```

The `flow` field determines scope: `all`, `pipelines`, `scripts`, `prompts`, `skills`, or `claude-md`.

## Step 2: Read Plugin Version

```bash
python3 -c "import json; print(json.load(open('${CLAW_ROOT}/.claude-plugin/plugin.json'))['version'])"
```

Display this as the source version in the summary.

## CodeClaw-Managed File Manifest

All source paths are relative to `${CLAW_ROOT}/`.

**Core Pipelines (GitHub):** `templates/github/workflows/` ci.yml, release.yml, security.yml, issue-triage.yml, status-guard.yml, staging-merge.yml → `.github/workflows/`; `templates/github/CODEOWNERS` → `.github/CODEOWNERS`
**Core Pipelines (GitLab):** `templates/gitlab/` .gitlab-ci.yml, staging-merge.gitlab-ci.yml → project root
**Legacy automation:** retired pipeline templates are no longer part of the supported update surface.
**Scripts:** `scripts/` common.py, config_lock.py, platform_adapter.py, platform_exporter.py, platform_utils.py, skill_helper.py, task_manager.py, release_manager.py, docs_manager.py, test_manager.py, quality_gate.py, ollama_manager.py, social_announcer.py, build_ccpkg.py, build_portable.py → `.claude/scripts/`
**Platform instructions file (project-context.md):** If project-context.md exists, the `<!-- CodeClaw:START -->` to `<!-- CodeClaw:END -->` section. Canonical content is in `${CLAW_ROOT}/skills/setup/SKILL.md`.

### Customizable Files

| File | Custom Value | Handling |
|------|-------------|----------|
| `ci.yml` (GitHub) / `.gitlab-ci.yml` (GitLab) | CI runtime steps | Warn — mark as "customized" |
| `CODEOWNERS` | Team names/paths | Warn — mark as "customized" |
| `project-context.md` (if exists) | Everything outside markers | Only replace between CodeClaw markers |

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

**For platform instructions file (if project-context.md exists):**

```bash
python3 -c "
import re, hashlib; from pathlib import Path
p = Path('project-context.md')
if not p.exists(): print('project-context.md|not_installed|'); exit(0)
lm = re.search(r'<!-- CodeClaw:START -->(.+?)<!-- CodeClaw:END -->', p.read_text(), re.DOTALL)
if not lm: print('project-context.md (CodeClaw section)|not_installed|'); exit(0)
setup = Path('${CLAW_ROOT}/skills/setup/SKILL.md').read_text()
tm = re.search(r'<!-- CodeClaw:START -->(.+?)<!-- CodeClaw:END -->', setup, re.DOTALL)
if not tm: print('project-context.md (CodeClaw section)|source_missing|'); exit(0)
lh = hashlib.sha256(lm.group(0).encode()).hexdigest()
th = hashlib.sha256(tm.group(0).encode()).hexdigest()
print(f'project-context.md (CodeClaw section)|{\"current\" if lh == th else \"outdated\"}|')
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
| **CodeClaw-section** | `project-context.md` (if exists) | Regex replace between `<!-- CodeClaw:START -->` / `<!-- CodeClaw:END -->` markers |

**CodeClaw-section implementation (if project-context.md exists):**
```bash
python3 -c "
import re; from pathlib import Path
p = Path('project-context.md')
if not p.exists(): print('project-context.md not found, skipping CodeClaw section update'); exit(0)
setup = Path('${CLAW_ROOT}/skills/setup/SKILL.md').read_text()
tm = re.search(r'(<!-- CodeClaw:START -->.*?<!-- CodeClaw:END -->)', setup, re.DOTALL)
if not tm: print('ERROR: No CodeClaw section in setup template'); exit(1)
p.write_text(re.sub(r'<!-- CodeClaw:START -->.*?<!-- CodeClaw:END -->', tm.group(1), p.read_text(), flags=re.DOTALL))
print('project-context.md CodeClaw section updated')
"
```

**Customized files** (`ci.yml`, `CODEOWNERS`, `.gitlab-ci.yml`): Before updating, warn that user customizations will be overwritten and will need to be re-applied. Then direct-copy.

## Step 7: Verify and Report

Verify each updated file exists and is non-empty. If project-context.md exists, verify both CodeClaw markers are intact.

```
## CodeClaw Update Complete

**Plugin version:** [version]

### Files Updated
| File | Action |
|------|--------|
| [file path] | Updated to latest template |
| project-context.md (if exists) | CodeClaw section updated |

### Files Skipped
| File | Reason |
|------|--------|
| [file path] | Already current |

### Not Installed
These files are available but were never deployed:
| File | Install With |
|------|-------------|
| [file path] | `/setup` or `/setup` |

### Next Steps
1. Review the changes: `git diff`
2. Commit the updates
3. Push to apply updated pipelines
```

---

## Important Rules

1. **Never create uninstalled files** — only update existing files. For new installations, suggest `/setup`.
2. **Keep customizations intact** when updating user-edited files.
3. **Only touch the CodeClaw:START/END section** in the platform instructions file — never modify content outside those markers.
4. **Warn before overwriting customized files** (`ci.yml`, `CODEOWNERS`, `.gitlab-ci.yml`) — user must re-apply project-specific changes after update.
