#!/usr/bin/env python3
"""Cross-platform config generator for CodeClaw skills.

Reads CodeClaw's canonical skill definitions from skills/*/SKILL.md,
extracts frontmatter and instructions, and templates them into
platform-specific configuration files.

Supported targets:
    opencode    -- opencode.json + .opencode/plugins/ JS wrappers
    openclaw    -- SKILL.md in AgentSkills format
    cursor      -- .cursor/rules/*.mdc
    windsurf    -- .windsurf/rules/*.md
    continue    -- .continue/ assistants
    copilot     -- .github/copilot-instructions.md
    agents_md   -- Universal AGENTS.md standard

The generator is idempotent: re-running updates existing files
without duplicating content.

Usage:
    python3 platform_exporter.py export --target cursor --output ./my-project
    python3 platform_exporter.py export-all --output ./my-project
    python3 platform_exporter.py list-targets
    python3 platform_exporter.py list-skills

Zero external dependencies -- stdlib only.
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from common import parse_skill_md


# ── Constants ───────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
SKILLS_DIR = PROJECT_ROOT / "skills"
TEMPLATES_DIR = PROJECT_ROOT / "templates" / "platforms"

# Idempotency markers embedded in generated files
MARKER_START = "<!-- CodeClaw-EXPORT:START -->"
MARKER_END = "<!-- CodeClaw-EXPORT:END -->"
MARKER_HASH_PREFIX = "<!-- CodeClaw-EXPORT-HASH:"
JSON_MARKER_KEY = "__claw_export_hash"

# Pre-compiled regex for replacing idempotency marker blocks
MARKER_BLOCK_RE = re.compile(
    re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END),
    re.DOTALL,
)

SUPPORTED_TARGETS = [
    "opencode",
    "openclaw",
    "cursor",
    "windsurf",
    "continue",
    "copilot",
    "agents_md",
]


# ── Version Detection ─────────────────────────────────────────────────────


def _read_plugin_version() -> str:
    """Read the current version from .claude-plugin/plugin.json."""
    manifest = PROJECT_ROOT / ".claude-plugin" / "plugin.json"
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return data.get("version", "0.0.0")
    except (OSError, json.JSONDecodeError):
        return "0.0.0"


# ── Skill Parsing ──────────────────────────────────────────────────────────


def discover_skills(skills_dir: Path | None = None) -> list[dict[str, Any]]:
    """Discover and parse all SKILL.md files in the skills directory."""
    sdir = skills_dir or SKILLS_DIR
    skills: list[dict[str, Any]] = []

    if not sdir.is_dir():
        return skills

    for entry in sorted(sdir.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        parsed = parse_skill_md(skill_md)
        if parsed:
            skills.append(parsed)

    return skills


# ── Idempotency Helpers ────────────────────────────────────────────────────


def _content_hash(content: str) -> str:
    """Compute a short SHA-256 hash of content for idempotency checks."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _has_matching_hash(existing: str, new_hash: str) -> bool:
    """Check if an existing file already contains the same content hash."""
    return f"{MARKER_HASH_PREFIX}{new_hash}" in existing


def _wrap_with_markers(content: str, content_hash: str) -> str:
    """Wrap generated content with idempotency markers."""
    return (
        f"{MARKER_START}\n"
        f"{MARKER_HASH_PREFIX}{content_hash} -->\n"
        f"{content}\n"
        f"{MARKER_END}"
    )


def _replace_marker_block(existing: str, new_block: str) -> str:
    """Replace the marked block in existing content, or append if absent."""
    if MARKER_BLOCK_RE.search(existing):
        return MARKER_BLOCK_RE.sub(new_block, existing)
    # Not found -- append
    return existing.rstrip() + "\n\n" + new_block + "\n"


def _write_idempotent(filepath: Path, generated: str, *, pure: bool = False) -> bool:
    """Write content idempotently.

    If pure=True, the file is entirely generated (no user content to
    preserve).  In that case, we replace the whole file when the hash
    differs.

    If pure=False, we use marker blocks so user content outside the
    markers is preserved.

    Returns True if the file was written/updated, False if unchanged.
    """
    content_hash = _content_hash(generated)

    if filepath.exists():
        existing = filepath.read_text(encoding="utf-8")
        if _has_matching_hash(existing, content_hash):
            return False  # Already up to date

        if pure:
            wrapped = _wrap_with_markers(generated, content_hash)
            filepath.write_text(wrapped + "\n", encoding="utf-8")
        else:
            wrapped = _wrap_with_markers(generated, content_hash)
            updated = _replace_marker_block(existing, wrapped)
            filepath.write_text(updated, encoding="utf-8")
    else:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        wrapped = _wrap_with_markers(generated, content_hash)
        filepath.write_text(wrapped + "\n", encoding="utf-8")

    return True


def _write_json_idempotent(filepath: Path, data: dict[str, Any]) -> bool:
    """Write a JSON file idempotently using a hash key inside the JSON."""
    # Remove old hash before computing new one
    clean_data = {k: v for k, v in data.items() if k != JSON_MARKER_KEY}
    content_hash = _content_hash(json.dumps(clean_data, sort_keys=True))

    if filepath.exists():
        try:
            existing = json.loads(filepath.read_text(encoding="utf-8"))
            if existing.get(JSON_MARKER_KEY) == content_hash:
                return False
        except (json.JSONDecodeError, OSError):
            pass

    data_with_hash = {JSON_MARKER_KEY: content_hash, **clean_data}
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(
        json.dumps(data_with_hash, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return True


# ── Template Loading ───────────────────────────────────────────────────────


def _load_template(name: str) -> str:
    """Load a template file from templates/platforms/."""
    tmpl_path = TEMPLATES_DIR / name
    if not tmpl_path.exists():
        _err(f"Template not found: {tmpl_path}")
        return ""
    return tmpl_path.read_text(encoding="utf-8")


def _escape_js_string(value: str) -> str:
    """Escape a string for safe embedding inside a JS string literal."""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("'", "\\'")
        .replace("`", "\\`")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("${", "\\${")
    )


def _render_template(template: str, variables: dict[str, str]) -> str:
    """Render a template by replacing {{VAR}} placeholders."""
    result = template
    for key, value in variables.items():
        result = result.replace("{{" + key + "}}", value)
    return result


# ── Platform Exporters ─────────────────────────────────────────────────────


def _to_opencode(skills: list[dict[str, Any]], output_dir: Path) -> list[str]:
    """Generate OpenCode configuration and JS plugin wrappers.

    Creates:
        <output>/opencode.json          -- plugin registry
        <output>/.opencode/plugins/*.js -- JS wrapper per skill
    """
    created: list[str] = []

    # Build plugin registry
    plugins = []
    for skill in skills:
        plugin_entry = {
            "name": f"claw-{skill['name']}",
            "description": skill["description"],
            "entry": f".opencode/plugins/{skill['name']}.js",
            "skill": skill["name"],
        }
        plugins.append(plugin_entry)

    registry = {
        "claw_version": _read_plugin_version(),
        "generated_by": "platform_exporter.py",
        "plugins": plugins,
    }

    oc_json = output_dir / "opencode.json"
    if _write_json_idempotent(oc_json, registry):
        created.append(str(oc_json))

    # Generate JS wrappers
    js_tmpl = _load_template("opencode-wrapper.js.tmpl")
    plugins_dir = output_dir / ".opencode" / "plugins"

    for skill in skills:
        variables = {
            "SKILL_NAME": _escape_js_string(skill["name"]),
            "SKILL_DESCRIPTION": _escape_js_string(skill["description"]),
            "SKILL_ARGUMENT_HINT": _escape_js_string(skill["frontmatter"].get("argument-hint", "")),
        }
        rendered = _render_template(js_tmpl, variables)
        js_path = plugins_dir / f"{skill['name']}.js"

        if _write_idempotent(js_path, rendered, pure=True):
            created.append(str(js_path))

    return created


def _to_openclaw(skills: list[dict[str, Any]], output_dir: Path) -> list[str]:
    """Generate OpenClaw AgentSkills format SKILL.md files.

    Creates:
        <output>/.openclaw/skills/<name>/SKILL.md
    """
    created: list[str] = []
    tmpl = _load_template("SKILL.md.tmpl")

    for skill in skills:
        variables = {
            "SKILL_NAME": skill["name"],
            "SKILL_DESCRIPTION": skill["description"],
            "SKILL_BODY": skill["body"],
            "SKILL_ARGUMENT_HINT": skill["frontmatter"].get("argument-hint", ""),
        }
        rendered = _render_template(tmpl, variables)
        skill_path = output_dir / ".openclaw" / "skills" / skill["name"] / "SKILL.md"

        if _write_idempotent(skill_path, rendered, pure=True):
            created.append(str(skill_path))

    return created


def _to_cursor_mdc(skills: list[dict[str, Any]], output_dir: Path) -> list[str]:
    """Generate Cursor MDC rule files.

    Creates:
        <output>/.cursor/rules/claw-<name>.mdc
    """
    created: list[str] = []
    tmpl = _load_template("cursor-rule.mdc.tmpl")

    for skill in skills:
        variables = {
            "SKILL_NAME": skill["name"],
            "SKILL_DESCRIPTION": skill["description"],
            "SKILL_BODY": skill["body"],
            "SKILL_ARGUMENT_HINT": skill["frontmatter"].get("argument-hint", ""),
        }
        rendered = _render_template(tmpl, variables)
        mdc_path = output_dir / ".cursor" / "rules" / f"claw-{skill['name']}.mdc"

        if _write_idempotent(mdc_path, rendered, pure=True):
            created.append(str(mdc_path))

    return created


def _to_windsurf(skills: list[dict[str, Any]], output_dir: Path) -> list[str]:
    """Generate Windsurf rule files.

    Creates:
        <output>/.windsurf/rules/claw-<name>.md
    """
    created: list[str] = []

    for skill in skills:
        # Windsurf uses plain markdown rules, similar to Cursor but .md
        header = (
            f"# CodeClaw Skill: {skill['name']}\n\n"
            f"> {skill['description']}\n\n"
        )
        if skill["frontmatter"].get("argument-hint"):
            header += f"**Usage:** `/{skill['name']} {skill['frontmatter']['argument-hint']}`\n\n"
        header += "---\n\n"
        rendered = header + skill["body"]

        md_path = output_dir / ".windsurf" / "rules" / f"claw-{skill['name']}.md"

        if _write_idempotent(md_path, rendered, pure=True):
            created.append(str(md_path))

    return created


def _to_continue(skills: list[dict[str, Any]], output_dir: Path) -> list[str]:
    """Generate Continue.dev assistant configuration.

    Creates:
        <output>/.continue/assistants/claw-<name>.json
    """
    created: list[str] = []

    for skill in skills:
        body = skill["body"]
        if len(body) > 2000:
            _info(
                f"  WARNING: skill '{skill['name']}' body truncated from "
                f"{len(body)} to 2000 chars for Continue.dev size limit."
            )
            body = body[:2000]
        assistant = {
            "name": f"CodeClaw {skill['name'].title()}",
            "description": skill["description"],
            "instructions": body,
            "slash_command": f"/{skill['name']}",
        }
        if skill["frontmatter"].get("argument-hint"):
            assistant["argument_hint"] = skill["frontmatter"]["argument-hint"]

        json_path = (
            output_dir / ".continue" / "assistants" / f"claw-{skill['name']}.json"
        )

        if _write_json_idempotent(json_path, assistant):
            created.append(str(json_path))

    return created


def _to_copilot(skills: list[dict[str, Any]], output_dir: Path) -> list[str]:
    """Generate GitHub Copilot instructions file.

    Creates:
        <output>/.github/copilot-instructions.md

    All skills are combined into a single instructions file since
    Copilot uses one unified context file.
    """
    created: list[str] = []

    sections: list[str] = []
    sections.append("# CodeClaw Project Skills\n")
    sections.append(
        "This project uses CodeClaw. "
        "The following skills are available:\n"
    )

    for skill in skills:
        section = f"## {skill['name'].title()} Skill\n\n"
        section += f"**Description:** {skill['description']}\n\n"
        if skill["frontmatter"].get("argument-hint"):
            section += (
                f"**Usage:** `/{skill['name']} "
                f"{skill['frontmatter']['argument-hint']}`\n\n"
            )
        section += "---\n\n"
        section += skill["body"]
        sections.append(section)

    rendered = "\n\n".join(sections)
    copilot_path = output_dir / ".github" / "copilot-instructions.md"

    if _write_idempotent(copilot_path, rendered, pure=True):
        created.append(str(copilot_path))

    return created


def _to_agents_md(skills: list[dict[str, Any]], output_dir: Path) -> list[str]:
    """Generate universal AGENTS.md file.

    Creates:
        <output>/AGENTS.md

    The AGENTS.md standard is used by multiple AI coding tools as a
    project-level instruction file.  All skills are combined into one
    document.
    """
    created: list[str] = []
    tmpl = _load_template("AGENTS.md.tmpl")

    # Build the skills table
    skill_table_rows: list[str] = []
    for skill in skills:
        arg_hint = skill["frontmatter"].get("argument-hint", "")
        skill_table_rows.append(
            f"| `/{skill['name']}` | {skill['description']} | `{arg_hint}` |"
        )
    skill_table = "\n".join(skill_table_rows)

    # Build individual skill sections
    skill_sections: list[str] = []
    for skill in skills:
        section = f"### {skill['name'].title()}\n\n"
        section += f"> {skill['description']}\n\n"
        if skill["frontmatter"].get("argument-hint"):
            section += (
                f"**Arguments:** `{skill['frontmatter']['argument-hint']}`\n\n"
            )
        section += skill["body"]
        skill_sections.append(section)

    skill_details = "\n\n---\n\n".join(skill_sections)

    variables = {
        "SKILL_TABLE": skill_table,
        "SKILL_DETAILS": skill_details,
        "GENERATED_DATE": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    rendered = _render_template(tmpl, variables)
    agents_path = output_dir / "AGENTS.md"

    if _write_idempotent(agents_path, rendered, pure=True):
        created.append(str(agents_path))

    return created


# ── Export Dispatcher ──────────────────────────────────────────────────────

EXPORTERS = {
    "opencode": _to_opencode,
    "openclaw": _to_openclaw,
    "cursor": _to_cursor_mdc,
    "windsurf": _to_windsurf,
    "continue": _to_continue,
    "copilot": _to_copilot,
    "agents_md": _to_agents_md,
}


def export_target(
    target: str,
    output_dir: Path,
    skills_dir: Path | None = None,
) -> dict[str, Any]:
    """Export skills to a specific platform target.

    Returns a result dict with: target, files_created, files_unchanged, errors.
    """
    if target not in EXPORTERS:
        return {
            "target": target,
            "success": False,
            "files_created": [],
            "files_unchanged": [],
            "errors": [f"Unknown target: {target}. Use one of: {', '.join(SUPPORTED_TARGETS)}"],
        }

    skills = discover_skills(skills_dir)
    if not skills:
        return {
            "target": target,
            "success": False,
            "files_created": [],
            "files_unchanged": [],
            "errors": ["No skills found. Ensure skills/*/SKILL.md files exist."],
        }

    try:
        created = EXPORTERS[target](skills, output_dir)
    except Exception as exc:
        return {
            "target": target,
            "success": False,
            "files_created": [],
            "files_unchanged": [],
            "errors": [str(exc)],
        }

    return {
        "target": target,
        "success": True,
        "files_created": created,
        "skills_count": len(skills),
        "errors": [],
    }


def export_all(
    output_dir: Path,
    skills_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Export skills to all supported platform targets."""
    results = []
    for target in SUPPORTED_TARGETS:
        results.append(export_target(target, output_dir, skills_dir))
    return results


# ── CLI ────────────────────────────────────────────────────────────────────


def _err(msg: str) -> None:
    """Print error to stderr."""
    print(f"ERROR: {msg}", file=sys.stderr)


def _info(msg: str) -> None:
    """Print info to stderr (keeps stdout clean for JSON)."""
    print(msg, file=sys.stderr)


def cmd_export(args: argparse.Namespace) -> int:
    """Handle the 'export' subcommand."""
    target = args.target.replace("-", "_")
    output_dir = Path(args.output).resolve()
    skills_dir = Path(args.skills_dir).resolve() if args.skills_dir else None

    result = export_target(target, output_dir, skills_dir)
    print(json.dumps(result, indent=2))

    if not result["success"]:
        for err in result["errors"]:
            _err(err)
        return 1

    created = result["files_created"]
    if created:
        _info(f"Exported {len(created)} file(s) for target '{args.target}':")
        for f in created:
            _info(f"  + {f}")
    else:
        _info(f"Target '{args.target}': all files already up to date.")

    return 0


def cmd_export_all(args: argparse.Namespace) -> int:
    """Handle the 'export-all' subcommand."""
    output_dir = Path(args.output).resolve()
    skills_dir = Path(args.skills_dir).resolve() if args.skills_dir else None

    results = export_all(output_dir, skills_dir)
    print(json.dumps(results, indent=2))

    total_created = 0
    total_errors = 0
    for r in results:
        total_created += len(r["files_created"])
        total_errors += len(r["errors"])
        if r["errors"]:
            for err in r["errors"]:
                _err(f"[{r['target']}] {err}")

    _info(f"Export complete: {total_created} file(s) created/updated across {len(SUPPORTED_TARGETS)} targets.")
    if total_errors:
        _info(f"  {total_errors} error(s) encountered.")
        return 1
    return 0


def cmd_list_targets(_args: argparse.Namespace) -> int:
    """Handle the 'list-targets' subcommand."""
    targets_info = []
    for t in SUPPORTED_TARGETS:
        targets_info.append({
            "target": t,
            "description": _target_description(t),
        })
    print(json.dumps(targets_info, indent=2))
    return 0


def cmd_list_skills(args: argparse.Namespace) -> int:
    """Handle the 'list-skills' subcommand."""
    skills_dir = Path(args.skills_dir).resolve() if args.skills_dir else None
    skills = discover_skills(skills_dir)
    summary = []
    for s in skills:
        summary.append({
            "name": s["name"],
            "description": s["description"],
            "path": s["path"],
            "argument_hint": s["frontmatter"].get("argument-hint", ""),
        })
    print(json.dumps(summary, indent=2))
    return 0


def _target_description(target: str) -> str:
    """Return a human-readable description for a target."""
    descs = {
        "opencode": "OpenCode JSON config + JS plugin wrappers (.opencode/plugins/)",
        "openclaw": "OpenClaw AgentSkills SKILL.md format (.openclaw/skills/)",
        "cursor": "Cursor MDC rule files (.cursor/rules/*.mdc)",
        "windsurf": "Windsurf rule files (.windsurf/rules/*.md)",
        "continue": "Continue.dev assistant configs (.continue/assistants/)",
        "copilot": "GitHub Copilot instructions (.github/copilot-instructions.md)",
        "agents_md": "Universal AGENTS.md standard (AGENTS.md)",
    }
    return descs.get(target, target)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="platform_exporter",
        description="Cross-platform config generator for CodeClaw skills.",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # export
    p_export = sub.add_parser(
        "export",
        help="Export skills to a specific platform target",
    )
    p_export.add_argument(
        "--target", "-t",
        required=True,
        choices=SUPPORTED_TARGETS,
        help="Target platform",
    )
    p_export.add_argument(
        "--output", "-o",
        default=".",
        help="Output directory (default: current directory)",
    )
    p_export.add_argument(
        "--skills-dir", "-s",
        default=None,
        help="Override skills directory (default: auto-detect)",
    )
    p_export.set_defaults(func=cmd_export)

    # export-all
    p_export_all = sub.add_parser(
        "export-all",
        help="Export skills to all supported platform targets",
    )
    p_export_all.add_argument(
        "--output", "-o",
        default=".",
        help="Output directory (default: current directory)",
    )
    p_export_all.add_argument(
        "--skills-dir", "-s",
        default=None,
        help="Override skills directory (default: auto-detect)",
    )
    p_export_all.set_defaults(func=cmd_export_all)

    # list-targets
    p_list = sub.add_parser(
        "list-targets",
        help="List all supported export targets",
    )
    p_list.set_defaults(func=cmd_list_targets)

    # list-skills
    p_skills = sub.add_parser(
        "list-skills",
        help="List discovered skills",
    )
    p_skills.add_argument(
        "--skills-dir", "-s",
        default=None,
        help="Override skills directory (default: auto-detect)",
    )
    p_skills.set_defaults(func=cmd_list_skills)

    return parser


def main() -> int:
    """Entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
