---
name: project-initialization
description: Initialize a new project from scratch. Guides through choosing a tech stack, scaffolds the project, and configures the skills ecosystem.
disable-model-invocation: true
allowed-tools: Bash, Read, Write, Edit, Grep, Glob, AskUserQuestion, WebSearch, WebFetch
argument-hint: "[project purpose or stack]"
---

# Initialize a New Project

You are a project initialization assistant. Your job is to guide the user through setting up a new project from scratch — from understanding their needs to scaffolding the project and configuring the entire skills ecosystem so that `/app-start`, `/app-stop`, and `/app-restart` work out of the box.

## Current Directory State

### Existing files:
!`ls -la 2>/dev/null || echo "(empty directory)"`

### Git status:
!`git status --short 2>/dev/null || echo "(not a git repository)"`

### CLAUDE.md status:
!`test -f CLAUDE.md && echo "Exists ($(wc -l < CLAUDE.md) lines)" || echo "Not found"`

## Arguments

The user invoked with: **$ARGUMENTS**

## Instructions

### Step 1: Understand the Project Purpose

If `$ARGUMENTS` already provides a clear project description, use it as context. Otherwise, use `AskUserQuestion` to gather:

1. **Purpose and domain** — What is the project for? (e.g., e-commerce platform, CLI tool, REST API, portfolio site, mobile app, data pipeline)
2. **Target audience** — Who will use it? (developers, end-users, internal team)
3. **Expected scale** — Prototype, small production, or large-scale?
4. **Deployment target** — Where will it run? (Vercel, AWS, self-hosted, Docker, static hosting, desktop, mobile)
5. **Any specific requirements** — Real-time features, multi-tenancy, offline support, etc.

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

Use `AskUserQuestion` to let the user:
- Accept the recommendation
- Choose a different stack (let them specify)
- Provide more details to refine the recommendation

### Step 3: Research Scaffolding Options

Use `WebSearch` to find the best scaffolding tools and templates for the chosen stack. Search for:
- `"[framework] official starter template [current year]"`
- `"best way to scaffold [framework] project"`
- `"create [framework] app quickstart"`

Use `WebFetch` on the most promising results to extract the actual scaffolding commands and options.

Present **2-3 options** to the user via `AskUserQuestion`:

1. **Official CLI / tool** — The framework's own scaffolding tool (e.g., `create-next-app`, `cargo init`, `django-admin startproject`, `go mod init`)
   - Pros and cons
   - Exact command

2. **Community template** — A popular community starter with extras (auth, testing, CI)
   - Pros and cons
   - Exact command

3. **Custom / manual setup** — For full control over every dependency

4. **User's own** — Let the user provide their own scaffolding command or template URL

### Step 4: Execute Scaffolding

**Before scaffolding:**
- Check the current directory state. If the directory is **not empty**, warn the user and ask how to proceed (scaffold in a subdirectory, clean first, or abort).
- Prefer **non-interactive flags** when available (e.g., `npx create-next-app@latest . --typescript --yes`, `cargo init --name myapp`).

**Execute** the chosen scaffolding command via `Bash`.

**After scaffolding:**
1. Verify the project structure was created: list key files and directories.
2. If dependencies were not installed by the scaffold, install them.

### Step 5: Initialize Git Repository

Use `AskUserQuestion` to ask the user if they want to initialize a git repository for this project.

**If yes:**

1. **Get the `.gitignore`:**
   - Use `WebSearch` to find the official `.gitignore` template for the chosen stack/framework (e.g., search for `"gitignore [language/framework] github"` — GitHub maintains templates at `github/gitignore`).
   - Use `WebFetch` to download the appropriate `.gitignore` content.
   - If no suitable template is found online, generate a comprehensive `.gitignore` yourself based on the stack (e.g., `node_modules/`, `__pycache__/`, `target/`, `.env`, IDE files, OS files, build output).
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

**If the user declines git initialization:**
- Skip this step entirely. Do not initialize git.
- If the scaffolding tool already initialized a git repo, inform the user that the scaffold created one and ask if they want to keep it or remove it.

### Step 6: Configure the Skills Ecosystem

This is the **critical integration step**. You must configure CLAUDE.md and the app lifecycle skills so the entire system works for this specific project.

#### 5a. Detect Project Configuration

Read the scaffolded project's configuration files to detect:

| What to detect | Where to look |
|----------------|---------------|
| Dev server start command | `package.json` (scripts.dev/start), `Makefile`, `Cargo.toml`, `pyproject.toml`, `go.mod`, `Procfile` |
| Dev server port(s) | Framework config files, default port for the framework, `docker-compose.yml` |
| Pre-dev command | Docker setup, database migrations, codegen steps |
| Verify/build command | `package.json` (scripts.build/lint/test), `Makefile`, `Cargo.toml` |
| File naming conventions | Scaffolded directory structure and framework conventions |

#### 5b. Update CLAUDE.md

Update the Development Commands section with the actual detected values:

```markdown
## Development Commands

```bash
DEV_PORTS=[detected ports]                    # Port(s) the dev server listens on
START_COMMAND="[detected start command]"       # Command to start the dev server
PREDEV_COMMAND="[detected predev or empty]"    # Optional pre-start setup
VERIFY_COMMAND="[detected verify command]"     # Quality gate command

# Common commands:
# [actual install command]    — Install dependencies
# [actual dev command]        — Start development server
# [actual build command]      — Build for production
# [actual test command]       — Run tests
```
```

Also update:
- **Environment Setup** section with instructions for the chosen stack
- **Architecture** section with the scaffolded project's structure overview
- **File Naming Conventions** table if the framework has established conventions

#### 5c. Update App Lifecycle Skills

Edit the following skill files to configure them for this specific project:

- `.claude/skills/app-start/SKILL.md` — Update the configuration note with the actual DEV_PORTS, START_COMMAND, and PREDEV_COMMAND values
- `.claude/skills/app-stop/SKILL.md` — Update with the actual DEV_PORTS
- `.claude/skills/app-restart/SKILL.md` — Update with the actual DEV_PORTS, START_COMMAND, and PREDEV_COMMAND values

In each skill, replace the generic `[DEV_PORTS]`, `[START_COMMAND]`, and `[PREDEV_COMMAND]` placeholders in the bash code blocks with the actual project values, so the skills work without any manual configuration.

### Step 7: Orientation Report

Present a comprehensive report to the user:

```
## Project Initialized Successfully

**Stack:** [framework] on [runtime]
**Directory:** [path]

### How to Get Started
1. [install command] — install dependencies (if not done already)
2. [start command] — start the dev server
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
- **Add tests:** Use the `/test-engineer` skill
- **Add CI/CD:** Use the `/test-engineer` skill with CI focus

### Git Repository
- Branches: `main` (initial commit), `develop` (current working branch)
- `.gitignore`: configured for [stack]
- Workflow: develop on `develop`, merge to `main` for releases

### Skills Ecosystem Status
The following skills are now configured for your project:
- `/app-start` — starts your dev server on port [port]
- `/app-stop` — stops your dev server
- `/app-restart` — restarts your dev server
- `/task-create`, `/task-pick` — manage your development tasks
```

## Important Rules

1. **NEVER scaffold without explicit user confirmation** of both the stack and the scaffolding tool.
2. **NEVER overwrite existing project files** — if the directory is not empty, warn the user and ask how to proceed.
3. **ALWAYS update CLAUDE.md** with DEV_PORTS, START_COMMAND, PREDEV_COMMAND, and VERIFY_COMMAND after scaffolding.
4. **ALWAYS update the app lifecycle skills** (app-start, app-stop, app-restart) with project-specific values.
5. **ALWAYS verify the scaffold succeeded** by checking that key files exist before reporting success.
6. **Use the project root directory** (current working directory) for scaffolding unless the user specifies otherwise.
7. **Respect user choice** — if the user wants a specific stack or tool, use it even if you would recommend differently.
8. **All output must be in English** — all reports, CLAUDE.md content, and skill configurations must be in English.
9. **Prefer non-interactive scaffolding** — use flags to avoid interactive prompts when possible.
10. **Do NOT enter an infinite loop** — if scaffolding fails, present the error and let the user decide how to proceed.
