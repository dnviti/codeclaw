---
title: Troubleshooting
description: Common errors, debugging techniques, and frequently asked questions
generated-by: ctdf-docs
generated-at: 2026-03-17T10:00:00Z
source-files:
  - scripts/task_manager.py
  - scripts/release_manager.py
  - scripts/skill_helper.py
  - scripts/agent_runner.py
  - scripts/app_manager.py
  - hooks/hooks.json
---

## Common Issues

### Plugin Not Found

**Symptom:** Slash commands like `/task` or `/idea` are not recognized.

**Causes and fixes:**
1. **Plugin not installed** — Run `/plugin install ctdf@dnviti-claude-task-development-framework`
2. **Plugin disabled** — Run `/plugin enable ctdf@dnviti-claude-task-development-framework`
3. **Local development** — Ensure you started Claude Code with `claude --plugin-dir ./claude-task-development-framework`

### "No task files found"

**Symptom:** `/task status` or `/task pick` reports no task files.

**Fix:** Run `/setup [project name]` to create the tracking files (`to-do.txt`, `progressing.txt`, `done.txt`, `ideas.txt`, `idea-disapproved.txt`).

### Worktree Conflicts

**Symptom:** `/task pick` fails with git worktree errors.

**Debugging:**
```bash
# List active worktrees
python3 scripts/skill_helper.py worktree-list

# Manually clean up a stale worktree
python3 scripts/skill_helper.py worktree-cleanup --task TASK-CODE
```

**Common causes:**
- A previous task session crashed without cleanup
- The worktree directory was manually deleted but git still tracks it
- Run `git worktree prune` to clean up stale references

### Release Pipeline Stuck

**Symptom:** `/release continue` hangs or fails at a specific stage.

**Fix:** Resume from the last saved state:
```
/release continue resume
```

**To check the saved state:**
```bash
python3 scripts/release_manager.py release-state-get
```

**To clear the state and start fresh:**
```bash
python3 scripts/release_manager.py release-state-clear
```

### Version Bump Fails

**Symptom:** Stage 7d of the release pipeline can't find manifest files.

**Debugging:**
```bash
# List discovered manifests
python3 scripts/release_manager.py discover-manifests
```

**Fix:** Ensure at least one of these files exists: `package.json`, `pyproject.toml`, `Cargo.toml`, `.claude-plugin/plugin.json`, `VERSION`, or other supported manifests.

### Platform Issues Integration Not Working

**Symptom:** Tasks/ideas are not synced to GitHub/GitLab Issues.

**Checklist:**
1. Config file exists at `.claude/issues-tracker.json`
2. `"enabled": true` is set
3. `"repo"` is set to a valid `owner/repo`
4. `gh` (GitHub) or `glab` (GitLab) CLI is authenticated
5. Labels exist — run `python3 scripts/setup_labels.py`

### Agentic Fleet Pipeline Fails

**Symptom:** CI/CD agentic pipeline exits with an error.

**Common causes:**

| Error | Fix |
|-------|-----|
| `ANTHROPIC_API_KEY is not set` | Add the API key as a repository secret |
| `claude: command not found` | The CLI installation step failed — check npm permissions |
| `Prompt not found at .claude/prompts/...` | Run `/setup agentic-fleet` to generate prompt files |
| `Budget exceeded` | Increase the budget in `agentic-provider.json` |

**Dry run to debug:**
```bash
python3 scripts/agent_runner.py run --pipeline task --dry-run
```

### Port Conflicts

**Symptom:** Dev server won't start because a port is in use.

**Fix:**
```bash
# Check what's using the port
python3 scripts/app_manager.py check-ports 3000 8080

# Kill the process
python3 scripts/app_manager.py kill-ports 3000
```

### PostToolUse Hook Errors

**Symptom:** Errors after every file edit/write operation.

**Cause:** The hook calls `task_manager.py hook` which looks for `progressing.txt`. If no tasks are in progress, the hook exits silently. If the file is missing, it may error.

**Fix:** Ensure task files exist (`/setup`) or temporarily disable the hook by removing `hooks/hooks.json`.

### Documentation Sync Reports All Stale

**Symptom:** `/docs sync` says everything is stale even after just generating.

**Cause:** The manifest wasn't written properly after generation.

**Fix:**
```bash
# Check manifest
python3 scripts/docs_manager.py check-staleness

# Regenerate
/docs reset
/docs generate
```

## Debugging Tips

### Check Script Output Directly

All scripts output JSON. Run them directly to diagnose issues:

```bash
# Check platform context
python3 scripts/skill_helper.py context

# List tasks
python3 scripts/task_manager.py list --file to-do.txt --format json

# Check release state
python3 scripts/release_manager.py release-state-get

# Discover codebase
python3 scripts/docs_manager.py discover
```

### Git Worktree Troubleshooting

```bash
# List all worktrees (git native)
git worktree list

# Prune stale worktree references
git worktree prune

# Force remove a worktree
git worktree remove .claude/worktrees/task/CODE --force
```

### Windows-Specific Issues

- Use `python` instead of `python3` if `python3` is not available
- Port management uses `netstat -ano` and `taskkill` instead of `lsof`/`ss`
- File paths use forward slashes internally but Windows paths are normalized

## FAQ

**Q: Can I use CTDF with any programming language?**
A: Yes. CTDF is project-agnostic — it works with any language, framework, or tech stack.

**Q: Do I need a GitHub/GitLab account?**
A: No. CTDF works in local-only mode by default with plain `.txt` files.

**Q: Can multiple people use CTDF on the same repo?**
A: Yes. Task files are plain text and can be committed to git. Worktrees are per-user.

**Q: What happens if the release pipeline is interrupted?**
A: The pipeline state is saved after each stage. Resume with `/release continue resume`.

**Q: Can I customize the task format?**
A: The format is fixed (78-dash separators, em dash titles, 2-space indent) to ensure consistent parsing by `task_manager.py`.

**Q: How do I update the plugin?**
A: Run `/plugin update ctdf@dnviti-claude-task-development-framework`, then `/update` to refresh CTDF-managed files in your project.

**Q: What is yolo mode?**
A: Appending `yolo` to any command auto-confirms all non-destructive gates, enabling fully autonomous execution.
