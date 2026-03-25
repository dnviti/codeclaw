# AGENTS.md

Project memory for AI agents. This file is automatically created by CodeClaw and referenced from CLAUDE.md. Agents should read this file for project context and update it as the project evolves.

## Project Overview

CodeClaw is a Claude Code plugin providing project-agnostic task and release management via 9 skills: `/task`, `/idea`, `/release`, `/setup`, `/docs`, `/tests`, `/update`, `/help`, and `/crazy`. It is designed to work across GitHub and GitLab, with local-only fallback, and supports Windows, macOS, and Linux.

## Architecture Decisions

- **Shared utilities in `scripts/common.py`**: Root detection (`find_project_root`, `get_main_repo_root`), CLAUDE.md parsing, JSON output, tag helpers, SKILL.md parsing, and project config loading are centralised here. All scripts import from `common.py` instead of defining their own copies.
- **Skill shorthand aliases and Yolo Mode defined in CLAUDE.md**: Common preamble content (TM/SH/RM/PM/DM/SA/TESTS aliases and the canonical Yolo Mode definition) lives in CLAUDE.md so it is always in context. Individual skills no longer repeat these sections.
- **Worktree-based task isolation**: Tasks are developed in isolated git worktrees under `.worktrees/task/<code>/`, enabling parallel work without branch switching.
- **Platform abstraction**: A single `platform_adapter.py` with 4 adapter classes (claude_code, opencode, openclaw, generic) handles all supported AI coding platforms.
- **Optional vector memory**: Semantic search over code and tasks via LanceDB + ONNX embeddings. Disabled by default, enabled in `project-config.json`.
- **AGENTS.md is always created**: Setup flow creates AGENTS.md alongside CLAUDE.md without prompting. This file acts as persistent project memory for all agents.

## Key Patterns

- **Task files split by status**: `to-do.txt` (pending), `progressing.txt` (in-progress), `done.txt` (completed). Tasks move between files on status change.
- **Idea pipeline**: Ideas start in `ideas.txt`, get approved into tasks or moved to `idea-disapproved.txt`. Ideas never bypass the approval step.
- **Three platform modes**: Platform-only (GitHub/GitLab issues as source of truth), Dual sync (local files + platform), Local only (text files).
- **Scripts are CLI entry points**: Every Python file in `scripts/` can run standalone via `python3 scripts/<name>.py <subcommand>`. Skills invoke them via shorthand aliases.
- **Config hierarchy**: `.claude/project-config.json` > `config/project-config.json` > `project-config.json` (first found wins).

## Known Issues & Constraints

- `test_sqlite_lock_mutual_exclusion` is a flaky test due to SQLite thread contention — intermittent failures are expected and unrelated to code changes.
- The `/crazy` skill is marked BETA — context compaction during long runs may lose progress.
- Vector memory requires optional pip dependencies (`lancedb`, `onnxruntime`, `tokenizers`, `numpy`, `pyarrow`).

## Memory Log

<!-- Agents append context here as they learn about the project.
     Format: YYYY-MM-DD — [topic] — description -->

2026-03-24 — [optimization] — Consolidated duplicate utility functions from 8+ scripts into `scripts/common.py`. Removed dead code from `platform_utils.py`. Moved shorthand tables and yolo definition from 9 skills into CLAUDE.md. Condensed crazy skill agent prompts. Net savings: ~481 lines.
2026-03-24 — [agents-md] — Established AGENTS.md as mandatory project memory file. Setup flow always creates it alongside CLAUDE.md. CLAUDE.md references it via `@AGENTS.md`.
