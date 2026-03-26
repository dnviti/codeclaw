---
name: docs
description: "Generate, sync, reset, and publish project documentation. Produces LLM-ready, bot-ready, and human-ready technical documentation with Mermaid diagrams."
disable-model-invocation: true
argument-hint: "[generate] [sync] [reset] [publish] [yolo]"
---

> **CLAUDE.md IS LAW.** Before executing this skill, read the project's `CLAUDE.md`. If any instruction in this skill contradicts `CLAUDE.md`, **CLAUDE.md takes absolute priority**. Aliases, branch names, commands, conventions, and behavioral flags defined in `CLAUDE.md` override anything stated here. When in doubt, `CLAUDE.md` is the single source of truth.

# Documentation Manager

You are a documentation engineer for this project. You produce and maintain precise technical documentation that is equally useful to humans, LLMs, and bots.

Always respond and work in English.

**Every AskUserQuestion is a GATE — STOP and wait for user response before proceeding.**

## Context

`SH context` → platform config, worktree state, branch config as JSON. Use throughout.

## Arguments

`SH dispatch --skill docs --args "$ARGUMENTS"`

Returns `flow` and `yolo`:
- **`"generate"`**: Full documentation generation from codebase analysis (default).
- **`"sync"`**: Incremental update of stale sections only.
- **`"reset"`**: Remove all generated documentation.
- **`"publish"`**: Build and publish docs as a website.

Also returns `yolo: true/false` (see **Yolo Mode** in CLAUDE.md).

---

## Documentation Structure

Generated documentation lives in `docs/` with this layout:

| File | Purpose |
|------|---------|
| `index.md` | Landing page, table of contents, project summary |
| `architecture.md` | System architecture, component diagrams (Mermaid) |
| `getting-started.md` | Installation, prerequisites, first run |
| `configuration.md` | Environment variables, config files, feature flags |
| `api-reference.md` | Endpoints, functions, CLI commands |
| `deployment.md` | Build, Docker, CI/CD, production setup |
| `development.md` | Contributing, local dev, testing, branch strategy |
| `troubleshooting.md` | Common errors, debugging, FAQ |
| `llm-context.md` | Consolidated single-file for LLM/bot consumption |
| `.docs-manifest.json` | Machine-readable manifest for staleness tracking |

## Documentation Standards

Every generated doc file MUST follow these standards:

### Front-Matter Metadata

Every file starts with YAML front-matter:

```yaml
---
title: Architecture
description: System architecture, component interactions, and data flow
generated-by: claw-docs
generated-at: 2026-03-16T14:30:00Z
source-files:
  - src/app.ts
  - src/server.ts
---
```

### Content Requirements

1. **Why** — Explain the purpose and rationale behind design decisions
2. **What** — Describe components, features, and capabilities
3. **Which** — Specify technologies, dependencies, and alternatives considered
4. **When** — Document lifecycle events, triggers, and scheduling
5. **How** — Step-by-step instructions for every operation

### Mermaid Diagrams

Use Mermaid for all visual explanations:
- **Architecture**: `flowchart TD` for component diagrams
- **Data flow**: `flowchart LR` for request/response pipelines
- **Sequences**: `sequenceDiagram` for API interactions
- **Deployment**: `flowchart TD` for infrastructure and CI/CD pipelines
- **State**: `stateDiagram-v2` for lifecycle states

### LLM-Readiness

- Use structured headings (H2/H3) with consistent naming across all files
- Include machine-parseable front-matter metadata
- Write `llm-context.md` as a single consolidated file containing: project summary, architecture overview, key APIs, configuration reference, and quick-start commands
- Avoid ambiguous references — always use full paths, exact command names, and concrete examples

---

## Generate Flow

Full documentation generation from codebase analysis. Creates all sections from scratch.

**1.** Discover codebase:
```bash
DM discover
```

Parse result: `languages`, `frameworks`, `role_counts`, `entry_points`, `config_files`, `docs_exist`, `existing_sections`.

**2.** If `docs_exist` is `true` and sections already generated → GATE: "Documentation already exists. Overwrite all?" / "Run /docs sync instead" / "Cancel"

**2.5.** Choose visual richness level.

GATE via `AskUserQuestion` with header "Visual Richness":
- **"Zero — plain Markdown"** — No icons, images, or decorative elements. Clean, text-only output.
- **"Tiny — logo + emoticons (Recommended)"** — Markdown with a project logo image and Unicode emoticons as section markers.
- **"Moderate — HTML callouts, badges, icons"** — Embedded HTML within Markdown: badge shields, styled callout boxes, inline SVG icons.
- **"Large — full HTML-rich docs"** — Styled cards, collapsible sections, colored headers, comprehensive visual treatment.

Store the selection as `visual_richness_level` (`zero`, `tiny`, `moderate`, or `large`) for use in all subsequent generation steps.

**3.** Read CLAUDE.md for project-specific architecture, commands, and patterns.

**4.** Present analysis:

> **Codebase Analysis**
> - Languages: [list with file counts]
> - Frameworks: [detected]
> - Source files: N total (M entry points, K configs, J tests)
> - Sections to generate: 9

GATE: "Proceed with documentation generation" / "Adjust scope" / "Cancel"

**5.** Generate each documentation section. For each section:

**5a. Read all relevant source files** based on their role classification from `DM discover`. Map roles to sections:
- `architecture.md` ← entry_points, server, app, middleware, router files
- `getting-started.md` ← README, package manifests, Dockerfiles, Makefiles
- `configuration.md` ← config files, .env examples, environment schemas
- `api-reference.md` ← route, controller, handler, API client files
- `deployment.md` ← CI/CD configs, Dockerfiles, infra files, scripts
- `development.md` ← test files, lint configs, CLAUDE.md, CONTRIBUTING.md
- `troubleshooting.md` ← error handling code, logging, health check files

After role classification, perform semantic discovery for each section to find cross-cutting source files (logging, error handling, middleware, utilities) that don't fit a single role but are essential to the documentation:

```bash
DM semantic-discover --section <section_name> --top-k 10
```

Parse `discovered_files` from the result and read those files alongside the role-classified ones. These are files semantically related to the section's topic that the static role classification missed.

**5b. Write the section** following [Documentation Standards](#documentation-standards) and the `visual_richness_level` selected in Step 2.5.

**Tier-specific formatting rules:**

| Tier | Formatting |
|------|------------|
| **zero** | Standard Markdown only. No emoji, no images, no inline HTML. Plain headings, lists, code blocks, and Mermaid diagrams only. |
| **tiny** | Prepend each H2 section header with a relevant Unicode emoticon (e.g., `## Configuration`, `## Deployment`). In `index.md`, include `![Project Logo](assets/logo.svg)`. If no logo file exists at `docs/assets/logo.svg`, create a simple project SVG logo using inline SVG markup (geometric shape + project initials, saved via the Write tool). |
| **moderate** | All of **tiny**, plus: use HTML `<div class="callout callout-info">` / `callout-warning` / `callout-tip` blocks for important notes, tips, and warnings. Use `<img>` badge shields (e.g., `<img src="https://img.shields.io/badge/...">`) for version, status, and license indicators in `index.md`. Use `<table>` with styled headers where Markdown tables are insufficient for complex data. Use inline SVG icons for visual markers. |
| **large** | All of **moderate**, plus: wrap feature overviews in card-style `<div class="card">` layouts. Use `<details><summary>` collapsible sections for lengthy reference content (e.g., full API listings, exhaustive config tables). Use styled headers via `<h2 style="border-bottom: 2px solid #4A90D9; padding-bottom: 0.3em;">`. Use `<picture>` elements with light/dark mode variants where applicable. Add a CSS `<style>` block at the top of each file defining `.card`, `.callout`, `.badge` classes. |

All tiers include:
- YAML front-matter with title, description, generation timestamp, source files list (including semantically discovered files)
- Structured content with H2/H3 headings
- Mermaid diagrams where the section involves workflows or architecture
- Concrete code examples, exact file paths, real command names
- Write each file to `docs/<section>.md` using the Write tool

**5b-bis. Re-index documentation** — after writing all sections, trigger incremental re-indexing so the vector index includes the latest documentation content:

```bash
DM reindex-docs
```

This ensures that subsequent `/docs sync` runs and release pipeline GC (Stage 9d-bis) operate on an up-to-date index.

**5c. Track source files** — record which source files contributed to each section for the manifest. Include both role-classified and semantically discovered sources.

**6.** Generate `index.md`:
- Project title and description (from README/CLAUDE.md)
- Table of contents linking all sections
- Quick-start commands
- Technology stack summary

**7.** Generate `llm-context.md`:
- Consolidate key content from architecture, API reference, configuration, and getting-started into one document
- Add clear section separators
- Include a structured metadata header summarizing the project

**8.** Write manifest:
```bash
DM init-manifest --sections-json '[{"name":"architecture","file":"architecture.md","source_files":["src/app.ts",...]}]' --visual-richness <visual_richness_level>
```

Pass all sections with their contributing source files. The `--visual-richness` parameter persists the selected tier so that `/docs sync` preserves the same visual style.

**9.** Present report:

| Section | File | Lines | Sources |
|---------|------|-------|---------|
| Architecture | architecture.md | N | M files |
| ... | ... | ... | ... |

> Documentation generated in `docs/`. Run `/docs publish` to create a website.

---

## Sync Flow

Incremental documentation update. Only regenerates stale sections based on source file changes. This flow is called automatically by `/release` at Stage 7h.

**1.** Check for existing docs:
```bash
DM list-sections
```

If `docs_exist` is `false` → "No documentation found. Run `/docs generate` first." **STOP.**

**2.** Check staleness:
```bash
DM check-staleness
```

**2b.** If called during a release (release state exists), also check tag-based diff:
```bash
RM release-state-get
DM diff-since-tag --tag <latest_tag>
```

Use `affected_sections` to supplement staleness data.

**2c.** Supplement hash-based staleness with semantic similarity. Collect all changed source files from step 2 (and 2b if applicable), then run:

```bash
DM semantic-staleness --changed-files '["path/to/changed.py", ...]'
```

This detects when a change to a utility module affects a documentation section even if the utility is not in that section's tracked source list. Merge the `affected_sections` result with the staleness data from step 2.

**3.** If all sections are `current` (including after semantic staleness check) → "Documentation is up to date. No changes needed." **STOP.**

**4.** Present stale sections:

> **Documentation Sync — N section(s) need updating:**
>
> | Section | Status | Changed Sources |
> |---------|--------|-----------------|
> | architecture | stale | src/app.ts, src/routes.ts |
> | api-reference | stale | src/controllers/auth.ts |

GATE: "Update stale sections" / "Update all" / "Cancel"

**5.** For each stale section:
- Read the visual richness tier from the manifest: `DM get-visual-richness`. Apply the same tier-specific formatting rules from Generate Flow Step 5b.
- Read the existing doc file
- Read all changed source files
- Update the documentation to reflect changes, **preserving structure, tone, and visual richness tier**
- Update front-matter: `generated-at` timestamp, `source-files` list
- Write updated file using Edit tool

**6.** Update manifest:
```bash
DM init-manifest --sections-json '[...]'
```

**6b.** Re-index updated documentation into vector memory:
```bash
DM reindex-docs
```

**7.** Present report:

| Section | Status |
|---------|--------|
| architecture | Updated (3 source files changed) |
| api-reference | Updated (1 source file changed) |
| configuration | Current (no changes) |

---

## Reset Flow

Remove all generated documentation files.

**1.** List current docs:
```bash
DM list-sections
```

If no docs exist → "No documentation to reset." **STOP.**

**2.** Present what will be deleted:

> **The following documentation files will be deleted:**
> - docs/architecture.md (N lines)
> - docs/api-reference.md (M lines)
> - ...
> - docs/.docs-manifest.json

**3.** GATE: "Confirm reset — delete all generated docs" / "Cancel"

**Yolo mode does NOT auto-select this gate.** Always ask for confirmation on destructive operations.

**4.** Execute:
```bash
DM clean
```

**5.** Present: "Documentation reset. Run `/docs generate` to regenerate."

---

## Publish Flow

Build and publish documentation as a static website. Source is always Markdown — this flow adds a presentation layer on top.

**1.** Verify docs exist:
```bash
DM list-sections
```

If no docs → "No documentation found. Run `/docs generate` first." **STOP.**

**2.** Detect existing site generator:
```bash
DM detect-site-generator
```

**3a.** If generator detected:

> **Found [name] (config: [config_file])**
> Build: `[build_command]`
> Serve: `[serve_command]`

GATE: "Build with [name]" / "Choose a different generator" / "Cancel"

**3b.** If no generator detected:

> **No static site generator found.**
> Recommended: [name] — [reason]
> Install: `[install_command]`

GATE: "Install [recommended]" / "Choose another" / "Cancel"

After installation, generate a default configuration file pointing at the `docs/` directory.

**4.** Build:
Run the generator's build command. Present output.

On failure → GATE: "Fix and retry" / "Cancel"

**5.** GATE: "Preview locally" / "Skip to deploy instructions"

If preview: run the serve command, present the local URL.

**6.** Present deployment options:

> **Documentation site built successfully.**
>
> Deploy options:
> - **GitHub Pages**: push to `gh-pages` branch or configure Actions
> - **Manual**: upload build output from `[output_dir]/`
>
> The Markdown source in `docs/` remains the single source of truth.

---

## Important Rules

1. **Markdown is always the source of truth.** The publish flow adds a presentation layer but never modifies the source Markdown.
2. **Every generated file has YAML front-matter** with title, description, generation timestamp, and contributing source files.
3. **Mermaid diagrams are mandatory** for architecture, deployment pipelines, API flows, and any multi-step process.
4. **Sync never rewrites from scratch** — it reads the existing doc, reads changed sources, and updates only what changed.
5. **The manifest tracks provenance** — `.docs-manifest.json` records which source files contributed to each section and their hashes at generation time.
6. **Reset requires explicit confirmation** — yolo mode does not auto-confirm destructive operations.
7. **LLM-readiness is a first-class requirement** — structured headings, front-matter metadata, and the consolidated `llm-context.md` file ensure any agent can consume the docs.
8. **All output in English.**
9. **Concrete over abstract** — use real file paths, exact commands, actual config values. Never use placeholder text where real data is available.
10. **Documentation explains why, what, which, when, and how** — every section must address the purpose (why), the components (what), the technologies (which), the lifecycle (when), and the procedures (how).
