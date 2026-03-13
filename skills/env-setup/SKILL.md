---
name: env-setup
description: "Scan the project to detect tech stack, dependencies, commands, and environment configuration, then update CLAUDE.md sections, skill file placeholders, and project-config.json accordingly."
disable-model-invocation: true
argument-hint: "[section to update: all | commands | setup | architecture | config]"
---

# Environment Setup Updater

You are an environment setup assistant. Your job is to scan the current project, detect its tech stack, dependencies, commands, services, and environment configuration, and then update CLAUDE.md, skill file placeholders, and optionally `.claude/project-config.json` so that all CTDF skills work correctly with the project.

This skill fills the gap left by `/ctdf:project-initialization` — it re-detects and updates everything that project-initialization would have set, for projects that have already been scaffolded or have evolved since initial setup.

## CRITICAL: User Interaction Rules

This skill requires user confirmation before applying changes. At each `AskUserQuestion` call, you MUST:

1. **STOP completely** after calling `AskUserQuestion` — do NOT generate any further text or tool calls in the same turn
2. **WAIT for the user's actual response** before proceeding
3. **Never assume an answer** — if the response is empty or unclear, ask again

## Current Environment State

### OS and runtime:
`python3 -c "import platform; print(f'OS: {platform.system()} {platform.release()}'); import shutil; [print(f'{cmd}: {shutil.which(cmd) or \"not found\"}') for cmd in ['node','npm','npx','pnpm','bun','yarn','python3','pip','pip3','cargo','go','java','mvn','gradle','dotnet','php','composer','ruby','gem']]"`

### Project root files:
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/task_manager.py find-files --patterns "package.json,pyproject.toml,Cargo.toml,go.mod,go.sum,Makefile,Dockerfile,docker-compose.yml,docker-compose.yaml,.env,.env.example,.env.sample,requirements.txt,Pipfile,poetry.lock,pnpm-lock.yaml,yarn.lock,bun.lockb,Gemfile,build.gradle,pom.xml,*.sln,*.csproj,composer.json" --max-depth 2 --limit 40`

### CLAUDE.md status:
`python3 -c "from pathlib import Path; p=Path('CLAUDE.md'); print(p.read_text()) if p.exists() else print('Not found')"`

### Project config status:
`python3 -c "from pathlib import Path; p=Path('.claude/project-config.json'); print(p.read_text()) if p.exists() else print('Not found')"`

### Git remote:
`git remote get-url origin 2>&1 || echo "(no remote configured)"`

### Existing branches:
`git branch --list 2>&1 | head -10`

### Existing git tags:
`git tag -l 2>&1 | tail -5 || echo "(no tags)"`

## Arguments

The user invoked with: **$ARGUMENTS**

## Instructions

### Step 1: Parse Arguments

Extract the **section** from `$ARGUMENTS`:
- Valid sections: `all`, `commands`, `setup`, `architecture`, `config`
- If empty or not provided, default to `all`

| Section | What it updates |
|---------|-----------------|
| `all` | Everything below (default) |
| `commands` | Development Commands in CLAUDE.md + app lifecycle skills + test-engineer skill |
| `setup` | Environment Setup in CLAUDE.md |
| `architecture` | Architecture in CLAUDE.md + task-create, idea-approve, idea-create, docs, task-scout skills |
| `config` | `.claude/project-config.json` + release, git-publish, task-pick skills |

### Step 2: Deep Scan the Project

Perform a thorough scan of the project to detect the following. Read the actual files — do NOT guess.

#### 2a. Package Manager & Dependencies

Read the primary manifest file(s) to detect:

| What | Where to look |
|------|---------------|
| Package manager | `package.json` (npm/pnpm/yarn/bun), `pyproject.toml` (pip/poetry/pdm), `Cargo.toml` (cargo), `go.mod` (go), `Gemfile` (bundler), `composer.json` (composer), `pom.xml`/`build.gradle` (maven/gradle) |
| Install command | Derived from package manager (e.g., `npm install`, `pip install -r requirements.txt`, `cargo build`) |
| Lock file | `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `bun.lockb`, `poetry.lock`, `Pipfile.lock`, `Cargo.lock`, `go.sum`, `Gemfile.lock`, `composer.lock` |
| Workspaces | `package.json` workspaces field, `pnpm-workspace.yaml`, Cargo workspace members |

#### 2b. Development Commands

Read manifest and config files to detect:

| What | Where to look |
|------|---------------|
| Dev server command | `package.json` scripts (`dev`, `start`, `serve`), `Makefile` targets, `Procfile`, `pyproject.toml` scripts |
| Build command | `package.json` scripts (`build`), `Makefile`, `Cargo.toml`, `go build` |
| Test command | `package.json` scripts (`test`), `pytest.ini`/`pyproject.toml` `[tool.pytest]`, `Cargo.toml`, `go test` |
| Lint command | `package.json` scripts (`lint`), `.eslintrc*`, `ruff.toml`, `pyproject.toml` `[tool.ruff]`, `clippy` |
| Format command | `package.json` scripts (`format`, `prettier`), `pyproject.toml` `[tool.black]`/`[tool.ruff.format]` |
| Type check command | `package.json` scripts (`typecheck`, `tsc`), `tsconfig.json`, `mypy.ini`, `pyproject.toml` `[tool.mypy]` |
| Verify/quality gate | `package.json` scripts (`verify`, `check`, `ci`), `Makefile` `check`/`ci` target |

#### 2c. Dev Server & Ports

Detect dev server ports from:

| Where | How |
|-------|-----|
| Framework config | `vite.config.*` (server.port), `next.config.*`, `webpack.config.*` (devServer.port), `angular.json` |
| Environment files | `.env*` files containing `PORT=` |
| Docker Compose | `docker-compose.yml` ports mappings |
| Manifest scripts | Commands containing `--port` or `-p` flags |
| Framework defaults | Known defaults: Vite=5173, Next.js=3000, Django=8000, Flask=5000, Rails=3000, Spring=8080, Go=8080 |

#### 2d. Environment Variables & Services

Detect from `.env*` files, `docker-compose.yml`, and config files:

| What | What to look for |
|------|------------------|
| Required env vars | Variables in `.env.example` or `.env.sample` |
| Database | `DATABASE_URL`, `DB_*`, `POSTGRES_*`, `MONGO_*`, `MYSQL_*`, `REDIS_*` in env files; database services in docker-compose |
| External services | Docker Compose services (redis, elasticsearch, rabbitmq, etc.) |
| Auth/secrets | `SECRET_KEY`, `JWT_SECRET`, `API_KEY` patterns (document the variable names only, never values) |

#### 2e. Architecture & Project Structure

Detect project structure by reading directory layout:

| What | How |
|------|-----|
| Framework | Package dependencies, config files (`next.config.*`, `vite.config.*`, `angular.json`, `settings.py`, etc.) |
| Directory structure | Top-level directories and their purpose (e.g., `src/`, `app/`, `pages/`, `api/`, `lib/`, `components/`, `tests/`) |
| Entry points | Main files (`index.ts`, `main.py`, `main.go`, `App.tsx`, `manage.py`, etc.) |
| Configuration files | Build, bundler, formatter, linter config files |

#### 2f. Pre-dev Setup Requirements

Detect any setup that must run before development:

| What | Where |
|------|-------|
| Database migrations | `prisma/`, `alembic/`, `django` `manage.py migrate`, `knex`, `sequelize` |
| Code generation | `prisma generate`, `graphql-codegen`, `protoc`, `openapi-generator` |
| Docker services | `docker-compose.yml` with required services |
| Build steps | `Makefile` prerequisites, pre-build scripts |

#### 2g. Test Framework Details

Detect test framework configuration:

| What | Where to look |
|------|---------------|
| Test framework | `package.json` devDependencies (vitest, jest, mocha), `pyproject.toml` (pytest), `Cargo.toml` (built-in), `go.mod` (built-in) |
| Test command | `package.json` scripts (`test`), `pytest` command, `cargo test`, `go test ./...` |
| Test file pattern | Framework conventions: `*.test.ts`, `*.spec.ts`, `test_*.py`, `*_test.go`, etc. |
| CI runtime setup | Detect runtime version and map to GitHub Actions setup step (e.g., `actions/setup-node@v4` with node version from `package.json` engines or `.nvmrc`) |

#### 2h. Release Configuration

Detect release-related configuration:

| What | Where to look |
|------|---------------|
| Manifest paths | All `package.json`, `Cargo.toml`, `pyproject.toml` files containing a version field (exclude `node_modules`, `target`, `.venv`) |
| Changelog file | `CHANGELOG.md` in project root (default path) |
| Tag prefix | Existing git tags (`git tag -l`), default: `v` |
| Repo URL | `git remote get-url origin` or `package.json` `repository.url` — convert SSH to HTTPS |
| Release branch | `develop` if that branch exists, otherwise `main` |

### Step 3: Present Findings

Present a clear summary of everything detected:

```
## Environment Scan Results

### Tech Stack
- **Runtime:** [detected runtime and version]
- **Framework:** [detected framework and version]
- **Package Manager:** [detected package manager]
- **Database:** [detected database or "none detected"]

### Development Commands
| Command | Value |
|---------|-------|
| Install | `[detected]` |
| Dev server | `[detected]` |
| Build | `[detected]` |
| Test | `[detected]` |
| Lint | `[detected]` |
| Format | `[detected]` |
| Type check | `[detected]` |
| Verify | `[detected]` |

### Dev Server
- **Port(s):** [detected ports]
- **Pre-dev command:** [detected or "none"]

### Test Framework
- **Framework:** [detected test framework]
- **Test command:** [detected test command]
- **File pattern:** [detected test file pattern]
- **CI runtime setup:** [detected GitHub Actions setup step]

### Release Configuration
- **Manifest paths:** [detected paths]
- **Changelog:** [detected or "CHANGELOG.md (default)"]
- **Tag prefix:** [detected or "v (default)"]
- **Repo URL:** [detected]
- **Release branch:** [detected]

### Environment Variables
- [list of required env vars from .env.example, names only]

### External Services
- [list of services from docker-compose or "none detected"]

### Architecture Layers
[list of detected architectural layers with directories]

### Project Structure
[brief directory tree with purpose annotations]
```

Then STOP and use `AskUserQuestion` with these options:

- **"Looks correct, apply changes"** — proceed to Step 4
- **"Some values are wrong (I will correct them)"** — wait for corrections, re-present, and ask again
- **"Cancel"** — abort without changes

STOP HERE after calling `AskUserQuestion`. Do NOT proceed until the user confirms.

### Step 4: Apply Updates

Based on the confirmed scan results and the requested section(s), apply the updates below. **Always read each file before editing it.**

#### 4a. Update CLAUDE.md Sections

##### Development Commands (section: `commands` or `all`)

Replace the `## Development Commands` section in CLAUDE.md with the detected values:

```markdown
## Development Commands

```bash
DEV_PORTS=[detected ports]                    # Port(s) the dev server listens on
START_COMMAND="[detected start command]"       # Command to start the dev server
PREDEV_COMMAND="[detected predev or empty]"    # Optional pre-start setup (migrations, docker, codegen)
VERIFY_COMMAND="[detected verify command]"     # Quality gate command (lint + test + build)

# Common commands:
# [install command]              — Install dependencies
# [dev command]                  — Start development server
# [build command]                — Build for production
# [test command]                 — Run tests
# [lint command]                 — Run linter
# [format command]               — Format code
# [typecheck command]            — Type checking
```
```

Only include commands that were actually detected. Omit lines for commands that don't exist in the project.

##### Environment Setup (section: `setup` or `all`)

Replace the `## Environment Setup` section in CLAUDE.md with clear setup instructions based on what was detected:

```markdown
## Environment Setup

### Prerequisites
- [runtime] [version] (required)
- [package manager] (required)
- [other tools like Docker, if detected]

### First-Time Setup
1. [Install dependencies command]
2. [Copy .env.example to .env, if applicable]
3. [Database setup/migration, if applicable]
4. [Docker services startup, if applicable]
5. [Code generation steps, if applicable]

### Environment Variables
[Table of required variables from .env.example with descriptions, NO values]

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Database connection string |
| `SECRET_KEY` | Application secret key |
| ... | ... |
```

Only include subsections that are relevant. If no env vars were detected, omit the Environment Variables subsection. If no Docker services, omit that step.

##### Architecture (section: `architecture` or `all`)

Replace the `## Architecture` section in CLAUDE.md with the detected project structure:

```markdown
## Architecture

### Project Structure
```
[directory tree with annotations]
```

### Key Entry Points
- [main entry point files and their purpose]

### Framework Details
- **Framework:** [name and version]
- **Routing:** [file-based / explicit / etc.]
- **State management:** [if applicable]
- **Styling:** [CSS approach if applicable]
```

Keep this section concise — only include what helps Claude Code navigate and understand the codebase.

#### 4b. Update Skill Files with Project-Specific Values

This mirrors project-initialization Step 6 (sections 5c-5d). Read each skill file, then replace the placeholders with detected values. **Only update skills relevant to the requested section.**

##### App Lifecycle Skills (section: `commands` or `all`)

Read and update these skill files in `${CLAUDE_PLUGIN_ROOT}/skills/`:

| Skill file | Placeholders to replace |
|-----------|------------------------|
| `app-start/SKILL.md` | `[DEV_PORTS]` → detected ports, `[START_COMMAND]` → detected start command, `[PREDEV_COMMAND]` → detected pre-dev command |
| `app-stop/SKILL.md` | `[DEV_PORTS]` → detected ports |
| `app-restart/SKILL.md` | `[DEV_PORTS]` → detected ports, `[START_COMMAND]` → detected start command, `[PREDEV_COMMAND]` → detected pre-dev command |

##### Test & CI Skill (section: `commands` or `all`)

| Skill file | Placeholders to replace |
|-----------|------------------------|
| `test-engineer/SKILL.md` | `[TEST_FRAMEWORK]` → detected test framework, `[TEST_COMMAND]` → detected test command, `[TEST_FILE_PATTERN]` → detected test file pattern, `[CI_RUNTIME_SETUP]` → detected GitHub Actions setup YAML block, `[RELEASE_BRANCH]` → detected release branch |

##### Architecture-Aware Skills (section: `architecture` or `all`)

| Skill file | Placeholders to replace |
|-----------|------------------------|
| `task-create/SKILL.md` | `[TECH_DETAIL_LAYERS]` → indented list of architectural layers with directories (e.g., `- App Router pages and layouts (app/)`) |
| `idea-approve/SKILL.md` | `[TECH_DETAIL_LAYERS]` → same as task-create |
| `idea-create/SKILL.md` | `[IDEA_CATEGORIES]` → markdown table of 3-4 universal categories (Core Features, Security, Performance, Infrastructure) + 2-3 project-domain categories derived from the detected framework and project structure |
| `docs/SKILL.md` | `[DOC_CATEGORIES]` → list of documentation categories derived from architectural layers (e.g., `api`, `database`, `components`, `architecture`, `deployment`) |
| `task-scout/SKILL.md` | `[PROJECT_CONTEXT]` → 3-line summary block with domain, tech stack, and target audience. `[SCOUT_CATEGORIES]` → category list combining universal + project-domain categories |

For `[PROJECT_CONTEXT]`, format as:
```
> - **Domain**: [detected project domain]
> - **Tech Stack**: [detected framework, database, key libraries]
> - **Target Audience**: [inferred from project type, or "General users"]
```

For `[IDEA_CATEGORIES]` and `[SCOUT_CATEGORIES]`, derive domain-specific categories from the project's purpose, framework, and directory structure. Always include universal categories alongside domain-specific ones.

##### Release & Git Skills (section: `config` or `all`)

| Skill file | Placeholders to replace |
|-----------|------------------------|
| `release/SKILL.md` | `[PACKAGE_JSON_PATHS]` → space-separated manifest paths, `[CHANGELOG_FILE]` → changelog path (default: `CHANGELOG.md`), `[TAG_PREFIX]` → tag prefix (default: `v`), `[GITHUB_REPO_URL]` → HTTPS repo URL, `[RELEASE_BRANCH]` → release branch |
| `git-publish/SKILL.md` | `[RELEASE_BRANCH]` → detected release branch |
| `task-pick/SKILL.md` | `[RELEASE_BRANCH]` → detected release branch |

When replacing `[GITHUB_REPO_URL]`, convert SSH URLs (`git@github.com:user/repo.git`) to HTTPS format (`https://github.com/user/repo`).

When replacing `[PACKAGE_JSON_PATHS]`, search for manifest files containing a `version` field in the project root and workspace directories, excluding `node_modules`, `target`, `.venv`, and other dependency directories.

**Important:** When replacing placeholders in skill files:
- Use the Edit tool to make targeted replacements
- Only replace `[PLACEHOLDER]` patterns — do not modify surrounding text
- If a placeholder has already been replaced with a real value, present the existing value alongside the new detected value and let the user choose (in Step 3)
- If a value could not be detected, leave the placeholder as-is and note it in the report

#### 4c. Update Project Config (section: `config` or `all`)

If `.claude/project-config.json` exists, update it with detected values. If it does not exist, create it by copying from `${CLAUDE_PLUGIN_ROOT}/config/project-config.example.json` and filling in detected values.

Map detected values to config fields:

| Config Field | Source |
|--------------|--------|
| `dev_ports` | Detected dev server ports |
| `start_command` | Detected dev server start command |
| `predev_command` | Detected pre-dev setup command |
| `verify_command` | Detected verify/quality gate command |
| `test_framework` | Detected test framework name |
| `test_command` | Detected test command |
| `test_file_pattern` | Detected test file naming pattern |
| `ci_runtime_setup` | Detected CI runtime setup YAML |
| `tech_detail_layers` | Detected architectural layers |
| `idea_categories` | Generated category table |
| `doc_categories` | Generated doc categories |
| `project_context` | Generated project context block |
| `scout_categories` | Generated scout categories |
| `package_json_paths` | Detected manifest paths |
| `changelog_file` | Detected or default `CHANGELOG.md` |
| `tag_prefix` | Detected or default `v` |
| `github_repo_url` | Detected HTTPS repo URL |
| `release_branch` | `develop` if exists, else `main` |
| `publish_skill` | Always `/git-publish` |

Leave fields empty if no value was detected — do not guess.

### Step 5: Post-Update Verification

After applying all changes:

1. **Re-read CLAUDE.md** and verify it is well-formed (no broken markdown, no duplicate sections, no orphaned markers).
2. **Verify `.claude/project-config.json`** is valid JSON (if it was created or updated):
   `python3 -c "import json; json.load(open('.claude/project-config.json')); print('Valid JSON')"`
3. **Check for CTDF marker integrity** — verify that no content inside `<!-- CTDF:START -->` / `<!-- CTDF:END -->` markers was modified.
4. **Spot-check skill files** — re-read 2-3 of the updated skill files and verify they still have valid markdown structure and the placeholders were replaced correctly.

### Step 6: Report

Present a summary of all changes made:

```
## Environment Setup Updated

### Changes Applied

#### CLAUDE.md Sections
| Section | Status |
|---------|--------|
| Development Commands | [Updated / Skipped / No changes needed] |
| Environment Setup | [Updated / Skipped / No changes needed] |
| Architecture | [Updated / Skipped / No changes needed] |

#### Skill Files Updated
| Skill | Placeholders Replaced |
|-------|----------------------|
| app-start | [DEV_PORTS], [START_COMMAND], [PREDEV_COMMAND] |
| app-stop | [DEV_PORTS] |
| app-restart | [DEV_PORTS], [START_COMMAND], [PREDEV_COMMAND] |
| test-engineer | [TEST_FRAMEWORK], [TEST_COMMAND], ... |
| task-create | [TECH_DETAIL_LAYERS] |
| ... | ... |

#### Project Config
- `.claude/project-config.json`: [Created / Updated / Skipped]

### Unreplaced Placeholders
[List any placeholders that could not be replaced because values were not detected]

### Next Steps
1. Review the updated CLAUDE.md to verify accuracy
2. Fill in any remaining `[TODO]` or `[PLACEHOLDER]` values that could not be auto-detected
3. Run `/ctdf:app-start` to verify the dev server configuration works
4. (Optional) Run `/ctdf:env-setup [section]` again to update specific sections
```

## Important Rules

1. **NEVER guess values** — only use what is actually detected from project files. If something cannot be detected, leave placeholders as-is or mark as `[TODO]`.
2. **NEVER modify content inside `<!-- CTDF:START -->` / `<!-- CTDF:END -->` markers** — those are managed by the setup skill.
3. **NEVER overwrite manual edits** — if a section already has content that looks manually written (not a TODO placeholder), or if a placeholder has already been replaced with a real value, present the detected values alongside existing values and let the user choose.
4. **NEVER expose secret values** — when documenting environment variables, list variable names and descriptions only, never actual values.
5. **Always read files before updating** — never edit a file you haven't read in the current session.
6. **Preserve existing CLAUDE.md structure** — only update the specific sections being targeted. Do not reorder, remove, or add unrelated sections.
7. **All output must be in English.**
8. **Idempotent operation** — running this skill multiple times should produce the same result if the project hasn't changed. Already-replaced placeholders should be detected and handled gracefully.
9. **Section-scoped updates** — only update skills and files relevant to the requested section. Do not touch unrelated skills when a specific section is requested.
10. **Skill files live in `${CLAUDE_PLUGIN_ROOT}/skills/`** — use the `${CLAUDE_PLUGIN_ROOT}` variable to locate them, not a hardcoded path.
