# AGENTS.md

Project memory for AI agents. This file is automatically created by CodeClaw. Agents should read this file for project context and update it as the project evolves.

## Project Overview

CodeClaw is a platform-agnostic skillset providing task and release management via 9 skills: `/task`, `/idea`, `/release`, `/setup`, `/docs`, `/tests`, `/update`, `/help`, and `/crazy`. It works across any AI coding platform (Claude Code, Cursor, Windsurf, Copilot, Aider, etc.), supports GitHub and GitLab with local-only fallback, and runs on Windows, macOS, and Linux.

## Architecture Decisions

- **Shared utilities in `scripts/common.py`**: Root detection (`find_project_root`, `get_main_repo_root`), config loading (`load_config`), JSON output, tag helpers, SKILL.md parsing, and project config loading are centralised here. All scripts import from `common.py` instead of defining their own copies.
- **Config-first architecture**: Project configuration lives in `project-config.json` (primary source). Skills read config via `SH context` and generated guidance lives in `project-context.md`.
- **Platform abstraction**: A single `platform_adapter.py` with 4 adapter classes (claude_code, opencode, openclaw, generic) handles all supported AI coding platforms.
- **Project-context guidance**: The setup flow creates `project-context.md` as the shared instructions file for agents and tools.
- **AGENTS.md is always created**: Setup flow creates AGENTS.md as persistent project memory for all agents.

## Key Patterns

- **Task files split by status**: `to-do.txt` (pending), `progressing.txt` (in-progress), `done.txt` (completed). Tasks move between files on status change.
- **Idea pipeline**: Ideas start in `ideas.txt`, get approved into tasks or moved to `idea-disapproved.txt`. Ideas never bypass the approval step.
- **Three platform modes**: Platform-only (GitHub/GitLab issues as source of truth), Dual sync (local files + platform), Local only (text files).
- **Scripts are CLI entry points**: Every Python file in `scripts/` can run standalone via `python3 scripts/<name>.py <subcommand>`. Skills invoke them via shorthand aliases.
- **Config hierarchy**: `.claude/project-config.json` > `config/project-config.json` > `project-config.json` (first found wins).

## Known Issues & Constraints

- `test_sqlite_lock_mutual_exclusion` is a flaky test due to SQLite thread contention — intermittent failures are expected and unrelated to code changes.
- The `/crazy` skill is marked BETA — context compaction during long runs may lose progress.
- Historical optional dependencies were removed from the supported surface.

## Memory Log

<!-- Agents append context here as they learn about the project.
     Format: YYYY-MM-DD — [topic] — description -->

2026-03-24 — [optimization] — Consolidated duplicate utility functions from 8+ scripts into `scripts/common.py`. Removed dead code from `platform_utils.py`. Moved shorthand tables and yolo definition from 9 skills into shared project guidance. Condensed crazy skill prompts. Net savings: ~481 lines.
2026-03-24 — [agents-md] — Established AGENTS.md as mandatory project memory file. Setup flow always creates it alongside the project guidance file.
