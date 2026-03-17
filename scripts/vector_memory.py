#!/usr/bin/env python3
"""Vector memory layer for CTDF — semantic search over repository content.

Provides an embedded vector database (LanceDB) that indexes source code,
tasks, git history, and agent-generated documents for semantic retrieval.

Subcommands:
    index      Full or incremental re-index of the repository
    search     Semantic query returning ranked results
    status     Index health, chunk counts, staleness report
    clear      Reset the vector index
    configure  Show/update vector memory configuration

This module is opt-in: all functionality gracefully degrades when optional
dependencies (LanceDB, ONNX Runtime) are not installed.

Zero required dependencies — stdlib only. Optional: lancedb, onnxruntime,
tokenizers, numpy, pyarrow.
"""

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

# Add scripts/ to path for sibling package imports
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from analyzers import (
    ALWAYS_SKIP, EXTENSION_MAP, load_gitignore_patterns, is_ignored,
    walk_source_files, read_file_safe, classify_file_role,
)


# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_INDEX_DIR = ".claude/memory/vectors"
DEFAULT_CHUNK_SIZE = 2000
DEFAULT_BATCH_SIZE = 64
HASH_MANIFEST = "file_hashes.json"
INDEX_META = "index_meta.json"
TABLE_NAME = "chunks"


# ── Configuration ────────────────────────────────────────────────────────────

def _find_project_root() -> Path:
    """Find project root by looking for .claude/ or .git/."""
    d = Path.cwd()
    while d != d.parent:
        if (d / ".claude").is_dir() or (d / ".git").exists():
            return d
        d = d.parent
    return Path.cwd()


def load_config(root: Path) -> dict:
    """Load vector_memory config from project-config.json."""
    config_paths = [
        root / ".claude" / "project-config.json",
        root / "config" / "project-config.json",
    ]
    for cp in config_paths:
        if cp.exists():
            try:
                data = json.loads(cp.read_text(encoding="utf-8"))
                return data.get("vector_memory", {})
            except (json.JSONDecodeError, OSError):
                pass
    return {}


def get_effective_config(root: Path) -> dict:
    """Return effective config with defaults applied."""
    user_cfg = load_config(root)
    return {
        "enabled": user_cfg.get("enabled", False),
        "auto_index": user_cfg.get("auto_index", False),
        "embedding_provider": user_cfg.get("embedding_provider", "local"),
        "embedding_model": user_cfg.get("embedding_model", "all-MiniLM-L6-v2"),
        "embedding_api_key_env": user_cfg.get("embedding_api_key_env", ""),
        "chunk_size": user_cfg.get("chunk_size", DEFAULT_CHUNK_SIZE),
        "index_path": user_cfg.get("index_path", DEFAULT_INDEX_DIR),
        "batch_size": user_cfg.get("batch_size", DEFAULT_BATCH_SIZE),
        "include_patterns": user_cfg.get("include_patterns", []),
        "exclude_patterns": user_cfg.get("exclude_patterns", []),
    }


# ── Merkle Hash Tree ────────────────────────────────────────────────────────

def compute_file_hash(filepath: Path) -> str:
    """Compute SHA-256 hash of file content."""
    try:
        return hashlib.sha256(
            filepath.read_bytes()
        ).hexdigest()
    except OSError:
        return ""


def build_hash_manifest(root: Path, gitignore_patterns: list[str],
                        config: dict) -> dict[str, str]:
    """Build a hash manifest of all indexable files.

    Returns {relative_path: content_sha256}.
    """
    manifest: dict[str, str] = {}
    exclude = set(config.get("exclude_patterns", []))

    for rel, fpath, ext, size in walk_source_files(root, gitignore_patterns):
        # Skip non-text files
        if ext in {".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
                   ".woff", ".woff2", ".ttf", ".eot", ".mp3", ".mp4",
                   ".zip", ".gz", ".tar", ".bin", ".exe", ".dll",
                   ".so", ".dylib", ".pyc", ".pyo", ".class", ".o",
                   ".pdf", ".doc", ".docx", ".xls", ".xlsx"}:
            continue
        # Apply user exclude patterns
        skip = False
        for pat in exclude:
            if rel.startswith(pat) or rel.endswith(pat):
                skip = True
                break
        if skip:
            continue
        h = compute_file_hash(fpath)
        if h:
            manifest[rel] = h

    return manifest


def load_stored_manifest(index_dir: Path) -> dict[str, str]:
    """Load the previously stored hash manifest."""
    path = index_dir / HASH_MANIFEST
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_manifest(index_dir: Path, manifest: dict[str, str]):
    """Save the hash manifest to disk."""
    path = index_dir / HASH_MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def diff_manifests(old: dict[str, str],
                   new: dict[str, str]) -> tuple[list[str], list[str], list[str]]:
    """Compare two manifests.

    Returns (added, modified, removed) lists of relative paths.
    """
    old_keys = set(old.keys())
    new_keys = set(new.keys())

    added = sorted(new_keys - old_keys)
    removed = sorted(old_keys - new_keys)
    modified = sorted(
        k for k in old_keys & new_keys if old[k] != new[k]
    )

    return added, modified, removed


# ── Vector Store Operations ──────────────────────────────────────────────────

def _check_deps() -> tuple[bool, str]:
    """Check if vector memory dependencies are available."""
    from deps_check import check_vector_memory_deps, install_instructions
    ok, missing = check_vector_memory_deps()
    if not ok:
        return False, install_instructions(missing)
    return True, ""


def _open_db(index_dir: Path):
    """Open or create a LanceDB database."""
    import lancedb
    db_path = str(index_dir / "lancedb")
    return lancedb.connect(db_path)


def _get_or_create_table(db, dimension: int):
    """Get existing table or create a new one."""
    import pyarrow as pa

    schema = pa.schema([
        pa.field("vector", pa.list_(pa.float32(), dimension)),
        pa.field("content", pa.string()),
        pa.field("file_path", pa.string()),
        pa.field("chunk_type", pa.string()),
        pa.field("name", pa.string()),
        pa.field("start_line", pa.int32()),
        pa.field("end_line", pa.int32()),
        pa.field("language", pa.string()),
        pa.field("file_role", pa.string()),
        pa.field("content_hash", pa.string()),
    ])

    existing = db.table_names()
    if TABLE_NAME in existing:
        return db.open_table(TABLE_NAME)
    else:
        return db.create_table(TABLE_NAME, schema=schema)


# ── Index Command ────────────────────────────────────────────────────────────

def cmd_index(args):
    """Full or incremental index of the repository."""
    root = Path(args.root).resolve()
    config = get_effective_config(root)
    index_dir = root / config["index_path"]
    index_dir.mkdir(parents=True, exist_ok=True)

    ok, msg = _check_deps()
    if not ok:
        print(f"Error: {msg}", file=sys.stderr)
        sys.exit(1)

    # Import optional modules now that deps are confirmed
    from chunkers import chunk_file, chunk_text_document
    from embeddings import create_provider, EmbeddingCache

    print("Vector Memory — Indexing", file=sys.stderr)
    print(f"  Root: {root}", file=sys.stderr)
    print(f"  Index: {index_dir}", file=sys.stderr)

    # Build hash manifest
    gitignore_patterns = load_gitignore_patterns(root)
    new_manifest = build_hash_manifest(root, gitignore_patterns, config)

    # Determine what needs indexing
    if args.full:
        files_to_index = list(new_manifest.keys())
        files_to_remove: list[str] = []
        print(f"  Mode: full rebuild ({len(files_to_index)} files)",
              file=sys.stderr)
    else:
        old_manifest = load_stored_manifest(index_dir)
        added, modified, removed = diff_manifests(old_manifest, new_manifest)
        files_to_index = added + modified
        files_to_remove = removed
        print(f"  Mode: incremental", file=sys.stderr)
        print(f"    Added: {len(added)}, Modified: {len(modified)}, "
              f"Removed: {len(removed)}", file=sys.stderr)

    if not files_to_index and not files_to_remove:
        print("  Nothing to index — everything is up to date.", file=sys.stderr)
        save_manifest(index_dir, new_manifest)
        _save_meta(index_dir, config, len(new_manifest))
        return

    # Initialize embedding provider
    emb_config = {
        "provider": config["embedding_provider"],
        "model": config["embedding_model"],
        "api_key_env": config["embedding_api_key_env"],
    }
    provider = create_provider(emb_config)
    cache = EmbeddingCache(index_dir / "embedding_cache")

    print(f"  Embedding: {provider.model_name()} "
          f"(dim={provider.dimension()})", file=sys.stderr)

    # Open vector DB
    db = _open_db(index_dir)
    table = _get_or_create_table(db, provider.dimension())

    # Remove stale entries
    if files_to_remove:
        for fp in files_to_remove:
            try:
                table.delete(f"file_path = '{fp}'")
            except Exception:
                pass  # Table may not have entries for this file

    # Remove entries for modified files (will be re-added)
    if not args.full:
        for fp in files_to_index:
            try:
                table.delete(f"file_path = '{fp}'")
            except Exception:
                pass
    else:
        # Full rebuild: drop and recreate
        try:
            db.drop_table(TABLE_NAME)
        except Exception:
            pass
        table = _get_or_create_table(db, provider.dimension())

    # Chunk and embed files
    total_chunks = 0
    batch_size = config.get("batch_size", DEFAULT_BATCH_SIZE)
    start_time = time.time()

    pending_records: list[dict] = []
    pending_texts: list[str] = []

    for i, rel_path in enumerate(files_to_index):
        fpath = root / rel_path
        content = read_file_safe(fpath)
        if not content:
            continue

        # Chunk the file
        ext = fpath.suffix.lower()
        if ext in {".md", ".txt", ".rst"}:
            chunks = chunk_text_document(rel_path, content,
                                         max_chunk_size=config["chunk_size"])
        else:
            chunks = chunk_file(rel_path, content,
                                max_chunk_size=config["chunk_size"])

        for chunk in chunks:
            record = {
                "content": chunk.content,
                "file_path": chunk.file_path,
                "chunk_type": chunk.chunk_type,
                "name": chunk.name,
                "start_line": chunk.start_line,
                "end_line": chunk.end_line,
                "language": chunk.language,
                "file_role": chunk.file_role,
                "content_hash": chunk.content_hash,
            }
            pending_records.append(record)
            pending_texts.append(chunk.content)
            total_chunks += 1

        # Flush batch
        if len(pending_texts) >= batch_size:
            _flush_batch(table, provider, cache, pending_records,
                         pending_texts)
            pending_records = []
            pending_texts = []

        # Progress
        if (i + 1) % 50 == 0:
            print(f"    Indexed {i + 1}/{len(files_to_index)} files...",
                  file=sys.stderr, flush=True)

    # Final flush
    if pending_texts:
        _flush_batch(table, provider, cache, pending_records, pending_texts)

    elapsed = time.time() - start_time
    save_manifest(index_dir, new_manifest)
    _save_meta(index_dir, config, len(new_manifest))

    print(f"  Done: {total_chunks} chunks from {len(files_to_index)} files "
          f"in {elapsed:.1f}s", file=sys.stderr)


def _flush_batch(table, provider, cache, records: list[dict],
                 texts: list[str]):
    """Embed a batch of texts and insert into the vector table."""
    embeddings = cache.embed_with_cache(provider, texts)
    for rec, emb in zip(records, embeddings):
        rec["vector"] = emb
    try:
        table.add(records)
    except Exception as e:
        print(f"    Warning: batch insert failed: {e}", file=sys.stderr)


def _save_meta(index_dir: Path, config: dict, file_count: int):
    """Save index metadata."""
    import time as _time
    meta = {
        "last_indexed": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
        "file_count": file_count,
        "embedding_provider": config.get("embedding_provider", "local"),
        "embedding_model": config.get("embedding_model", "all-MiniLM-L6-v2"),
        "chunk_size": config.get("chunk_size", DEFAULT_CHUNK_SIZE),
    }
    path = index_dir / INDEX_META
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


# ── Search Command ───────────────────────────────────────────────────────────

def cmd_search(args):
    """Semantic search over the vector index."""
    root = Path(args.root).resolve()
    config = get_effective_config(root)
    index_dir = root / config["index_path"]

    ok, msg = _check_deps()
    if not ok:
        print(f"Error: {msg}", file=sys.stderr)
        sys.exit(1)

    if not (index_dir / "lancedb").exists():
        print("Error: No vector index found. Run 'vector_memory.py index' first.",
              file=sys.stderr)
        sys.exit(1)

    from embeddings import create_provider

    query = args.query
    top_k = args.top_k
    file_filter = args.file_filter
    type_filter = args.type_filter

    # Initialize provider and embed query
    emb_config = {
        "provider": config["embedding_provider"],
        "model": config["embedding_model"],
        "api_key_env": config["embedding_api_key_env"],
    }
    provider = create_provider(emb_config)
    query_embedding = provider.embed([query])[0]

    # Search
    db = _open_db(index_dir)
    try:
        table = db.open_table(TABLE_NAME)
    except Exception:
        print("Error: Vector table not found. Run 'vector_memory.py index' first.",
              file=sys.stderr)
        sys.exit(1)

    results = table.search(query_embedding).limit(top_k * 3)

    # Apply filters
    if file_filter:
        results = results.where(f"file_path LIKE '%{file_filter}%'")
    if type_filter:
        results = results.where(f"chunk_type = '{type_filter}'")

    df = results.limit(top_k).to_pandas()

    # Format output
    if args.json_output:
        records = []
        for _, row in df.iterrows():
            records.append({
                "file_path": row.get("file_path", ""),
                "name": row.get("name", ""),
                "chunk_type": row.get("chunk_type", ""),
                "language": row.get("language", ""),
                "start_line": int(row.get("start_line", 0)),
                "end_line": int(row.get("end_line", 0)),
                "score": float(row.get("_distance", 0.0)),
                "content": row.get("content", "")[:500] if not args.full_content else row.get("content", ""),
            })
        print(json.dumps(records, indent=2))
    else:
        if df.empty:
            print("No results found.")
            return

        print(f"\nSearch results for: {query!r}")
        print(f"{'=' * 60}")
        for i, (_, row) in enumerate(df.iterrows(), 1):
            score = row.get("_distance", 0.0)
            print(f"\n[{i}] {row.get('file_path', '?')}:"
                  f"{row.get('start_line', '?')}-{row.get('end_line', '?')}"
                  f"  ({row.get('chunk_type', '?')}: {row.get('name', '?')})"
                  f"  score={score:.4f}")
            content = row.get("content", "")
            if not args.full_content:
                content = content[:300]
                if len(row.get("content", "")) > 300:
                    content += "..."
            print(f"    {content[:200].replace(chr(10), chr(10) + '    ')}")
        print()


# ── Status Command ───────────────────────────────────────────────────────────

def cmd_status(args):
    """Show index health, chunk counts, and staleness."""
    root = Path(args.root).resolve()
    config = get_effective_config(root)
    index_dir = root / config["index_path"]

    # Check dependencies
    from deps_check import check_vector_memory_deps
    deps_ok, missing = check_vector_memory_deps()

    status = {
        "enabled": config.get("enabled", False),
        "dependencies_installed": deps_ok,
        "missing_dependencies": missing,
        "index_path": str(index_dir),
    }

    meta_path = index_dir / INDEX_META
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            status["last_indexed"] = meta.get("last_indexed", "unknown")
            status["indexed_files"] = meta.get("file_count", 0)
            status["embedding_provider"] = meta.get("embedding_provider", "")
            status["embedding_model"] = meta.get("embedding_model", "")
            status["chunk_size"] = meta.get("chunk_size", 0)
        except (json.JSONDecodeError, OSError):
            status["last_indexed"] = "unknown"
            status["indexed_files"] = 0
    else:
        status["last_indexed"] = None
        status["indexed_files"] = 0
        status["index_exists"] = False

    # Check staleness
    stored = load_stored_manifest(index_dir)
    if stored:
        gitignore_patterns = load_gitignore_patterns(root)
        current = build_hash_manifest(root, gitignore_patterns, config)
        added, modified, removed = diff_manifests(stored, current)
        status["stale_files"] = len(added) + len(modified) + len(removed)
        status["files_added"] = len(added)
        status["files_modified"] = len(modified)
        status["files_removed"] = len(removed)
    else:
        status["stale_files"] = -1  # Unknown — no manifest

    # Chunk count from DB
    if deps_ok and (index_dir / "lancedb").exists():
        try:
            db = _open_db(index_dir)
            if TABLE_NAME in db.table_names():
                table = db.open_table(TABLE_NAME)
                status["total_chunks"] = table.count_rows()
            else:
                status["total_chunks"] = 0
        except Exception:
            status["total_chunks"] = -1
    else:
        status["total_chunks"] = 0

    if args.json_output:
        print(json.dumps(status, indent=2))
    else:
        print("Vector Memory Status")
        print("=" * 40)
        print(f"  Enabled:      {status['enabled']}")
        print(f"  Dependencies: {'OK' if deps_ok else 'MISSING'}")
        if missing:
            print(f"                Missing: {', '.join(missing)}")
        print(f"  Index path:   {status['index_path']}")
        li = status.get("last_indexed")
        print(f"  Last indexed: {li if li else 'never'}")
        print(f"  Indexed files: {status.get('indexed_files', 0)}")
        tc = status.get("total_chunks", 0)
        print(f"  Total chunks: {tc if tc >= 0 else 'unknown'}")
        sf = status.get("stale_files", -1)
        if sf == 0:
            print(f"  Staleness:    up to date")
        elif sf > 0:
            print(f"  Staleness:    {sf} file(s) changed since last index")
            print(f"    Added: {status.get('files_added', 0)}, "
                  f"Modified: {status.get('files_modified', 0)}, "
                  f"Removed: {status.get('files_removed', 0)}")
        else:
            print(f"  Staleness:    unknown (no manifest)")


# ── Clear Command ────────────────────────────────────────────────────────────

def cmd_clear(args):
    """Reset the vector index."""
    import shutil

    root = Path(args.root).resolve()
    config = get_effective_config(root)
    index_dir = root / config["index_path"]

    if not index_dir.exists():
        print("No vector index found — nothing to clear.", file=sys.stderr)
        return

    if not args.force:
        print(f"This will delete: {index_dir}", file=sys.stderr)
        print("Use --force to confirm.", file=sys.stderr)
        sys.exit(1)

    shutil.rmtree(index_dir)
    print(f"Vector index cleared: {index_dir}", file=sys.stderr)


# ── Configure Command ────────────────────────────────────────────────────────

def cmd_configure(args):
    """Show or update vector memory configuration."""
    root = Path(args.root).resolve()
    config = get_effective_config(root)

    if args.json_output:
        print(json.dumps(config, indent=2))
    else:
        print("Vector Memory Configuration")
        print("=" * 40)
        for k, v in config.items():
            print(f"  {k}: {v}")
        print()
        print("To modify, edit 'vector_memory' section in:")
        print(f"  {root}/.claude/project-config.json")


# ── Hook: Incremental Update ────────────────────────────────────────────────

def hook_file_changed(file_path: str):
    """Called by PostToolUse hook when a file is edited/written.

    Performs incremental re-indexing of the single changed file.
    Designed to be fast and non-blocking.
    """
    root = _find_project_root()
    config = get_effective_config(root)

    if not config.get("enabled") or not config.get("auto_index"):
        return

    # Check deps silently
    ok, _ = _check_deps()
    if not ok:
        return

    index_dir = root / config["index_path"]
    if not (index_dir / "lancedb").exists():
        return  # No index yet — skip

    try:
        abs_path = Path(file_path).resolve()
        if not abs_path.exists():
            return

        rel_path = str(abs_path.relative_to(root))
    except ValueError:
        return  # File is outside project root

    from chunkers import chunk_file, chunk_text_document
    from embeddings import create_provider, EmbeddingCache

    content = read_file_safe(abs_path)
    if not content:
        return

    emb_config = {
        "provider": config["embedding_provider"],
        "model": config["embedding_model"],
        "api_key_env": config["embedding_api_key_env"],
    }

    try:
        provider = create_provider(emb_config)
        cache = EmbeddingCache(index_dir / "embedding_cache")
        db = _open_db(index_dir)
        table = _get_or_create_table(db, provider.dimension())

        # Remove old entries for this file
        try:
            table.delete(f"file_path = '{rel_path}'")
        except Exception:
            pass

        # Chunk and embed
        ext = abs_path.suffix.lower()
        if ext in {".md", ".txt", ".rst"}:
            chunks = chunk_text_document(rel_path, content,
                                         max_chunk_size=config["chunk_size"])
        else:
            chunks = chunk_file(rel_path, content,
                                max_chunk_size=config["chunk_size"])

        if chunks:
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

        # Update manifest for this file
        manifest = load_stored_manifest(index_dir)
        manifest[rel_path] = compute_file_hash(abs_path)
        save_manifest(index_dir, manifest)

    except Exception:
        pass  # Hook failures must be silent and non-blocking


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="CTDF Vector Memory — semantic search over repository content",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s index                    # Incremental index
  %(prog)s index --full             # Full rebuild
  %(prog)s search "authentication"  # Semantic search
  %(prog)s status                   # Index health check
  %(prog)s clear --force            # Reset index
""",
    )

    sub = parser.add_subparsers(dest="command")

    # ── index ──
    idx = sub.add_parser("index", help="Index repository for semantic search")
    idx.add_argument("--root", default=".", help="Project root directory")
    idx.add_argument("--full", action="store_true",
                     help="Full rebuild (ignore incremental hashes)")

    # ── search ──
    srch = sub.add_parser("search", help="Semantic search over indexed content")
    srch.add_argument("query", help="Search query text")
    srch.add_argument("--root", default=".", help="Project root directory")
    srch.add_argument("--top-k", "-k", type=int, default=10,
                      help="Number of results (default: 10)")
    srch.add_argument("--file-filter", "-f", default="",
                      help="Filter results by file path substring")
    srch.add_argument("--type-filter", "-t", default="",
                      help="Filter by chunk type (function, class, etc.)")
    srch.add_argument("--json", dest="json_output", action="store_true",
                      help="Output results as JSON")
    srch.add_argument("--full-content", action="store_true",
                      help="Show full chunk content instead of truncated")

    # ── status ──
    stat = sub.add_parser("status", help="Show index health and statistics")
    stat.add_argument("--root", default=".", help="Project root directory")
    stat.add_argument("--json", dest="json_output", action="store_true",
                      help="Output as JSON")

    # ── clear ──
    clr = sub.add_parser("clear", help="Reset the vector index")
    clr.add_argument("--root", default=".", help="Project root directory")
    clr.add_argument("--force", action="store_true",
                     help="Confirm deletion")

    # ── configure ──
    cfg = sub.add_parser("configure", help="Show vector memory configuration")
    cfg.add_argument("--root", default=".", help="Project root directory")
    cfg.add_argument("--json", dest="json_output", action="store_true",
                     help="Output as JSON")

    # ── hook (internal) ──
    hk = sub.add_parser("hook", help="Internal: incremental update hook")
    hk.add_argument("file_path", help="Path to the changed file")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "index":
        cmd_index(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "clear":
        cmd_clear(args)
    elif args.command == "configure":
        cmd_configure(args)
    elif args.command == "hook":
        hook_file_changed(args.file_path)


if __name__ == "__main__":
    main()
