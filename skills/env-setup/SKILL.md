---
name: env-setup
description: "Scan the project to detect tech stack, dependencies, commands, and environment configuration, then update CLAUDE.md (Development Commands, Environment Setup, Architecture) and project-config.json accordingly."
disable-model-invocation: true
argument-hint: "[section to update: all | commands | setup | architecture | config]"
---

# Environment Setup Updater

You are an environment setup assistant. Your job is to scan the current project, detect its tech stack, dependencies, commands, services, and environment configuration, and then update CLAUDE.md and optionally `.claude/project-config.json` so that all CTDF skills work correctly with the project.

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
| `commands` | Development Commands in CLAUDE.md |
| `setup` | Environment Setup in CLAUDE.md |
| `architecture` | Architecture in CLAUDE.md |
| `config` | `.claude/project-config.json` only |

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

### Environment Variables
- [list of required env vars from .env.example, names only]

### External Services
- [list of services from docker-compose or "none detected"]

### Project Structure
[brief directory tree with purpose annotations]
```

Then STOP and use `AskUserQuestion` with these options:

- **"Looks correct, apply changes"** — proceed to Step 4
- **"Some values are wrong (I will correct them)"** — wait for corrections, re-present, and ask again
- **"Cancel"** — abort without changes

STOP HERE after calling `AskUserQuestion`. Do NOT proceed until the user confirms.

### Step 4: Apply Updates

Based on the confirmed scan results and the requested section(s), apply the updates below.

#### 4a. Update Development Commands (section: `commands` or `all`)

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

#### 4b. Update Environment Setup (section: `setup` or `all`)

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

#### 4c. Update Architecture (section: `architecture` or `all`)

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

#### 4d. Update Project Config (section: `config` or `all`)

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
| `tech_detail_layers` | Detected architectural layers |
| `github_repo_url` | Detected from git remote |
| `release_branch` | `develop` if exists, else `main` |

Leave fields empty if no value was detected — do not guess.

### Step 5: Post-Update Verification

After applying changes:

1. **Re-read CLAUDE.md** and verify it is well-formed (no broken markdown, no duplicate sections, no orphaned markers).
2. **Verify `.claude/project-config.json`** is valid JSON (if it was created or updated).
3. **Check for conflicts** with the `<!-- CTDF:START -->` / `<!-- CTDF:END -->` markers — never modify content inside these markers.

### Step 6: Report

Present a summary of all changes made:

```
## Environment Setup Updated

### Changes Applied
- [list of sections updated in CLAUDE.md]
- [project-config.json: created / updated / skipped]

### CLAUDE.md Sections Updated
| Section | Status |
|---------|--------|
| Development Commands | [Updated / Skipped / No changes needed] |
| Environment Setup | [Updated / Skipped / No changes needed] |
| Architecture | [Updated / Skipped / No changes needed] |

### Next Steps
1. Review the updated CLAUDE.md to verify accuracy
2. Fill in any `[TODO]` placeholders that could not be auto-detected
3. Run `/ctdf:app-start` to verify the dev server configuration works
4. (Optional) Run `/ctdf:docs claude-md` to further refine CLAUDE.md
```

## Important Rules

1. **NEVER guess values** — only use what is actually detected from project files. If something cannot be detected, leave it empty or mark it as `[TODO]`.
2. **NEVER modify content inside `<!-- CTDF:START -->` / `<!-- CTDF:END -->` markers** — those are managed by the setup skill.
3. **NEVER overwrite manual edits** — if a section already has content that looks manually written (not a TODO placeholder), present the detected values alongside existing values and let the user choose.
4. **NEVER expose secret values** — when documenting environment variables, list variable names and descriptions only, never actual values.
5. **Always read files before updating** — never edit a file you haven't read in the current session.
6. **Preserve existing CLAUDE.md structure** — only update the specific sections being targeted. Do not reorder, remove, or add unrelated sections.
7. **All output must be in English.**
8. **Idempotent operation** — running this skill multiple times should produce the same result if the project hasn't changed.
