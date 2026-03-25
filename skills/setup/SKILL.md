---
name: setup
description: "Initialize and configure projects: create task/idea files, detect tech stack, scaffold new projects, configure branch strategy, set up agentic fleet pipelines, or export skills to other AI coding platforms."
disable-model-invocation: true
argument-hint: "[project name] [env [section]] [init [purpose]] [branch-strategy] [agentic-fleet] [platform [target]]"
---

# Project Setup

You are a setup assistant for the CodeClaw plugin. Your job is to initialize, configure, and scaffold projects so that all other CodeClaw skills work correctly.

Always respond and work in English.

**CRITICAL:** At every `AskUserQuestion`: STOP completely, wait for the user's response, never assume an answer, never batch questions. This applies to ALL flows in this skill.

### Submodule Awareness

When `SH context` returns `worktree.submodules` with entries, the project uses git submodules. The setup skill should:
- Detect and report submodules during project analysis (`SH list-submodules`)
- Allow the user to choose which submodule to configure if running `/setup env` on a submodule project
- Apply CLAUDE.md and branch configuration to the selected submodule's repository context

## Arguments

The user invoked with: **$ARGUMENTS**

## Argument Dispatcher

`SH dispatch --skill setup --args "$ARGUMENTS"`

Route based on `flow` in the JSON result:
- `env` -> [Env Flow](#env-flow)
- `init` -> [Init Flow](#init-flow)
- `branch-strategy` -> [Branch Strategy Flow](#branch-strategy-flow)
- `agentic-fleet` -> [Agentic Fleet Flow](#agentic-fleet-setup)
- `platform` -> [Platform Export Flow](#platform-export-flow)
- `standard` -> [Standard Setup Flow](#standard-setup-flow)

---

## Standard Setup Flow

This is a guided setup wizard. Ask the user each question one at a time.

### Step 0: Analyze Existing Project

`SH check-project-state`

Also run:
```bash
git remote get-url origin 2>&1 || echo "(no remote)"
git branch --list 2>&1 | head -10
```

**If the directory is NOT empty**, perform a quick codebase scan: discover source files (Glob), read manifest files, check for existing CI and config files, detect platform from git remote, detect framework/runtime/test framework/package manager.

Store all scan results as `SCAN`. Present:
> **Existing project detected:**
> - **Runtime/Framework/Package manager/Git remote/Platform hint/Existing CI/Issues config/Source files**
>
> I'll tailor the setup questions to your existing project.

**If the directory IS empty**, skip the scan and set `SCAN = null`.

### Step 1: Project Name

If `$ARGUMENTS` provides a project name, use it. If `SCAN` detected a name (from manifest or directory name), suggest it.

Use `AskUserQuestion`:
- **"Use `<detected-name>`"**
- **"I want a different name"** — wait for free-text input

STOP HERE and wait.

### Step 2: Platform Choice

**If `SCAN` detected an existing `.claude/issues-tracker.json`**, read it and skip — platform is already configured.

**If `SCAN` detected a git remote**, pre-select the matching platform as "(Recommended)".

Use `AskUserQuestion`:
- **"GitHub (Recommended)"** or **"GitHub"**
- **"GitLab (Recommended)"** or **"GitLab"**
- **"Local only"**

STOP.

### Step 3: Tracking Mode (GitHub / GitLab only)

**Skip if "Local only" was chosen or platform config already exists.**

Use `AskUserQuestion`:
- **"Platform-only (issues are the single source of truth)"**
- **"Dual sync (local files + platform issues)"**
- **"Cancel platform integration"**

STOP.

**If a platform was chosen:**
1. **If `SCAN` detected a git remote**, extract `owner/repo` and ask to confirm. STOP.
   If no remote, ask for repository via free-text. STOP.
2. Create issues tracker config:
   ```bash
   mkdir -p .claude
   cp ${CLAUDE_PLUGIN_ROOT}/config/issues-tracker.example.json .claude/issues-tracker.json
   ```
3. Update config with repo, platform, enabled=true, sync based on choice.
4. Run label setup: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup_labels.py`

### Step 4: Branch Strategy

**If `SCAN` detected existing branches**, show what was found and adjust defaults.

Use `AskUserQuestion`:
- **"Standard (develop / staging / main)"** — mark recommended if `develop` exists
- **"Simple (main only)"**
- **"Custom branch names"**

STOP.

**If "Standard":** Create `develop` and `staging` if missing. Set DEVELOPMENT_BRANCH=develop, STAGING_BRANCH=staging, PRODUCTION_BRANCH=main.

**If "Simple":** Set all three to `main`.

**If "Custom":** Ask for each branch name one at a time. STOP after each.

### Step 5: CI/CD Pipelines

**Skip if "Local only" was chosen.**

**If `SCAN` detected existing CI workflows**, inform the user.

Use `AskUserQuestion`:
- **"Full CI/CD (lint + test + build + security + release + staging)"**
- **"Basic CI only (lint + test + build)"**
- **"No CI/CD (keep existing)"**

STOP.

**If Full CI/CD:** Copy templates based on platform:
- **GitHub:** `ci.yml`, `release.yml`, `security.yml`, `staging-merge.yml` to `.github/workflows/`. If issues tracker enabled: also `issue-triage.yml`, `status-guard.yml`, `CODEOWNERS`.
- **GitLab:** `.gitlab-ci.yml`, `staging-merge.gitlab-ci.yml`

**If Basic CI:** Copy only `ci.yml` (GitHub) or `.gitlab-ci.yml` (GitLab).

### Step 6: Branch Protection

**Skip if "Local only" or "No CI/CD" was chosen.**

Use `AskUserQuestion`:
- **"Yes, protect main branch"**
- **"No, skip protection"**

STOP.

**If "Yes":** Run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup_protection.py --branch main --required-reviews 1 --status-checks "Lint, Test & Build"`

### Step 7: Tech Stack Detection

**If `SCAN` detected the tech stack**, present findings and ask:

Use `AskUserQuestion`:
- **"Yes, auto-configure with detected values"** — apply SCAN results to CLAUDE.md (run Env Steps 3-4 with pre-filled data)
- **"Auto-detect again (deeper scan)"** — run full Env Flow
- **"I'll configure manually later"** — create CLAUDE.md with empty placeholders

STOP.

**If SCAN = null:**

Use `AskUserQuestion`:
- **"I'll configure manually later"**
- **"Skip"**

STOP.

Then return here for Step 8.

### Step 8: Release Workflow

Use `AskUserQuestion`:
- **"Full release pipeline (develop -> staging -> main)"**
- **"Simple releases (tag from main)"**
- **"No releases yet"**

STOP.

Store the preference. If "Full pipeline", ensure branch strategy includes staging.

### Step 8.5: Worktree-Based Task Isolation [BETA] (Optional)

Use `AskUserQuestion`:
- **"Yes, enable worktree-based task isolation [BETA]"** — each `/task pick` creates an isolated git worktree
- **"No, use standard branch switching (default)"** — `/task pick` uses `git checkout` (recommended for most projects)

STOP.

**If "Yes":**
1. Ensure `.claude/project-config.json` exists (copy from example if not).
2. Set `worktrees.enabled = true` in `.claude/project-config.json`.
3. Add `.worktrees/` to `.gitignore` if not already present.
4. Inform: "Worktree isolation enabled. Each task will get its own directory under `.worktrees/task/<code>/`. This is a [BETA] feature — you can disable it later by setting `worktrees.enabled` to `false` in `.claude/project-config.json`."

**If "No":**
1. Ensure `.claude/project-config.json` exists (copy from example if not).
2. Set `worktrees.enabled = false` in `.claude/project-config.json` (this is the default).

Then return here for Step 9.

### Step 9: Agentic Fleet (Optional)

Use `AskUserQuestion`:
- **"Yes, set up AI-powered automation"**
- **"No, skip"**

STOP.

**If "Yes":** Run the [Agentic Fleet Setup](#agentic-fleet-setup) flow inline, then return for Step 10.

### Step 9.5: Local Model — Ollama (Optional)

Use `AskUserQuestion`:
- **"Yes, set up local AI model (Ollama)"**
- **"No, skip"**

STOP.

**If "Yes":**

1. Detect hardware:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/ollama_manager.py detect-hardware
   ```
   Parse the JSON result: `ram_gb`, `vram_gb`, `gpu_vendor`, `cpu_cores`.

2. Check if Ollama is installed:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/ollama_manager.py check-install
   ```

3. **If not installed**, use `AskUserQuestion`:
   - **"Yes, install Ollama now"**
   - **"No, I will install it manually"**

   STOP.

   If "Yes":
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/ollama_manager.py install
   ```

4. Recommend a model based on detected hardware:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/ollama_manager.py recommend-model --ram <RAM_GB> --vram <VRAM_GB>
   ```

   Present the recommendation:
   > **Recommended model:** `<model_name>` (~<size>GB)
   > **Reason:** <description>
   > **Your hardware:** <ram>GB RAM, <vram>GB VRAM (<gpu_vendor>), <cpu_cores> CPU cores

   Use `AskUserQuestion`:
   - **"Use recommended model"**
   - **"Choose a different model (I will specify)"** — wait for free-text model name
   - **"Skip model pull (I will do it later)"**

   STOP.

5. **If a model was chosen**, pull it:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/ollama_manager.py pull-model --name <MODEL_NAME>
   ```

6. Ask about offloading level:

   Present the offloading scale:
   > **Offloading Level (0-10):** Controls how aggressively tool calls are routed to the local Ollama model instead of the cloud.
   >
   > | Level | Behavior |
   > |-------|----------|
   > | 0 | Never offload — all tool calls go to the cloud |
   > | 1-2 | Minimal — only trivial operations |
   > | 3-4 | Light — simple bash commands (ls, cat, git status) |
   > | 5 | Moderate (default) — simple commands + short edits |
   > | 6-7 | Aggressive — includes read/grep/glob + complex bash |
   > | 8-9 | Very aggressive — includes structural edits |
   > | 10 | Always — all tool calls go to Ollama (except destructive commands) |

   Use `AskUserQuestion`:
   - **"Level 5 — Moderate (recommended)"** — good balance of token savings and quality
   - **"Level 3 — Light"** — conservative, only simple commands
   - **"Level 8 — Very aggressive"** — maximum token savings, requires capable local model
   - **"Level 0 — Disabled"** — no offloading, all tool calls go to the cloud

   STOP.

7. Save configuration:
   ```bash
   mkdir -p .claude
   cp ${CLAUDE_PLUGIN_ROOT}/config/ollama-config.example.json .claude/ollama-config.json
   ```
   Update `.claude/ollama-config.json` with:
   - `enabled: true`
   - `model`: selected model name
   - `hardware`: detected hardware values
   - `offloading.level`: chosen level (0-10)
   - `offloading.tool_calls.enabled: true` (so the level controls routing)
   - `offloading.tool_calls.include_tools`: `["Bash", "Read", "Grep", "Glob", "Edit", "Write"]`

   Also update `.claude/project-config.json`:
   - `ollama.enabled: true`
   - `ollama.model`: selected model name
   - `ollama.offloading_level`: chosen level (0-10)

Then return here for Step 9.7.

### Step 9.7: Vector Memory MCP (Optional — opt-in)

**9.7a. Gitignore hardening (unconditional — always runs):**

Before asking the user about vector memory, ensure `.gitignore` contains the required entries. This runs regardless of the user's choice:

```bash
# Append .claude/memory/ if not already present
grep -qxF '.claude/memory/' .gitignore 2>/dev/null || echo '.claude/memory/' >> .gitignore

# Append .claude/worktrees/ if not already present
grep -qxF '.claude/worktrees/' .gitignore 2>/dev/null || echo '.claude/worktrees/' >> .gitignore

# Append .mcp.json if not already present (contains machine-specific absolute paths)
grep -qxF '.mcp.json' .gitignore 2>/dev/null || echo '.mcp.json' >> .gitignore
```

**9.7b. GATE — ask the user:**

Use `AskUserQuestion`:
- **"Yes, enable vector memory MCP (recommended)"** — proceed to 9.7c (full automated install)
- **"No, keep disabled"** — set `vector_memory.enabled = false`, `mcp_server.enabled = false` in `.claude/project-config.json` and skip to Step 10

**9.7c. Automated installation sequence (when user enables):**

1. **Detect GPU hardware and install correct ONNX Runtime variant:**

   First, detect the user's GPU hardware:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/deps_check.py detect-gpu
   ```

   Parse the JSON result to get `vendor`, `vram_gb`, `recommended_package`, and `gpu_mode`.

   Present the detection result:
   > **GPU Detection:**
   > - **Vendor:** `<vendor>` (nvidia / amd / apple / none)
   > - **VRAM:** `<vram_gb>` GB
   > - **Recommended package:** `<recommended_package>`
   > - **Mode:** `<gpu_mode>` (gpu / cpu)

   If `vendor` is `"none"` and `gpu_mode` is `"cpu"`:
   > No GPU detected. ONNX Runtime will use CPU-only mode.

   **Install all Python packages** in one command, using the detected ONNX Runtime variant:

   ```bash
   pip install "mcp>=1.0" "lancedb>=0.5.0,<1.0" "sentence-transformers>=2.7.0,<3.0" "<recommended_package>"
   ```

   Where `<recommended_package>` is the value from the GPU detection (e.g., `onnxruntime-gpu` for NVIDIA, `onnxruntime-rocm` for AMD, `onnxruntime-silicon` for Apple Silicon, `onnxruntime-directml` for Windows, or `onnxruntime` for CPU-only).

   If `pip install` fails, display:
   > **Action required:** Install vector memory dependencies manually:
   > ```
   > pip install "mcp>=1.0" "lancedb>=0.5.0,<1.0" "sentence-transformers>=2.7.0,<3.0" "<recommended_package>"
   > ```
   > Then re-run: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/vector_memory.py index --force-init`

   Do NOT continue with remaining sub-steps if pip fails — skip to Step 10 with a warning.

   **After install, discover GPU library paths and auto-configure:**

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/deps_check.py discover-gpu-libs
   ```

   Parse the JSON result. If `paths` is non-empty:
   - Auto-inject the discovered paths into the current process environment before verification
   - Store the paths for later persistence in project-config.json (see step 2 below)

   **Verify GPU provider is available (with auto-fix):**

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/deps_check.py verify-gpu --auto-fix
   ```

   - If `available` is `true`: report the active GPU provider(s). Note whether `auto_fixed` was needed.
   - If `available` is `false` and a GPU was detected: warn that GPU provider failed to load and falling back to CPU mode. Set `gpu_mode` to `"cpu"` for the config update below. Display the `fix_command` from the discovery output so the user can manually fix their environment.

2. **Update project config:**

   Read `.claude/project-config.json` (or create from template if missing):
   ```bash
   mkdir -p .claude
   [ -f .claude/project-config.json ] || cp ${CLAUDE_PLUGIN_ROOT}/config/project-config.example.json .claude/project-config.json
   ```

   Set the following fields in `.claude/project-config.json`:
   - `vector_memory.enabled = true`
   - `vector_memory.auto_index = true`
   - `vector_memory.gpu_acceleration.mode` = `<gpu_mode>` from GPU detection (`"gpu"` or `"cpu"`)
   - `vector_memory.gpu_acceleration.log_provider = true`
   - `vector_memory.gpu_acceleration.lib_paths` = `<paths>` array from `discover-gpu-libs` output (e.g., `["/path/to/site-packages/nvidia/cublas/lib", ...]`). Set to `[]` if no paths were discovered or on macOS. These paths are auto-injected by `local_onnx.py` at runtime before creating the ONNX session, ensuring GPU libraries are found without manual `LD_LIBRARY_PATH`/`PATH` configuration.
   - `mcp_server.enabled = true`
   - `mcp_server.auto_start = true`

3. **Generate `.mcp.json` at repository root:**

   Resolve the actual paths and write `.mcp.json` to the project root directory:
   ```json
   {
     "mcpServers": {
       "claw-vector-memory": {
         "command": "python3",
         "args": [
           "<RESOLVED_PATH_TO_CLAW_SCRIPTS>/mcp_server.py",
           "--root", "<RESOLVED_PROJECT_ROOT>"
         ],
         "env": {
           "CLAW_PROJECT_ROOT": "<RESOLVED_PROJECT_ROOT>"
         }
       }
     }
   }
   ```

   Where:
   - `<RESOLVED_PATH_TO_CLAW_SCRIPTS>` = the absolute path to the CodeClaw `scripts/` directory (resolve `${CLAUDE_PLUGIN_ROOT}/scripts`)
   - `<RESOLVED_PROJECT_ROOT>` = the absolute path to the current project root (resolve `.`)

4. **Build initial vector index:**

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/vector_memory.py index --force-init --root .
   ```

   - If the index succeeds, report: "Vector memory index built successfully."
   - If it fails with exit code 2 (missing deps), show the install message above.
   - If it fails for any other reason, show the error and continue setup.

5. **Verify MCP server starts:**

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/mcp_server.py --check
   ```

   - If `{"mcp_sdk": true}` → report: "MCP server ready. It will start automatically via `.mcp.json` when your AI assistant connects."
   - If fails → log warning: "MCP SDK check failed. The server may not start automatically. You can install manually with: `pip install mcp`"

Then return here for Step 10.

### Step 9.6: Memory Configuration (Optional)

Use `AskUserQuestion`:
- **"Use defaults (recommended)"** — proceed to next step with default memory settings unchanged
- **"Customize memory settings"** — proceed below

STOP.

**If "Customize":**

Ask the following questions **one at a time** (each is a separate `AskUserQuestion` STOP):

1. **GC TTL:** "How many days before stale memory entries are garbage collected? (default: 30)"
   - Collect free-text integer input. Store as `gc_ttl_days`.

2. **Conflict strategy:** "How should memory conflicts between agents be resolved?"
   - **"Auto (recommended)"** — `conflict_strategy: "auto"`
   - **"Latest wins"** — `conflict_strategy: "latest-wins"`
   - **"Manual review"** — `conflict_strategy: "manual"`

3. **Vector memory embedding provider:** "Which embedding provider should be used for semantic search?"
   - **"Local — sentence-transformers (no API key needed, recommended)"** — `embedding_provider: "local"`
   - **"OpenAI"** — `embedding_provider: "openai"`
   - **"Voyage AI"** — `embedding_provider: "voyage"`

   If "OpenAI" or "Voyage AI": ask "Enter the environment variable name that holds your API key (e.g. `OPENAI_API_KEY`):" and store as `embedding_api_key_env`.

After collecting all inputs, write to `.claude/project-config.json`:
- Under `memory_consistency`: set `gc_ttl_days` and `conflict_strategy`
- Under `vector_memory`: set `embedding_provider` and `embedding_api_key_env` (if provided)

If `.claude/project-config.json` does not exist, copy from example first:
```bash
mkdir -p .claude
cp ${CLAUDE_PLUGIN_ROOT}/config/project-config.example.json .claude/project-config.json
```

Then return here for Step 9.8.

### Step 9.8: Social Posting Configuration (Optional)

Use `AskUserQuestion`:
- **"Configure social media announcements"** — proceed below
- **"Skip"** — proceed to Step 10

STOP.

**If "Configure":**

1. Run to see current credential status:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/social_announcer.py platforms
   ```

2. Ask which platforms to enable (multiSelect):
   - **"Bluesky"**
   - **"Mastodon"**
   - **"Discord (webhook)"**
   - **"Slack (webhook)"**
   - **"Twitter / X (clipboard — no API key needed)"**
   - **"LinkedIn (clipboard — no API key needed)"**
   - **"Reddit (clipboard — no API key needed)"**
   - **"Hacker News (clipboard — no API key needed)"**

   STOP.

3. **For each selected direct-posting platform** (Bluesky, Mastodon, Discord, Slack):

   Ask for the required credentials **one platform at a time**:

   - **Bluesky:** "Enter the env var name for your Bluesky handle (e.g. `CLAW_BLUESKY_HANDLE`):" and "Enter the env var name for your Bluesky app password (e.g. `CLAW_BLUESKY_APP_PASSWORD`):"
   - **Mastodon:** "Enter the env var name for your Mastodon instance URL (e.g. `CLAW_MASTODON_INSTANCE`):" and "Enter the env var name for your Mastodon access token (e.g. `CLAW_MASTODON_ACCESS_TOKEN`):"
   - **Discord:** "Enter the env var name for your Discord webhook URL (e.g. `CLAW_DISCORD_WEBHOOK`):"
   - **Slack:** "Enter the env var name for your Slack webhook URL (e.g. `CLAW_SLACK_WEBHOOK`):"

   > **Important:** Enter only the environment variable **name** (e.g. `CLAW_BLUESKY_HANDLE`), never the actual secret value. Storing secrets in project config would expose them to version control.

   Store only the env var **names** (never the values) in project config. Inform: "Set `<ENV_VAR>=<value>` in your shell profile or `.env` file."

   Set `"enabled": true` for each configured platform.

4. **For each selected clipboard platform** (Twitter/X, LinkedIn, Reddit, Hacker News):
   - In the `social_announce.clipboard_platforms` array, find the object whose `"name"` matches the selected platform (e.g. `"twitter"`, `"linkedin"`, `"reddit"`, `"hackernews"`) and set its `"enabled": true`
   - No credentials needed

5. Ensure `.claude/project-config.json` exists (copy from example if not — see Step 9.6), then update the `social_announce` section using the Edit or Write tool.

6. Inform: "Social announcement configuration saved. Platforms will be used during `/release` pipeline (Stage 8.5)."

Then return here for Step 10.

### Step 10: Create Files

Based on all answers collected:

1. Create task/idea files: `SH create-project-files --project-name "<NAME>"`
2. Create/update CLAUDE.md (see Step 11)
3. Create AGENTS.md with project memory (see Step 11b — always, no prompt)
4. Create branches (from Step 4)
5. Create `.worktrees/` in `.gitignore` if not present

### Step 11: Create/Update CLAUDE.md

**If CLAUDE.md does not exist**, create it by copying the template:

```bash
cp ${CLAUDE_PLUGIN_ROOT}/templates/CLAUDE.md ./CLAUDE.md
```

Then apply any detected values (branch strategy, release config, etc.) to the newly created file.

**If CLAUDE.md exists but does NOT contain `<!-- CodeClaw:START -->`**, extract the framework section (from `<!-- CodeClaw:START -->` to `<!-- CodeClaw:END -->`) from `${CLAUDE_PLUGIN_ROOT}/templates/CLAUDE.md` and append it at the end of the existing file.

**If CLAUDE.md exists and already contains `<!-- CodeClaw:START -->`**, skip.

**Ensure CLAUDE.md contains `@AGENTS.md`**: If the file does not already contain the line `@AGENTS.md`, add it after the first heading/description line.

### Step 11b: Create AGENTS.md (Always)

**Always create AGENTS.md** — do NOT ask the user. This file stores project memory for all agents.

**If AGENTS.md does not exist**, create it by copying the template:

```bash
cp ${CLAUDE_PLUGIN_ROOT}/templates/AGENTS.md ./AGENTS.md
```

Then populate the **Project Overview** section with a brief description based on the project scan (`SCAN`) results — project name, detected tech stack, and purpose (if derivable from README or manifest).

**If AGENTS.md already exists**, skip — do not overwrite existing project memory.

### Step 12: Final Report

Present a summary covering: project name, platform (tracking mode, repository, labels), branch strategy table (name + status per branch), CI/CD (pipelines, protection, files), task files created, CLAUDE.md status, AGENTS.md status, release workflow, agentic fleet status.

**Next Steps** (include only applicable items): fill CLAUDE.md sections, review pipeline files, replace CI placeholders, verify platform labels, customize `to-do.txt`, use `/task create` and `/idea create`, add API key secret.

---

## Env Flow

You are an environment setup assistant. Scan the project, detect its tech stack, and update CLAUDE.md so all CodeClaw skills work correctly.

### Environment Detection

`SH context`

Returns platform config, worktree state, branch info, and release config.

#### Worktree check:
If `worktree.in_worktree` is `true`, warn: "You are in a worktree. CLAUDE.md should be updated in the main repository."

Use `AskUserQuestion`:
- **"Switch to main repo"** — change working directory to `worktree.main_root`
- **"Update in worktree instead"** — proceed (changes need manual propagation)
- **"Cancel"** — abort

STOP.

### Env Step 1: Parse Arguments

Extract the **section** from `$ARGUMENTS` (after `env` prefix). Default: `all`.

| Section | Updates |
|---------|---------|
| `all` | Everything (default) |
| `commands` | Development Commands in CLAUDE.md |
| `setup` | Environment Setup in CLAUDE.md |
| `architecture` | Architecture in CLAUDE.md |
| `config` | `.claude/project-config.json` |

### Env Step 2: Deep Scan the Project

Scan manifests and config files for: package manager, commands (dev/build/test/lint/verify), ports, env vars, architecture, test framework, release config. Read actual files — do NOT guess.

Examine: manifests (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, etc.), lock files, config files (`vite.config.*`, `tsconfig.json`, `.eslintrc*`, `Makefile`, `Dockerfile`, etc.), env files (`.env.example`), and directory structure. Also detect pre-dev setup, CI runtime setup, and release config.

**Version manifest discovery:** Explicitly discover all version-bearing manifest files (`package.json` outside `node_modules/`, `pyproject.toml`, `setup.cfg`, `Cargo.toml`, `pom.xml`, `build.gradle`) and store their space-separated paths for `PACKAGE_JSON_PATHS`.

### Env Step 3: Present Findings

Present a summary covering: tech stack (runtime, framework, package manager, database), development commands table (install/dev/build/test/lint/verify), dev server (ports, pre-dev), test framework (framework, command, pattern, CI setup), release config (manifests, tag prefix, repo URL, branch), environment variables (names only), and architecture layers.

Use `AskUserQuestion`:
- **"Looks correct, apply changes"**
- **"Some values are wrong (I will correct them)"** — wait for corrections, re-present
- **"Cancel"**

STOP.

### Env Step 4: Apply Updates

**Always read each file before editing it.**

##### Development Commands (section: `commands` or `all`)

Update the Development Commands section with detected values, following the template format from Step 11.

Only include commands that were actually detected. Omit lines for commands that don't exist.

**`PACKAGE_JSON_PATHS`:** Set this to the space-separated list of version-bearing manifest file paths discovered in Env Step 2 (e.g., `package.json apps/api/package.json`). This tells the release pipeline where to auto-bump version numbers. If no manifests were found, leave it empty.

##### Environment Setup (section: `setup` or `all`)

Replace `## Environment Setup` with prerequisites, first-time setup steps, and environment variable table (names and descriptions only, never values). Only include relevant subsections.

##### Architecture (section: `architecture` or `all`)

Replace `## Architecture` with: project structure (annotated directory tree), key entry points, framework details. Keep concise.

##### Project Config (section: `config` or `all`)

If `.claude/project-config.json` exists, update it. If not, create from `${CLAUDE_PLUGIN_ROOT}/config/project-config.example.json` and fill detected values. Leave empty fields for undetected values.

### Env Step 5: Post-Update Verification

1. Re-read CLAUDE.md — verify well-formed markdown, no duplicates, no broken markers.
2. Verify `.claude/project-config.json` is valid JSON (if updated).
3. Verify `<!-- CodeClaw:START -->` / `<!-- CodeClaw:END -->` content was not modified.

### Env Step 6: Report

Present: changes applied per section (Updated/Skipped/No changes needed), undetected values the user should fill manually, and next steps (review CLAUDE.md, fill remaining values, verify dev server).

---

## Init Flow

You are a project initialization assistant. Guide the user through setting up a new project from scratch.

### Current Directory State

`SH check-project-state`

Also run: `git status --short 2>&1 || echo "(not a git repository)"`

### Init Step 1: Understand the Project Purpose

Analyze `$ARGUMENTS` (after `init` prefix) for purpose, audience, scale, deployment target, requirements.

**If arguments provide enough context**, infer defaults and proceed to Step 2.

**If empty or too vague**, use `AskUserQuestion`:
- **"Web application (frontend + backend)"**
- **"API / backend service"**
- **"CLI tool / script"**
- **"Other (I will describe it)"**

STOP.

### Init Step 2: Suggest the Implementation Approach

Recommend a tech stack (runtime, framework, database, styling, package manager) with rationale (2-3 sentences).

Use `AskUserQuestion`:
- **"Looks good, use this stack"**
- **"I want a different stack (I will specify)"** — wait, re-present
- **"Cancel"**

STOP.

### Init Step 3: Research Scaffolding Options

Use `WebSearch` for best scaffolding tools/templates. Use `WebFetch` on promising results.

Present numbered options:
1. **Official CLI / tool** — exact command, pros/cons
2. **Community template** — exact command, pros/cons
3. **Manual setup** — for full control

Use `AskUserQuestion`:
- **"Option 1: Official CLI"**
- **"Option 2: Community template"**
- **"Option 3: Manual setup"**
- **"I have my own (I will provide the command)"**

STOP.

### Init Step 4: Execute Scaffolding

**If directory is not empty**, use `AskUserQuestion`:
- **"Scaffold here anyway"**
- **"Scaffold in a subdirectory (I will name it)"**
- **"Abort"**

STOP (if directory is not empty).

Execute the chosen command via `Bash` with non-interactive flags.

**After scaffolding:**
1. Verify project structure — list key files.
2. Install dependencies if scaffold didn't.
3. Generate `.gitignore`: use `WebSearch`/`WebFetch` for official GitHub template. Merge with existing if scaffold created one.

### Init Step 5: Initialize Git Repository

Use `AskUserQuestion`:
- **"Yes, initialize git"**
- **"No, skip git"**

STOP.

**If "Yes":**
1. Generate/merge `.gitignore` (WebSearch for official template, merge with existing).
2. `git init && git add -A && git commit -m "Initial project scaffold"`
3. `git checkout -b develop`
4. Report: branches `main` (initial commit) and `develop` (current).

**If "No":** Skip. If scaffold already created a repo, inform user and ask to keep or remove.

### Init Step 6: Configure the Project

Scan the scaffolded project using Glob, Grep, and Read tools to detect: dev server command/ports, pre-dev command, verify/build command, test framework/command/pattern, CI runtime setup, release branch, manifest paths, changelog, tag prefix, repo URL, file naming conventions. Also discover all version-bearing manifest files (`package.json` outside `node_modules/`, `pyproject.toml`, `setup.cfg`, `Cargo.toml`, `pom.xml`, `build.gradle`) and populate `PACKAGE_JSON_PATHS` in CLAUDE.md with their space-separated paths.

#### 6b. Update CLAUDE.md

Update Development Commands with all detected values (same format as Env Step 4). Update Environment Setup, Architecture, and File Naming Conventions.

#### 6c. Generate Makefile and Scripts

Generate `Makefile` with targets: `dev`, `stop`, `restart`, `install`, `build`, `test`, `lint`, `verify` — using detected commands and `app_manager.py` for port management.

Generate `scripts/dev.sh` (Bash) and `scripts/dev.ps1` (PowerShell) for cross-platform dev server lifecycle.

#### 6d. Create Changelog (if not exists)

Create `CHANGELOG.md` with Keep a Changelog boilerplate and `## [Unreleased]` section.

### Init Step 7: Orientation Report

Present: stack, directory, getting started commands (install, `make dev`, localhost URL), project structure overview, git branches (`main`, `develop`), Makefile targets (`dev/stop/restart/test/lint/verify`), cross-platform scripts, and available CodeClaw skills (`/task create`, `/idea create`, `/release`).

### Init Step 8: Issues Tracker Integration (Optional)

Use `AskUserQuestion`:
- **"Yes, enable issues tracker"**
- **"No, use local files only"**

STOP.

**If "Yes":**
1. Ask platform: **"GitHub"** / **"GitLab"** — STOP.
2. Copy: `cp ${CLAUDE_PLUGIN_ROOT}/config/issues-tracker.example.json .claude/issues-tracker.json`
3. Ask for repository (free-text) — STOP.
4. Update config with repo, platform, enabled=true.
5. Ask sync mode: **"Platform-only"** / **"Dual sync"** — STOP.
6. Run: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup_labels.py`
7. Report the setup.

### Init Step 9: CI/CD & Branch Protection Setup (Optional)

Use `AskUserQuestion`:
- **"Yes, set up CI/CD and branch protection"**
- **"CI/CD only (no branch protection)"**
- **"No, skip CI/CD setup"**

STOP.

**If CI/CD selected:**

1. Detect platform from issues tracker config (default: GitHub).
2. Copy CI/CD templates:
   - **GitHub:** `${CLAUDE_PLUGIN_ROOT}/templates/github/workflows/*.yml` to `.github/workflows/`
   - **GitLab:** `${CLAUDE_PLUGIN_ROOT}/templates/gitlab/.gitlab-ci.yml` to project root
3. Customize templates: replace `[CI_RUNTIME_SETUP]`, `[INSTALL_COMMAND]`, `[LINT_COMMAND]`, `[TEST_COMMAND]`, `[BUILD_COMMAND]`, `[CI_IMAGE]` with actual values.
4. Copy additional templates (if issues tracker enabled): `issue-triage.yml`, `status-guard.yml`, `CODEOWNERS`.

5. **Agentic Fleet (Optional):** Use `AskUserQuestion`:
   - **"Idea Scout only"** / **"Task Implementation only"** / **"Both"** / **"No, skip"**
   STOP.

   If selected:
   - Copy `memory_builder.py` to `.claude/scripts/`
   - Copy appropriate pipeline templates per platform
   - If Task Implementation: ask cron interval (**"Every 4/6/8/12/24 hours"** / **"Custom"**) — STOP. Replace `__AGENTIC_TASK_CRON__` in template.
   - For GitLab: instruct user to add `include:` directives if `.gitlab-ci.yml` exists.
   - Warn: "Add `ANTHROPIC_API_KEY` as a repository secret / CI/CD masked variable."

**If branch protection also selected:**

6. Run: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup_protection.py --branch main --required-reviews 1 --status-checks "Lint, Test & Build"`
7. Report full CI/CD and protection setup.

---

## Branch Strategy Flow

This flow is identical to Standard Setup Step 4 when invoked standalone. See Step 4 for the full logic.

### Step B1: Detect Current State

`SH detect-branch-strategy`

Returns `branches_exist`, `branches_remote`, `claude_md_config`, `needs_creation`, `needs_claude_md_update`.

### Step B2: Present Findings

Show what exists and what's missing: develop, staging, main branches and CLAUDE.md config.

### Step B3: Ask User

Use `AskUserQuestion`:
- **"Use defaults (develop/staging/main)"**
- **"Customize branch names"**
- **"Cancel"**

STOP.

**If "Customize":** Ask for each branch name one at a time. STOP after each.

### Step B4: Create Missing Branches

For each missing branch: `git checkout -b <name> && git checkout -`

### Step B5: Update CLAUDE.md

Update the Development Commands section Branch Strategy fields. If fields exist, update them. If not, add after the Release section in the bash block.

### Step B6: Report

Present: branch table (name + Created/Already existed for each), CLAUDE.md update status, and workflow summary (develop -> staging -> production).

---

## Agentic Fleet Setup

Activated when `$ARGUMENTS` contains `agentic-fleet`. Configures CI/CD pipelines for AI-driven idea scouting and task implementation. Both pipelines are fully headless.

### Step A1: Detect Platform

`TM platform-config`

If no config, use `AskUserQuestion`: **"GitHub"** / **"GitLab"**. STOP.

### Step A1.5: Select AI Provider

Use `AskUserQuestion`:
- **"Claude Code (Recommended)"** — uses CLAUDE.md, plugin skills
- **"OpenAI Codex CLI"** — uses AGENTS.md, raw prompts
- **"OpenClaw"** — raw prompts

STOP. Store provider: `claude`, `openai`, or `openclaw`.

### Step A2: Select Pipelines

Use `AskUserQuestion`:
- **"Idea Scout only"** / **"Task Implementation only"** / **"Docs only"** / **"All"** / **"Custom"** / **"Cancel"**

STOP.

### Step A3: Configure Cron (Task Implementation only)

Skip if only Idea Scout or Docs selected.

Use `AskUserQuestion`:
- **"Every 4 hours"** — `0 */4 * * *`
- **"Every 6 hours"** — `0 */6 * * *`
- **"Every 8 hours"** — `0 */8 * * *`
- **"Every 12 hours"** — `0 */12 * * *`
- **"Every 24 hours"** — `0 0 * * *`
- **"Custom"** — ask for cron expression

STOP.

### Step A4: Copy Pipeline Templates

Based on platform and selected pipelines:

**GitHub:** `mkdir -p .github/workflows`
- Idea Scout: `cp ${CLAUDE_PLUGIN_ROOT}/templates/github/workflows/agentic-fleet.yml .github/workflows/`
- Task Implementation: `cp ${CLAUDE_PLUGIN_ROOT}/templates/github/workflows/agentic-task.yml .github/workflows/` then `sed -i 's|__AGENTIC_TASK_CRON__|<cron>|' .github/workflows/agentic-task.yml`
- Docs: `cp ${CLAUDE_PLUGIN_ROOT}/templates/github/workflows/agentic-docs.yml .github/workflows/`

**GitLab:** Copy corresponding `.gitlab-ci.yml` files from `${CLAUDE_PLUGIN_ROOT}/templates/gitlab/`. If `.gitlab-ci.yml` exists, instruct user to add `include:` directives.

### Step A5: Copy Scripts, Prompts, and Skills

```bash
mkdir -p .claude/scripts .claude/prompts .claude/skills/idea-scout .claude/skills/docs
cp ${CLAUDE_PLUGIN_ROOT}/scripts/memory_builder.py .claude/scripts/memory_builder.py
cp ${CLAUDE_PLUGIN_ROOT}/scripts/codebase_analyzer.py .claude/scripts/codebase_analyzer.py
cp ${CLAUDE_PLUGIN_ROOT}/scripts/agent_runner.py .claude/scripts/agent_runner.py
cp ${CLAUDE_PLUGIN_ROOT}/templates/prompts/agentic-task-prompt.md .claude/prompts/agentic-task-prompt.md
cp ${CLAUDE_PLUGIN_ROOT}/templates/prompts/agentic-docs-prompt.md .claude/prompts/agentic-docs-prompt.md
cp ${CLAUDE_PLUGIN_ROOT}/skills/idea-scout/SKILL.md .claude/skills/idea-scout/SKILL.md
cp ${CLAUDE_PLUGIN_ROOT}/skills/docs/SKILL.md .claude/skills/docs/SKILL.md
```

### Step A5.5: Create Provider Configuration

Create `.claude/agentic-provider.json`:

**claude:**
```json
{"provider":"claude","model":{"task":"claude-opus-4-6","scout":"claude-sonnet-4-6","docs":"claude-sonnet-4-6"},"budget":{"task":15,"scout":5,"docs":5},"auto_pr":true}
```

For openai/openclaw, adjust `provider`, `model`, and `budget` fields per the example configs in `${CLAUDE_PLUGIN_ROOT}/config/agentic-provider.example.json`.

AGENTS.md is already created in Step 11b. If the provider is `openai` or `openclaw`, ensure AGENTS.md contains the same key sections as CLAUDE.md (the template already handles this).

### Step A6: Verify Files

Confirm all copied files exist — pipeline files, scripts, prompts, skills, and provider config.

### Step A7: Report

Present: AI provider, enabled pipelines (with triggers and models), platform, all created file paths, required configuration (API key secret, `AGENTIC_PROVIDER` variable, optional `AGENTIC_AUTO_PR`), and how to change provider later (edit `.claude/agentic-provider.json`).

---

## Platform Export Flow

Activated when `$ARGUMENTS` contains `platform`. Generates platform-specific configuration files from CodeClaw skill definitions so that other AI coding tools can consume the same skills.

Shorthand for the exporter script:

| Alias | Expands to |
|-------|------------|
| `PE`  | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/platform_exporter.py` |

### Step P1: Discover Skills

Run: `PE list-skills`

Present the list of discovered skills:
> **Found N CodeClaw skills:** task, idea, release, setup, ...
>
> These skills will be exported to the selected platform format.

### Step P2: Select Target Platform

**If `$ARGUMENTS` specifies a target** (e.g., `platform cursor`), use it directly and skip to Step P3.

**If `$ARGUMENTS` is just `platform`**, use `AskUserQuestion`:
- **"OpenCode (opencode.json + JS wrappers)"**
- **"OpenClaw (AgentSkills SKILL.md)"**
- **"Cursor (.cursor/rules/*.mdc)"**
- **"Windsurf (.windsurf/rules/*.md)"**
- **"Continue (.continue/ assistants)"**
- **"GitHub Copilot (.github/copilot-instructions.md)"**
- **"AGENTS.md (universal standard)"**
- **"All platforms"**
- **"Cancel"**

STOP.

Map the choice to a target name: `opencode`, `openclaw`, `cursor`, `windsurf`, `continue`, `copilot`, `agents_md`, or `all`.

### Step P3: Select Output Directory

Use `AskUserQuestion`:
- **"Current project directory (recommended)"** — use `.` (the project root)
- **"Custom directory (I will specify)"** — wait for free-text input

STOP.

### Step P4: Run Export

**If target is a single platform:**
```bash
PE export --target <target> --output <output_dir>
```

**If target is "all":**
```bash
PE export-all --output <output_dir>
```

Capture the JSON output.

### Step P5: Report Results

Parse the JSON result and present:
> **Platform export complete:**
> - **Target:** <platform name>
> - **Skills exported:** N
> - **Files created/updated:** list each file path
> - **Files unchanged:** (already up to date)
>
> **Note:** The export is idempotent. Re-running will update files only when skill content changes.

If errors occurred, present them and ask the user how to proceed.

### Step P6: Post-Export Guidance

Based on the target, provide platform-specific next steps:

- **OpenCode:** "Add `opencode.json` to your project root. OpenCode will discover plugins from `.opencode/plugins/`."
- **OpenClaw:** "Register skills with ClawHub if desired: `openclaw publish .openclaw/skills/<name>`"
- **Cursor:** "Rules will be loaded automatically from `.cursor/rules/`. Set `alwaysApply: true` in the MDC frontmatter for rules you want active by default."
- **Windsurf:** "Rules will be loaded from `.windsurf/rules/`. Restart Windsurf to pick up new rules."
- **Continue:** "Assistants are available in `.continue/assistants/`. Restart Continue to load them."
- **Copilot:** "Instructions file at `.github/copilot-instructions.md` will be used by Copilot in agent mode."
- **AGENTS.md:** "The `AGENTS.md` file is read by multiple AI tools (Codex, OpenAI agents, etc.) as project context."

---

## Important Rules

1. **NEVER overwrite existing files** — only create missing files or update specific sections
2. **Use exact formatting** — 80 `=` for section headers, 78 `-` for task separators
3. **All output in English**
4. **NEVER guess values** — use only what is detected. Use `[TODO]` for unknowns.
5. **NEVER modify `<!-- CodeClaw:START -->` / `<!-- CodeClaw:END -->` content**
6. **NEVER overwrite manual edits** — present detected values alongside existing, let user choose
7. **NEVER expose secret values** — names and descriptions only
8. **Always read files before updating**; preserve existing CLAUDE.md structure
9. **Idempotent** — multiple runs produce the same result
10. **Init Flow:** NEVER scaffold without confirmation; ALWAYS update CLAUDE.md, generate Makefile/scripts, verify scaffold succeeded; respect user's stack choice; prefer non-interactive flags
11. **Do NOT enter infinite loops** — on failure, present error and let user decide
