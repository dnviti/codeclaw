---
title: Troubleshooting
description: Common errors, debugging techniques, and frequently asked questions
generated-by: claw-docs
generated-at: 2026-03-29T00:00:00Z
source-files:
  - scripts/task_manager.py
  - scripts/release_manager.py
  - scripts/skill_helper.py
  - scripts/ollama_manager.py
  - scripts/hooks/pre_tool_offload.py
  - hooks/hooks.json
---

## Common Issues

### Plugin Not Found

**Symptom:** Slash commands like `/task` or `/idea` are not recognized.

**Causes and fixes:**
1. Plugin not installed
2. Plugin disabled
3. Local development started with the wrong plugin path

### "No task files found"

**Symptom:** `/task status` or `/task pick` reports no task files.

**Fix:** Run `/setup [project name]` to create the tracking files.

### Release Pipeline Stuck

**Symptom:** `/release continue` hangs or fails at a specific stage.

**Fix:** Resume from the last saved state:

```bash
/release resume
```

Check the saved state with:

```bash
python3 scripts/release_manager.py release-state-get
```

### Version Bump Fails

**Symptom:** Stage 7d cannot find manifest files.

**Fix:** Ensure at least one supported manifest exists, such as `.claude-plugin/plugin.json`, `package.json`, `pyproject.toml`, or `Cargo.toml`.

### Platform Issues Integration Not Working

**Symptom:** Tasks or ideas are not synced to GitHub or GitLab Issues.

**Checklist:**
1. `.claude/issues-tracker.json` exists
2. `"enabled": true` is set
3. `"repo"` is set to a valid `owner/repo`
4. `gh` or `glab` is authenticated
5. Labels exist in the target repository

### Platform Release State Not Syncing

**Symptom:** In platform-only mode, collaborators see different release state.

**Checklist:**
1. Confirm platform-only mode: `"enabled": true, "sync": false`
2. Verify the `claw-release-state` issue exists
3. Recreate the release state by rerunning `/release resume`
4. Ensure the platform CLI is authenticated on all machines

### Ollama Offloading Not Working

**Symptom:** Tool calls are not being routed to Ollama despite `enabled: true`.

**Checklist:**
1. Verify Ollama is running: `curl http://localhost:11434/api/tags`
2. Check the configured model is pulled: `ollama list`
3. Verify `offloading.tool_calls.enabled: true`
4. Check that the tool is in `offloading.tool_calls.include_tools`
5. Check that the command does not match `offloading.tool_calls.exclude_patterns`

### Documentation Sync Reports All Stale

**Symptom:** `/docs sync` says everything is stale after generation.

**Fix:**

```bash
python3 scripts/docs_manager.py check-staleness
/docs reset
/docs generate
```

### Port Conflicts

**Symptom:** Dev server will not start because a port is in use.

**Fix:**

```bash
lsof -i :3000
kill -9 <pid>
```

On Windows, use `netstat -ano | findstr :3000` and `taskkill /PID <pid> /F`.

### PostToolUse Hook Errors

**Symptom:** Errors after every file edit or write operation.

**Cause 1:** `task_manager.py hook` cannot find `progressing.txt`. If no tasks are in progress, the hook exits silently.
**Fix:** Ensure task files exist (`/setup`) or temporarily disable hooks by removing `hooks/hooks.json`.

**Cause 2:** The branch is stale and still references retired legacy hooks.
**Fix:** Update to the current branch and regenerate the docs/configuration from the supported surface.

## Debugging Tips

### Check Script Output Directly

```bash
python3 scripts/skill_helper.py context
python3 scripts/release_manager.py release-state-get
python3 scripts/docs_manager.py discover
python3 scripts/ollama_manager.py detect-hardware
```

### Windows-Specific Issues

- Use `python` instead of `python3` if needed
- Port management uses `netstat -ano` and `taskkill`
- File paths are normalized internally

## FAQ

**Q: Can I use CodeClaw with any programming language?**
A: Yes. CodeClaw is project-agnostic.

**Q: Do I need a GitHub/GitLab account?**
A: No. CodeClaw works in local-only mode by default.

**Q: Can multiple people use CodeClaw on the same repo?**
A: Yes. Platform-only mode stores release state in a shared issue.

**Q: What happens if the release pipeline is interrupted?**
A: The pipeline state is saved after each stage. Resume with `/release resume`.

**Q: How do I update the plugin?**
A: Run `/update` to refresh CodeClaw-managed files in your project.

**Q: What is yolo mode?**
A: Appending `yolo` to a command auto-confirms non-destructive gates.
