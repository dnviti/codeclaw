<#
.SYNOPSIS
    CTDF Portable Installer - PowerShell Bootstrap

.DESCRIPTION
    Auto-detects the target AI coding platform and installs CTDF files into
    the correct locations. Supports Claude Code, OpenCode, OpenClaw, Cursor,
    Windsurf, Continue, Copilot, Aider, and generic setups.

.PARAMETER Platform
    Force a specific platform (skip auto-detection).
    Valid values: claude-code, opencode, openclaw, cursor, windsurf, continue, copilot, aider, generic

.PARAMETER Target
    Target project directory (default: current directory).

.PARAMETER Link
    Use symlinks instead of copies (requires elevated permissions on older Windows).

.PARAMETER DryRun
    Show what would be done without making changes.

.EXAMPLE
    .\install.ps1
    .\install.ps1 -Platform cursor
    .\install.ps1 -Target C:\Projects\my-app -DryRun
    .\install.ps1 -Link
#>

[CmdletBinding()]
param(
    [ValidateSet("claude-code", "opencode", "openclaw", "cursor", "windsurf", "continue", "copilot", "aider", "generic")]
    [string]$Platform = "",
    [string]$Target = "",
    [switch]$Link,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Constants ────────────────────────────────────────────────────────────────

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Version = "unknown"

# ── Helper Functions ─────────────────────────────────────────────────────────

function Write-Info  { param([string]$Msg) Write-Host "[info]  $Msg" -ForegroundColor Cyan }
function Write-Ok    { param([string]$Msg) Write-Host "[ok]    $Msg" -ForegroundColor Green }
function Write-Warn  { param([string]$Msg) Write-Host "[warn]  $Msg" -ForegroundColor Yellow }
function Write-Err   { param([string]$Msg) Write-Host "[error] $Msg" -ForegroundColor Red }
function Write-Step  { param([string]$Msg) Write-Host "-> $Msg" -ForegroundColor White }

# ── Version Detection ────────────────────────────────────────────────────────

function Get-CtdfVersion {
    $manifestPath = Join-Path $ScriptRoot "manifest.json"
    if (Test-Path $manifestPath) {
        try {
            $manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json
            if ($manifest.version) {
                return $manifest.version
            }
        } catch { }
    }

    $pluginPath = Join-Path $ScriptRoot ".claude-plugin" "plugin.json"
    if (Test-Path $pluginPath) {
        try {
            $plugin = Get-Content -Raw $pluginPath | ConvertFrom-Json
            if ($plugin.version) {
                return $plugin.version
            }
        } catch { }
    }

    return "unknown"
}

# ── Platform Detection ───────────────────────────────────────────────────────

function Detect-Platform {
    param([string]$TargetDir)

    # Check CTDF_PLATFORM env var
    $envPlatform = $env:CTDF_PLATFORM
    if ($envPlatform) {
        return $envPlatform.ToLower()
    }

    # Claude Code markers
    if ($env:CLAUDE_CODE -or $env:CLAUDE_PLUGIN -or (Test-Path (Join-Path $TargetDir ".claude"))) {
        return "claude-code"
    }

    # OpenCode markers
    if ($env:OPENCODE_HOME -or $env:OPENCODE -or (Test-Path (Join-Path $TargetDir ".opencode"))) {
        return "opencode"
    }

    # OpenClaw markers
    if ($env:OPENCLAW -or $env:CLAWHUB -or (Test-Path (Join-Path $TargetDir ".agent"))) {
        return "openclaw"
    }

    # Cursor markers
    if ($env:CURSOR_SESSION -or $env:CURSOR -or (Test-Path (Join-Path $TargetDir ".cursor"))) {
        return "cursor"
    }

    # Windsurf markers
    if ($env:WINDSURF -or $env:CODEIUM_SESSION -or (Test-Path (Join-Path $TargetDir ".windsurf"))) {
        return "windsurf"
    }

    # Continue.dev markers
    if ($env:CONTINUE_SESSION -or $env:CONTINUE -or (Test-Path (Join-Path $TargetDir ".continue"))) {
        return "continue"
    }

    # Copilot markers
    if ($env:COPILOT_AGENT -or $env:GITHUB_COPILOT -or (Test-Path (Join-Path $TargetDir ".github" "copilot-instructions.md"))) {
        return "copilot"
    }

    # Aider markers
    if ($env:AIDER -or $env:AIDER_SESSION -or (Test-Path (Join-Path $TargetDir ".aider.conf.yml"))) {
        return "aider"
    }

    # Default
    return "claude-code"
}

# ── File Operations ──────────────────────────────────────────────────────────

function Place-File {
    param(
        [string]$Source,
        [string]$Destination
    )

    if (-not (Test-Path $Source)) {
        Write-Warn "Source file not found, skipping: $Source"
        return
    }

    $destDir = Split-Path -Parent $Destination

    if ($DryRun) {
        $method = if ($Link) { "symlink" } else { "copy" }
        Write-Info "[dry-run] $method $Source -> $Destination"
        return
    }

    if (-not (Test-Path $destDir)) {
        New-Item -ItemType Directory -Path $destDir -Force | Out-Null
    }

    if ($Link) {
        if (Test-Path $Destination) { Remove-Item $Destination -Force }
        New-Item -ItemType SymbolicLink -Path $Destination -Target $Source -Force | Out-Null
    } else {
        Copy-Item -Path $Source -Destination $Destination -Force
    }
}

function Place-Directory {
    param(
        [string]$Source,
        [string]$Destination
    )

    if (-not (Test-Path $Source)) {
        Write-Warn "Source directory not found, skipping: $Source"
        return
    }

    if ($DryRun) {
        $method = if ($Link) { "symlink dir" } else { "copy dir" }
        Write-Info "[dry-run] $method $Source -> $Destination"
        return
    }

    if (-not (Test-Path $Destination)) {
        New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    }

    if ($Link) {
        # Symlink individual files to maintain directory structure
        Get-ChildItem -Path $Source -Recurse -File | ForEach-Object {
            $relPath = $_.FullName.Substring($Source.Length + 1)
            $targetPath = Join-Path $Destination $relPath
            $targetDir = Split-Path -Parent $targetPath
            if (-not (Test-Path $targetDir)) {
                New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
            }
            if (Test-Path $targetPath) { Remove-Item $targetPath -Force }
            New-Item -ItemType SymbolicLink -Path $targetPath -Target $_.FullName -Force | Out-Null
        }
    } else {
        Copy-Item -Path "$Source\*" -Destination $Destination -Recurse -Force
    }
}

# ── Common Installation ──────────────────────────────────────────────────────

function Install-Common {
    param([string]$TargetDir)

    Write-Step "Installing scripts..."
    Place-Directory (Join-Path $ScriptRoot "scripts") (Join-Path $TargetDir "scripts")

    Write-Step "Installing skills..."
    Place-Directory (Join-Path $ScriptRoot "skills") (Join-Path $TargetDir "skills")

    Write-Step "Installing configuration templates..."
    Place-Directory (Join-Path $ScriptRoot "config") (Join-Path $TargetDir "config")

    $hooksDir = Join-Path $ScriptRoot "hooks"
    if (Test-Path $hooksDir) {
        Write-Step "Installing hooks..."
        Place-Directory $hooksDir (Join-Path $TargetDir "hooks")
    }

    $docsDir = Join-Path $ScriptRoot "docs"
    if (Test-Path $docsDir) {
        Write-Step "Installing documentation..."
        Place-Directory $docsDir (Join-Path $TargetDir "docs")
    }
}

# ── Platform-Specific Installation ───────────────────────────────────────────

function Install-ClaudeCode {
    param([string]$TargetDir)
    Write-Info "Installing for Claude Code..."
    Install-Common -TargetDir $TargetDir

    Write-Step "Setting up Claude Code plugin structure..."
    Place-Directory (Join-Path $ScriptRoot ".claude-plugin") (Join-Path $TargetDir ".claude-plugin")

    $claudeMd = Join-Path $TargetDir "CLAUDE.md"
    if (-not (Test-Path $claudeMd)) {
        $templateMd = Join-Path $ScriptRoot "templates" "CLAUDE.md"
        if (Test-Path $templateMd) {
            Write-Step "Installing CLAUDE.md template..."
            Place-File $templateMd $claudeMd
        }
    } else {
        Write-Info "CLAUDE.md already exists, skipping"
    }
}

function Install-OpenCode {
    param([string]$TargetDir)
    Write-Info "Installing for OpenCode..."
    Install-Common -TargetDir $TargetDir

    Write-Step "Setting up OpenCode plugin directory..."
    Place-Directory (Join-Path $ScriptRoot "skills") (Join-Path $TargetDir ".opencode" "plugins" "ctdf" "skills")
    Place-Directory (Join-Path $ScriptRoot "scripts") (Join-Path $TargetDir ".opencode" "plugins" "ctdf" "scripts")

    if (-not $DryRun) {
        $pluginDir = Join-Path $TargetDir ".opencode" "plugins" "ctdf"
        if (-not (Test-Path $pluginDir)) {
            New-Item -ItemType Directory -Path $pluginDir -Force | Out-Null
        }
        $pluginContent = @"
{
  "name": "ctdf",
  "version": "$Version",
  "description": "Claude Task Development Framework",
  "entry": "scripts/skill_helper.py"
}
"@
        Set-Content -Path (Join-Path $pluginDir "plugin.json") -Value $pluginContent -Encoding UTF8
    }
}

function Install-OpenClaw {
    param([string]$TargetDir)
    Write-Info "Installing for OpenClaw / ClawHub..."
    Install-Common -TargetDir $TargetDir

    Write-Step "Setting up OpenClaw agent directory..."
    Place-Directory (Join-Path $ScriptRoot "skills") (Join-Path $TargetDir ".agent" "skills")
    Place-Directory (Join-Path $ScriptRoot "scripts") (Join-Path $TargetDir ".agent" "scripts")
}

function Install-Cursor {
    param([string]$TargetDir)
    Write-Info "Installing for Cursor..."
    Install-Common -TargetDir $TargetDir

    Write-Step "Setting up Cursor rules..."
    $rulesDir = Join-Path $TargetDir ".cursor" "rules"
    if (-not (Test-Path $rulesDir)) {
        New-Item -ItemType Directory -Path $rulesDir -Force | Out-Null
    }

    $rulesFile = Join-Path $rulesDir "ctdf.md"
    if ((-not $DryRun) -and (-not (Test-Path $rulesFile))) {
        $rulesContent = @"
# CTDF Integration

This project uses the Claude Task Development Framework (CTDF).

## Available Commands
- Task management: ``python3 scripts/task_manager.py``
- Release management: ``python3 scripts/release_manager.py``
- Skill helper: ``python3 scripts/skill_helper.py``

## Skill Definitions
See the ``skills/`` directory for available skill SKILL.md files.

## Configuration
See ``config/`` for configuration templates.
"@
        Set-Content -Path $rulesFile -Value $rulesContent -Encoding UTF8
        Write-Ok "Created .cursor/rules/ctdf.md"
    }
}

function Install-Windsurf {
    param([string]$TargetDir)
    Write-Info "Installing for Windsurf..."
    Install-Common -TargetDir $TargetDir

    Write-Step "Setting up Windsurf rules..."
    $rulesDir = Join-Path $TargetDir ".windsurf" "rules"
    if (-not (Test-Path $rulesDir)) {
        New-Item -ItemType Directory -Path $rulesDir -Force | Out-Null
    }

    $rulesFile = Join-Path $rulesDir "ctdf.md"
    if ((-not $DryRun) -and (-not (Test-Path $rulesFile))) {
        $rulesContent = @"
# CTDF Integration

This project uses the Claude Task Development Framework (CTDF).

## Available Commands
- Task management: ``python3 scripts/task_manager.py``
- Release management: ``python3 scripts/release_manager.py``
- Skill helper: ``python3 scripts/skill_helper.py``

## Skill Definitions
See the ``skills/`` directory for available skill SKILL.md files.
"@
        Set-Content -Path $rulesFile -Value $rulesContent -Encoding UTF8
        Write-Ok "Created .windsurf/rules/ctdf.md"
    }
}

function Install-Continue {
    param([string]$TargetDir)
    Write-Info "Installing for Continue.dev..."
    Install-Common -TargetDir $TargetDir

    Write-Step "Setting up Continue.dev configuration..."
    $configFile = Join-Path $TargetDir ".continue" "config.json"
    if ((-not $DryRun) -and (-not (Test-Path $configFile))) {
        $configDir = Join-Path $TargetDir ".continue"
        if (-not (Test-Path $configDir)) {
            New-Item -ItemType Directory -Path $configDir -Force | Out-Null
        }
        $configContent = @"
{
  "customCommands": [
    {
      "name": "ctdf-task",
      "description": "Run CTDF task manager",
      "command": "python3 scripts/task_manager.py"
    }
  ]
}
"@
        Set-Content -Path $configFile -Value $configContent -Encoding UTF8
        Write-Ok "Created .continue/config.json"
    }
}

function Install-Copilot {
    param([string]$TargetDir)
    Write-Info "Installing for GitHub Copilot..."
    Install-Common -TargetDir $TargetDir

    Write-Step "Setting up Copilot instructions..."
    $ghDir = Join-Path $TargetDir ".github"
    if (-not (Test-Path $ghDir)) {
        New-Item -ItemType Directory -Path $ghDir -Force | Out-Null
    }

    $instrFile = Join-Path $ghDir "copilot-instructions.md"
    if ((-not $DryRun) -and (-not (Test-Path $instrFile))) {
        $instrContent = @"
# CTDF Integration

This project uses the Claude Task Development Framework (CTDF) for task
and release management.

## Scripts
- ``scripts/task_manager.py`` -- Task lifecycle management
- ``scripts/release_manager.py`` -- Release pipeline
- ``scripts/skill_helper.py`` -- Skill execution helper

## Skills
See ``skills/`` for available SKILL.md definitions.
"@
        Set-Content -Path $instrFile -Value $instrContent -Encoding UTF8
        Write-Ok "Created .github/copilot-instructions.md"
    }
}

function Install-Aider {
    param([string]$TargetDir)
    Write-Info "Installing for Aider..."
    Install-Common -TargetDir $TargetDir

    Write-Step "Setting up Aider configuration..."
    $ignoreFile = Join-Path $TargetDir ".aiderignore"
    if ((-not $DryRun) -and (-not (Test-Path $ignoreFile))) {
        $ignoreContent = @"
# CTDF generated files
dist/
.worktrees/
__pycache__/
"@
        Set-Content -Path $ignoreFile -Value $ignoreContent -Encoding UTF8
        Write-Ok "Created .aiderignore"
    }
}

function Install-Generic {
    param([string]$TargetDir)
    Write-Info "Installing for generic platform..."
    Install-Common -TargetDir $TargetDir

    $agentsMd = Join-Path $TargetDir "AGENTS.md"
    if ((-not $DryRun) -and (-not (Test-Path $agentsMd))) {
        $agentsContent = @"
# CTDF Agent Instructions

This project uses the Claude Task Development Framework (CTDF).

## Available Scripts
- ``python3 scripts/task_manager.py`` -- Task lifecycle management
- ``python3 scripts/release_manager.py`` -- Release pipeline
- ``python3 scripts/skill_helper.py`` -- Skill execution helper

## Skills
See ``skills/`` for available SKILL.md definitions.

## Configuration
See ``config/`` for configuration templates.
"@
        Set-Content -Path $agentsMd -Value $agentsContent -Encoding UTF8
        Write-Ok "Created AGENTS.md"
    }
}

# ── Post-Install ─────────────────────────────────────────────────────────────

function Post-Install {
    param([string]$TargetDir)

    # Create task files if they don't exist
    foreach ($f in @("to-do.txt", "progressing.txt", "done.txt", "ideas.txt")) {
        $fpath = Join-Path $TargetDir $f
        if (-not (Test-Path $fpath)) {
            if (-not $DryRun) {
                New-Item -ItemType File -Path $fpath -Force | Out-Null
            }
        }
    }

    # Ensure .gitignore has common entries
    $gitignore = Join-Path $TargetDir ".gitignore"
    if (Test-Path $gitignore) {
        $content = Get-Content -Raw $gitignore -ErrorAction SilentlyContinue
        foreach ($entry in @("__pycache__/", "*.pyc", ".worktrees/", "dist/")) {
            if ($content -and ($content -notmatch [regex]::Escape($entry))) {
                if (-not $DryRun) {
                    Add-Content -Path $gitignore -Value $entry
                }
            }
        }
    }
}

# ── Main ─────────────────────────────────────────────────────────────────────

function Main {
    # Resolve target directory
    if (-not $Target) {
        $Target = Get-Location
    }
    $TargetDir = (Resolve-Path $Target -ErrorAction Stop).Path

    # Detect version
    $script:Version = Get-CtdfVersion

    # Detect platform
    if (-not $Platform) {
        $Platform = Detect-Platform -TargetDir $TargetDir
    }

    # Banner
    Write-Host ""
    Write-Host "CTDF Portable Installer v$Version" -ForegroundColor White
    Write-Host ("=" * 50)
    Write-Info "Platform:  $Platform"
    Write-Info "Target:    $TargetDir"
    $method = if ($Link) { "symlinks" } else { "copy" }
    Write-Info "Method:    $method"
    if ($DryRun) {
        Write-Warn "DRY RUN - no files will be modified"
    }
    Write-Host ""

    # Dispatch to platform installer
    switch ($Platform) {
        "claude-code"   { Install-ClaudeCode -TargetDir $TargetDir }
        "opencode"      { Install-OpenCode -TargetDir $TargetDir }
        "openclaw"      { Install-OpenClaw -TargetDir $TargetDir }
        "cursor"        { Install-Cursor -TargetDir $TargetDir }
        "windsurf"      { Install-Windsurf -TargetDir $TargetDir }
        "continue"      { Install-Continue -TargetDir $TargetDir }
        "copilot"       { Install-Copilot -TargetDir $TargetDir }
        "aider"         { Install-Aider -TargetDir $TargetDir }
        "generic"       { Install-Generic -TargetDir $TargetDir }
        default {
            Write-Err "Unknown platform: $Platform"
            exit 1
        }
    }

    Post-Install -TargetDir $TargetDir

    Write-Host ""
    Write-Ok "CTDF installed successfully for platform: $Platform"
    Write-Host ""
    Write-Info "Next steps:"
    Write-Info "  1. Review configuration in config/"
    Write-Info "  2. Customize your CLAUDE.md (or platform equivalent)"
    Write-Info "  3. Run: python3 scripts/task_manager.py list"
    Write-Host ""
}

# Execute
Main
