# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [4.0.0] - 2026-03-19

### Added
- [BETA] /crazy skill — fully autonomous end-to-end project builder (CRZY-0043) (#158)
- Unified memory orchestrator for tandem multi-backend coordination (MORC-0040) (#150)
- SQLite hybrid memory backend with FTS5 and sqlite-vec (SQLM-0038) (#149)
- RLM-style recursive context processing for deep memory analysis (RLM-0039) (#148)
- Event-sourced memory log for concurrent agent writes (VMEM-0030) (#146)
- Pluggable distributed lock backend for networked agent coordination (VMEM-0028) (#144)
- LLM-as-judge voting protocol for opinion conflict auto-resolution (VMEM-0029) (#143)
- GPU-accelerated ONNX inference for vector store embeddings (VMEM-0041) (#152)
- On-demand image generation with interactive preview (IMGN-0023) (#139)
- Frontend task design wizard with template search and color palette picker (FEND-0024) (#136)
- Enhance /task skill with semantic codebase exploration (VMEM-0033) (#141)
- Enhance /idea skill with vector-powered duplicate detection (VMEM-0034) (#162)
- Enhance /docs skill with semantic source discovery and visual richness tiers (VMEM-0036, DOCS-0045) (#142, #160)
- Enhance /tests skill with semantic gap analysis and test pattern discovery (VMEM-0035) (#147)
- Enhance /help skill with semantic search over skills and documentation (VMEM-0037) (#140)
- MCP vector memory toggleable via configuration parameter (MCP-0032) (#138)
- Cache branch topology and protection settings (CONF-0031) (#145)
- Edit flows for /task edit, /idea edit, and /release edit (EDIT-0044) (#157)
- Rebrand project from CodeClaw to CodeClaw with plugin id claw (REBR-0042) (#156)

### Fixed
- Add missing timeout parameter to FileLockBackend.__init__
- Resolve RLM model recommendations collision and restore export_context
- Resolve vector memory and MCP review findings (config caching, glob filtering, filter injection hardening)
- Resolve memory subsystem review findings (redundant reads, full UUID event IDs)
- Resolve RLM and ollama review findings (AST-based code validation, model recommendations consolidation)
- Resolve config, utility, and provider review findings (path validation, dynamic version read, duplicate run_cmd removal)
- Resolve task/docs/test manager review findings (magic number extraction, design decision documentation)
- Resolve skill definition review findings (security considerations, trust boundary documentation)
- Address security and optimization findings from PR review (#162)

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
