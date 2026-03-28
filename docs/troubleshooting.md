---
title: Troubleshooting
description: Common errors, debugging techniques, and frequently asked questions
generated-by: claw-docs
generated-at: 2026-03-20T00:25:00Z
source-files:
  - scripts/task_manager.py
  - scripts/release_manager.py
  - scripts/skill_helper.py
  - scripts/agent_runner.py
  - scripts/app_manager.py
  - scripts/ollama_manager.py
  - scripts/vector_memory.py
  - scripts/deps_check.py
  - scripts/mcp_server.py
  - scripts/hooks/pre_tool_offload.py
  - hooks/hooks.json
---

## Common Issues

### Plugin Not Found

**Symptom:** Slash commands like `/task` or `/idea` are not recognized.

**Causes and fixes:**
1. **Plugin not installed** — Run `/plugin install claw@dnviti-plugins`
2. **Plugin disabled** — Run `/plugin enable claw@dnviti-plugins`
3. **Local development** — Ensure you started Claude Code with `claude --plugin-dir ./codeclaw`

### "No task files found"

**Symptom:** `/task status` or `/task pick` reports no task files.

**Fix:** Run `/setup [project name]` to create the tracking files (`to-do.txt`, `progressing.txt`, `done.txt`, `ideas.txt`, `idea-disapproved.txt`).

### Release Pipeline Stuck

**Symptom:** `/release continue` hangs or fails at a specific stage.

**Fix:** Resume from the last saved state:
```
/release resume
```

**To check the saved state:**
```bash
python3 scripts/release_manager.py release-state-get
```

**To clear the state and start fresh:**
```bash
python3 scripts/release_manager.py release-state-clear
```

**Platform-only mode:** The release state is stored in a `claw-release-state` GitHub/GitLab issue. If the issue is missing or corrupt, `release-state-get` returns `{"error": "No release state found"}`. Recreate by running `release-state-set` with the required fields.

### Version Bump Fails

**Symptom:** Stage 7d of the release pipeline can't find manifest files.

**Debugging:**
```bash
# List discovered manifests
python3 scripts/release_manager.py update-versions --version "0.0.0"
```

**Fix:** Ensure at least one of these files exists: `.claude-plugin/plugin.json`, `package.json`, `pyproject.toml`, `Cargo.toml`, or other supported manifests.

### Platform Issues Integration Not Working

**Symptom:** Tasks/ideas are not synced to GitHub/GitLab Issues.

**Checklist:**
1. Config file exists at `.claude/issues-tracker.json`
2. `"enabled": true` is set
3. `"repo"` is set to a valid `owner/repo`
4. `gh` (GitHub) or `glab` (GitLab) CLI is authenticated
5. Labels exist — run `python3 scripts/setup_labels.py`

### Platform Release State Not Syncing

**Symptom:** In platform-only mode, different users see different (or missing) release state.

**Checklist:**
1. Confirm platform-only mode: `"enabled": true, "sync": false` in `.claude/issues-tracker.json`
2. Run `gh issue list --label claw-release-state --state open --repo owner/repo` to verify the state issue exists
3. If missing: the state was cleared or never created — run `/release resume` to recreate it at the current stage
4. Ensure `gh`/`glab` CLI is authenticated on all machines

**Debugging:**
```bash
python3 scripts/release_manager.py release-state-get
# Should return JSON from the platform issue body
```

### Ollama Offloading Not Working

**Symptom:** Tool calls are not being routed to Ollama despite `enabled: true` in `ollama-config.json`.

**Checklist:**
1. Verify Ollama is running: `curl http://localhost:11434/api/tags`
2. Check the configured model is pulled: `ollama list`
3. Verify `offloading.tool_calls.enabled: true` in `.claude/ollama-config.json`
4. Check that the tool is in `offloading.tool_calls.include_tools`
5. Check that the command doesn't match `offloading.tool_calls.exclude_patterns`

**Debugging the PreToolUse hook:**
```bash
# Test a command that should proceed
python3 scripts/hooks/pre_tool_offload.py Bash "git status"
# Expected: {"action": "proceed"} or {"action": "offload", ...}

# Test an excluded command
python3 scripts/hooks/pre_tool_offload.py Bash "git push origin main"
# Expected: {"action": "proceed", "reason": "excluded_pattern"}
```

**Check offloading level:**
```bash
python3 scripts/ollama_manager.py get-offload-level
```

### Ollama Tool Calling Loop Not Terminating

**Symptom:** An offloaded tool call hangs or runs many iterations.

**Cause:** The Ollama model keeps requesting tool calls instead of returning a text response.

**Fix:** Reduce `tool_calling.max_tool_rounds` in `ollama-config.json` (default: 10). If the model consistently fails to terminate, disable tool calling: set `tool_calling.enabled: false`.

### Vector Memory Errors

**Symptom:** Errors mentioning `lancedb`, `onnxruntime`, `tokenizers`, or `pyarrow` after file edits.

**Cause:** Optional dependencies not installed.

**Fix:**
```bash
pip install lancedb onnxruntime tokenizers numpy pyarrow
```

**To verify installed dependencies:**
```bash
python3 scripts/deps_check.py
```

The checker reports each dependency's status and also detects available GPU acceleration providers.

**To disable vector memory** (if dependencies can't be installed):
```json
// .claude/project-config.json
{
  "vector_memory": { "enabled": false },
  "mcp_server": { "enabled": false }
}
```

**Debugging vector memory:**
```bash
python3 scripts/vector_memory.py status
python3 scripts/vector_memory.py gc --json
```

### GPU Path Allowlist Rejection

**Symptom:** Warning messages like `Ignoring non-allowlisted GPU library path: /some/path` or ONNX Runtime falls back to CPU despite GPU libraries being installed.

**Cause:** The `deps_check.py` GPU path allowlist rejects library paths not matching the built-in defaults or user-configured patterns. This is a security measure to prevent config-injected paths from reaching ONNX Runtime.

**Fix:**

1. Check which paths are being rejected:
   ```bash
   python3 scripts/deps_check.py
   ```

2. Add the rejected path to the allowlist in `project-config.json`:
   ```json
   {
     "vector_memory": {
       "gpu_acceleration": {
         "gpu_path_allowlist": ["/usr/local/cuda-12/lib64", "/opt/rocm/lib"]
       }
     }
   }
   ```

3. Overly broad patterns like `"*"` or `"/*"` are rejected with a warning. Use specific directory paths or glob patterns.

**Built-in defaults:** System library directories (`/usr/lib*`, `/usr/local/lib*`), CUDA paths (`/usr/local/cuda*/lib*`), ROCm paths (`/opt/rocm*/lib*`), and pip site-packages GPU directories are always permitted.

### Search Log Security

**Symptom:** Unexpected search log files appearing or permission errors on search log.

**Details:** Search query logging is opt-in only (`vector_memory.search_log.enabled`). When enabled:
- Logs are created with `0o600` permissions (owner-only read/write)
- Entries are auto-purged after `retention_days` (default: 30)
- A privacy notice is included in the config as `_privacy_notice`

**To disable logging:**
```json
{
  "vector_memory": {
    "search_log": { "enabled": false }
  }
}
```

**To check/clear existing logs:**
```bash
ls -la .claude/memory/search_log.jsonl
# Delete if no longer needed
rm .claude/memory/search_log.jsonl
```

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

**Cause 1:** `task_manager.py hook` can't find `progressing.txt`. If no tasks are in progress, the hook exits silently. If the file is missing entirely, it may error.
**Fix:** Ensure task files exist (`/setup`) or temporarily disable hooks by removing `hooks/hooks.json`.

**Cause 2:** `vector_memory.py hook` fails because dependencies aren't installed.
**Fix:** `pip install lancedb onnxruntime tokenizers numpy pyarrow` or disable vector memory in `project-config.json`.

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

# Check release state
python3 scripts/release_manager.py release-state-get

# Discover codebase
python3 scripts/docs_manager.py discover

# Check Ollama hardware
python3 scripts/ollama_manager.py detect-hardware

# Check vector memory
python3 scripts/vector_memory.py status

# Check vector memory dependencies and GPU support
python3 scripts/deps_check.py

# Check MCP SDK availability
python3 scripts/mcp_server.py --check
```

### Windows-Specific Issues

- Use `python` instead of `python3` if `python3` is not available
- Port management uses `netstat -ano` and `taskkill` instead of `lsof`/`ss`
- File paths use forward slashes internally but Windows paths are normalized

## FAQ

**Q: Can I use CodeClaw with any programming language?**
A: Yes. CodeClaw is project-agnostic — it works with any language, framework, or tech stack.

**Q: Do I need a GitHub/GitLab account?**
A: No. CodeClaw works in local-only mode by default with plain `.txt` files.

**Q: Can multiple people use CodeClaw on the same repo?**
A: Yes. In local mode, task files are plain text committed to git. In platform-only mode, release state is synced through a platform issue so all collaborators share the same state automatically.

**Q: What happens if the release pipeline is interrupted?**
A: The pipeline state is saved after each stage. Resume with `/release resume`.

**Q: Can I customize the task format?**
A: The format is fixed (78-dash separators, em dash titles, 2-space indent) to ensure consistent parsing by `task_manager.py`.

**Q: How do I update the plugin?**
A: Run `/plugin update claw@dnviti-plugins`, then `/update` to refresh CodeClaw-managed files in your project.

**Q: What is yolo mode?**
A: Appending `yolo` to any command auto-confirms all non-destructive gates, enabling fully autonomous execution. Yolo never auto-selects "Abort release".

**Q: Why is my exclude pattern not blocking a command?**
A: The pattern matching is NFKC-normalized to handle Unicode variants (e.g., fullwidth space U+3000). Verify the pattern matches the NFKC form of the command. Run: `python3 -c "import unicodedata; print(unicodedata.normalize('NFKC', 'your command'))"`

**Q: Do I need Ollama for CodeClaw to work?**
A: No. Ollama integration is entirely optional. All core features (task management, release pipeline, documentation) work without it.
