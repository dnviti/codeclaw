# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [3.5.2] - 2026-03-18

### Added
- opt-in vector memory MCP with seamless setup installation (VMEM-0029) (#105)

### Fixed
- migrate MCP server to FastMCP API and harden .gitignore entries
- enable Ollama tool call offloading with 0-10 level control (OLLAM-0030)

## [3.5.1] - 2026-03-18

### Added
- sync release-state to platform issue in platform-only mode (REL-0028) (#97)
- add Ollama tool calling with full /api/chat loop (OLLAM-0027) (#90)
- mandatory vector memory always-on (VMEM-0024) (#78)
- configurable Ollama offloading level 0-10 (OLLAM-0023) (#79)
- add memory config and social posting steps to setup wizard (SETUP-0026) (#83)

### Fixed
- NFKC Unicode normalization for exclude-pattern bypass hardening (RPAT-v3.5.1-3) (#94)
- VMEM-0024 patch — refactor _Args, pin pip deps (RPAT-v3.5.1-2) (#86)
- OLLAM-0023 patch — normalize scoring input, deduplicate level helper, harden exclude patterns, add api_base warning (RPAT-v3.5.1-1) (#87)
- merge task branch into local develop on worktree removal (CodeClaw-0025) (#81)

## [3.5.0] - 2026-03-17

### Added
- multi-agent memory consistency protocol (VMEM-0019) (#73)
- local vector memory layer for semantic search (VMEM-0017) (#71)
- Ollama local model integration (OLLAM-0022) (#69)
- MCP server for vector memory access (VMEM-0018) (#72)
- post-release social media announcement (REL-0021) (#68)
- multiplatform support hardening (XPLAT-0020) (#70)

## [3.4.6] - 2026-03-17

### Added
- ZIP-based portable distribution (DIST-0014) (#59)
- universal platform abstraction layer (XPLAT-0013) (#57)
- cross-platform config generator (XPLAT-0015) (#58)
- ccpkg-compatible packaging (DIST-0016) (#60)
- add show_generated_footer toggle to project config (CFG-0012) (#41)

## [3.2.4] - 2026-03-17

### Added
- Add staging tag suffix to differentiate from production tags (REL-0011) (#37)
