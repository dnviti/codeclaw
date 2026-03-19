#!/usr/bin/env python3
"""Frontend design wizard for claude-task-development-framework.

Detects the project's frontend framework, searches for starter templates,
offers bundled color palettes, and generates design constraints (CSS variables,
typography, motion settings) that guide task implementation.

Zero external dependencies -- stdlib only.

Usage:
    python3 frontend_wizard.py detect-framework --root /path/to/project
    python3 frontend_wizard.py search-templates --framework react --query "dashboard"
    python3 frontend_wizard.py list-palettes
    python3 frontend_wizard.py generate-palette --seed "#3b82f6"
    python3 frontend_wizard.py apply-constraints --template T --palette P
    python3 frontend_wizard.py run --root /path/to/project [--yolo]
"""

import argparse
import colorsys
import json
import re
import subprocess
import sys
from pathlib import Path

# ── Constants ────────────────────────────────────────────────────────────────

_SCRIPT_DIR = Path(__file__).resolve().parent
PALETTES_DIR = _SCRIPT_DIR / "palettes"

# Framework detection config files and their associated framework names
FRAMEWORK_INDICATORS = {
    "next.config.js": "nextjs",
    "next.config.mjs": "nextjs",
    "next.config.ts": "nextjs",
    "nuxt.config.js": "nuxt",
    "nuxt.config.ts": "nuxt",
    "svelte.config.js": "svelte",
    "svelte.config.ts": "svelte",
    "angular.json": "angular",
    "astro.config.mjs": "astro",
    "astro.config.ts": "astro",
    "remix.config.js": "remix",
    "remix.config.ts": "remix",
    "gatsby-config.js": "gatsby",
    "gatsby-config.ts": "gatsby",
    "vite.config.js": "vite",
    "vite.config.ts": "vite",
}

# package.json dependency -> framework mapping (checked after config files)
DEPENDENCY_FRAMEWORKS = {
    "next": "nextjs",
    "nuxt": "nuxt",
    "react": "react",
    "vue": "vue",
    "svelte": "svelte",
    "@angular/core": "angular",
    "astro": "astro",
    "@remix-run/react": "remix",
    "gatsby": "gatsby",
    "solid-js": "solid",
    "preact": "preact",
    "lit": "lit",
}

# Default typography stacks per framework style
TYPOGRAPHY_STACKS = {
    "modern": (
        "'Inter', 'Segoe UI', -apple-system, BlinkMacSystemFont, "
        "'Helvetica Neue', Arial, sans-serif"
    ),
    "editorial": (
        "'Playfair Display', 'Georgia', 'Times New Roman', "
        "'Noto Serif', serif"
    ),
    "monospace": (
        "'JetBrains Mono', 'Fira Code', 'SF Mono', 'Cascadia Code', "
        "'Consolas', monospace"
    ),
    "system": (
        "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', "
        "'Oxygen', 'Ubuntu', 'Cantarell', sans-serif"
    ),
}

# GitHub template search queries per framework
TEMPLATE_SEARCH_QUERIES = {
    "nextjs": "nextjs template starter",
    "react": "react template starter vite",
    "vue": "vue template starter vite",
    "nuxt": "nuxt template starter",
    "svelte": "sveltekit template starter",
    "angular": "angular template starter",
    "astro": "astro template starter",
    "remix": "remix template starter",
    "gatsby": "gatsby starter template",
    "solid": "solid-js template starter",
    "vite": "vite template starter",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _hex_to_hsl(hex_color: str) -> tuple[float, float, float]:
    """Convert a hex color string to HSL (h: 0-360, s: 0-100, l: 0-100).

    Raises:
        ValueError: If hex_color is not a valid 3- or 6-digit hex color.
    """
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(c * 2 for c in hex_color)
    if len(hex_color) != 6 or not re.match(r'^[0-9a-fA-F]{6}$', hex_color):
        raise ValueError(f"Invalid hex color: #{hex_color}")
    r, g, b = (int(hex_color[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return round(h * 360, 1), round(s * 100, 1), round(l * 100, 1)


def _hsl_to_hex(h: float, s: float, l: float) -> str:
    """Convert HSL (h: 0-360, s: 0-100, l: 0-100) to hex color string."""
    r, g, b = colorsys.hls_to_rgb(h / 360.0, l / 100.0, s / 100.0)
    return "#{:02x}{:02x}{:02x}".format(
        int(round(r * 255)),
        int(round(g * 255)),
        int(round(b * 255)),
    )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp a value between minimum and maximum."""
    return max(minimum, min(maximum, value))


# ── FrontendWizard Class ────────────────────────────────────────────────────

class FrontendWizard:
    """Design wizard orchestrator for frontend tasks.

    Detects the project framework, searches for starter templates,
    provides palette options, and generates design constraints.
    """

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root).resolve() if root else Path.cwd().resolve()

    # ── Framework Detection ──────────────────────────────────────────────

    def detect_framework(self, root: str | Path | None = None) -> str:
        """Detect the frontend framework from project config files and package.json.

        Returns the framework identifier string (e.g., 'react', 'nextjs', 'vue')
        or 'vanilla' if no framework is detected.
        """
        project_root = Path(root).resolve() if root else self.root

        # 1. Check for framework-specific config files
        for config_file, framework in FRAMEWORK_INDICATORS.items():
            if (project_root / config_file).exists():
                return framework

        # 2. Check package.json dependencies
        pkg_path = project_root / "package.json"
        if pkg_path.exists():
            try:
                pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
                all_deps = {}
                for dep_key in ("dependencies", "devDependencies", "peerDependencies"):
                    all_deps.update(pkg.get(dep_key, {}))

                # Check in priority order (meta-frameworks before base frameworks)
                for dep_name, framework in DEPENDENCY_FRAMEWORKS.items():
                    if dep_name in all_deps:
                        return framework
            except (json.JSONDecodeError, OSError):
                pass

        # 3. Check for index.html (vanilla frontend project)
        if (project_root / "index.html").exists():
            return "vanilla"

        # 4. Check for src/index.html or public/index.html
        for subdir in ("src", "public"):
            if (project_root / subdir / "index.html").exists():
                return "vanilla"

        return "vanilla"

    # ── Template Search ──────────────────────────────────────────────────

    def search_templates(
        self, framework: str, query: str = "", limit: int = 3
    ) -> list[dict]:
        """Search GitHub for starter templates matching the framework.

        Uses the GitHub API via the `gh` CLI to find relevant templates.
        Returns a list of dicts with keys: name, url, description, stars.
        """
        base_query = TEMPLATE_SEARCH_QUERIES.get(framework, f"{framework} template")
        if query:
            # Sanitize user query: strip GitHub search operators to prevent
            # query manipulation (e.g., injecting "is:private" or "org:...")
            sanitized = re.sub(r'\b\w+:', '', query).strip()
            sanitized = sanitized[:200]  # Cap query length
            search_query = f"{base_query} {sanitized}" if sanitized else base_query
        else:
            search_query = base_query

        try:
            result = subprocess.run(
                [
                    "gh", "api", "search/repositories",
                    "-X", "GET",
                    "-f", f"q={search_query} in:name,description",
                    "-f", "sort=stars",
                    "-f", "order=desc",
                    "-f", f"per_page={limit}",
                    "--jq", ".items[] | {name: .full_name, url: .html_url, "
                    "description: .description, stars: .stargazers_count}",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return self._fallback_templates(framework)

            templates = []
            # gh --jq outputs one JSON object per line
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    templates.append({
                        "name": obj.get("name", ""),
                        "url": obj.get("url", ""),
                        "description": (obj.get("description") or "")[:120],
                        "stars": obj.get("stars", 0),
                    })
                except json.JSONDecodeError:
                    continue
            return templates[:limit] if templates else self._fallback_templates(framework)

        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return self._fallback_templates(framework)

    def _fallback_templates(self, framework: str) -> list[dict]:
        """Provide curated fallback templates when GitHub API is unavailable."""
        fallbacks = {
            "nextjs": [
                {
                    "name": "vercel/next.js/examples/with-tailwindcss",
                    "url": "https://github.com/vercel/next.js/tree/canary/examples/with-tailwindcss",
                    "description": "Next.js starter with Tailwind CSS pre-configured",
                    "stars": 0,
                },
                {
                    "name": "shadcn-ui/next-template",
                    "url": "https://github.com/shadcn-ui/next-template",
                    "description": "Next.js 14 template with shadcn/ui components",
                    "stars": 0,
                },
                {
                    "name": "vercel/next.js/examples/with-typescript",
                    "url": "https://github.com/vercel/next.js/tree/canary/examples/with-typescript",
                    "description": "Next.js TypeScript starter template",
                    "stars": 0,
                },
            ],
            "react": [
                {
                    "name": "vitejs/vite/packages/create-vite/template-react-ts",
                    "url": "https://github.com/vitejs/vite/tree/main/packages/create-vite/template-react-ts",
                    "description": "React + TypeScript Vite starter",
                    "stars": 0,
                },
                {
                    "name": "alan2207/bulletproof-react",
                    "url": "https://github.com/alan2207/bulletproof-react",
                    "description": "Scalable React architecture with best practices",
                    "stars": 0,
                },
                {
                    "name": "shadcn-ui/ui",
                    "url": "https://github.com/shadcn-ui/ui",
                    "description": "Beautifully designed components built with Radix UI and Tailwind",
                    "stars": 0,
                },
            ],
            "vue": [
                {
                    "name": "vitejs/vite/packages/create-vite/template-vue-ts",
                    "url": "https://github.com/vitejs/vite/tree/main/packages/create-vite/template-vue-ts",
                    "description": "Vue 3 + TypeScript Vite starter",
                    "stars": 0,
                },
                {
                    "name": "antfu/vitesse",
                    "url": "https://github.com/antfu/vitesse",
                    "description": "Opinionated Vue + Vite starter template",
                    "stars": 0,
                },
                {
                    "name": "vbenjs/vue-vben-admin",
                    "url": "https://github.com/vbenjs/vue-vben-admin",
                    "description": "Modern Vue 3 admin template",
                    "stars": 0,
                },
            ],
            "svelte": [
                {
                    "name": "sveltejs/kit/packages/create-svelte",
                    "url": "https://github.com/sveltejs/kit",
                    "description": "Official SvelteKit starter with routing and SSR",
                    "stars": 0,
                },
                {
                    "name": "huntabyte/shadcn-svelte",
                    "url": "https://github.com/huntabyte/shadcn-svelte",
                    "description": "shadcn/ui components ported to Svelte",
                    "stars": 0,
                },
                {
                    "name": "sveltejs/template",
                    "url": "https://github.com/sveltejs/template",
                    "description": "Official Svelte component template",
                    "stars": 0,
                },
            ],
            "angular": [
                {
                    "name": "angular/angular-cli",
                    "url": "https://github.com/angular/angular-cli",
                    "description": "Official Angular CLI for generating projects",
                    "stars": 0,
                },
                {
                    "name": "tomastrajan/angular-ngrx-material-starter",
                    "url": "https://github.com/tomastrajan/angular-ngrx-material-starter",
                    "description": "Angular Material + NgRx starter",
                    "stars": 0,
                },
                {
                    "name": "nicolestandifer3/angular-real-world-example",
                    "url": "https://github.com/nicolestandifer3/angular-real-world-example",
                    "description": "Angular RealWorld example app",
                    "stars": 0,
                },
            ],
        }

        return fallbacks.get(framework, [
            {
                "name": f"{framework}-starter-template",
                "url": f"https://github.com/topics/{framework}",
                "description": f"Search GitHub for {framework} starter templates",
                "stars": 0,
            },
        ])

    # ── Palette Management ───────────────────────────────────────────────

    def get_palettes(self) -> dict:
        """Load all bundled palette collections from the palettes directory.

        Returns a dict keyed by palette file stem (e.g., 'open-color') with
        the full palette JSON as values.
        """
        palettes = {}
        if not PALETTES_DIR.is_dir():
            return palettes

        for palette_file in sorted(PALETTES_DIR.glob("*.json")):
            try:
                data = json.loads(palette_file.read_text(encoding="utf-8"))
                palettes[palette_file.stem] = data
            except (json.JSONDecodeError, OSError):
                continue

        return palettes

    def generate_palette(self, seed_color: str) -> dict:
        """Generate a complementary color palette from a seed hex color.

        Uses HSL color space to derive harmonious colors:
        - Primary: the seed color
        - Secondary: 30 degrees offset (analogous)
        - Accent: 180 degrees offset (complementary)
        - Success, warning, error: fixed hue positions
        - Neutral: desaturated version of the seed

        Each color includes a full tonal scale (50-900).
        """
        h, s, l = _hex_to_hsl(seed_color)

        def _tonal_scale(hue: float, sat: float) -> dict:
            """Generate a 10-step tonal scale for a hue/saturation pair."""
            lightness_steps = {
                "50": 97, "100": 93, "200": 86, "300": 76,
                "400": 62, "500": 50, "600": 42, "700": 34,
                "800": 26, "900": 18,
            }
            scale = {}
            for step, light in lightness_steps.items():
                # Slightly adjust saturation at extremes for more natural feel
                adjusted_sat = sat
                if light > 90:
                    adjusted_sat = max(sat * 0.3, 5)
                elif light > 80:
                    adjusted_sat = max(sat * 0.6, 10)
                elif light < 25:
                    adjusted_sat = max(sat * 0.8, 15)
                scale[step] = _hsl_to_hex(hue, adjusted_sat, light)
            return scale

        palette = {
            "name": f"Generated from {seed_color}",
            "source": "seed-generated",
            "description": f"HSL-based complementary palette generated from seed color {seed_color}.",
            "seed": seed_color,
            "palettes": {
                "primary": _tonal_scale(h, s),
                "secondary": _tonal_scale((h + 30) % 360, _clamp(s * 0.9, 10, 100)),
                "accent": _tonal_scale((h + 180) % 360, _clamp(s * 0.85, 10, 100)),
                "success": _tonal_scale(145, _clamp(s * 0.7, 30, 80)),
                "warning": _tonal_scale(38, _clamp(s * 0.8, 40, 90)),
                "error": _tonal_scale(0, _clamp(s * 0.85, 50, 95)),
                "neutral": _tonal_scale(h, _clamp(s * 0.1, 2, 12)),
            },
            "recommended": {
                "primary": "primary",
                "accent": "accent",
                "success": "success",
                "warning": "warning",
                "error": "error",
                "neutral": "neutral",
            },
        }

        return palette

    # ── Design Constraints ───────────────────────────────────────────────

    def apply_design_constraints(
        self,
        template: dict | None = None,
        palette: dict | None = None,
        typography: str = "modern",
        motion: bool = True,
    ) -> dict:
        """Generate design constraints from a template and palette selection.

        Returns a dict containing:
        - css_variables: dict of CSS custom properties for theming
        - typography: font stack and sizing
        - motion: animation/transition settings
        - background: atmospheric background recommendations
        - template_ref: reference to selected template
        """
        # Resolve palette colors
        palette_data = palette or {}
        palettes = palette_data.get("palettes", {})
        recommended = palette_data.get("recommended", {})

        primary_key = recommended.get("primary", "blue")
        accent_key = recommended.get("accent", "violet")
        neutral_key = recommended.get("neutral", "gray")
        success_key = recommended.get("success", "green")
        warning_key = recommended.get("warning", "orange")
        error_key = recommended.get("error", "red")

        def _get_color(key: str, shade: str, fallback: str) -> str:
            """Safely get a color from the palette."""
            color_set = palettes.get(key, {})
            return color_set.get(shade, fallback)

        # Build CSS variables
        css_variables = {
            "--color-primary-50": _get_color(primary_key, "50", "#eff6ff"),
            "--color-primary-100": _get_color(primary_key, "100", "#dbeafe"),
            "--color-primary-200": _get_color(primary_key, "200", "#bfdbfe"),
            "--color-primary-300": _get_color(primary_key, "300", "#93c5fd"),
            "--color-primary-400": _get_color(primary_key, "400", "#60a5fa"),
            "--color-primary-500": _get_color(primary_key, "500", "#3b82f6"),
            "--color-primary-600": _get_color(primary_key, "600", "#2563eb"),
            "--color-primary-700": _get_color(primary_key, "700", "#1d4ed8"),
            "--color-primary-800": _get_color(primary_key, "800", "#1e40af"),
            "--color-primary-900": _get_color(primary_key, "900", "#1e3a8a"),
            "--color-accent-500": _get_color(accent_key, "500", "#8b5cf6"),
            "--color-accent-600": _get_color(accent_key, "600", "#7c3aed"),
            "--color-neutral-50": _get_color(neutral_key, "50", "#f8fafc"),
            "--color-neutral-100": _get_color(neutral_key, "100", "#f1f5f9"),
            "--color-neutral-200": _get_color(neutral_key, "200", "#e2e8f0"),
            "--color-neutral-700": _get_color(neutral_key, "700", "#334155"),
            "--color-neutral-800": _get_color(neutral_key, "800", "#1e293b"),
            "--color-neutral-900": _get_color(neutral_key, "900", "#0f172a"),
            "--color-success-500": _get_color(success_key, "500", "#22c55e"),
            "--color-warning-500": _get_color(warning_key, "500", "#f97316"),
            "--color-error-500": _get_color(error_key, "500", "#ef4444"),
            # Typography
            "--font-family-body": TYPOGRAPHY_STACKS.get(
                typography, TYPOGRAPHY_STACKS["system"]
            ),
            "--font-family-heading": TYPOGRAPHY_STACKS.get(
                typography, TYPOGRAPHY_STACKS["system"]
            ),
            "--font-family-mono": TYPOGRAPHY_STACKS["monospace"],
            "--font-size-xs": "0.75rem",
            "--font-size-sm": "0.875rem",
            "--font-size-base": "1rem",
            "--font-size-lg": "1.125rem",
            "--font-size-xl": "1.25rem",
            "--font-size-2xl": "1.5rem",
            "--font-size-3xl": "1.875rem",
            "--font-size-4xl": "2.25rem",
            # Spacing
            "--spacing-unit": "0.25rem",
            "--radius-sm": "0.25rem",
            "--radius-md": "0.375rem",
            "--radius-lg": "0.5rem",
            "--radius-xl": "0.75rem",
            "--radius-2xl": "1rem",
            "--radius-full": "9999px",
        }

        # Motion settings
        motion_config = {
            "enabled": motion,
            "transition_fast": "150ms cubic-bezier(0.4, 0, 0.2, 1)",
            "transition_base": "200ms cubic-bezier(0.4, 0, 0.2, 1)",
            "transition_slow": "300ms cubic-bezier(0.4, 0, 0.2, 1)",
            "transition_spring": "500ms cubic-bezier(0.34, 1.56, 0.64, 1)",
            "css_only_recommended": True,
            "motion_library": "framer-motion",
            "reduce_motion_query": "@media (prefers-reduced-motion: reduce)",
        }
        if motion:
            css_variables["--transition-fast"] = motion_config["transition_fast"]
            css_variables["--transition-base"] = motion_config["transition_base"]
            css_variables["--transition-slow"] = motion_config["transition_slow"]
            css_variables["--transition-spring"] = motion_config["transition_spring"]

        # Background recommendations (atmospheric, not flat)
        background = {
            "style": "atmospheric",
            "recommendation": (
                "Use subtle gradients, grain textures, or layered radial "
                "gradients instead of flat solid backgrounds. Combine "
                "neutral-50 with primary-50 for depth."
            ),
            "css_example": (
                "background: linear-gradient(135deg, "
                f"{_get_color(neutral_key, '50', '#f8fafc')} 0%, "
                f"{_get_color(primary_key, '50', '#eff6ff')} 50%, "
                f"{_get_color(neutral_key, '100', '#f1f5f9')} 100%);"
            ),
        }

        constraints = {
            "css_variables": css_variables,
            "typography": {
                "stack": typography,
                "font_family": TYPOGRAPHY_STACKS.get(
                    typography, TYPOGRAPHY_STACKS["system"]
                ),
                "scale": "modular (1.25 ratio)",
                "heading_weight": "700",
                "body_weight": "400",
                "line_height_body": "1.6",
                "line_height_heading": "1.2",
            },
            "motion": motion_config,
            "background": background,
            "palette_name": palette_data.get("name", "custom"),
            "template_ref": template or {},
        }

        return constraints

    # ── Wizard Runner ────────────────────────────────────────────────────

    def run(self, yolo: bool = False) -> dict:
        """Execute the full design wizard flow.

        In yolo mode, auto-selects the first template and the recommended
        palette without user interaction.

        Returns a dict summarizing the wizard results:
        - framework: detected framework
        - templates: list of found templates
        - selected_template: chosen template (first in yolo mode)
        - palettes: available palette names
        - selected_palette: chosen palette name
        - constraints: generated design constraints
        """
        # Step 1: Detect framework
        framework = self.detect_framework()

        # Step 2: Search for templates
        templates = self.search_templates(framework)

        # Step 3: Load palettes
        palettes = self.get_palettes()
        palette_names = list(palettes.keys())

        if yolo:
            # In yolo mode, auto-select first template and first palette
            selected_template = templates[0] if templates else None
            selected_palette_name = palette_names[0] if palette_names else None
            selected_palette = (
                palettes[selected_palette_name] if selected_palette_name else None
            )

            # Generate constraints with auto-selected options
            constraints = self.apply_design_constraints(
                template=selected_template,
                palette=selected_palette,
                typography="modern",
                motion=True,
            )
        else:
            # In interactive mode, present options without auto-selecting
            selected_template = None
            selected_palette_name = None
            constraints = None

        result = {
            "framework": framework,
            "templates": templates,
            "selected_template": selected_template,
            "palettes": palette_names,
            "selected_palette": selected_palette_name,
            "constraints": constraints,
            "yolo": yolo,
        }

        return result


# ── CLI Commands ─────────────────────────────────────────────────────────────

def cmd_detect_framework(args):
    """Detect the frontend framework for a project."""
    wizard = FrontendWizard(root=args.root)
    framework = wizard.detect_framework()
    print(json.dumps({"framework": framework, "root": str(wizard.root)}))


def cmd_search_templates(args):
    """Search for starter templates matching a framework."""
    wizard = FrontendWizard()
    templates = wizard.search_templates(
        framework=args.framework,
        query=args.query or "",
        limit=args.limit,
    )
    print(json.dumps({"framework": args.framework, "templates": templates}, indent=2))


def cmd_list_palettes(args):
    """List all available bundled palettes."""
    wizard = FrontendWizard()
    palettes = wizard.get_palettes()
    summary = {}
    for name, data in palettes.items():
        summary[name] = {
            "name": data.get("name", name),
            "description": data.get("description", ""),
            "source": data.get("source", ""),
            "color_groups": list(data.get("palettes", {}).keys()),
            "recommended": data.get("recommended", {}),
        }
    print(json.dumps(summary, indent=2))


def cmd_generate_palette(args):
    """Generate a palette from a seed color."""
    wizard = FrontendWizard()

    # Validate hex color format
    seed = args.seed.strip()
    if not re.match(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$", seed):
        print(json.dumps({"error": f"Invalid hex color: {seed}"}))
        sys.exit(1)

    if not seed.startswith("#"):
        seed = f"#{seed}"

    palette = wizard.generate_palette(seed)
    print(json.dumps(palette, indent=2))


def cmd_apply_constraints(args):
    """Apply design constraints from template and palette selections."""
    wizard = FrontendWizard()

    # Load palette
    palette = None
    if args.palette:
        palettes = wizard.get_palettes()
        if args.palette in palettes:
            palette = palettes[args.palette]
        elif args.palette.startswith("#"):
            if not re.match(r'^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$', args.palette):
                print(json.dumps({"error": f"Invalid hex color: {args.palette}"}))
                sys.exit(1)
            palette = wizard.generate_palette(args.palette)
        else:
            print(json.dumps({
                "error": f"Unknown palette: {args.palette}",
                "available": list(palettes.keys()),
            }))
            sys.exit(1)

    # Load template reference
    template = None
    if args.template:
        template = {"name": args.template, "url": "", "description": "User-specified"}

    constraints = wizard.apply_design_constraints(
        template=template,
        palette=palette,
        typography=args.typography or "modern",
        motion=not args.no_motion,
    )
    print(json.dumps(constraints, indent=2))


def cmd_run(args):
    """Run the full design wizard."""
    wizard = FrontendWizard(root=args.root)
    result = wizard.run(yolo=args.yolo)
    print(json.dumps(result, indent=2))


# ── Argument Parser ──────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Frontend design wizard for CodeClaw task implementation.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # detect-framework
    p = sub.add_parser(
        "detect-framework",
        help="Detect the frontend framework in a project",
    )
    p.add_argument("--root", default=".", help="Project root directory")
    p.set_defaults(func=cmd_detect_framework)

    # search-templates
    p = sub.add_parser(
        "search-templates",
        help="Search GitHub for framework starter templates",
    )
    p.add_argument("--framework", required=True, help="Framework name (e.g., react)")
    p.add_argument("--query", default="", help="Additional search terms")
    p.add_argument("--limit", type=int, default=3, help="Max results")
    p.set_defaults(func=cmd_search_templates)

    # list-palettes
    p = sub.add_parser("list-palettes", help="List bundled color palettes")
    p.set_defaults(func=cmd_list_palettes)

    # generate-palette
    p = sub.add_parser(
        "generate-palette",
        help="Generate a color palette from a seed hex color",
    )
    p.add_argument("--seed", required=True, help="Seed hex color (e.g., #3b82f6)")
    p.set_defaults(func=cmd_generate_palette)

    # apply-constraints
    p = sub.add_parser(
        "apply-constraints",
        help="Generate design constraints from template/palette selection",
    )
    p.add_argument("--template", default=None, help="Template name or URL")
    p.add_argument(
        "--palette", default=None,
        help="Palette name (e.g., tailwind) or seed hex color",
    )
    p.add_argument(
        "--typography", default="modern",
        choices=["modern", "editorial", "monospace", "system"],
        help="Typography style",
    )
    p.add_argument(
        "--no-motion", action="store_true", default=False,
        help="Disable motion/animation settings",
    )
    p.set_defaults(func=cmd_apply_constraints)

    # run
    p = sub.add_parser("run", help="Run the full design wizard flow")
    p.add_argument("--root", default=".", help="Project root directory")
    p.add_argument(
        "--yolo", action="store_true", default=False,
        help="Auto-select first template and recommended palette",
    )
    p.set_defaults(func=cmd_run)

    return parser


def main():
    parser = build_parser()
    try:
        args = parser.parse_args()
        args.func(args)
    except (ValueError, KeyError, TypeError) as e:
        print(json.dumps({"error": str(e), "type": type(e).__name__}))
        sys.exit(1)
    except Exception:
        print(json.dumps({"error": "An unexpected error occurred", "type": "InternalError"}))
        sys.exit(1)


if __name__ == "__main__":
    main()
