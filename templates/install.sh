#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# CTDF Portable Installer — POSIX Bootstrap
# ──────────────────────────────────────────────────────────────────────────────
#
# Auto-detects the target AI coding platform and installs CTDF files into
# the correct locations. Supports Claude Code, OpenCode, OpenClaw, Cursor,
# Windsurf, Continue, Copilot, Aider, and generic setups.
#
# Usage:
#   ./install.sh [OPTIONS]
#
# Options:
#   --platform PLATFORM   Force a specific platform (skip auto-detection)
#   --target DIR          Target project directory (default: current directory)
#   --link                Use symlinks instead of copies (default: copy)
#   --dry-run             Show what would be done without making changes
#   --help                Show this help message
#
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Constants ────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION=""
PLATFORM=""
TARGET_DIR=""
USE_LINKS=false
DRY_RUN=false

# Known platforms
PLATFORMS="claude-code opencode openclaw cursor windsurf continue copilot aider generic"

# ── Color helpers (auto-disable when not a terminal) ─────────────────────────

if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[0;33m'
    BLUE='\033[0;34m'
    BOLD='\033[1m'
    NC='\033[0m'
else
    RED='' GREEN='' YELLOW='' BLUE='' BOLD='' NC=''
fi

info()  { printf "${BLUE}[info]${NC}  %s\n" "$*"; }
ok()    { printf "${GREEN}[ok]${NC}    %s\n" "$*"; }
warn()  { printf "${YELLOW}[warn]${NC}  %s\n" "$*" >&2; }
err()   { printf "${RED}[error]${NC} %s\n" "$*" >&2; }
step()  { printf "${BOLD}→${NC} %s\n" "$*"; }

# ── Usage ────────────────────────────────────────────────────────────────────

usage() {
    cat <<'USAGE'
CTDF Portable Installer

Usage:
  ./install.sh [OPTIONS]

Options:
  --platform PLATFORM   Force a specific platform (skip auto-detection)
                        Platforms: claude-code, opencode, openclaw, cursor,
                        windsurf, continue, copilot, aider, generic
  --target DIR          Target project directory (default: current directory)
  --link                Use symlinks instead of copies
  --dry-run             Show what would be done without making changes
  --help                Show this help message

Examples:
  ./install.sh                          # Auto-detect platform, install to cwd
  ./install.sh --platform cursor        # Force Cursor platform
  ./install.sh --target ~/my-project    # Install to a specific project
  ./install.sh --link --dry-run         # Preview symlink installation
USAGE
}

# ── Argument parsing ─────────────────────────────────────────────────────────

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --platform)
                shift
                PLATFORM="${1:-}"
                if [ -z "$PLATFORM" ]; then
                    err "Missing value for --platform"
                    exit 1
                fi
                # Validate platform
                if ! echo "$PLATFORMS" | grep -qw "$PLATFORM"; then
                    err "Unknown platform: $PLATFORM"
                    err "Valid platforms: $PLATFORMS"
                    exit 1
                fi
                ;;
            --target)
                shift
                TARGET_DIR="${1:-}"
                if [ -z "$TARGET_DIR" ]; then
                    err "Missing value for --target"
                    exit 1
                fi
                ;;
            --link)
                USE_LINKS=true
                ;;
            --dry-run)
                DRY_RUN=true
                ;;
            --help|-h)
                usage
                exit 0
                ;;
            *)
                err "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
        shift
    done

    # Default target to current directory
    if [ -z "$TARGET_DIR" ]; then
        TARGET_DIR="$(pwd)"
    fi

    # Resolve to absolute path
    TARGET_DIR="$(cd "$TARGET_DIR" 2>/dev/null && pwd)" || {
        err "Target directory does not exist: $TARGET_DIR"
        exit 1
    }
}

# ── Version detection ────────────────────────────────────────────────────────

detect_version() {
    local manifest="$SCRIPT_DIR/manifest.json"
    if [ -f "$manifest" ]; then
        VERSION=$(python3 -c "import json; print(json.load(open('$manifest'))['version'])" 2>/dev/null || echo "")
    fi
    if [ -z "$VERSION" ]; then
        local plugin_json="$SCRIPT_DIR/.claude-plugin/plugin.json"
        if [ -f "$plugin_json" ]; then
            VERSION=$(python3 -c "import json; print(json.load(open('$plugin_json'))['version'])" 2>/dev/null || echo "unknown")
        else
            VERSION="unknown"
        fi
    fi
}

# ── Platform detection ───────────────────────────────────────────────────────

detect_platform() {
    if [ -n "$PLATFORM" ]; then
        return
    fi

    # Check CTDF_PLATFORM env var first
    if [ -n "${CTDF_PLATFORM:-}" ]; then
        PLATFORM="$CTDF_PLATFORM"
        return
    fi

    # Claude Code markers
    if [ -n "${CLAUDE_CODE:-}" ] || [ -n "${CLAUDE_PLUGIN:-}" ] || [ -d "$TARGET_DIR/.claude" ]; then
        PLATFORM="claude-code"
        return
    fi

    # OpenCode markers
    if [ -n "${OPENCODE_HOME:-}" ] || [ -n "${OPENCODE:-}" ] || [ -d "$TARGET_DIR/.opencode" ]; then
        PLATFORM="opencode"
        return
    fi

    # OpenClaw / ClawHub markers
    if [ -n "${OPENCLAW:-}" ] || [ -n "${CLAWHUB:-}" ] || [ -d "$TARGET_DIR/.agent" ]; then
        PLATFORM="openclaw"
        return
    fi

    # Cursor markers
    if [ -n "${CURSOR_SESSION:-}" ] || [ -n "${CURSOR:-}" ] || [ -d "$TARGET_DIR/.cursor" ]; then
        PLATFORM="cursor"
        return
    fi

    # Windsurf / Codeium markers
    if [ -n "${WINDSURF:-}" ] || [ -n "${CODEIUM_SESSION:-}" ] || [ -d "$TARGET_DIR/.windsurf" ]; then
        PLATFORM="windsurf"
        return
    fi

    # Continue.dev markers
    if [ -n "${CONTINUE_SESSION:-}" ] || [ -n "${CONTINUE:-}" ] || [ -d "$TARGET_DIR/.continue" ]; then
        PLATFORM="continue"
        return
    fi

    # GitHub Copilot markers
    if [ -n "${COPILOT_AGENT:-}" ] || [ -n "${GITHUB_COPILOT:-}" ] || [ -f "$TARGET_DIR/.github/copilot-instructions.md" ]; then
        PLATFORM="copilot"
        return
    fi

    # Aider markers
    if [ -n "${AIDER:-}" ] || [ -n "${AIDER_SESSION:-}" ] || [ -f "$TARGET_DIR/.aider.conf.yml" ]; then
        PLATFORM="aider"
        return
    fi

    # Default: Claude Code (CTDF's native platform)
    PLATFORM="claude-code"
}

# ── File operations ──────────────────────────────────────────────────────────

# Copy or symlink a file, creating parent directories as needed
place_file() {
    local src="$1"
    local dst="$2"

    if [ ! -f "$src" ]; then
        warn "Source file not found, skipping: $src"
        return
    fi

    local dst_dir
    dst_dir="$(dirname "$dst")"

    if $DRY_RUN; then
        if $USE_LINKS; then
            info "[dry-run] symlink $src -> $dst"
        else
            info "[dry-run] copy $src -> $dst"
        fi
        return
    fi

    mkdir -p "$dst_dir"

    if $USE_LINKS; then
        # Remove existing file/link before creating symlink
        rm -f "$dst"
        ln -s "$src" "$dst"
    else
        cp -f "$src" "$dst"
    fi
}

# Copy or symlink a directory recursively
place_dir() {
    local src="$1"
    local dst="$2"

    if [ ! -d "$src" ]; then
        warn "Source directory not found, skipping: $src"
        return
    fi

    if $DRY_RUN; then
        if $USE_LINKS; then
            info "[dry-run] symlink dir $src -> $dst"
        else
            info "[dry-run] copy dir $src -> $dst"
        fi
        return
    fi

    mkdir -p "$dst"

    if $USE_LINKS; then
        # For directories, symlink individual files to maintain structure
        find "$src" -type f | while read -r file; do
            local rel="${file#"$src/"}"
            local target="$dst/$rel"
            mkdir -p "$(dirname "$target")"
            rm -f "$target"
            ln -s "$file" "$target"
        done
    else
        cp -rf "$src/." "$dst/"
    fi
}

# ── Platform-specific installation ───────────────────────────────────────────

install_common() {
    # Install core scripts
    step "Installing scripts..."
    place_dir "$SCRIPT_DIR/scripts" "$TARGET_DIR/scripts"

    # Install skills
    step "Installing skills..."
    place_dir "$SCRIPT_DIR/skills" "$TARGET_DIR/skills"

    # Install config templates
    step "Installing configuration templates..."
    place_dir "$SCRIPT_DIR/config" "$TARGET_DIR/config"

    # Install hooks
    if [ -d "$SCRIPT_DIR/hooks" ]; then
        step "Installing hooks..."
        place_dir "$SCRIPT_DIR/hooks" "$TARGET_DIR/hooks"
    fi

    # Install docs
    if [ -d "$SCRIPT_DIR/docs" ]; then
        step "Installing documentation..."
        place_dir "$SCRIPT_DIR/docs" "$TARGET_DIR/docs"
    fi
}

install_claude_code() {
    info "Installing for Claude Code..."
    install_common

    # Claude Code uses .claude/ and .claude-plugin/
    step "Setting up Claude Code plugin structure..."
    place_dir "$SCRIPT_DIR/.claude-plugin" "$TARGET_DIR/.claude-plugin"

    # Install CLAUDE.md template if not present
    if [ ! -f "$TARGET_DIR/CLAUDE.md" ]; then
        if [ -f "$SCRIPT_DIR/templates/CLAUDE.md" ]; then
            step "Installing CLAUDE.md template..."
            place_file "$SCRIPT_DIR/templates/CLAUDE.md" "$TARGET_DIR/CLAUDE.md"
        fi
    else
        info "CLAUDE.md already exists, skipping"
    fi
}

install_opencode() {
    info "Installing for OpenCode..."
    install_common

    # OpenCode uses .opencode/plugins/
    step "Setting up OpenCode plugin directory..."
    place_dir "$SCRIPT_DIR/skills" "$TARGET_DIR/.opencode/plugins/ctdf/skills"
    place_dir "$SCRIPT_DIR/scripts" "$TARGET_DIR/.opencode/plugins/ctdf/scripts"

    # Create a minimal plugin descriptor for OpenCode
    if ! $DRY_RUN; then
        mkdir -p "$TARGET_DIR/.opencode/plugins/ctdf"
        cat > "$TARGET_DIR/.opencode/plugins/ctdf/plugin.json" <<OJSON
{
  "name": "ctdf",
  "version": "$VERSION",
  "description": "Claude Task Development Framework",
  "entry": "scripts/skill_helper.py"
}
OJSON
    fi
}

install_openclaw() {
    info "Installing for OpenClaw / ClawHub..."
    install_common

    # OpenClaw uses .agent/ directory
    step "Setting up OpenClaw agent directory..."
    place_dir "$SCRIPT_DIR/skills" "$TARGET_DIR/.agent/skills"
    place_dir "$SCRIPT_DIR/scripts" "$TARGET_DIR/.agent/scripts"
}

install_cursor() {
    info "Installing for Cursor..."
    install_common

    # Cursor uses .cursor/rules/ for instructions
    step "Setting up Cursor rules..."
    mkdir -p "$TARGET_DIR/.cursor/rules" 2>/dev/null || true

    # Create a Cursor rules file referencing CTDF skills
    if ! $DRY_RUN; then
        if [ ! -f "$TARGET_DIR/.cursor/rules/ctdf.md" ]; then
            cat > "$TARGET_DIR/.cursor/rules/ctdf.md" <<'CURSOR_RULES'
# CTDF Integration

This project uses the Claude Task Development Framework (CTDF).

## Available Commands
- Task management: `python3 scripts/task_manager.py`
- Release management: `python3 scripts/release_manager.py`
- Skill helper: `python3 scripts/skill_helper.py`

## Skill Definitions
See the `skills/` directory for available skill SKILL.md files.

## Configuration
See `config/` for configuration templates.
CURSOR_RULES
            ok "Created .cursor/rules/ctdf.md"
        fi
    fi
}

install_windsurf() {
    info "Installing for Windsurf..."
    install_common

    # Windsurf uses .windsurf/rules/
    step "Setting up Windsurf rules..."
    mkdir -p "$TARGET_DIR/.windsurf/rules" 2>/dev/null || true

    if ! $DRY_RUN; then
        if [ ! -f "$TARGET_DIR/.windsurf/rules/ctdf.md" ]; then
            cat > "$TARGET_DIR/.windsurf/rules/ctdf.md" <<'WS_RULES'
# CTDF Integration

This project uses the Claude Task Development Framework (CTDF).

## Available Commands
- Task management: `python3 scripts/task_manager.py`
- Release management: `python3 scripts/release_manager.py`
- Skill helper: `python3 scripts/skill_helper.py`

## Skill Definitions
See the `skills/` directory for available skill SKILL.md files.
WS_RULES
            ok "Created .windsurf/rules/ctdf.md"
        fi
    fi
}

install_continue_dev() {
    info "Installing for Continue.dev..."
    install_common

    # Continue uses .continue/ directory
    step "Setting up Continue.dev configuration..."
    if ! $DRY_RUN && [ ! -f "$TARGET_DIR/.continue/config.json" ]; then
        mkdir -p "$TARGET_DIR/.continue"
        cat > "$TARGET_DIR/.continue/config.json" <<'CONT_CFG'
{
  "customCommands": [
    {
      "name": "ctdf-task",
      "description": "Run CTDF task manager",
      "command": "python3 scripts/task_manager.py"
    }
  ]
}
CONT_CFG
        ok "Created .continue/config.json"
    fi
}

install_copilot() {
    info "Installing for GitHub Copilot..."
    install_common

    # Copilot uses .github/copilot-instructions.md
    step "Setting up Copilot instructions..."
    if ! $DRY_RUN; then
        mkdir -p "$TARGET_DIR/.github"
        if [ ! -f "$TARGET_DIR/.github/copilot-instructions.md" ]; then
            cat > "$TARGET_DIR/.github/copilot-instructions.md" <<'COPILOT_MD'
# CTDF Integration

This project uses the Claude Task Development Framework (CTDF) for task
and release management.

## Scripts
- `scripts/task_manager.py` — Task lifecycle management
- `scripts/release_manager.py` — Release pipeline
- `scripts/skill_helper.py` — Skill execution helper

## Skills
See `skills/` for available SKILL.md definitions.
COPILOT_MD
            ok "Created .github/copilot-instructions.md"
        fi
    fi
}

install_aider() {
    info "Installing for Aider..."
    install_common

    # Aider uses .aider.conf.yml and .aiderignore
    step "Setting up Aider configuration..."
    if ! $DRY_RUN; then
        if [ ! -f "$TARGET_DIR/.aiderignore" ]; then
            cat > "$TARGET_DIR/.aiderignore" <<'AIDER_IGNORE'
# CTDF generated files
dist/
.worktrees/
__pycache__/
AIDER_IGNORE
            ok "Created .aiderignore"
        fi
    fi
}

install_generic() {
    info "Installing for generic platform..."
    install_common

    # Generic: create an AGENTS.md if not present
    if ! $DRY_RUN && [ ! -f "$TARGET_DIR/AGENTS.md" ]; then
        cat > "$TARGET_DIR/AGENTS.md" <<'AGENTS_MD'
# CTDF Agent Instructions

This project uses the Claude Task Development Framework (CTDF).

## Available Scripts
- `python3 scripts/task_manager.py` — Task lifecycle management
- `python3 scripts/release_manager.py` — Release pipeline
- `python3 scripts/skill_helper.py` — Skill execution helper

## Skills
See `skills/` for available SKILL.md definitions.

## Configuration
See `config/` for configuration templates.
AGENTS_MD
        ok "Created AGENTS.md"
    fi
}

# ── Post-install ─────────────────────────────────────────────────────────────

post_install() {
    # Create task files if they don't exist
    for f in to-do.txt progressing.txt done.txt ideas.txt; do
        if [ ! -f "$TARGET_DIR/$f" ]; then
            if ! $DRY_RUN; then
                touch "$TARGET_DIR/$f"
            fi
        fi
    done

    # Ensure .gitignore has common entries
    if [ -f "$TARGET_DIR/.gitignore" ]; then
        for entry in __pycache__/ "*.pyc" .worktrees/ dist/; do
            if ! grep -qF "$entry" "$TARGET_DIR/.gitignore" 2>/dev/null; then
                if ! $DRY_RUN; then
                    echo "$entry" >> "$TARGET_DIR/.gitignore"
                fi
            fi
        done
    fi
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
    parse_args "$@"
    detect_version
    detect_platform

    echo ""
    printf "${BOLD}CTDF Portable Installer v%s${NC}\n" "$VERSION"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    info "Platform:  $PLATFORM"
    info "Target:    $TARGET_DIR"
    info "Method:    $(if $USE_LINKS; then echo 'symlinks'; else echo 'copy'; fi)"
    if $DRY_RUN; then
        warn "DRY RUN — no files will be modified"
    fi
    echo ""

    case "$PLATFORM" in
        claude-code)    install_claude_code ;;
        opencode)       install_opencode ;;
        openclaw)       install_openclaw ;;
        cursor)         install_cursor ;;
        windsurf)       install_windsurf ;;
        continue)       install_continue_dev ;;
        copilot)        install_copilot ;;
        aider)          install_aider ;;
        generic)        install_generic ;;
        *)
            err "Unknown platform: $PLATFORM"
            exit 1
            ;;
    esac

    post_install

    echo ""
    ok "CTDF installed successfully for platform: $PLATFORM"
    echo ""
    info "Next steps:"
    info "  1. Review configuration in config/"
    info "  2. Customize your CLAUDE.md (or platform equivalent)"
    info "  3. Run: python3 scripts/task_manager.py list"
    echo ""
}

main "$@"
