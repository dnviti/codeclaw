#!/usr/bin/env python3
"""Codebase analyzer for the agentic fleet pipeline.

Generates structured Markdown reports on infrastructure, features, and
code quality — replacing expensive LLM-based reader agents with
deterministic static analysis.

Zero external dependencies — stdlib only.

Usage:
    # All three reports
    python3 codebase_analyzer.py analyze --output-dir .

    # Single focus area
    python3 codebase_analyzer.py analyze --focus infrastructure --output report.md

    # With memory file and custom root
    python3 codebase_analyzer.py analyze --root /path/to/project --output-dir . --memory project-memory.md
"""

import argparse
import sys
import time
from pathlib import Path

# Add parent directory to path so analyzers package can be found
# when running from any location
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from analyzers import load_gitignore_patterns
from analyzers.infrastructure import generate_report as gen_infrastructure
from analyzers.features import generate_report as gen_features
from analyzers.quality import generate_report as gen_quality

FOCUS_AREAS = {
    "infrastructure": ("report-infrastructure.md", gen_infrastructure),
    "features": ("report-features.md", gen_features),
    "quality": ("report-quality.md", gen_quality),
}


def analyze(root: Path, focus: list[str], output_dir: Path | None, output: Path | None):
    """Run analysis for the specified focus areas."""
    root = root.resolve()
    if not root.is_dir():
        print(f"Error: {root} is not a directory", file=sys.stderr)
        sys.exit(1)

    gitignore_patterns = load_gitignore_patterns(root)

    for area in focus:
        if area not in FOCUS_AREAS:
            print(f"Error: unknown focus area '{area}'. Valid: {', '.join(FOCUS_AREAS)}", file=sys.stderr)
            sys.exit(1)

        default_filename, generator = FOCUS_AREAS[area]
        start = time.time()

        print(f"Analyzing: {area}...", file=sys.stderr, end=" ", flush=True)
        report = generator(root, gitignore_patterns)
        elapsed = time.time() - start
        print(f"done ({elapsed:.1f}s)", file=sys.stderr)

        # Determine output path
        if output and len(focus) == 1:
            out_path = output
        elif output_dir:
            out_path = output_dir / default_filename
        else:
            # stdout
            print(report)
            continue

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        size = len(report.encode("utf-8"))
        print(f"  Written to {out_path} ({size:,} bytes)", file=sys.stderr)

        # Optionally index report into vector memory store
        _try_vector_index(root, report, default_filename)


def main():
    parser = argparse.ArgumentParser(
        description="Generate codebase analysis reports for agent context (replaces Sonnet reader agents)."
    )
    sub = parser.add_subparsers(dest="command")

    analyze_cmd = sub.add_parser(
        "analyze",
        help="Analyze the codebase and generate reports",
    )
    analyze_cmd.add_argument(
        "--root",
        default=".",
        help="Project root directory (default: current directory)",
    )
    analyze_cmd.add_argument(
        "--focus",
        default="infrastructure,features,quality",
        help="Comma-separated focus areas (default: all three)",
    )
    analyze_cmd.add_argument(
        "--output-dir",
        default=None,
        help="Directory to write report files (uses default filenames)",
    )
    analyze_cmd.add_argument(
        "--output", "-o",
        default=None,
        help="Output file path (only valid with a single focus area)",
    )
    analyze_cmd.add_argument(
        "--memory",
        default=None,
        help="Path to project-memory.md (currently unused, reserved for future)",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "analyze":
        focus = [f.strip() for f in args.focus.split(",")]
        output_dir = Path(args.output_dir) if args.output_dir else None
        output = Path(args.output) if args.output else None

        if output and len(focus) > 1:
            print("Error: --output can only be used with a single --focus area", file=sys.stderr)
            sys.exit(1)

        analyze(Path(args.root), focus, output_dir, output)


def _try_vector_index(root: Path, content: str, doc_name: str):
    """Attempt to index an analyzer report into vector store (opt-in, non-fatal)."""
    try:
        from vector_memory import get_effective_config, _check_deps, _open_db, _get_or_create_table
        from chunkers import chunk_text_document
        from embeddings import create_provider, EmbeddingCache

        config = get_effective_config(root)
        if not config.get("enabled"):
            return

        ok, _ = _check_deps()
        if not ok:
            return

        index_dir = root / config["index_path"]
        if not (index_dir / "lancedb").exists():
            return

        chunks = chunk_text_document(doc_name, content, doc_type="report",
                                     max_chunk_size=config.get("chunk_size", 2000))
        if not chunks:
            return

        emb_config = {
            "provider": config["embedding_provider"],
            "model": config["embedding_model"],
            "api_key_env": config["embedding_api_key_env"],
        }
        provider = create_provider(emb_config)
        cache = EmbeddingCache(index_dir / "embedding_cache")
        db = _open_db(index_dir)
        table = _get_or_create_table(db, provider.dimension())

        try:
            table.delete(f"file_path = '{doc_name}'")
        except Exception:
            pass

        texts = [c.content for c in chunks]
        embeddings = cache.embed_with_cache(provider, texts)
        records = []
        for chunk, emb in zip(chunks, embeddings):
            records.append({
                "vector": emb,
                "content": chunk.content,
                "file_path": chunk.file_path,
                "chunk_type": chunk.chunk_type,
                "name": chunk.name,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "language": chunk.language,
                "file_role": chunk.file_role,
                "content_hash": chunk.content_hash,
            })
        table.add(records)
        print(f"  Indexed {len(chunks)} report chunks into vector memory.", file=sys.stderr)
    except Exception:
        pass  # Vector indexing is opt-in; failures are non-fatal


if __name__ == "__main__":
    main()
