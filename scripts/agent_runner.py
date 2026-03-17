#!/usr/bin/env python3
"""Multi-provider agent runner for the agentic fleet pipeline.

Abstracts provider-specific CLI details (install, plugin setup, prompt
construction, invocation) so that CI/CD templates remain provider-agnostic.

Supported providers: claude, openai, openclaw, ollama.

Zero external dependencies — stdlib only.
"""

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"

# Add scripts/ to path so platform_utils can be imported
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


# ── Constants ───────────────────────────────────────────────────────────────

VALID_PROVIDERS = ("claude", "openai", "openclaw", "ollama")
VALID_PIPELINES = ("task", "scout", "docs")

CONFIG_FILE = ".claude/agentic-provider.json"
PROMPTS_DIR = ".claude/prompts"
SKILLS_DIR = ".claude/skills"
SCRIPTS_DIR = ".claude/scripts"

# Provider defaults
PROVIDER_DEFAULTS = {
    "claude": {
        "model": {"task": "claude-opus-4-6", "scout": "claude-sonnet-4-6", "docs": "claude-sonnet-4-6"},
        "budget": {"task": 15, "scout": 5, "docs": 5},
    },
    "openai": {
        "model": {"task": "o3", "scout": "o3-mini", "docs": "o3-mini"},
        "budget": {"task": 0, "scout": 0, "docs": 0},
    },
    "openclaw": {
        "model": {"task": "", "scout": "", "docs": ""},
        "budget": {"task": 0, "scout": 0, "docs": 0},
    },
    "ollama": {
        "model": {"task": "qwen2.5-coder:7b", "scout": "qwen2.5-coder:7b", "docs": "qwen2.5-coder:7b"},
        "budget": {"task": 0, "scout": 0, "docs": 0},
    },
}

# API key environment variable per provider
PROVIDER_ENV_KEYS = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openclaw": "OPENCLAW_API_KEY",
    "ollama": "",  # No API key needed for local Ollama
}

# CLI binary name per provider
PROVIDER_CLI_BIN = {
    "claude": "claude",
    "openai": "codex",
    "openclaw": "openclaw",
    "ollama": "ollama",
}

# npm package per provider
PROVIDER_NPM_PKG = {
    "claude": "@anthropic-ai/claude-code",
    "openai": "@openai/codex",
    "openclaw": "openclaw",
    "ollama": None,  # Ollama is installed via its own installer, not npm
}

# Allowed tools per pipeline (Claude only)
CLAUDE_ALLOWED_TOOLS = {
    "task": "Bash,Read,Grep,Glob,Edit,Write",
    "scout": "Bash,Read,Grep,Glob,WebSearch,WebFetch,Edit,Write",
    "docs": "Bash,Read,Grep,Glob,Edit,Write",
}

# Instructions file per provider
INSTRUCTIONS_FILE = {
    "claude": "CLAUDE.md",
    "openai": "AGENTS.md",
    "openclaw": "CLAUDE.md",
    "ollama": "CLAUDE.md",
}

# Co-Authored-By line templates
CO_AUTHORED_BY = {
    "claude": "Co-Authored-By: Claude {model} <noreply@anthropic.com>",
    "openai": "Co-Authored-By: OpenAI Codex ({model}) <noreply@openai.com>",
    "openclaw": "Co-Authored-By: OpenClaw Agent <noreply@openclaw.ai>",
    "ollama": "Co-Authored-By: Ollama Local ({model}) <noreply@ollama.com>",
}

# CTDF plugin repo URL
CTDF_REPO_URL = "https://github.com/dnviti/claude-task-development-framework.git"


# ── Configuration ───────────────────────────────────────────────────────────

def load_config(
    cli_provider: str | None = None,
    cli_model: str | None = None,
    cli_budget: float | None = None,
    pipeline: str = "task",
) -> dict:
    """Load provider configuration with precedence: CLI flags > env var > config file > defaults."""
    # Start with defaults
    provider = "claude"
    model = ""
    budget = 0.0

    # Layer 1: config file
    config_path = Path(CONFIG_FILE)
    file_config = {}
    if config_path.exists():
        try:
            file_config = json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: Could not parse {CONFIG_FILE}: {e}", file=sys.stderr)

    if file_config.get("provider"):
        provider = file_config["provider"]

    # Layer 2: environment variable
    env_provider = os.environ.get("AGENTIC_PROVIDER", "").strip().lower()
    if env_provider:
        provider = env_provider

    # Layer 3: CLI flag
    if cli_provider:
        provider = cli_provider.strip().lower()

    # Validate provider
    if provider not in VALID_PROVIDERS:
        print(
            f"Error: Unknown provider '{provider}'. "
            f"Valid providers: {', '.join(VALID_PROVIDERS)}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Resolve model
    defaults = PROVIDER_DEFAULTS[provider]
    model = defaults["model"].get(pipeline, "")

    # Override from config file
    if file_config.get("model", {}).get(pipeline):
        model = file_config["model"][pipeline]

    # Override from CLI
    if cli_model:
        model = cli_model

    # Resolve budget
    budget = defaults["budget"].get(pipeline, 0)
    if file_config.get("budget", {}).get(pipeline) is not None:
        budget = file_config["budget"][pipeline]
    if cli_budget is not None:
        budget = cli_budget

    # Resolve auto_pr (task pipeline only)
    auto_pr = True  # default: create PRs
    if file_config.get("auto_pr") is not None:
        auto_pr = bool(file_config["auto_pr"])
    # Environment variable override
    env_auto_pr = os.environ.get("AGENTIC_AUTO_PR", "").strip().lower()
    if env_auto_pr:
        auto_pr = env_auto_pr in ("true", "1", "yes")

    return {
        "provider": provider,
        "model": model,
        "budget": budget,
        "auto_pr": auto_pr,
    }


# ── Environment Validation ──────────────────────────────────────────────────

def validate_env(provider: str) -> None:
    """Check that the required API key environment variable is set."""
    env_key = PROVIDER_ENV_KEYS[provider]
    if not env_key:
        # Provider does not require an API key (e.g., ollama)
        return
    if not os.environ.get(env_key):
        print(
            f"Error: {env_key} is not set. "
            f"Required for provider '{provider}'. "
            f"Set it as a repository secret in your CI/CD platform.",
            file=sys.stderr,
        )
        sys.exit(1)


# ── CLI Installation ────────────────────────────────────────────────────────

def install_cli(provider: str) -> None:
    """Install the provider's CLI tool via npm if not already present."""
    cli_bin = PROVIDER_CLI_BIN[provider]
    if shutil.which(cli_bin):
        print(f"  {cli_bin} is already installed, skipping install.")
        return

    pkg = PROVIDER_NPM_PKG[provider]

    # Ollama uses its own installer, not npm
    if provider == "ollama":
        print("  Ollama is not installed. Attempting installation...")
        scripts_dir = Path(__file__).resolve().parent
        ollama_script = scripts_dir / "ollama_manager.py"
        try:
            result = subprocess.run(
                [sys.executable, str(ollama_script), "install"],
                capture_output=True, text=True, timeout=600,
            )
            if result.returncode == 0:
                print(f"  Ollama installed successfully.")
                return
            else:
                print(f"Error: Ollama installation failed:\n{result.stderr}", file=sys.stderr)
                sys.exit(1)
        except subprocess.TimeoutExpired:
            print("Error: Ollama installation timed out after 10 minutes.", file=sys.stderr)
            sys.exit(1)
        except OSError as e:
            print(f"Error: Could not install Ollama: {e}", file=sys.stderr)
            sys.exit(1)

    print(f"  Installing {pkg} via npm...")
    result = subprocess.run(
        ["npm", "install", "-g", pkg],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Error: Failed to install {pkg}:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    print(f"  {pkg} installed successfully.")


# ── Plugin Setup (Claude only) ──────────────────────────────────────────────

def setup_plugin(provider: str) -> None:
    """Install the CTDF plugin for Claude Code. No-op for other providers."""
    if provider != "claude":
        print(f"  Skipping plugin setup (not needed for {provider}).")
        return

    print("  Setting up CTDF plugin for Claude Code...")

    plugin_dir = Path.home() / ".claude" / "plugins"
    market_dir = plugin_dir / "marketplaces" / "dnviti-plugins"
    (plugin_dir / "marketplaces").mkdir(parents=True, exist_ok=True)

    # Clone if not already present
    if not market_dir.exists():
        result = subprocess.run(
            ["git", "clone", "--depth", "1", CTDF_REPO_URL, str(market_dir)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"Warning: Could not clone CTDF plugin repo:\n{result.stderr}", file=sys.stderr)
            return
    else:
        print("  CTDF plugin repo already cloned.")

    # Read version
    plugin_json = market_dir / ".claude-plugin" / "plugin.json"
    try:
        version = json.loads(plugin_json.read_text())["version"]
    except (json.JSONDecodeError, OSError, KeyError):
        print("Warning: Could not read plugin version.", file=sys.stderr)
        return

    cache_dir = plugin_dir / "cache" / "dnviti-plugins" / "ctdf" / version
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Copy plugin files to cache (cross-platform: uses shutil instead of cp -r)
    shutil.copytree(str(market_dir), str(cache_dir), dirs_exist_ok=True)

    # Write plugin registry files
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    installed = {
        "version": 2,
        "plugins": {
            "ctdf@dnviti-plugins": [{
                "scope": "user",
                "installPath": str(cache_dir),
                "version": version,
                "installedAt": now,
                "lastUpdated": now,
            }],
        },
    }
    (plugin_dir / "installed_plugins.json").write_text(json.dumps(installed))

    known = {
        "dnviti-plugins": {
            "source": {"source": "git", "url": CTDF_REPO_URL},
            "installLocation": str(market_dir),
            "lastUpdated": now,
        },
    }
    (plugin_dir / "known_marketplaces.json").write_text(json.dumps(known))

    # Enable plugin in settings
    settings_file = Path.home() / ".claude" / "settings.json"
    settings = {}
    if settings_file.exists():
        try:
            settings = json.loads(settings_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    settings.setdefault("enabledPlugins", {})["ctdf@dnviti-plugins"] = True
    settings_file.write_text(json.dumps(settings))

    print(f"  CTDF plugin v{version} installed and enabled.")


# ── Prompt Building ─────────────────────────────────────────────────────────

def _strip_yaml_frontmatter(text: str) -> str:
    """Remove YAML frontmatter (--- ... ---) from the beginning of a markdown file."""
    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            return text[end + 3:].lstrip("\n")
    return text


def _read_file_or_empty(path: str) -> str:
    """Read a file's content, returning empty string if not found."""
    p = Path(path)
    if p.exists():
        try:
            return p.read_text(encoding="utf-8")
        except OSError:
            pass
    return ""


def _make_co_authored_by(provider: str, model: str) -> str:
    """Generate the Co-Authored-By line for the given provider."""
    template = CO_AUTHORED_BY[provider]
    return template.format(model=model)


def _detect_platform() -> str:
    """Detect the CI/CD platform from the issues tracker config."""
    for cfg_name in (".claude/issues-tracker.json", ".claude/github-issues.json"):
        cfg_path = Path(cfg_name)
        if cfg_path.exists():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                return data.get("platform", "github")
            except (json.JSONDecodeError, OSError):
                pass
    # Detect from CI environment variables
    if os.environ.get("GITLAB_CI"):
        return "gitlab"
    return "github"


def _get_platform_placeholders(platform: str) -> dict:
    """Get platform-specific placeholder values for prompt templates."""
    if platform == "gitlab":
        return {
            "{{PLATFORM_CLI}}": "glab",
            "{{PLATFORM_VIEW_FLAGS}}": "--output json",
            "{{MR_LABEL}}": "Merge Request",
            "{{CHECK_EXISTING_MR_CMD}}": 'glab mr list --source-branch task/<task-code-lowercase> --state opened',
            "{{CREATE_MR_CMD}}": (
                'glab mr create \\\n'
                '  --target-branch <RELEASE_BRANCH> \\\n'
                '  --source-branch task/<task-code-lowercase> \\\n'
                '  --title "[<TASK-CODE>] — <Task Title>" \\\n'
                '  --description "## Task <TASK-CODE> — <Task Title>\n\n'
                '### Summary\n<brief list of what was created/modified>\n\n'
                '### Verify Command Result\n<PASS or FAIL with details>\n\n'
                '### Testing Guide\n<concrete numbered steps to manually verify the implementation>\n\n'
                '### Related Issue\nRefs #<ISSUE_NUM> (<TASK-CODE>)\n\n'
                '---\n*Implemented autonomously by Agentic Fleet*"'
            ),
            "{{RELEASE_BRANCH}}": "develop",
        }
    else:
        return {
            "{{PLATFORM_CLI}}": "gh",
            "{{PLATFORM_VIEW_FLAGS}}": "--json body",
            "{{MR_LABEL}}": "Pull Request",
            "{{CHECK_EXISTING_MR_CMD}}": 'gh pr list --head task/<task-code-lowercase> --state open --json number,url',
            "{{CREATE_MR_CMD}}": (
                'gh pr create \\\n'
                '  --base <RELEASE_BRANCH> \\\n'
                '  --head task/<task-code-lowercase> \\\n'
                '  --title "[<TASK-CODE>] — <Task Title>" \\\n'
                '  --body "## Task <TASK-CODE> — <Task Title>\n\n'
                '### Summary\n<brief list of what was created/modified>\n\n'
                '### Verify Command Result\n<PASS or FAIL with details>\n\n'
                '### Testing Guide\n<concrete numbered steps to manually verify the implementation>\n\n'
                '### Related Issue\nRefs #<ISSUE_NUM> (<TASK-CODE>)\n\n'
                '---\n*Implemented autonomously by Agentic Fleet*"'
            ),
            "{{RELEASE_BRANCH}}": "develop",
        }


def _get_mcp_server_info() -> str:
    """Build an MCP server connection info snippet for agent prompts.

    When the MCP server is configured and the ``mcp`` package is available,
    this returns a markdown section that instructs spawned agents how to
    connect to the shared vector memory MCP server.
    """
    mcp_script = Path(SCRIPTS_DIR) / "mcp_server.py"
    if not mcp_script.exists():
        return ""

    # Check project config for mcp_server.enabled
    for cfg_name in (".claude/project-config.json", "config/project-config.json"):
        cfg_path = Path(cfg_name)
        if cfg_path.exists():
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                mcp_cfg = data.get("mcp_server", {})
                if not mcp_cfg.get("enabled", False):
                    return ""
                break
            except (json.JSONDecodeError, OSError):
                pass
    else:
        return ""

    return (
        "\n\n## Vector Memory MCP Server\n\n"
        "A shared vector memory MCP server is available for semantic code search,\n"
        "memory storage, and task context retrieval.  The server uses stdio\n"
        "transport and can be started with:\n\n"
        "```bash\n"
        f"python3 {mcp_script} --root .\n"
        "```\n\n"
        "Tools: `index_repository`, `semantic_search`, `store_memory`, "
        "`get_task_context`\n"
        "Resource: `memory://status`\n\n"
    )


def build_prompt(pipeline: str, provider: str, model: str, auto_pr: bool = True) -> str:
    """Construct the agent prompt for the given pipeline and provider.

    Claude uses plugin-resolved skills where possible.
    OpenAI and OpenClaw get inlined skill content.
    """
    instructions_file = INSTRUCTIONS_FILE[provider]
    co_authored_by = _make_co_authored_by(provider, model)
    platform = _detect_platform()
    platform_placeholders = _get_platform_placeholders(platform)

    # MCP server connection info for agents
    mcp_info = _get_mcp_server_info()

    if pipeline == "task":
        # Task prompt is self-contained (no skill references)
        prompt_path = Path(PROMPTS_DIR) / "agentic-task-prompt.md"
        prompt = _read_file_or_empty(str(prompt_path))
        if not prompt:
            print(
                f"Error: Task prompt not found at {prompt_path}. "
                "Run /setup agentic-fleet to generate it.",
                file=sys.stderr,
            )
            sys.exit(1)
        prompt = prompt.replace("{{INSTRUCTIONS_FILE}}", instructions_file)
        prompt = prompt.replace("{{CO_AUTHORED_BY}}", co_authored_by)
        for placeholder, value in platform_placeholders.items():
            prompt = prompt.replace(placeholder, value)
        # Handle auto_pr toggle
        if auto_pr:
            prompt = prompt.replace("{{AUTO_PR_START}}", "")
            prompt = prompt.replace("{{AUTO_PR_END}}", "")
        else:
            # Remove everything between AUTO_PR markers
            import re as _re
            prompt = _re.sub(
                r"\{\{AUTO_PR_START\}\}.*?\{\{AUTO_PR_END\}\}",
                "15. Skip PR creation — auto_pr is disabled. "
                "The branch has been pushed; a human will create the PR manually.\n",
                prompt,
                flags=_re.DOTALL,
            )
        return prompt + mcp_info

    elif pipeline == "scout":
        research_comment_instructions = (
            "\n\n## Additional Instructions: Research Comments\n\n"
            "After creating each idea issue, post a comment ON THAT IDEA ISSUE\n"
            "documenting the research that led to it. This makes the reasoning\n"
            "transparent and helps reviewers evaluate the idea.\n\n"
            "**For each idea you create**, immediately post a comment:\n"
            "```bash\n"
            f"{platform_placeholders.get('{{{{PLATFORM_CLI}}}}', 'gh')} issue comment <IDEA_ISSUE_NUM> --body \"<research comment>\"\n"
            "```\n\n"
            "**Comment content should include:**\n"
            "- 🔍 **Sources consulted**: which online sources, reports, or codebase\n"
            "  files informed this idea (with links where available)\n"
            "- 💡 **Reasoning**: why this idea is relevant to the project specifically\n"
            "- 📊 **Evidence**: trends, data points, or patterns that support the idea\n"
            "- 🔗 **Related existing work**: any existing tasks or code that this\n"
            "  idea builds upon or relates to\n"
            "- ⚖️ **Trade-offs considered**: alternatives you evaluated and why\n"
            "  this approach was chosen\n\n"
            "Write naturally, like a product strategist presenting their findings.\n"
            "Use markdown formatting. Be specific — reference actual file paths,\n"
            "endpoints, or components from the codebase analysis reports.\n"
        )

        if provider == "claude":
            # Claude uses the plugin-resolved /idea-scout skill
            return (
                "/idea-scout "
                "@project-memory.md "
                "@report-infrastructure.md "
                "@report-features.md "
                "@report-quality.md"
                + research_comment_instructions
                + mcp_info
            )
        else:
            # Inline the idea-scout skill for non-Claude providers
            skill_path = Path(SKILLS_DIR) / "idea-scout" / "SKILL.md"
            skill_content = _read_file_or_empty(str(skill_path))
            if not skill_content:
                print(
                    f"Error: Idea scout skill not found at {skill_path}. "
                    "Run /setup agentic-fleet to copy skill files.",
                    file=sys.stderr,
                )
                sys.exit(1)
            skill_content = _strip_yaml_frontmatter(skill_content)
            # Replace plugin root references with local paths
            skill_content = skill_content.replace(
                "${CLAUDE_PLUGIN_ROOT}/scripts/",
                f"{SCRIPTS_DIR}/",
            )
            skill_content = skill_content.replace(
                "${CLAUDE_PLUGIN_ROOT}/",
                ".claude/",
            )
            # Replace arguments placeholder
            skill_content = skill_content.replace(
                "$ARGUMENTS",
                "@project-memory.md @report-infrastructure.md "
                "@report-features.md @report-quality.md",
            )
            # Replace instructions file reference
            skill_content = skill_content.replace("CLAUDE.md", instructions_file)
            # Prepend autonomous agent preamble
            preamble = (
                "You are a fully autonomous idea scout agent. You operate\n"
                "headlessly — make ALL decisions yourself with no user interaction.\n"
                "Never use AskUserQuestion. Never wait for confirmation. Act decisively.\n\n"
                "## Context Files\n"
                "Read these files for deep codebase understanding:\n"
                "- @project-memory.md — structural codebase summary\n"
                "- @report-infrastructure.md — infrastructure analysis\n"
                "- @report-features.md — feature analysis\n"
                "- @report-quality.md — code quality analysis\n\n"
                "## Skill Instructions\n\n"
            )
            return preamble + skill_content + research_comment_instructions + mcp_info

    elif pipeline == "docs":
        if provider == "claude":
            # Claude uses the prompt file which references /docs skill via plugin
            prompt_path = Path(PROMPTS_DIR) / "agentic-docs-prompt.md"
            prompt = _read_file_or_empty(str(prompt_path))
            if not prompt:
                print(
                    f"Error: Docs prompt not found at {prompt_path}. "
                    "Run /setup agentic-fleet to generate it.",
                    file=sys.stderr,
                )
                sys.exit(1)
            prompt = prompt.replace("{{INSTRUCTIONS_FILE}}", instructions_file)
            prompt = prompt.replace("{{CO_AUTHORED_BY}}", co_authored_by)
            prompt = prompt.replace("{{RELEASE_BRANCH}}", platform_placeholders.get("{{RELEASE_BRANCH}}", "develop"))
            return prompt + mcp_info
        else:
            # For non-Claude providers, inline the docs skill
            skill_path = Path(SKILLS_DIR) / "docs" / "SKILL.md"
            skill_content = _read_file_or_empty(str(skill_path))
            if skill_content:
                skill_content = _strip_yaml_frontmatter(skill_content)
                skill_content = skill_content.replace(
                    "${CLAUDE_PLUGIN_ROOT}/scripts/",
                    f"{SCRIPTS_DIR}/",
                )
                skill_content = skill_content.replace(
                    "${CLAUDE_PLUGIN_ROOT}/",
                    ".claude/",
                )
                skill_content = skill_content.replace("CLAUDE.md", instructions_file)

            # Build the docs prompt with inlined skill
            prompt_path = Path(PROMPTS_DIR) / "agentic-docs-prompt.md"
            prompt = _read_file_or_empty(str(prompt_path))
            if not prompt:
                print(
                    f"Error: Docs prompt not found at {prompt_path}. "
                    "Run /setup agentic-fleet to generate it.",
                    file=sys.stderr,
                )
                sys.exit(1)
            prompt = prompt.replace("{{INSTRUCTIONS_FILE}}", instructions_file)
            prompt = prompt.replace("{{CO_AUTHORED_BY}}", co_authored_by)
            prompt = prompt.replace("{{RELEASE_BRANCH}}", platform_placeholders.get("{{RELEASE_BRANCH}}", "develop"))

            # Append inlined skill reference if available
            if skill_content:
                prompt += (
                    "\n\n## Documentation Skill Reference\n\n"
                    "Use the following instructions as a guide for updating documentation:\n\n"
                    + skill_content
                )
            return prompt + mcp_info

    print(f"Error: Unknown pipeline '{pipeline}'.", file=sys.stderr)
    sys.exit(1)


# ── CLI Invocation Building ─────────────────────────────────────────────────

def _read_prompt_file(prompt_file: str) -> str:
    """Read prompt file contents directly (cross-platform, no shell expansion).

    Delegates to ``platform_utils.read_file_for_prompt`` when available,
    with a local fallback to keep the module self-contained.
    """
    try:
        from platform_utils import read_file_for_prompt
        return read_file_for_prompt(prompt_file)
    except ImportError:
        return Path(prompt_file).read_text(encoding="utf-8")


def build_invocation(
    provider: str,
    prompt_file: str,
    model: str,
    budget: float,
    pipeline: str,
) -> list[str]:
    """Build the CLI command to invoke the agent.

    Uses direct file reading instead of ``$(cat ...)`` shell expansion,
    so the returned list can be used with ``subprocess.run()`` without
    ``shell=True`` on any OS (Windows, macOS, Linux).

    Args:
        provider: The AI provider name.
        prompt_file: Path to the temp file containing the prompt.
        model: The model identifier to use.
        budget: Budget limit in USD (Claude only).
        pipeline: The pipeline type (for tool selection).

    Returns:
        A list of command-line arguments for subprocess.
    """
    prompt_content = _read_prompt_file(prompt_file)

    if provider == "claude":
        cmd = [
            "claude", "-p",
            prompt_content,
        ]
        if model:
            cmd.extend(["--model", model])
        if budget > 0:
            cmd.extend(["--max-budget-usd", str(int(budget))])
        tools = CLAUDE_ALLOWED_TOOLS.get(pipeline, "Bash,Read,Grep,Glob,Edit,Write")
        cmd.extend(["--allowedTools", tools])
        return cmd

    elif provider == "openai":
        cmd = [
            "codex", "-q",
            "-a", "full-auto",
        ]
        if model:
            cmd.extend(["-m", model])
        cmd.append(prompt_content)
        return cmd

    elif provider == "openclaw":
        cmd = [
            "openclaw", "agent",
            "--message", prompt_content,
            "--local",
        ]
        return cmd

    elif provider == "ollama":
        # Ollama is invoked via the ollama_manager.py query subcommand
        scripts_dir = Path(__file__).resolve().parent
        cmd = [
            sys.executable, str(scripts_dir / "ollama_manager.py"),
            "query",
            "--model", model or "qwen2.5-coder:7b",
            "--prompt", prompt_content,
        ]
        return cmd

    print(f"Error: Unknown provider '{provider}'.", file=sys.stderr)
    sys.exit(1)


def build_shell_command(
    provider: str,
    prompt_file: str,
    model: str,
    budget: float,
    pipeline: str,
) -> str:
    """Build a shell command string for the agent invocation.

    On Unix (bash/zsh), uses ``$(cat ...)`` shell expansion.
    On Windows, uses PowerShell ``$(Get-Content ...)`` syntax.
    Both require ``shell=True`` when passed to ``subprocess.run()``.
    """
    if IS_WINDOWS:
        # Sanitize path for PowerShell: escape backticks and dollar signs
        safe_path = prompt_file.replace("`", "``").replace("$", "`$")
        cat_expr = f'$(Get-Content -Raw "{safe_path}")'
        line_cont = " `\n  "
    else:
        cat_expr = f'"$(cat {prompt_file})"'
        line_cont = " \\\n  "

    if provider == "claude":
        parts = [f"claude -p {cat_expr}"]
        if model:
            parts.append(f"--model {model}")
        if budget > 0:
            parts.append(f"--max-budget-usd {int(budget)}")
        tools = CLAUDE_ALLOWED_TOOLS.get(pipeline, "Bash,Read,Grep,Glob,Edit,Write")
        parts.append(f'--allowedTools "{tools}"')
        return line_cont.join(parts)

    elif provider == "openai":
        parts = ["codex -q -a full-auto"]
        if model:
            parts.append(f"-m {model}")
        parts.append(cat_expr)
        return line_cont.join(parts)

    elif provider == "openclaw":
        return (
            f"openclaw agent{line_cont}"
            f"--message {cat_expr}{line_cont}"
            f"--local"
        )

    elif provider == "ollama":
        scripts_dir = Path(__file__).resolve().parent
        ollama_script = scripts_dir / "ollama_manager.py"
        model_name = model or "qwen2.5-coder:7b"
        if IS_WINDOWS:
            # On Windows, shlex.quote is not suitable; use basic quoting
            safe_model = f'"{model_name}"'
        else:
            import shlex as _shlex
            safe_model = _shlex.quote(model_name)
        return (
            f"{sys.executable} {ollama_script} query{line_cont}"
            f"--model {safe_model}{line_cont}"
            f"--prompt {cat_expr}"
        )

    return ""


# ── Ollama Offload Config ───────────────────────────────────────────────────

def _load_ollama_offload_config() -> dict | None:
    """Load Ollama offloading configuration if enabled.

    Returns the config dict if Ollama offloading is enabled, None otherwise.
    """
    config_path = Path(".claude/ollama-config.json")
    if not config_path.exists():
        return None
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if config.get("enabled") and config.get("offloading", {}).get("enabled"):
            return config
    except (json.JSONDecodeError, OSError):
        pass
    return None


# ── Main Runner ─────────────────────────────────────────────────────────────

def run_agent(
    pipeline: str,
    cli_provider: str | None = None,
    cli_model: str | None = None,
    cli_budget: float | None = None,
    dry_run: bool = False,
) -> None:
    """Main orchestrator: load config, validate, install, build prompt, invoke."""
    print(f"=== Agentic Fleet — {pipeline.title()} Pipeline ===\n")

    # 1. Load configuration
    config = load_config(cli_provider, cli_model, cli_budget, pipeline)
    provider = config["provider"]
    model = config["model"]
    budget = config["budget"]

    print(f"  Provider: {provider}")
    print(f"  Model:    {model or '(default)'}")
    print(f"  Budget:   ${budget}" if budget > 0 else "  Budget:   (not applicable)")
    print()

    # 1b. Check for Ollama offloading (when using a cloud provider)
    ollama_offload = False
    ollama_config = _load_ollama_offload_config()
    if ollama_config and provider != "ollama":
        ollama_offload = True
        print(f"  Ollama offloading: enabled (model: {ollama_config.get('model', 'auto')})")

    # 2. Validate environment
    if not dry_run:
        validate_env(provider)
    else:
        env_key = PROVIDER_ENV_KEYS[provider]
        if env_key and not os.environ.get(env_key):
            print(f"  [dry-run] Warning: {env_key} is not set (would fail in real run).")

    # 3. Install CLI
    print("[1/4] Installing CLI...")
    if not dry_run:
        install_cli(provider)
    else:
        pkg = PROVIDER_NPM_PKG.get(provider)
        if pkg:
            print(f"  [dry-run] Would install: {pkg}")
        else:
            print(f"  [dry-run] Would install {provider} via its own installer.")

    # 4. Setup plugin
    print("[2/4] Setting up plugin...")
    if not dry_run:
        setup_plugin(provider)
    else:
        if provider == "claude":
            print("  [dry-run] Would install CTDF plugin.")
        else:
            print(f"  [dry-run] Skipping plugin setup (not needed for {provider}).")

    # 5. Build prompt
    print("[3/4] Building prompt...")
    auto_pr = config.get("auto_pr", True)
    if pipeline == "task":
        print(f"  Auto-PR: {'enabled' if auto_pr else 'disabled'}")
    prompt = build_prompt(pipeline, provider, model, auto_pr=auto_pr)

    # Write prompt to temp file (cross-platform temp directory)
    prompt_file = str(Path(tempfile.gettempdir()) / "agent-prompt.md")
    if not dry_run:
        Path(prompt_file).write_text(prompt, encoding="utf-8")
        print(f"  Prompt written to {prompt_file} ({len(prompt)} chars)")
    else:
        print(f"  [dry-run] Prompt length: {len(prompt)} chars")
        print(f"  [dry-run] Prompt preview (first 200 chars):")
        print(f"    {prompt[:200]}...")

    # 6. Invoke agent
    print("[4/4] Invoking agent...")

    if dry_run:
        shell_cmd = build_shell_command(provider, prompt_file, model, budget, pipeline)
        print(f"\n  [dry-run] Would execute:\n")
        for line in shell_cmd.split("\n"):
            print(f"    {line}")
        print("\n  [dry-run] Complete. No agent was invoked.")
        return

    # Use list-format invocation (no shell=True) for cross-platform safety
    cmd_list = build_invocation(provider, prompt_file, model, budget, pipeline)
    print(f"\n  Executing:\n    {cmd_list[0]} ...")
    result = subprocess.run(
        cmd_list,
        cwd=os.getcwd(),
    )

    if result.returncode != 0:
        print(
            f"\nError: Agent exited with code {result.returncode}.",
            file=sys.stderr,
        )
        sys.exit(result.returncode)

    print(f"\n=== {pipeline.title()} pipeline completed successfully. ===")


# ── CLI Entry Point ─────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-provider agent runner for CTDF agentic fleet pipelines.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 agent_runner.py run --pipeline task\n"
            "  python3 agent_runner.py run --pipeline scout --provider openai --model o3\n"
            "  python3 agent_runner.py run --pipeline task --provider ollama --model qwen2.5-coder:7b\n"
            "  python3 agent_runner.py run --pipeline docs --dry-run\n"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run subcommand
    run_parser = subparsers.add_parser("run", help="Run an agentic pipeline")
    run_parser.add_argument(
        "--pipeline",
        required=True,
        choices=VALID_PIPELINES,
        help="Pipeline type to run",
    )
    run_parser.add_argument(
        "--provider",
        choices=VALID_PROVIDERS,
        default=None,
        help=f"AI provider (overrides config file and env var). Default: from {CONFIG_FILE} or AGENTIC_PROVIDER env var",
    )
    run_parser.add_argument(
        "--model",
        default=None,
        help="Model name (overrides config file default)",
    )
    run_parser.add_argument(
        "--budget",
        type=float,
        default=None,
        help="Budget in USD (Claude only, overrides config file)",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the command that would be executed without running it",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "run":
        run_agent(
            pipeline=args.pipeline,
            cli_provider=args.provider,
            cli_model=args.model,
            cli_budget=args.budget,
            dry_run=args.dry_run,
        )


if __name__ == "__main__":
    main()
