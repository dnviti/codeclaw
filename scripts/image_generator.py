#!/usr/bin/env python3
"""On-demand image generation with interactive preview for CTDF.

Provides a provider-agnostic image generation pipeline with cross-platform
preview and confirm/regenerate/cancel workflow. Supports local diffusion
models and cloud APIs (DALL-E, Replicate, Stability AI).

Subcommands:
    generate   Generate an image from a text prompt
    preview    Open an image file in the system viewer
    providers  List available/configured providers
    config     Show current image generation configuration

Zero external dependencies -- stdlib only for core logic.
Pillow is optional (used for preview fallback on headless systems).
"""

import argparse
import atexit
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional

# Add scripts/ to path for sibling package imports
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from platform_utils import open_file

# Maximum prompt length to prevent DoS on API endpoints
_MAX_PROMPT_LENGTH = 4000

# Track temp directories for cleanup
_TEMP_DIRS: list[Path] = []


def _cleanup_temp_dirs() -> None:
    """Remove temporary directories created during this session."""
    for d in _TEMP_DIRS:
        try:
            shutil.rmtree(str(d), ignore_errors=True)
        except OSError:
            pass


atexit.register(_cleanup_temp_dirs)


# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "enabled": False,
    "provider": "local",
    "api_key_env": "",
    "default_size": "1024x1024",
    "default_style": "natural",
    "output_dir": "assets/generated",
}


# ── Configuration ────────────────────────────────────────────────────────────

def _find_project_root() -> Path:
    """Find project root by looking for .claude/ or .git/."""
    current = Path.cwd()
    for parent in [current, *current.parents]:
        if (parent / ".claude").is_dir() or (parent / ".git").is_dir():
            return parent
    return current


def load_config() -> dict:
    """Load image generation configuration from project-config.json."""
    root = _find_project_root()
    config_path = root / ".claude" / "project-config.json"

    config = dict(DEFAULT_CONFIG)

    if config_path.exists():
        try:
            full_config = json.loads(
                config_path.read_text(encoding="utf-8")
            )
            img_config = full_config.get("image_generation", {})
            config.update(img_config)
        except (json.JSONDecodeError, OSError):
            pass

    return config


# ── Image Generator ──────────────────────────────────────────────────────────

class ImageGenerator:
    """Provider-agnostic image generation with preview and save workflow.

    Orchestrates the generate -> preview -> confirm/regenerate/cancel loop.
    """

    def __init__(self, config: Optional[dict] = None):
        self._config = config or load_config()
        self._provider = None

    @property
    def config(self) -> dict:
        """Return the current configuration."""
        return dict(self._config)

    def _get_provider(self):
        """Lazy-initialize the image provider."""
        if self._provider is None:
            from image_providers import create_provider
            self._provider = create_provider(self._config)
        return self._provider

    def generate(self, prompt: str, size: Optional[str] = None,
                 style: Optional[str] = None,
                 provider: Optional[str] = None) -> Path:
        """Generate an image and save to a temporary file.

        Parameters
        ----------
        prompt : str
            Text description of the desired image.
        size : str, optional
            Image dimensions (default from config).
        style : str, optional
            Style hint (default from config).
        provider : str, optional
            Override provider for this generation.

        Returns
        -------
        Path
            Path to the generated temporary image file.
        """
        # S-6: Cap prompt length to prevent DoS
        if len(prompt) > _MAX_PROMPT_LENGTH:
            prompt = prompt[:_MAX_PROMPT_LENGTH]

        size = size or self._config.get("default_size", "1024x1024")
        style = style or self._config.get("default_style", "natural")

        # Use override provider if specified
        if provider:
            from image_providers import create_provider
            config_override = dict(self._config)
            config_override["provider"] = provider
            gen_provider = create_provider(config_override)
        else:
            gen_provider = self._get_provider()

        # Generate image bytes
        image_bytes = gen_provider.generate(prompt, size=size, style=style)

        # Save to temp file (O-2: register for cleanup at exit)
        temp_dir = Path(tempfile.mkdtemp(prefix="ctdf_img_"))
        _TEMP_DIRS.append(temp_dir)
        # S-2: Sanitize prompt for filename — strip non-alphanum, guard
        # against dot-only or hidden-file names
        safe_name = "".join(
            c if c.isalnum() or c in "-_ " else "" for c in prompt[:50]
        ).strip().replace(" ", "_").lstrip(".")
        if not safe_name or safe_name in (".", ".."):
            safe_name = "generated"
        temp_path = temp_dir / f"{safe_name}.png"
        temp_path.write_bytes(image_bytes)

        return temp_path

    def preview(self, image_path: Path) -> bool:
        """Open an image file in the system's default viewer.

        Parameters
        ----------
        image_path : Path
            Path to the image file to preview.

        Returns
        -------
        bool
            True if preview was launched successfully.
        """
        return open_image_preview(image_path)

    def save(self, image_path: Path, target_path: Path) -> Path:
        """Copy a generated image to its final project location.

        Parameters
        ----------
        image_path : Path
            Path to the source image (usually a temp file).
        target_path : Path
            Destination path within the project. Must resolve to a
            location under the project root (path traversal is rejected).

        Returns
        -------
        Path
            The final path where the image was saved.

        Raises
        ------
        ValueError
            If target_path resolves outside the project root.
        """
        target_path = Path(target_path)
        project_root = _find_project_root()

        # S-1: Validate that target is within project root to prevent
        # path traversal (e.g., --output ../../etc/cron.d/evil)
        resolved = target_path.resolve()
        if not str(resolved).startswith(str(project_root.resolve())):
            raise ValueError(
                f"Target path must be within the project root "
                f"({project_root}). Got: {target_path}"
            )

        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(image_path), str(target_path))
        return target_path

    def get_output_dir(self) -> Path:
        """Get the configured output directory for generated images."""
        root = _find_project_root()
        output_dir = self._config.get("output_dir", "assets/generated")
        return root / output_dir

    def list_providers(self) -> list[dict]:
        """List all available image providers with their status."""
        from image_providers import create_provider

        providers_info = []
        for ptype in ("local", "dalle", "replicate", "stability"):
            info = {
                "provider": ptype,
                "configured": False,
                "available": False,
            }
            try:
                config_check = dict(self._config)
                config_check["provider"] = ptype
                p = create_provider(config_check)
                info["configured"] = True
                info["available"] = p.is_available()
                info["name"] = p.provider_name()
            except (ValueError, RuntimeError):
                info["name"] = ptype
            providers_info.append(info)

        return providers_info


# ── Cross-Platform Preview ───────────────────────────────────────────────────

def open_image_preview(image_path: Path) -> bool:
    """Open an image file in the system's default image viewer.

    Delegates to ``platform_utils.open_file()`` for cross-platform support,
    with a Pillow fallback for headless environments.

    Parameters
    ----------
    image_path : Path
        Path to the image file.

    Returns
    -------
    bool
        True if preview was successfully launched.
    """
    image_path = Path(image_path)
    if not image_path.exists():
        return False

    # O-1: Delegate to platform_utils.open_file instead of duplicating logic
    if open_file(image_path):
        return True

    # Fallback: try Pillow for headless environments
    try:
        from PIL import Image
        img = Image.open(str(image_path))
        img.show()
        return True
    except ImportError:
        pass
    except Exception:
        pass

    return False


# ── CLI ──────────────────────────────────────────────────────────────────────

def cmd_generate(args: argparse.Namespace) -> None:
    """Handle the 'generate' subcommand."""
    config = load_config()

    if not config.get("enabled", False):
        print(json.dumps({
            "success": False,
            "error": (
                "Image generation is disabled. Enable it in "
                "project-config.json > image_generation > enabled."
            ),
        }))
        return

    gen = ImageGenerator(config)

    try:
        image_path = gen.generate(
            prompt=args.prompt,
            size=args.size,
            style=args.style,
            provider=args.provider,
        )

        result = {
            "success": True,
            "image_path": str(image_path),
            "prompt": args.prompt,
            "size": args.size or config.get("default_size", "1024x1024"),
            "style": args.style or config.get("default_style", "natural"),
            "provider": args.provider or config.get("provider", "local"),
        }

        # Auto-preview unless --no-preview
        if not args.no_preview:
            preview_ok = gen.preview(image_path)
            result["preview_shown"] = preview_ok

        # Auto-save if --output is specified
        if args.output:
            saved_path = gen.save(image_path, Path(args.output))
            result["saved_to"] = str(saved_path)

        print(json.dumps(result, indent=2))

    except (RuntimeError, ValueError) as e:
        print(json.dumps({
            "success": False,
            "error": str(e),
        }))


def cmd_preview(args: argparse.Namespace) -> None:
    """Handle the 'preview' subcommand."""
    image_path = Path(args.path)
    if not image_path.exists():
        print(json.dumps({
            "success": False,
            "error": f"Image file not found: {args.path}",
        }))
        return

    ok = open_image_preview(image_path)
    print(json.dumps({
        "success": ok,
        "path": str(image_path),
    }))


def cmd_providers(args: argparse.Namespace) -> None:
    """Handle the 'providers' subcommand."""
    gen = ImageGenerator(load_config())
    providers = gen.list_providers()
    print(json.dumps({"providers": providers}, indent=2))


def cmd_config(args: argparse.Namespace) -> None:
    """Handle the 'config' subcommand."""
    config = load_config()
    print(json.dumps({"image_generation": config}, indent=2))


def main() -> None:
    """CLI entry point for image generator."""
    parser = argparse.ArgumentParser(
        description="CTDF Image Generator — on-demand image generation "
                    "with interactive preview."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # generate
    gen_parser = subparsers.add_parser(
        "generate", help="Generate an image from a text prompt"
    )
    gen_parser.add_argument("prompt", help="Text prompt for image generation")
    gen_parser.add_argument(
        "--size", default=None,
        help="Image size as WIDTHxHEIGHT (default: from config)"
    )
    gen_parser.add_argument(
        "--style", default=None,
        help="Style hint: natural, vivid, anime (default: from config)"
    )
    gen_parser.add_argument(
        "--provider", default=None,
        help="Override provider: local, dalle, replicate, stability"
    )
    gen_parser.add_argument(
        "--output", "-o", default=None,
        help="Save image to this path"
    )
    gen_parser.add_argument(
        "--no-preview", action="store_true",
        help="Skip opening the image preview"
    )
    gen_parser.set_defaults(func=cmd_generate)

    # preview
    prev_parser = subparsers.add_parser(
        "preview", help="Preview an existing image file"
    )
    prev_parser.add_argument("path", help="Path to image file")
    prev_parser.set_defaults(func=cmd_preview)

    # providers
    prov_parser = subparsers.add_parser(
        "providers", help="List available image generation providers"
    )
    prov_parser.set_defaults(func=cmd_providers)

    # config
    cfg_parser = subparsers.add_parser(
        "config", help="Show current image generation configuration"
    )
    cfg_parser.set_defaults(func=cmd_config)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
