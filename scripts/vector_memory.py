#!/usr/bin/env python3
"""Vector memory layer for CodeClaw — semantic search over repository content.

Provides an embedded vector database (LanceDB) that indexes source code,
tasks, git history, and agent-generated documents for semantic retrieval.

Subcommands:
    index      Full or incremental re-index of the repository
    search     Semantic query returning ranked results
    status     Index health, chunk counts, staleness report
    clear      Reset the vector index
    configure  Show/update vector memory configuration
    gc         Garbage collection: prune old entries, compact tables
    agents     List active/historical agent sessions
    conflicts  Show flagged contradictions between agents

Vector memory is always-on by default. The index is built automatically
during /setup and updated on every file write via the PostToolUse hook.
Missing configuration is treated as enabled (always-on default).

Required dependencies: lancedb, sentence-transformers
Install with: pip install "lancedb>=0.5.0,<1.0" "sentence-transformers>=2.7.0,<3.0"

Zero stdlib dependencies — stdlib only for core logic. Required for indexing:
lancedb, sentence-transformers (or onnxruntime+tokenizers), numpy, pyarrow.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from contextlib import nullcontext
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


# ── Sanitization ─────────────────────────────────────────────────────────────
# Note: helper functions below are module-level rather than class methods.
# No @staticmethod is needed because there is no enclosing class.

_SAFE_FILTER_RE = re.compile(r"^[a-zA-Z0-9_./ -]+$")


def _sanitize_filter_value(value: str) -> str:
    """Sanitize a string value for use in LanceDB filter expressions.

    Uses an allowlist regex to reject unexpected characters, then escapes
    single quotes and strips SQL-injection markers as a defense-in-depth
    measure.  Raises ValueError if the value contains disallowed characters.
    """
    if not _SAFE_FILTER_RE.match(value):
        raise ValueError(
            f"Filter value contains disallowed characters: {value!r}. "
            f"Only alphanumerics, dots, slashes, hyphens, underscores, "
            f"and spaces are permitted."
        )
    # Defense-in-depth: escape quotes and strip SQL markers even after allowlist
    sanitized = value.replace("'", "''")
    sanitized = re.sub(r"[;]", "", sanitized)
    sanitized = re.sub(r"--", "", sanitized)
    return sanitized


def apply_search_filters(search_query, top_k: int,
                         file_filter: str = "",
                         type_filter: str = ""):
    """Apply glob/type filters to a LanceDB search query and return a DataFrame.

    Shared helper so filtering logic lives in one place.  Used by cmd_search
    and importable by mcp_tools/search.py for in-process searches.

    Args:
        search_query: A LanceDB search builder (table.search(...)).
        top_k: Number of results requested.
        file_filter: Optional substring filter on file paths.
        type_filter: Optional chunk type filter.

    Returns:
        A pandas DataFrame with the filtered results.
    """
    # Over-fetch 3x to compensate for post-query glob filtering; tuned empirically
    results = search_query.limit(top_k * 3)

    if file_filter:
        safe_filter = _sanitize_filter_value(file_filter)
        results = results.where(f"file_path LIKE '%{safe_filter}%'")
    if type_filter:
        safe_type = _sanitize_filter_value(type_filter)
        results = results.where(f"chunk_type = '{safe_type}'")

    return results.limit(top_k).to_pandas()


# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_INDEX_DIR = ".claude/memory/vectors"
DEFAULT_CHUNK_SIZE = 2000
DEFAULT_BATCH_SIZE = 64
HASH_MANIFEST = "file_hashes.json"
INDEX_META = "index_meta.json"
TABLE_NAME = "chunks"

# Module-level embedding provider cache (lazy singleton).
# Avoids re-creating the provider on every search/hook call, which is
# expensive for local ONNX models that load weights into memory.
_cached_provider = None
_cached_provider_key = None


def _get_cached_provider(emb_config: dict):
    """Return a cached embedding provider instance.

    Re-creates only when the provider/model config changes.
    """
    global _cached_provider, _cached_provider_key
    key = (emb_config.get("provider"), emb_config.get("model"),
           emb_config.get("api_key_env"))
    if _cached_provider is not None and _cached_provider_key == key:
        return _cached_provider
    from embeddings import create_provider
    _cached_provider = create_provider(emb_config)
    _cached_provider_key = key
    return _cached_provider


# ── Configuration ────────────────────────────────────────────────────────────

def _find_project_root() -> Path:
    """Find project root, resolving through git worktrees to the main repo.

    Uses a single ``git rev-parse --git-common-dir --git-dir`` call to detect
    if the current working directory is inside a worktree.  When it is, the
    main repository root is returned so that vector memory storage is shared
    across all worktrees instead of being isolated per-worktree.

    Falls back to the legacy directory-walk approach when git is unavailable.
    """
    import subprocess as _sp
    try:
        result = _sp.run(
            ["git", "rev-parse", "--git-common-dir", "--git-dir"],
            capture_output=True, text=True, check=True,
        )
        lines = result.stdout.strip().splitlines()
        if len(lines) >= 2:
            common_path = Path(lines[0]).resolve()
            git_dir_path = Path(lines[1]).resolve()
            if common_path != git_dir_path:
                # Inside a worktree — common dir is <main-repo>/.git
                return common_path.parent
            # Not a worktree — git dir is <repo>/.git, return its parent
            return git_dir_path.parent
    except (FileNotFoundError, _sp.CalledProcessError):
        pass

    # Fallback: walk up directories looking for .claude/ or .git/
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


def load_consistency_config(root: Path) -> dict:
    """Load memory_consistency config section from project-config.json."""
    config_paths = [
        root / ".claude" / "project-config.json",
        root / "config" / "project-config.json",
    ]
    for cp in config_paths:
        if cp.exists():
            try:
                data = json.loads(cp.read_text(encoding="utf-8"))
                return data.get("memory_consistency", {})
            except (json.JSONDecodeError, OSError):
                pass
    return {}


def get_effective_config(root: Path) -> dict:
    """Return effective config with defaults applied.

    Missing configuration is treated as always-on (enabled=True, auto_index=True)
    to match the always-on default behavior introduced in VMEM-0024.
    """
    user_cfg = load_config(root)
    return {
        "enabled": user_cfg.get("enabled", True),
        "auto_index": user_cfg.get("auto_index", True),
        "embedding_provider": user_cfg.get("embedding_provider", "local"),
        "embedding_model": user_cfg.get("embedding_model", "all-MiniLM-L6-v2"),
        "embedding_api_key_env": user_cfg.get("embedding_api_key_env", ""),
        "chunk_size": user_cfg.get("chunk_size", DEFAULT_CHUNK_SIZE),
        "index_path": user_cfg.get("index_path", DEFAULT_INDEX_DIR),
        "batch_size": user_cfg.get("batch_size", DEFAULT_BATCH_SIZE),
        "include_patterns": user_cfg.get("include_patterns", []),
        "exclude_patterns": user_cfg.get("exclude_patterns", []),
    }


def get_effective_consistency_config(root: Path) -> dict:
    """Return effective consistency config with defaults applied."""
    user_cfg = load_consistency_config(root)
    return {
        "gc_ttl_days": user_cfg.get("gc_ttl_days", 30),
        "max_index_size_mb": user_cfg.get("max_index_size_mb", 500),
        "conflict_strategy": user_cfg.get("conflict_strategy", "auto"),
        "enable_versioned_reads": user_cfg.get("enable_versioned_reads", False),
    }


# ── Initialization Guard ──────────────────────────────────────────────────────

def ensure_initialized(root: Path) -> bool:
    """Check if vector index exists; if not, trigger auto-index with a warning.

    Returns True if the index is ready (or was just built), False on failure.
    This is called by commands that require an existing index to operate.

    A lock file (.init_in_progress) prevents concurrent initialization races
    when multiple agents or hook invocations run simultaneously before the
    index exists.
    """
    config = get_effective_config(root)
    index_dir = root / config["index_path"]

    if (index_dir / "lancedb").exists():
        return True

    # Guard against concurrent initialization using an exclusive lock file
    index_dir.mkdir(parents=True, exist_ok=True)
    lock_file = index_dir / ".init_in_progress"
    if lock_file.exists():
        # Another process is already initializing — wait briefly then check
        import time as _time
        for _ in range(10):
            _time.sleep(1)
            if (index_dir / "lancedb").exists():
                return True
        return False

    try:
        lock_file.touch()

        print(
            "WARNING: Vector memory index not found. "
            "Running initial index build now...",
            file=sys.stderr,
        )

        ok, msg = _check_deps()
        if not ok:
            print(f"Cannot auto-initialize: {msg}", file=sys.stderr)
            print(
                'To install required dependencies run:\n'
                '  pip install "lancedb>=0.5.0,<1.0" "sentence-transformers>=2.7.0,<3.0"',
                file=sys.stderr,
            )
            return False

        # Build the index using a minimal args namespace
        try:
            cmd_index(argparse.Namespace(root=str(root), full=True, force_init=True))
            return True
        except Exception as e:
            print(f"Auto-initialization failed: {e}", file=sys.stderr)
            return False
    finally:
        try:
            lock_file.unlink(missing_ok=True)
        except OSError:
            pass


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
    """Check if vector memory dependencies are available.

    Returns (ok, message). If dependencies are missing, message contains
    an actionable install command.
    """
    try:
        from deps_check import check_vector_memory_deps, install_instructions
        ok, missing = check_vector_memory_deps()
        if not ok:
            msg = install_instructions(missing)
            if not msg:
                msg = (
                    "Missing required dependencies for vector memory.\n"
                    'Install with: pip install "lancedb>=0.5.0,<1.0" "sentence-transformers>=2.7.0,<3.0"'
                )
            return False, msg
        return True, ""
    except ImportError:
        # Fallback: try importing the key packages directly
        missing = []
        try:
            import lancedb  # noqa: F401
        except ImportError:
            missing.append("lancedb")
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            missing.append("sentence-transformers")
        if missing:
            pkg_list = " ".join(missing)
            return False, (
                f"Missing required dependencies: {', '.join(missing)}\n"
                f"Install with: pip install {pkg_list}"
            )
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


# ── Directory Size Utility ───────────────────────────────────────────────────

def _dir_size_mb(path: Path) -> float:
    """Compute total size of a directory in MB."""
    total = 0
    if path.exists():
        for f in path.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    return total / (1024 * 1024)


# ── Index Command ────────────────────────────────────────────────────────────

def cmd_index(args):
    """Full or incremental index of the repository.

    When --force-init is passed (used by setup and ensure_initialized),
    the index is always built from scratch regardless of existing state.
    """
    root = Path(args.root).resolve()
    config = get_effective_config(root)
    index_dir = root / config["index_path"]
    index_dir.mkdir(parents=True, exist_ok=True)

    ok, msg = _check_deps()
    if not ok:
        print(f"Error: {msg}", file=sys.stderr)
        print(
            'To install required dependencies run:\n'
            '  pip install "lancedb>=0.5.0,<1.0" "sentence-transformers>=2.7.0,<3.0"',
            file=sys.stderr,
        )
        sys.exit(2)

    # Import optional modules now that deps are confirmed
    from chunkers import chunk_file, chunk_text_document
    from embeddings import create_provider, EmbeddingCache

    # Acquire write lock if memory_lock is available
    lock = None
    try:
        from memory_lock import MemoryLock
        agent_id = os.environ.get("CodeClaw_AGENT_ID", f"agent-{os.getpid()}")
        session_id = os.environ.get("CodeClaw_SESSION_ID", "")
        lock = MemoryLock(index_dir, agent_id=agent_id, session_id=session_id)
    except ImportError:
        pass

    print("Vector Memory — Indexing", file=sys.stderr)
    print(f"  Root: {root}", file=sys.stderr)
    print(f"  Index: {index_dir}", file=sys.stderr)

    # Build hash manifest
    gitignore_patterns = load_gitignore_patterns(root)
    new_manifest = build_hash_manifest(root, gitignore_patterns, config)

    # Determine what needs indexing
    # --force-init (used by setup) is equivalent to --full
    force_full = args.full or getattr(args, "force_init", False)
    if force_full:
        files_to_index = list(new_manifest.keys())
        files_to_remove: list[str] = []
        mode_label = "force-init" if getattr(args, "force_init", False) else "full rebuild"
        print(f"  Mode: {mode_label} ({len(files_to_index)} files)",
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

    # Perform writes under lock if available
    _ctx = lock.write() if lock else nullcontext()
    with _ctx:
        # Open vector DB
        db = _open_db(index_dir)
        table = _get_or_create_table(db, provider.dimension())

        # Remove stale entries
        if files_to_remove:
            for fp in files_to_remove:
                try:
                    table.delete(f"file_path = '{_sanitize_filter_value(fp)}'")
                except Exception:
                    pass

        # Remove entries for modified files (will be re-added)
        if not force_full:
            for fp in files_to_index:
                try:
                    table.delete(f"file_path = '{_sanitize_filter_value(fp)}'")
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


# _nullcontext removed — use contextlib.nullcontext (Python 3.7+)


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
    meta = {
        "last_indexed": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "file_count": file_count,
        "embedding_provider": config.get("embedding_provider", "local"),
        "embedding_model": config.get("embedding_model", "all-MiniLM-L6-v2"),
        "chunk_size": config.get("chunk_size", DEFAULT_CHUNK_SIZE),
    }
    path = index_dir / INDEX_META
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


# ── Search Command ───────────────────────────────────────────────────────────
# Sequential: bounded by fixed pattern list (~5 queries), parallelizing adds
# thread complexity for marginal gain

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

    query = args.query
    top_k = args.top_k
    file_filter = args.file_filter
    type_filter = args.type_filter

    # Initialize provider (cached) and embed query
    emb_config = {
        "provider": config["embedding_provider"],
        "model": config["embedding_model"],
        "api_key_env": config["embedding_api_key_env"],
    }
    provider = _get_cached_provider(emb_config)
    query_embedding = provider.embed([query])[0]

    # Optional: use versioned read
    consistency_cfg = get_effective_consistency_config(root)
    version = None
    if consistency_cfg.get("enable_versioned_reads") and hasattr(args, "version") and args.version:
        version = args.version

    # Acquire read lock if available
    lock = None
    try:
        from memory_lock import MemoryLock
        agent_id = os.environ.get("CodeClaw_AGENT_ID", f"agent-{os.getpid()}")
        lock = MemoryLock(index_dir, agent_id=agent_id)
    except ImportError:
        pass

    _ctx = lock.read() if lock else nullcontext()
    with _ctx:
        db = _open_db(index_dir)

        # Use versioned query if requested
        if version is not None:
            try:
                from memory_protocol import versioned_query
                table = versioned_query(db, TABLE_NAME, version=version)
            except (ImportError, Exception):
                table = db.open_table(TABLE_NAME)
        else:
            try:
                table = db.open_table(TABLE_NAME)
            except Exception:
                print("Error: Vector table not found. Run 'vector_memory.py index' first.",
                      file=sys.stderr)
                sys.exit(1)

        df = apply_search_filters(
            table.search(query_embedding),
            top_k, file_filter, type_filter,
        )

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
    # Per-file hashing: uses in-process hashlib (not subprocess); current
    # scale (~100-1000 files) is acceptable without batching.
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

    # Index size
    status["index_size_mb"] = round(_dir_size_mb(index_dir), 2)

    # Agent session count
    try:
        from memory_protocol import MemoryProtocol
        protocol = MemoryProtocol(root)
        proto_status = protocol.get_status()
        status["active_agents"] = proto_status["active_agents"]
        status["pending_conflicts"] = proto_status["pending_conflicts"]
    except (ImportError, Exception):
        status["active_agents"] = 0
        status["pending_conflicts"] = 0

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
        print(f"  Index size:   {status.get('index_size_mb', 0):.2f} MB")
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
        print(f"  Active agents:     {status.get('active_agents', 0)}")
        print(f"  Pending conflicts: {status.get('pending_conflicts', 0)}")


# ── Clear Command ────────────────────────────────────────────────────────────

def cmd_clear(args):
    """Reset the vector index."""
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
    consistency = get_effective_consistency_config(root)

    if args.json_output:
        print(json.dumps({"vector_memory": config, "memory_consistency": consistency}, indent=2))
    else:
        print("Vector Memory Configuration")
        print("=" * 40)
        for k, v in config.items():
            print(f"  {k}: {v}")
        print()
        print("Memory Consistency Configuration")
        print("=" * 40)
        for k, v in consistency.items():
            print(f"  {k}: {v}")
        print()
        print("To modify, edit 'vector_memory' and 'memory_consistency' sections in:")
        print(f"  {root}/.claude/project-config.json")


# ── GC Command ───────────────────────────────────────────────────────────────

def cmd_gc(args):
    """Garbage collection: prune old entries, compact tables, clean sessions."""
    root = Path(args.root).resolve()
    config = get_effective_config(root)
    consistency = get_effective_consistency_config(root)
    index_dir = root / config["index_path"]

    ttl_days = args.ttl_days if args.ttl_days is not None else consistency.get("gc_ttl_days", 30)
    max_size_mb = consistency.get("max_index_size_mb", 500)

    report = {
        "ttl_days": ttl_days,
        "max_index_size_mb": max_size_mb,
        "index_path": str(index_dir),
    }

    # Index size before
    size_before = _dir_size_mb(index_dir)
    report["size_before_mb"] = round(size_before, 2)

    if not args.json_output:
        print("Vector Memory — Garbage Collection", file=sys.stderr)
        print(f"  Index: {index_dir}", file=sys.stderr)
        print(f"  TTL: {ttl_days} days", file=sys.stderr)
        print(f"  Size before: {size_before:.2f} MB", file=sys.stderr)

    # 1. Prune old entries from the vector table (TTL-based)
    entries_pruned = 0
    ttl_cutoff = time.time() - (ttl_days * 86400)
    deps_ok = False
    try:
        ok, _ = _check_deps()
        deps_ok = ok
    except Exception:
        pass

    if deps_ok and (index_dir / "lancedb").exists():
        try:
            db = _open_db(index_dir)
            if TABLE_NAME in db.table_names():
                table = db.open_table(TABLE_NAME)
                initial_count = table.count_rows()

                # Try to delete entries with written_at older than TTL
                # (Only applies to entries tagged by memory_protocol)
                try:
                    table.delete(f"written_at < {ttl_cutoff}")
                except Exception:
                    pass  # Column may not exist in older indices

                # Trade-off: auto-compaction adds ~10ms overhead but keeps index performant over time
                try:
                    table.compact_files()
                except Exception:
                    pass  # compact_files may not be available in all versions

                try:
                    table.cleanup_old_versions()
                except Exception:
                    pass

                final_count = table.count_rows()
                entries_pruned = max(0, initial_count - final_count)
        except Exception as e:
            if not args.json_output:
                print(f"  Warning: DB operations failed: {e}", file=sys.stderr)

    report["entries_pruned"] = entries_pruned

    # 2. Clean up orphaned agent sessions
    sessions_cleaned = 0
    try:
        from memory_protocol import MemoryProtocol
        protocol = MemoryProtocol(root)
        gc_result = protocol.gc_sessions()
        sessions_cleaned = gc_result.get("sessions_purged", 0) + gc_result.get("sessions_orphaned", 0)
        report["sessions_orphaned"] = gc_result.get("sessions_orphaned", 0)
        report["sessions_purged"] = gc_result.get("sessions_purged", 0)
        report["conflicts_purged"] = gc_result.get("conflicts_purged", 0)
    except (ImportError, Exception):
        report["sessions_orphaned"] = 0
        report["sessions_purged"] = 0
        report["conflicts_purged"] = 0

    # 3. Clean up stale locks
    locks_cleaned = 0
    try:
        from memory_lock import cleanup_stale_locks
        locks_cleaned = cleanup_stale_locks(index_dir)
    except (ImportError, Exception):
        pass
    report["locks_cleaned"] = locks_cleaned

    # 4. Clean up embedding cache (remove entries for pruned content)
    cache_dir = index_dir / "embedding_cache"
    cache_cleaned = 0
    if cache_dir.exists() and args.deep:
        # In deep mode, clear the entire embedding cache
        try:
            shutil.rmtree(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_cleaned = 1
        except OSError:
            pass
    report["cache_cleaned"] = cache_cleaned

    # Index size after
    size_after = _dir_size_mb(index_dir)
    report["size_after_mb"] = round(size_after, 2)
    report["size_freed_mb"] = round(max(0, size_before - size_after), 2)

    # Size warning
    if size_after > max_size_mb:
        report["size_warning"] = (
            f"Index size ({size_after:.1f} MB) exceeds configured maximum "
            f"({max_size_mb} MB). Consider running 'gc --deep' or 'clear --force'."
        )

    if args.json_output:
        print(json.dumps(report, indent=2))
    else:
        print(f"  Entries pruned:    {entries_pruned}", file=sys.stderr)
        print(f"  Sessions cleaned:  {sessions_cleaned}", file=sys.stderr)
        print(f"  Locks cleaned:     {locks_cleaned}", file=sys.stderr)
        print(f"  Cache cleaned:     {'yes' if cache_cleaned else 'no'}", file=sys.stderr)
        print(f"  Size after:        {size_after:.2f} MB", file=sys.stderr)
        print(f"  Space freed:       {report['size_freed_mb']:.2f} MB", file=sys.stderr)
        if report.get("size_warning"):
            print(f"  WARNING: {report['size_warning']}", file=sys.stderr)
        print("  Done.", file=sys.stderr)


# ── Agents Command ───────────────────────────────────────────────────────────

def cmd_agents(args):
    """List active and historical agent sessions."""
    root = Path(args.root).resolve()

    try:
        from memory_protocol import MemoryProtocol
        protocol = MemoryProtocol(root)
    except ImportError:
        print(json.dumps({"error": "memory_protocol module not available"}))
        sys.exit(1)

    status_filter = args.status if args.status != "all" else None
    type_filter = args.type if args.type != "all" else None

    sessions = protocol.registry.list_sessions(
        status=status_filter,
        agent_type=type_filter,
    )

    if args.json_output:
        print(json.dumps({"sessions": sessions, "count": len(sessions)}, indent=2))
    else:
        if not sessions:
            print("No agent sessions found.")
            return

        print(f"\nAgent Sessions ({len(sessions)} total)")
        print("=" * 70)
        for s in sessions:
            status_icon = {
                "active": "[ACTIVE]",
                "completed": "[DONE]",
                "orphaned": "[ORPHAN]",
            }.get(s.get("status", ""), "[?]")
            print(
                f"  {status_icon} {s.get('agent_id', '?')}"
                f"  type={s.get('agent_type', '?')}"
                f"  task={s.get('task_code', '-')}"
                f"  session={s.get('session_id', '?')}"
            )
            print(
                f"           started={s.get('started_iso', '?')}"
                f"  writes={s.get('entries_written', 0)}"
                f"  conflicts={s.get('conflicts_detected', 0)}"
            )
        print()


# ── Conflicts Command ────────────────────────────────────────────────────────

def cmd_conflicts(args):
    """Show flagged contradictions between agents."""
    root = Path(args.root).resolve()

    try:
        from memory_protocol import MemoryProtocol
        protocol = MemoryProtocol(root)
    except ImportError:
        print(json.dumps({"error": "memory_protocol module not available"}))
        sys.exit(1)

    resolved_filter = None
    if args.status == "pending":
        resolved_filter = False
    elif args.status == "resolved":
        resolved_filter = True

    conflicts = protocol.resolver.list_conflicts(resolved=resolved_filter)

    if args.resolve_id:
        success = protocol.resolver.resolve_conflict_by_id(args.resolve_id)
        if success:
            result = {"resolved": True, "conflict_id": args.resolve_id}
        else:
            result = {"resolved": False, "error": f"Conflict {args.resolve_id} not found"}
        print(json.dumps(result, indent=2))
        return

    if args.json_output:
        print(json.dumps({"conflicts": conflicts, "count": len(conflicts)}, indent=2))
    else:
        if not conflicts:
            print("No conflicts found.")
            return

        print(f"\nMemory Conflicts ({len(conflicts)} total)")
        print("=" * 70)
        for c in conflicts:
            status = "RESOLVED" if c.get("resolved") else "PENDING"
            print(
                f"  [{status}] {c.get('conflict_id', '?')}"
                f"  field={c.get('field', '?')}"
                f"  resolution={c.get('resolution', '?')}"
            )
            print(
                f"           agent_a={c.get('entry_a_agent', '?')}"
                f"  agent_b={c.get('entry_b_agent', '?')}"
            )
            print(
                f"           detected={c.get('detected_iso', '?')}"
            )
        print()
        print(f"  To resolve: vector_memory.py conflicts --resolve <conflict_id>")
        print()


# ── Hook: Incremental Update ────────────────────────────────────────────────

def hook_file_changed(file_path: str):
    """Called by PostToolUse hook when a file is edited/written.

    Performs incremental re-indexing of the single changed file.
    Designed to be fast and non-blocking.

    Always-on: missing config is treated as enabled. The hook will run
    unless explicitly disabled (enabled=false) in project-config.json.
    """
    root = _find_project_root()
    config = get_effective_config(root)

    # Only skip if explicitly disabled; missing config defaults to enabled
    if config.get("enabled") is False:
        return
    if config.get("auto_index") is False:
        return

    # Check deps silently — do not block on missing deps
    ok, _ = _check_deps()
    if not ok:
        return

    index_dir = root / config["index_path"]
    if not (index_dir / "lancedb").exists():
        # Index not yet built — trigger initialization once.
        # Sentinel file prevents repeated full-repo scans on every hook call.
        sentinel = index_dir / ".init_attempted"
        if sentinel.exists():
            return  # Already attempted; skip to avoid unbounded resource use
        try:
            index_dir.mkdir(parents=True, exist_ok=True)
            sentinel.touch()
            initialized = ensure_initialized(root)
        except Exception:
            return
        if not initialized or not (index_dir / "lancedb").exists():
            return
        # Index now ready — fall through to index the changed file

    try:
        abs_path = Path(file_path).resolve()
        if not abs_path.exists():
            return

        rel_path = str(abs_path.relative_to(root))
    except ValueError:
        return  # File is outside project root

    from chunkers import chunk_file, chunk_text_document
    from embeddings import EmbeddingCache

    content = read_file_safe(abs_path)
    if not content:
        return

    emb_config = {
        "provider": config["embedding_provider"],
        "model": config["embedding_model"],
        "api_key_env": config["embedding_api_key_env"],
    }

    try:
        provider = _get_cached_provider(emb_config)
        cache = EmbeddingCache(index_dir / "embedding_cache")

        # Acquire write lock
        lock = None
        try:
            from memory_lock import MemoryLock
            agent_id = os.environ.get("CodeClaw_AGENT_ID", f"agent-{os.getpid()}")
            session_id = os.environ.get("CodeClaw_SESSION_ID", "")
            lock = MemoryLock(index_dir, agent_id=agent_id, session_id=session_id, timeout=5.0)
        except ImportError:
            pass

        _ctx = lock.write() if lock else nullcontext()
        with _ctx:
            db = _open_db(index_dir)
            table = _get_or_create_table(db, provider.dimension())

            # Remove old entries for this file
            try:
                table.delete(f"file_path = '{_sanitize_filter_value(rel_path)}'")
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

                # Tag entries with agent metadata if available
                agent_id = os.environ.get("CodeClaw_AGENT_ID", "")
                agent_type = os.environ.get("CodeClaw_AGENT_TYPE", "task")
                session_id = os.environ.get("CodeClaw_SESSION_ID", "")
                task_code = os.environ.get("CodeClaw_TASK_CODE", "")

                records = []
                for chunk, emb in zip(chunks, embeddings):
                    record = {
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
                    }
                    # Add agent metadata if available
                    if agent_id:
                        try:
                            from memory_protocol import tag_entry
                            tag_entry(record, agent_id, agent_type,
                                     task_code, session_id)
                        except ImportError:
                            pass
                    records.append(record)
                table.add(records)

        # Update manifest for this file
        manifest = load_stored_manifest(index_dir)
        manifest[rel_path] = compute_file_hash(abs_path)
        save_manifest(index_dir, manifest)

    except Exception:
        pass  # Hook failures must be silent and non-blocking


# ── Export Context for RLM ───────────────────────────────────────────────────

def export_context(
    file_paths: list[str],
    fmt: str = "dict",
    root: Optional[Path] = None,
) -> dict:
    """Export indexed content as structured context for RLM processing.

    Reads file contents and returns them in a format suitable for the RLM
    backend to process. Supports dict format (file path -> content mapping)
    and flat format (concatenated text with file markers).

    Args:
        file_paths: List of file paths (relative to root or absolute) to export.
        fmt: Output format — 'dict' (default) or 'flat'.
        root: Project root for resolving relative paths. Auto-detected if None.

    Returns:
        Dict with 'success', 'context', 'files_loaded', and 'total_size_bytes'.
    """
    if root is None:
        root = _find_project_root()

    context_dict = {}
    files_loaded = 0
    total_size = 0

    for fpath in file_paths:
        abs_path = Path(fpath)
        if not abs_path.is_absolute():
            abs_path = root / fpath

        if not abs_path.exists() or not abs_path.is_file():
            continue

        try:
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        try:
            rel_key = str(abs_path.relative_to(root))
        except ValueError:
            rel_key = str(abs_path)

        context_dict[rel_key] = content
        files_loaded += 1
        total_size += len(content.encode("utf-8"))

    if fmt == "flat":
        parts = []
        for path, content in context_dict.items():
            parts.append(f"=== FILE: {path} ===\n{content}\n")
        context_output = "\n".join(parts)
    else:
        context_output = context_dict

    return {
        "success": files_loaded > 0,
        "context": context_output,
        "files_loaded": files_loaded,
        "files_requested": len(file_paths),
        "total_size_bytes": total_size,
    }


# ── Shared Helper: Index a Document ──────────────────────────────────────────

def try_vector_index(root: Path, content: str, doc_name: str,
                     doc_type: str = "report"):
    """Index a text document into the vector store (always-on, non-fatal).

    Shared helper used by codebase_analyzer and memory_builder to index
    their output into the vector memory layer. Always-on by default —
    only skips if explicitly disabled in project-config.json.

    Args:
        root: Project root path.
        content: Document content to index.
        doc_name: Logical name / file_path for the document in the index.
        doc_type: Chunk type label (e.g. "report", "memory").
    """
    try:
        from chunkers import chunk_text_document
        from embeddings import EmbeddingCache

        config = get_effective_config(root)
        # Only skip if explicitly disabled; missing config defaults to enabled
        if config.get("enabled") is False:
            return

        ok, _ = _check_deps()
        if not ok:
            return

        index_dir = root / config["index_path"]
        if not (index_dir / "lancedb").exists():
            # Try to initialize the index before indexing the document
            try:
                ensure_initialized(root)
            except Exception:
                return
            if not (index_dir / "lancedb").exists():
                return

        chunks = chunk_text_document(doc_name, content, doc_type=doc_type,
                                     max_chunk_size=config.get("chunk_size", 2000))
        if not chunks:
            return

        emb_config = {
            "provider": config["embedding_provider"],
            "model": config["embedding_model"],
            "api_key_env": config["embedding_api_key_env"],
        }
        provider = _get_cached_provider(emb_config)
        cache = EmbeddingCache(index_dir / "embedding_cache")
        db = _open_db(index_dir)
        table = _get_or_create_table(db, provider.dimension())

        # Remove old entries for this doc
        try:
            table.delete(f"file_path = '{_sanitize_filter_value(doc_name)}'")
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
        print(f"  Indexed {len(chunks)} {doc_type} chunks into vector memory.",
              file=sys.stderr)
    except Exception:
        pass  # Failures are non-fatal to avoid blocking callers


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="CodeClaw Vector Memory — semantic search over repository content",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s index                    # Incremental index
  %(prog)s index --full             # Full rebuild
  %(prog)s search "authentication"  # Semantic search
  %(prog)s status                   # Index health check
  %(prog)s gc                       # Garbage collection
  %(prog)s gc --deep                # Deep GC (clears embedding cache)
  %(prog)s agents                   # List agent sessions
  %(prog)s agents --status active   # List only active agents
  %(prog)s conflicts                # Show conflicts
  %(prog)s conflicts --resolve ID   # Resolve a conflict
  %(prog)s clear --force            # Reset index
""",
    )

    sub = parser.add_subparsers(dest="command")

    # ── index ──
    idx = sub.add_parser("index", help="Index repository for semantic search")
    idx.add_argument("--root", default=".", help="Project root directory")
    idx.add_argument("--full", action="store_true",
                     help="Full rebuild (ignore incremental hashes)")
    idx.add_argument("--force-init", action="store_true", dest="force_init",
                     help="Force initialization even if index already exists (used by setup)")

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
    srch.add_argument("--version", type=int, default=None,
                      help="Query at a specific dataset version (point-in-time)")

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

    # ── gc ──
    gc_p = sub.add_parser("gc", help="Garbage collection: prune old entries, compact tables")
    gc_p.add_argument("--root", default=".", help="Project root directory")
    gc_p.add_argument("--ttl-days", type=int, default=None,
                      help="TTL in days for pruning (default: from config or 30)")
    gc_p.add_argument("--deep", action="store_true",
                      help="Deep GC: also clear embedding cache")
    gc_p.add_argument("--json", dest="json_output", action="store_true",
                      help="Output as JSON")

    # ── agents ──
    ag = sub.add_parser("agents", help="List active/historical agent sessions")
    ag.add_argument("--root", default=".", help="Project root directory")
    ag.add_argument("--status", choices=["all", "active", "completed", "orphaned"],
                    default="all", help="Filter by session status")
    ag.add_argument("--type", choices=["all", "task", "scout", "release", "docs",
                                       "pr-analysis", "monitor"],
                    default="all", help="Filter by agent type")
    ag.add_argument("--json", dest="json_output", action="store_true",
                    help="Output as JSON")

    # ── conflicts ──
    cfl = sub.add_parser("conflicts", help="Show flagged contradictions")
    cfl.add_argument("--root", default=".", help="Project root directory")
    cfl.add_argument("--status", choices=["all", "pending", "resolved"],
                     default="all", help="Filter by conflict status")
    cfl.add_argument("--resolve", dest="resolve_id", default=None,
                     help="Resolve a conflict by ID")
    cfl.add_argument("--json", dest="json_output", action="store_true",
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
    elif args.command == "gc":
        cmd_gc(args)
    elif args.command == "agents":
        cmd_agents(args)
    elif args.command == "conflicts":
        cmd_conflicts(args)
    elif args.command == "hook":
        hook_file_changed(args.file_path)


if __name__ == "__main__":
    main()
