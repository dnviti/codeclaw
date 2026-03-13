---
name: project-initialization
description: Initialize a new project from scratch. Guides through choosing a tech stack, scaffolds the project, and configures the skills ecosystem.
disable-model-invocation: true
argument-hint: "[project purpose or stack]"
---

# Initialize a New Project

You are a project initialization assistant. Your job is to guide the user through setting up a new project from scratch — from understanding their needs to scaffolding the project and configuring the entire skills ecosystem so that all CTDF skills work correctly with the project.

## CRITICAL: User Interaction Rules

This skill requires multiple user decisions. At each `AskUserQuestion` call, you MUST:

1. **STOP completely** after calling `AskUserQuestion` — do NOT generate any further text or tool calls in the same turn
2. **WAIT for the user's actual response** before proceeding to the next step
3. **Never assume an answer** — if the response is empty or unclear, ask again with the same options
4. **Never batch multiple questions** — ask ONE question at a time and wait for each answer
5. **Only use the exact options specified** in each step — do not invent additional options or rephrase them

There are exactly 4-5 decision points in this skill (Steps 1, 2, 3, 4, and 5). Each one requires a full stop and wait.

## Current Directory State

### Existing files:
`python3 -c "from pathlib import Path; files=sorted(Path('.').iterdir()); [print(f.name) for f in files] if files else print('(empty directory)')"`

### Git status:
`git status --short 2>&1 || echo "(not a git repository)"`

### CLAUDE.md status:
`python3 -c "from pathlib import Path; p=Path('CLAUDE.md'); print(f'Exists ({len(p.read_text().splitlines())} lines)') if p.exists() else print('Not found')"`

## Arguments

The user invoked with: **$ARGUMENTS**

## Instructions

### Step 1: Understand the Project Purpose

Analyze `$ARGUMENTS` to determine the project's purpose. You need to understand these aspects:
1. **Purpose and domain** — What is the project for?
2. **Target audience** — Who will use it?
3. **Expected scale** — Prototype, small production, or large-scale?
4. **Deployment target** — Where will it run?
5. **Any specific requirements** — Real-time, multi-tenancy, offline, etc.

**If `$ARGUMENTS` provides enough context** (e.g., "React e-commerce app" or "Python CLI tool for data processing"), infer reasonable defaults for all 5 aspects and proceed directly to Step 2. Do NOT ask the user to restate what they already told you.

**If `$ARGUMENTS` is empty or too vague to determine even the project type**, you MUST STOP and use `AskUserQuestion` with these options:

- **"Web application (frontend + backend)"**
- **"API / backend service"**
- **"CLI tool / script"**
- **"Other (I will describe it)"**

STOP HERE after calling `AskUserQuestion`. Do NOT proceed to Step 2 until you have a clear understanding of the project type.

### Step 2: Suggest the Implementation Approach

Based on the user's answers, recommend a tech stack. Present it clearly:

```
## Recommended Stack

**Runtime:** [e.g., Node.js 22, Python 3.12, Go 1.22, Rust, Java 21]
**Framework:** [e.g., Next.js, FastAPI, Gin, Actix-web, Spring Boot]
**Database:** [e.g., PostgreSQL, SQLite, MongoDB, none]
**Styling:** [e.g., Tailwind CSS, CSS Modules, N/A]
**Package Manager:** [e.g., npm, pnpm, bun, pip, cargo, go modules]

**Rationale:** [2-3 sentences explaining why this stack fits the user's needs]
```

Present the recommended stack to the user, then STOP and use `AskUserQuestion` with these exact options:

- **"Looks good, use this stack"** — proceed to Step 3
- **"I want a different stack (I will specify)"** — wait for user to describe their preferred stack, then re-present
- **"Cancel"** — abort the initialization

STOP HERE after calling `AskUserQuestion`. Do NOT proceed to Step 3 until the user confirms the stack.

### Step 3: Research Scaffolding Options

Use `WebSearch` to find the best scaffolding tools and templates for the chosen stack. Search for:
- `"[framework] official starter template [current year]"`
- `"best way to scaffold [framework] project"`
- `"create [framework] app quickstart"`

Use `WebFetch` on the most promising results to extract the actual scaffolding commands and options.

Present your findings to the user as a numbered list:
1. **Official CLI / tool** — The framework's own scaffolding. Show the exact command, pros and cons.
2. **Community template** — A popular starter with extras. Show the exact command, pros and cons.
3. **Manual setup** — For full control over every dependency.

Then STOP and use `AskUserQuestion` with these exact options:

- **"Option 1: Official CLI"** — use the official scaffolding tool
- **"Option 2: Community template"** — use the community template
- **"Option 3: Manual setup"** — set up manually
- **"I have my own (I will provide the command)"** — wait for user input

STOP HERE after calling `AskUserQuestion`. Do NOT proceed to Step 4 until the user chooses a scaffolding approach.

### Step 4: Execute Scaffolding

**Before scaffolding:**
- Check the current directory state. If the directory is **not empty**, STOP and use `AskUserQuestion` with these options:
  - **"Scaffold here anyway"** — proceed in current directory
  - **"Scaffold in a subdirectory (I will name it)"** — wait for user to provide a directory name
  - **"Abort"** — cancel the initialization

  STOP HERE after calling `AskUserQuestion` if the directory is not empty. Do NOT proceed until the user responds.

- Prefer **non-interactive flags** when available.

**Execute** the chosen scaffolding command via `Bash`.

**After scaffolding:**
1. Verify the project structure was created: list key files and directories.
2. If dependencies were not installed by the scaffold, install them.
3. **Generate `.gitignore`:** Always generate a `.gitignore` for the chosen stack, even if the user skips git init:
   - Use `WebSearch` to find the official GitHub `.gitignore` template for the stack/framework (e.g., search for `"gitignore [language/framework] github"`)
   - Use `WebFetch` to download the template
   - If the scaffolding tool already created a `.gitignore`, merge the downloaded template with it — do not overwrite useful entries
   - If no suitable template is found online, generate a comprehensive `.gitignore` based on the stack

### Step 5: Initialize Git Repository

STOP and use `AskUserQuestion` with these exact options:

- **"Yes, initialize git"** — proceed with git init, .gitignore, and branch setup
- **"No, skip git"** — skip this step entirely

STOP HERE after calling `AskUserQuestion`. Do NOT proceed until the user responds.

**If the user chose "Yes, initialize git":**

1. **Get the `.gitignore`:**
   - Use `WebSearch` to find the official `.gitignore` template for the chosen stack/framework (e.g., search for `"gitignore [language/framework] github"` — GitHub maintains templates at `github/gitignore`).
   - Use `WebFetch` to download the appropriate `.gitignore` content.
   - If no suitable template is found online, generate a comprehensive `.gitignore` yourself based on the stack (e.g., `.env`, IDE files, OS files, build output).
   - If the scaffolding tool already created a `.gitignore`, merge the downloaded/generated one with it — do not overwrite useful entries already present.

2. **Initialize the repository:**
   ```bash
   git init
   ```

3. **Create branch structure:**
   - Create an initial commit on `main`:
     ```bash
     git add -A
     git commit -m "Initial project scaffold"
     ```
   - Create a `develop` branch and switch to it:
     ```bash
     git checkout -b develop
     ```
   - The `develop` branch is the **default working branch**. All development should happen here or in feature branches off `develop`.

4. **Report the git setup:**
   > "Git repository initialized:
   > - Branches: `main` (initial commit), `develop` (current, default working branch)
   > - `.gitignore` configured for [stack]"

**If the user chose "No, skip git":**
- Skip this step entirely. Do not initialize git.
- If the scaffolding tool already initialized a git repo, inform the user that the scaffold created one and ask if they want to keep it or remove it.

### Step 6: Configure the Project

This is the **critical integration step**. You must detect the project's configuration and write it to CLAUDE.md. Skills are generic and read their configuration from CLAUDE.md at runtime — no skill files need to be edited.

#### 6a. Detect Project Configuration

Read the scaffolded project's configuration files to detect:

| What to detect | Where to look |
|----------------|---------------|
| Dev server start command | Project manifest scripts section, task runner configs, process managers |
| Dev server port(s) | Project/framework config files, environment variables, container orchestration files |
| Pre-dev command | Container setup, database migrations, code generation steps, dependency installation |
| Verify/build command | Manifest-defined build/lint/test scripts, task runner targets |
| Test framework | Dev dependencies in project manifest, language-native test tooling |
| Test command | Manifest-defined test scripts, language-native test runners |
| Test file pattern | Existing test files in the repo (glob for common `test`/`spec` naming patterns) |
| CI runtime setup | Detect language runtime and version, map to CI provider setup step |
| Release branch | `develop` if exists, otherwise default branch |
| Manifest paths | Language-specific project manifests containing a version field |
| Changelog file | Default `CHANGELOG.md` |
| Tag prefix | Existing git tags or default `v` |
| Repo URL | `git remote get-url origin`, normalize to HTTPS |
| File naming conventions | Existing directory structure and naming patterns in the repo |

#### 6b. Update CLAUDE.md

Update CLAUDE.md with all detected values:

**Development Commands section:**
````markdown
## Development Commands

```bash
# Development
DEV_PORTS=[detected ports]                     # Port(s) the dev server listens on
START_COMMAND="[detected start command]"        # Command to start dev server
PREDEV_COMMAND="[detected predev or empty]"     # Optional pre-start setup (migrations, codegen, etc.)
VERIFY_COMMAND="[detected verify command]"      # Quality gate (lint + test + build)

# Testing
TEST_FRAMEWORK="[detected test framework]"     # e.g., Vitest, Jest, pytest, go test, RSpec, PHPUnit
TEST_COMMAND="[detected test command]"          # e.g., npm run test, pytest, go test ./..., bundle exec rspec
TEST_FILE_PATTERN="[detected pattern]"          # e.g., *.test.ts, test_*.py, *_test.go, *_spec.rb

# CI
CI_RUNTIME_SETUP="[detected CI setup step]"    # GitHub Actions setup step YAML (setup-node, setup-python, setup-go, etc.)

# Release
RELEASE_BRANCH="[detected release branch]"     # e.g., main, develop, master
MANIFEST_PATHS="[detected manifest paths]"      # Space-separated package manifests (package.json, pyproject.toml, Cargo.toml, go.mod, etc.)
CHANGELOG_FILE="[detected or CHANGELOG.md]"    # Changelog file path
TAG_PREFIX="[detected or v]"                    # Git tag prefix
GITHUB_REPO_URL="[detected HTTPS URL]"         # HTTPS repo URL

# Common commands:
# [actual install command]    — Install dependencies (npm ci, pip install, go mod download, bundle install, etc.)
# [actual dev command]        — Start development server
# [actual build command]      — Build for production
# [actual test command]       — Run tests
# [actual lint command]       — Run linter
```
````

**Environment Setup section:**
Update with prerequisites and setup instructions for the chosen stack.

**Architecture section:**
Update with the scaffolded project's structure overview, key entry points, and framework details.

**File Naming Conventions:**
Update with conventions from the framework if applicable.

#### 6c. Generate Makefile and Scripts

Generate a `Makefile` with targets based on detected commands:

```makefile
.PHONY: dev stop restart install build test lint verify

dev:
	[START_COMMAND]

stop:
	python3 <plugin-path>/scripts/app_manager.py stop --ports [DEV_PORTS]

restart: stop dev

install:
	[INSTALL_COMMAND]

build:
	[BUILD_COMMAND]

test:
	[TEST_COMMAND]

lint:
	[LINT_COMMAND]

verify:
	[VERIFY_COMMAND]
```

Also generate cross-platform scripts:
- `scripts/dev.sh` (Bash) — starts dev server with port management
- `scripts/dev.ps1` (PowerShell) — Windows equivalent

These scripts use `app_manager.py` from the plugin for cross-platform port management.

#### 6d. Create Changelog (if not exists)

If `CHANGELOG.md` does not exist, create it with the Keep a Changelog boilerplate:

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
```

### Step 7: Orientation Report

Present a comprehensive report to the user:

```
## Project Initialized Successfully

**Stack:** [framework] on [runtime]
**Directory:** [path]

### How to Get Started
1. [install command] — install dependencies (if not done already)
2. `make dev` or `[start command]` — start the dev server
3. Open http://localhost:[port] in your browser

### Project Structure
[Brief explanation of key directories and their purpose]

### Framework Limitations to Be Aware Of
- [Known limitation 1]
- [Known limitation 2]
- [Known limitation 3]

### How to Expand This Project
- **Add a database:** [brief guidance for the chosen stack]
- **Add authentication:** [brief guidance]
- **Add an API layer:** [brief guidance]
- **Add tests:** Use `/test-create` to generate tests
- **Run tests:** Use `/test-run` to execute tests
- **Security audit:** Use `/vulnerability-scout` to scan for vulnerabilities
- **Add CI/CD:** CI/CD templates are available in `${CLAUDE_PLUGIN_ROOT}/templates/` (see Step 9)

### Git Repository
- Branches: `main` (initial commit), `develop` (current working branch)
- `.gitignore`: configured for [stack]
- Workflow: develop on `develop`, merge to `main` for releases

### Makefile & Scripts
- `make dev` / `make stop` / `make restart` — dev server lifecycle
- `make test` / `make lint` / `make verify` — quality commands
- `scripts/dev.sh` / `scripts/dev.ps1` — cross-platform dev scripts

### Skills Available
The following CTDF skills are ready (they read configuration from CLAUDE.md):
- `/task-create`, `/task-pick` — task management with platform-agnostic issues tracker
- `/idea-create`, `/idea-approve` — idea pipeline
- `/test-scout`, `/test-create`, `/test-run`, `/test-review` — test lifecycle
- `/vulnerability-scout`, `/vulnerability-create`, `/vulnerability-report` — security auditing
- `/release` — semantic versioning, changelog, and tagging
- `/release plan` — release planning and task grouping
- `/docs` — documentation management
- `/idea-scout` — idea research and scouting
- `/code-optimize` — code quality analysis
```

### Step 8: Issues Tracker Integration (Optional)

After the orientation report, ask the user if they want to enable issues tracker integration (GitHub or GitLab) for task and idea tracking.

Use `AskUserQuestion` with these options:
- **"Yes, enable issues tracker"** — proceed with setup
- **"No, use local files only"** — skip this step

STOP HERE after calling `AskUserQuestion`. Do NOT proceed until the user responds.

**If the user chose "Yes, enable issues tracker":**

1. Ask which platform:
   Use `AskUserQuestion` to ask which platform:
   - **"GitHub"** — set `platform: "github"`
   - **"GitLab"** — set `platform: "gitlab"`

   STOP HERE after calling `AskUserQuestion`. Do NOT proceed until the user responds.

2. Copy the example config:
   ```bash
   cp ${CLAUDE_PLUGIN_ROOT}/config/issues-tracker.example.json .claude/issues-tracker.json
   ```

3. Ask the user for their repository (e.g., `user/project`):
   Use `AskUserQuestion` with a free-text prompt.

4. Update the config with the provided repo and platform:
   ```bash
   jq --arg repo "$REPO" --arg platform "$PLATFORM" '.repo = $repo | .platform = $platform | .enabled = true' .claude/issues-tracker.json > tmp.json && mv tmp.json .claude/issues-tracker.json
   ```

5. Ask the user about the sync mode:
   Use `AskUserQuestion` with these options:
   - **"Platform-only (no local task files)"** — set `sync: false`
   - **"Dual sync (local files + platform)"** — set `sync: true`

6. Run the label setup script:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup_labels.py
   ```

7. Report the issues tracker setup:
   > "Issues tracker integration enabled:
   > - Platform: [GitHub / GitLab]
   > - Repository: [repo]
   > - Mode: [Platform-only / Dual sync]
   > - Labels: created on [platform]
   > - All task/idea skills will now use [platform] issues"

### Step 9: CI/CD & Branch Protection Setup (Optional)

After the issues tracker step, ask the user if they want to set up CI/CD pipelines and branch protection.

Use `AskUserQuestion` with these options:
- **"Yes, set up CI/CD and branch protection"** — proceed with setup
- **"CI/CD only (no branch protection)"** — only copy workflow templates
- **"No, skip CI/CD setup"** — skip this step

STOP HERE after calling `AskUserQuestion`. Do NOT proceed until the user responds.

**If the user chose to set up CI/CD (either option):**

1. **Detect the platform** from the issues tracker config (default: GitHub).

2. **Copy CI/CD templates** to the project:
   - **GitHub:** Copy `${CLAUDE_PLUGIN_ROOT}/templates/github/workflows/*.yml` to `.github/workflows/`
   - **GitLab:** Copy `${CLAUDE_PLUGIN_ROOT}/templates/gitlab/.gitlab-ci.yml` to the project root

3. **Customize the templates** based on the detected stack from Steps 1-2:
   - Replace `[CI_RUNTIME_SETUP]` with the actual setup action (e.g., `actions/setup-node@v4`)
   - Replace `[INSTALL_COMMAND]`, `[LINT_COMMAND]`, `[TEST_COMMAND]`, `[BUILD_COMMAND]` with actual commands
   - Replace `[CI_IMAGE]` in GitLab templates with the appropriate Docker image
   - Uncomment the relevant sections and remove placeholder comments

4. **Copy additional templates:**
   - Copy `${CLAUDE_PLUGIN_ROOT}/templates/github/workflows/issue-triage.yml` for auto-labeling (if issues tracker is enabled)
   - Copy `${CLAUDE_PLUGIN_ROOT}/templates/github/workflows/status-guard.yml` for status transition enforcement (if issues tracker is enabled)
   - Copy `${CLAUDE_PLUGIN_ROOT}/templates/github/CODEOWNERS` to `.github/CODEOWNERS` and remind the user to replace `@your-org/platform-team`

**If the user also chose branch protection:**

5. **Run the branch protection setup script:**
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/setup_protection.py --branch main --required-reviews 1 --status-checks "Lint, Test & Build"
   ```

6. **Report the CI/CD setup:**
   > "CI/CD and branch protection configured:
   > - CI pipeline: runs lint, test, build on every PR
   > - Security scanning: dependency review + secret scanning on PRs, weekly SAST
   > - Release pipeline: auto-creates releases on version tags
   > - Issue triage: auto-labels new issues with type and priority
   > - Status guard: enforces status:todo → in-progress → to-test → done transitions
   > - Branch protection: PRs required, status checks enforced, force-push blocked
   > - CODEOWNERS: protects workflow files (update team names in .github/CODEOWNERS)"

## Important Rules

1. **NEVER scaffold without explicit user confirmation** of both the stack and the scaffolding tool.
2. **NEVER overwrite existing project files** — if the directory is not empty, warn the user and ask how to proceed.
3. **ALWAYS update CLAUDE.md** with all detected configuration values after scaffolding.
4. **ALWAYS generate a Makefile and dev scripts** for the project's detected commands.
5. **ALWAYS verify the scaffold succeeded** by checking that key files exist before reporting success.
6. **Use the project root directory** (current working directory) for scaffolding unless the user specifies otherwise.
7. **Respect user choice** — if the user wants a specific stack or tool, use it even if you would recommend differently.
8. **All output must be in English** — all reports, CLAUDE.md content, and skill configurations must be in English.
9. **Prefer non-interactive scaffolding** — use flags to avoid interactive prompts when possible.
10. **Do NOT enter an infinite loop** — if scaffolding fails, present the error and let the user decide how to proceed.
