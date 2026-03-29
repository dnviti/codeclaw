# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [4.0.5] - 2026-03-29

### Added
- make CodeClaw platform-agnostic — remove legacy Claude-specific coupling
- add explicit release workflow sections to all 9 skills
- enforce project configuration as authoritative source of truth across all skills

### Fixed
- remove hardcoded isolation worktree from release workflow tables
## [4.0.4] - 2026-03-28

### Added
- Make CodeClaw platform-agnostic: remove legacy Claude-specific coupling from all 9 skills
- Add `load_config()` to common.py reading project-config.json
- Add `skills.sh` as canonical platform-agnostic installer
- Extract release coordination documentation to a standalone page
- Add `development_branch`, `staging_branch`, `production_branch` to project-config.example.json

### Changed
- Replace `${CLAUDE_PLUGIN_ROOT}` with `${CLAW_ROOT}` across all files
- Replace legacy source-of-truth wording with project configuration guidance in all skills
- Remove release workflow sections from all 9 skills
- Default install platform changed from claude-code to generic
- Update skill_helper.py, release_manager.py, test_manager.py to use load_config()
- Mark the legacy plugin template optional
- Simplify the public documentation surface and remove legacy references from the docs navigation
- Make `/docs` generation and sync rely on manifest-based discovery and hash-based staleness only

## [Earlier Releases]

Earlier release history has been archived in git to keep this changelog focused on the current supported surface.
- add show_generated_footer toggle to project config (CFG-0012) (#41)

## [3.2.4] - 2026-03-17

### Added
- Add staging tag suffix to differentiate from production tags (REL-0011) (#37)
