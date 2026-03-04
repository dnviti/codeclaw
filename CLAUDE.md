# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Language

Always respond and work in English, even if the user's prompt is written in another language.

## Development Commands

```bash
# [TODO: Add your project's development commands here]
# Example:
# npm run dev          # Start development server
# npm run build        # Build for production
# npm run test         # Run tests

# Code quality & verification
# [TODO: Define your verify command — e.g., npm run verify, make check, etc.]
# This command should run typecheck, lint, audit, and build in sequence.
```

**Important:** Your project's verify command must pass before closing any task. Define it above and reference it throughout the skills.

## Environment Setup

<!-- [TODO: Describe how to set up the development environment] -->
<!-- Example: Copy `.env.example` to `.env`. Install dependencies with `npm install`. -->

## Architecture

<!-- [TODO: Describe your project's architecture here] -->
<!-- Example:
**Monorepo** with workspaces: `backend/` and `frontend/`.

### Backend
- Entry point, framework, ORM, middleware, etc.
- Key file paths and patterns

### Frontend
- Framework, state management, routing, etc.
- Key file paths and patterns
-->

## Key Patterns

### Task Files

Tasks are split across three files by status:

| File | Status | Symbol |
|------|--------|--------|
| `to-do.txt` | Pending tasks | `[ ]` |
| `progressing.txt` | In-progress tasks | `[~]` |
| `done.txt` | Completed tasks | `[x]` |

When a task changes status, move it to the corresponding file.

### Idea Files

Ideas are stored separately from tasks and must be explicitly approved before entering the task pipeline:

| File | Purpose |
|------|---------|
| `ideas.txt` | Ideas awaiting evaluation |
| `idea-disapproved.txt` | Rejected ideas archive |

Use `/idea-create` to add ideas, `/idea-approve` to promote an idea to a task, `/idea-refactor` to update ideas based on codebase changes, and `/idea-disapprove` to reject an idea. Ideas must never be picked up directly by `/task-pick`.

### File Naming Conventions

<!-- [TODO: Define your project's file naming conventions] -->
<!-- Example:
| Layer | Pattern | Example |
|-------|---------|---------|
| Routes | `*.routes.ts` | `auth.routes.ts` |
| Controllers | `*.controller.ts` | `user.controller.ts` |
| Services | `*.service.ts` | `auth.service.ts` |
| Components | `*.tsx` | `Dashboard.tsx` |
| Stores | `*Store.ts` | `authStore.ts` |
| Hooks | `use*.ts` | `useAuth.ts` |
-->
