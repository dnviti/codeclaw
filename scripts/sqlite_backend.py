#!/usr/bin/env python3
"""SQLite hybrid memory backend with FTS5 and sqlite-vec.

Provides a complementary memory storage and retrieval backend alongside
the existing LanceDB vector store. Uses sqlite-vec for vector similarity
search and FTS5 for BM25 keyword matching, combined in a hybrid retrieval
pipeline with configurable weighting (default 0.7 vector + 0.3 text).

Each repository gets its own .sqlite file under .claude/memory/, making
the index single-file portable and trivially backupable. Transactional
writes via SQLite WAL mode ensure data integrity across concurrent agent
writes.

Required dependencies:
    - sqlite-vec (pip install sqlite-vec) — for vector similarity search
    - sqlite3 (stdlib) — always available

The backend implements the MemoryBackend interface for integration with
the vector memory orchestrator.
"""

import logging
import sqlite3
import struct
import sys
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Add scripts/ to path for sibling package imports
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


# ── MemoryBackend Interface ──────────────────────────────────────────────────

class MemoryBackend(ABC):
    """Abstract interface for vector memory backends."""

    @abstractmethod
    def index(self, file_paths: list[str], root: Path, config: dict,
              full: bool = False) -> dict:
        """Chunk, embed, and insert files into the index.

        Args:
            file_paths: List of relative file paths to index.
            root: Project root directory.
            config: Effective vector memory configuration.
            full: If True, perform full rebuild (drop existing data first).

        Returns:
            Dict with indexing statistics (chunks_indexed, files_indexed, etc.).
        """
        ...

    @abstractmethod
    def search(self, query: str, top_k: int = 10,
               file_filter: str = "", type_filter: str = "",
               hybrid_weight: Optional[float] = None) -> list[dict]:
        """Search the index with hybrid vector + text retrieval.

        Args:
            query: Natural-language search query.
            top_k: Maximum number of results.
            file_filter: Optional substring filter on file paths.
            type_filter: Optional chunk type filter.
            hybrid_weight: Vector weight (0.0-1.0). Text weight = 1 - vector.

        Returns:
            List of result dicts with file_path, name, chunk_type, score,
            content, start_line, end_line, language fields.
        """
        ...

    @abstractmethod
    def status(self) -> dict:
        """Return index health and statistics.

        Returns:
            Dict with total_chunks, index_size_mb, last_indexed, etc.
        """
        ...

    @abstractmethod
    def gc(self, ttl_days: int = 30, deep: bool = False) -> dict:
        """Garbage collection: prune old entries, optimize database.

        Args:
            ttl_days: Entries older than this are eligible for pruning.
            deep: If True, run VACUUM and rebuild FTS.

        Returns:
            Dict with gc statistics (entries_pruned, size_freed_mb, etc.).
        """
        ...


# ── Helpers ──────────────────────────────────────────────────────────────────

def _float_list_to_blob(vec: list[float]) -> bytes:
    """Convert a list of floats to a little-endian float32 BLOB for sqlite-vec."""
    return struct.pack(f"<{len(vec)}f", *vec)


def _blob_to_float_list(blob: bytes) -> list[float]:
    """Convert a little-endian float32 BLOB back to a list of floats."""
    count = len(blob) // 4
    return list(struct.unpack(f"<{count}f", blob))


def _sanitize_fts_query(query: str) -> str:
    """Sanitize a query string for FTS5 to prevent syntax errors.

    FTS5 has special syntax characters (*, ", OR, AND, NOT, NEAR, etc.)
    that can cause parse errors. We strip all non-alphanumeric characters
    (except spaces and underscores) and wrap each token in double quotes
    to treat as literal search terms.
    """
    import re
    # Strip all characters that could interfere with FTS5 syntax
    # Keep alphanumerics, spaces, underscores, hyphens, and dots
    cleaned = re.sub(r'[^\w\s.\-]', '', query)
    words = cleaned.split()
    if not words:
        return '""'
    return " ".join(f'"{w}"' for w in words)


# ── SQLite Backend ───────────────────────────────────────────────────────────

class SQLiteMemoryBackend(MemoryBackend):
    """SQLite-based hybrid memory backend with FTS5 + sqlite-vec.

    Schema:
        chunks table:
            id INTEGER PRIMARY KEY,
            file_path TEXT,
            chunk_type TEXT,
            name TEXT,
            start_line INTEGER,
            end_line INTEGER,
            language TEXT,
            file_role TEXT,
            content TEXT,
            content_hash TEXT,
            embedding BLOB (float32 little-endian),
            indexed_at REAL (unix timestamp)

        chunks_fts (FTS5 virtual table):
            content column from chunks table

        chunks_vec (sqlite-vec virtual table):
            embedding vector for cosine similarity search
    """

    def __init__(self, db_path: Path, dimension: int = 384,
                 hybrid_weight_vector: float = 0.7,
                 hybrid_weight_text: float = 0.3):
        """Initialize the SQLite memory backend.

        Args:
            db_path: Path to the SQLite database file.
            dimension: Embedding vector dimensionality.
            hybrid_weight_vector: Weight for vector similarity (0.0-1.0).
            hybrid_weight_text: Weight for text/BM25 similarity (0.0-1.0).
        """
        self.db_path = Path(db_path)
        self.dimension = self._validate_dimension(dimension)
        self.hybrid_weight_vector = hybrid_weight_vector
        self.hybrid_weight_text = hybrid_weight_text
        self._vec_available = False

        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize the database
        self._init_db()

    @staticmethod
    def _validate_dimension(dimension) -> int:
        """Validate and return dimension as a positive integer.

        Prevents SQL injection via f-string interpolation in DDL statements.
        """
        dim = int(dimension)
        if dim <= 0:
            raise ValueError(f"Embedding dimension must be positive, got {dim}")
        return dim

    def _load_sqlite_vec(self, conn: sqlite3.Connection) -> bool:
        """Try to load the sqlite-vec extension.

        Returns True if successful, False if not available.
        """
        try:
            import sqlite_vec
            sqlite_vec.load(conn)
            return True
        except (ImportError, Exception):
            return False

    def _init_db(self):
        """Initialize database schema with WAL mode."""
        conn = sqlite3.connect(str(self.db_path))
        try:
            # Enable WAL mode for concurrent read/write safety
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")

            # Create chunks table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_path TEXT NOT NULL,
                    chunk_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    start_line INTEGER NOT NULL,
                    end_line INTEGER NOT NULL,
                    language TEXT NOT NULL,
                    file_role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    embedding BLOB,
                    indexed_at REAL NOT NULL
                )
            """)

            # Create indexes for common queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_file_path
                ON chunks(file_path)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_content_hash
                ON chunks(content_hash)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_chunks_chunk_type
                ON chunks(chunk_type)
            """)

            # Create FTS5 virtual table for BM25 text search
            # Use content-sync (external content) to avoid data duplication
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    content,
                    content='chunks',
                    content_rowid='id'
                )
            """)

            # Create FTS triggers for automatic sync
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
                    INSERT INTO chunks_fts(rowid, content)
                    VALUES (new.id, new.content);
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
                    INSERT INTO chunks_fts(chunks_fts, rowid, content)
                    VALUES ('delete', old.id, old.content);
                END
            """)
            conn.execute("""
                CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
                    INSERT INTO chunks_fts(chunks_fts, rowid, content)
                    VALUES ('delete', old.id, old.content);
                    INSERT INTO chunks_fts(rowid, content)
                    VALUES (new.id, new.content);
                END
            """)

            # Try to load sqlite-vec and create vector table
            self._vec_available = self._load_sqlite_vec(conn)
            if self._vec_available:
                conn.execute(f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
                        chunk_id INTEGER PRIMARY KEY,
                        embedding float[{self.dimension}]
                    )
                """)

            # Create metadata table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS index_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)

            conn.commit()
        finally:
            conn.close()

    @contextmanager
    def _connect(self):
        """Context manager for database connections with sqlite-vec loaded."""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        self._vec_available = self._load_sqlite_vec(conn)
        try:
            yield conn
        finally:
            conn.close()

    def index(self, file_paths: list[str], root: Path, config: dict,
              full: bool = False) -> dict:
        """Chunk, embed, and insert files into the SQLite index."""
        from chunkers import chunk_file, chunk_text_document
        from embeddings import create_provider, EmbeddingCache

        index_dir = root / config.get("index_path", ".claude/memory/vectors")

        # Initialize embedding provider
        emb_config = {
            "provider": config.get("embedding_provider", "local"),
            "model": config.get("embedding_model", "all-MiniLM-L6-v2"),
            "api_key_env": config.get("embedding_api_key_env", ""),
        }
        provider = create_provider(emb_config)
        cache = EmbeddingCache(index_dir / "embedding_cache")

        # Update dimension from provider
        actual_dim = self._validate_dimension(provider.dimension())
        if actual_dim != self.dimension:
            self.dimension = actual_dim
            # Recreate vec table with correct dimension if needed
            self._init_db()

        batch_size = config.get("batch_size", 64)
        chunk_size = config.get("chunk_size", 2000)

        total_chunks = 0
        start_time = time.time()

        with self._connect() as conn:
            if full:
                # Full rebuild: clear existing data
                conn.execute("DELETE FROM chunks")
                if self._vec_available:
                    conn.execute("DELETE FROM chunks_vec")
                # Rebuild FTS index
                conn.execute(
                    "INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')"
                )
                conn.commit()

            pending_records: list[dict] = []
            pending_texts: list[str] = []

            for i, rel_path in enumerate(file_paths):
                fpath = root / rel_path
                try:
                    content = fpath.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue

                if not content.strip():
                    continue

                # Remove old entries for this file (for incremental updates)
                if not full:
                    self._remove_file_entries(conn, rel_path)

                # Chunk the file
                ext = fpath.suffix.lower()
                if ext in {".md", ".txt", ".rst"}:
                    chunks = chunk_text_document(rel_path, content,
                                                 max_chunk_size=chunk_size)
                else:
                    chunks = chunk_file(rel_path, content,
                                        max_chunk_size=chunk_size)

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
                    self._flush_batch(conn, provider, cache,
                                      pending_records, pending_texts)
                    pending_records = []
                    pending_texts = []

                # Progress
                if (i + 1) % 50 == 0:
                    print(f"    Indexed {i + 1}/{len(file_paths)} files...",
                          file=sys.stderr, flush=True)

            # Final flush
            if pending_texts:
                self._flush_batch(conn, provider, cache,
                                  pending_records, pending_texts)

            # Update metadata
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._set_meta(conn, "last_indexed", now)
            self._set_meta(conn, "file_count", str(len(file_paths)))
            self._set_meta(conn, "embedding_model", provider.model_name())
            self._set_meta(conn, "embedding_dimension", str(provider.dimension()))
            conn.commit()

        elapsed = time.time() - start_time
        return {
            "chunks_indexed": total_chunks,
            "files_indexed": len(file_paths),
            "elapsed_seconds": round(elapsed, 1),
        }

    def _remove_file_entries(self, conn: sqlite3.Connection, file_path: str):
        """Remove all entries for a given file path."""
        # Batch-remove from vec table first
        if self._vec_available:
            cursor = conn.execute(
                "SELECT id FROM chunks WHERE file_path = ?", (file_path,)
            )
            ids = [row[0] for row in cursor.fetchall()]
            if ids:
                placeholders = ",".join("?" * len(ids))
                try:
                    conn.execute(
                        f"DELETE FROM chunks_vec WHERE chunk_id IN ({placeholders})",
                        ids
                    )
                except Exception as e:
                    logger.warning("Failed to remove vec entries for %s: %s",
                                   file_path, e)

        conn.execute("DELETE FROM chunks WHERE file_path = ?", (file_path,))

    def _flush_batch(self, conn: sqlite3.Connection, provider, cache,
                     records: list[dict], texts: list[str]):
        """Embed a batch of texts and insert into the database."""
        embeddings = cache.embed_with_cache(provider, texts)

        now = time.time()
        for rec, emb in zip(records, embeddings):
            embedding_blob = _float_list_to_blob(emb)

            cursor = conn.execute(
                """INSERT INTO chunks
                   (file_path, chunk_type, name, start_line, end_line,
                    language, file_role, content, content_hash, embedding,
                    indexed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (rec["file_path"], rec["chunk_type"], rec["name"],
                 rec["start_line"], rec["end_line"], rec["language"],
                 rec["file_role"], rec["content"], rec["content_hash"],
                 embedding_blob, now)
            )

            # Insert into vec table
            if self._vec_available:
                chunk_id = cursor.lastrowid
                try:
                    conn.execute(
                        "INSERT INTO chunks_vec (chunk_id, embedding) VALUES (?, ?)",
                        (chunk_id, embedding_blob)
                    )
                except Exception as e:
                    logger.warning("Failed to insert vec entry for chunk %d: %s",
                                   chunk_id, e)

        conn.commit()

    def search(self, query: str, top_k: int = 10,
               file_filter: str = "", type_filter: str = "",
               hybrid_weight: Optional[float] = None) -> list[dict]:
        """Hybrid search combining vector similarity and FTS5 BM25."""
        vec_weight = hybrid_weight if hybrid_weight is not None else self.hybrid_weight_vector
        text_weight = 1.0 - vec_weight

        results_by_id: dict[int, dict] = {}

        with self._connect() as conn:
            # Vector search (if sqlite-vec is available and embeddings exist)
            if self._vec_available and vec_weight > 0:
                try:
                    from embeddings import create_provider

                    # Load config to get embedding settings
                    emb_config = self._load_embedding_config(conn)
                    provider = create_provider(emb_config)
                    query_embedding = provider.embed([query])[0]
                    query_blob = _float_list_to_blob(query_embedding)

                    # Use sqlite-vec for cosine distance search
                    # Fetch more results than top_k for hybrid merging
                    fetch_k = top_k * 3
                    vec_results = conn.execute(
                        """SELECT chunk_id, distance
                           FROM chunks_vec
                           WHERE embedding MATCH ?
                           ORDER BY distance
                           LIMIT ?""",
                        (query_blob, fetch_k)
                    ).fetchall()

                    for row in vec_results:
                        chunk_id = row[0]
                        distance = row[1]
                        # Convert distance to similarity score (0-1, higher is better)
                        # sqlite-vec returns L2 distance by default
                        vec_score = 1.0 / (1.0 + distance)
                        results_by_id[chunk_id] = {
                            "vec_score": vec_score,
                            "text_score": 0.0,
                        }
                except Exception as e:
                    logger.warning("Vector search failed, falling back to "
                                   "text-only: %s", e)

            # FTS5 text search
            if text_weight > 0:
                try:
                    safe_query = _sanitize_fts_query(query)
                    fetch_k = top_k * 3

                    fts_results = conn.execute(
                        """SELECT rowid, rank
                           FROM chunks_fts
                           WHERE chunks_fts MATCH ?
                           ORDER BY rank
                           LIMIT ?""",
                        (safe_query, fetch_k)
                    ).fetchall()

                    if fts_results:
                        # Normalize BM25 ranks to 0-1 range
                        # FTS5 rank is negative (lower = better match)
                        # Use reciprocal rank normalization for better score
                        # distribution: score = 1 / (1 + abs(rank))
                        for row in fts_results:
                            chunk_id = row[0]
                            # Reciprocal normalization: higher is better
                            text_score = 1.0 / (1.0 + abs(row[1]))
                            if chunk_id in results_by_id:
                                results_by_id[chunk_id]["text_score"] = text_score
                            else:
                                results_by_id[chunk_id] = {
                                    "vec_score": 0.0,
                                    "text_score": text_score,
                                }
                except Exception as e:
                    logger.warning("FTS search failed: %s", e)

            if not results_by_id:
                return []

            # Compute hybrid scores
            scored_ids = []
            for chunk_id, scores in results_by_id.items():
                hybrid_score = (
                    vec_weight * scores["vec_score"] +
                    text_weight * scores["text_score"]
                )
                scored_ids.append((chunk_id, hybrid_score))

            # Sort by hybrid score descending
            scored_ids.sort(key=lambda x: x[1], reverse=True)

            # Over-fetch to compensate for post-filtering
            fetch_limit = top_k * 3 if (file_filter or type_filter) else top_k
            candidate_ids = [cid for cid, _ in scored_ids[:fetch_limit]]
            score_map = {cid: s for cid, s in scored_ids[:fetch_limit]}

            # Batch-fetch full chunk data (fixes N+1 query pattern)
            if not candidate_ids:
                return []

            placeholders = ",".join("?" * len(candidate_ids))
            query_sql = f"""SELECT id, file_path, chunk_type, name, start_line,
                                   end_line, language, file_role, content, content_hash
                            FROM chunks WHERE id IN ({placeholders})"""
            params = list(candidate_ids)

            # Apply filters in SQL when possible
            if file_filter:
                query_sql += " AND file_path LIKE ?"
                params.append(f"%{file_filter}%")
            if type_filter:
                query_sql += " AND chunk_type = ?"
                params.append(type_filter)

            rows = conn.execute(query_sql, params).fetchall()

            # Build results preserving score-based ordering
            row_map = {row["id"]: row for row in rows}
            results = []
            for chunk_id in candidate_ids:
                if len(results) >= top_k:
                    break
                row = row_map.get(chunk_id)
                if row is None:
                    continue

                results.append({
                    "file_path": row["file_path"],
                    "name": row["name"],
                    "chunk_type": row["chunk_type"],
                    "language": row["language"],
                    "start_line": row["start_line"],
                    "end_line": row["end_line"],
                    "score": round(score_map[chunk_id], 6),
                    "content": row["content"],
                    "content_hash": row["content_hash"],
                })

        return results

    def _load_embedding_config(self, conn: Optional[sqlite3.Connection] = None) -> dict:
        """Load embedding configuration from stored metadata or defaults.

        Args:
            conn: Optional existing connection to reuse (avoids nested connections).
        """
        try:
            if conn is not None:
                model = self._get_meta(conn, "embedding_model") or "all-MiniLM-L6-v2"
            else:
                with self._connect() as new_conn:
                    model = self._get_meta(new_conn, "embedding_model") or "all-MiniLM-L6-v2"
        except Exception as e:
            logger.warning("Failed to load embedding config: %s", e)
            model = "all-MiniLM-L6-v2"

        return {
            "provider": "local",
            "model": model,
        }

    def status(self) -> dict:
        """Return index health and statistics."""
        result = {
            "backend": "sqlite",
            "db_path": str(self.db_path),
            "db_exists": self.db_path.exists(),
            "vec_available": False,
        }

        if not self.db_path.exists():
            result["total_chunks"] = 0
            result["index_size_mb"] = 0.0
            return result

        try:
            with self._connect() as conn:
                result["vec_available"] = self._vec_available

                # Count chunks
                row = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
                result["total_chunks"] = row[0] if row else 0

                # File count
                row = conn.execute(
                    "SELECT COUNT(DISTINCT file_path) FROM chunks"
                ).fetchone()
                result["indexed_files"] = row[0] if row else 0

                # Metadata
                result["last_indexed"] = self._get_meta(conn, "last_indexed")
                result["embedding_model"] = self._get_meta(conn, "embedding_model")
                result["embedding_dimension"] = self._get_meta(
                    conn, "embedding_dimension"
                )

            # Database file size
            result["index_size_mb"] = round(
                self.db_path.stat().st_size / (1024 * 1024), 2
            )

            # Include WAL file size if present
            wal_path = Path(str(self.db_path) + "-wal")
            if wal_path.exists():
                result["index_size_mb"] += round(
                    wal_path.stat().st_size / (1024 * 1024), 2
                )

        except Exception as e:
            result["error"] = str(e)

        return result

    def gc(self, ttl_days: int = 30, deep: bool = False) -> dict:
        """Garbage collection: prune old entries and optimize database."""
        report = {
            "entries_pruned": 0,
            "size_before_mb": 0.0,
            "size_after_mb": 0.0,
            "size_freed_mb": 0.0,
        }

        if not self.db_path.exists():
            return report

        size_before = self.db_path.stat().st_size / (1024 * 1024)
        report["size_before_mb"] = round(size_before, 2)

        with self._connect() as conn:
            # Prune entries older than TTL
            ttl_cutoff = time.time() - (ttl_days * 86400)
            cursor = conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE indexed_at < ?",
                (ttl_cutoff,)
            )
            row = cursor.fetchone()
            entries_to_prune = row[0] if row else 0

            if entries_to_prune > 0:
                # Batch-remove from vec table first
                if self._vec_available:
                    ids_cursor = conn.execute(
                        "SELECT id FROM chunks WHERE indexed_at < ?",
                        (ttl_cutoff,)
                    )
                    ids = [id_row[0] for id_row in ids_cursor.fetchall()]
                    if ids:
                        placeholders = ",".join("?" * len(ids))
                        try:
                            conn.execute(
                                f"DELETE FROM chunks_vec WHERE chunk_id IN ({placeholders})",
                                ids
                            )
                        except Exception as e:
                            logger.warning("Failed to batch-delete vec entries "
                                           "during GC: %s", e)

                conn.execute(
                    "DELETE FROM chunks WHERE indexed_at < ?",
                    (ttl_cutoff,)
                )
                report["entries_pruned"] = entries_to_prune

            if deep:
                # Rebuild FTS index
                try:
                    conn.execute(
                        "INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')"
                    )
                except Exception as e:
                    logger.warning("Failed to rebuild FTS index during GC: %s", e)

                conn.commit()

                # VACUUM to reclaim space (must be outside transaction)
                try:
                    conn.execute("VACUUM")
                except Exception as e:
                    logger.warning("Failed to VACUUM during GC: %s", e)
            else:
                conn.commit()

        size_after = self.db_path.stat().st_size / (1024 * 1024)
        report["size_after_mb"] = round(size_after, 2)
        report["size_freed_mb"] = round(max(0, size_before - size_after), 2)

        return report

    def _set_meta(self, conn: sqlite3.Connection, key: str, value: str):
        """Set a metadata key-value pair."""
        conn.execute(
            """INSERT INTO index_meta (key, value) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (key, value)
        )

    def _get_meta(self, conn: sqlite3.Connection, key: str) -> Optional[str]:
        """Get a metadata value by key."""
        row = conn.execute(
            "SELECT value FROM index_meta WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def remove_file(self, file_path: str):
        """Remove all entries for a given file path."""
        with self._connect() as conn:
            self._remove_file_entries(conn, file_path)
            conn.commit()

    def index_single_file(self, rel_path: str, content: str,
                          root: Path, config: dict):
        """Index a single file (used by hook for incremental updates)."""
        from chunkers import chunk_file, chunk_text_document
        from embeddings import create_provider, EmbeddingCache

        index_dir = root / config.get("index_path", ".claude/memory/vectors")

        emb_config = {
            "provider": config.get("embedding_provider", "local"),
            "model": config.get("embedding_model", "all-MiniLM-L6-v2"),
            "api_key_env": config.get("embedding_api_key_env", ""),
        }
        provider = create_provider(emb_config)
        cache = EmbeddingCache(index_dir / "embedding_cache")

        chunk_size = config.get("chunk_size", 2000)
        ext = Path(rel_path).suffix.lower()

        if ext in {".md", ".txt", ".rst"}:
            chunks = chunk_text_document(rel_path, content,
                                         max_chunk_size=chunk_size)
        else:
            chunks = chunk_file(rel_path, content,
                                max_chunk_size=chunk_size)

        if not chunks:
            return

        with self._connect() as conn:
            # Remove old entries
            self._remove_file_entries(conn, rel_path)

            # Insert new entries
            texts = [c.content for c in chunks]
            records = []
            for chunk in chunks:
                records.append({
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

            self._flush_batch(conn, provider, cache, records, texts)


def create_sqlite_backend(root: Path, config: dict) -> SQLiteMemoryBackend:
    """Factory: create a SQLiteMemoryBackend from project config.

    Args:
        root: Project root directory.
        config: Effective vector memory configuration dict.

    Returns:
        Configured SQLiteMemoryBackend instance.
    """
    sqlite_config = config.get("sqlite", {})
    db_path = root / sqlite_config.get("db_path",
                                        ".claude/memory/sqlite/memory.db")
    hybrid_weight_vector = sqlite_config.get("hybrid_weight_vector", 0.7)
    hybrid_weight_text = sqlite_config.get("hybrid_weight_text", 0.3)

    # Get dimension from embedding config
    dimension = 384  # default for all-MiniLM-L6-v2
    model = config.get("embedding_model", "all-MiniLM-L6-v2")
    if model == "all-MiniLM-L6-v2":
        dimension = 384

    return SQLiteMemoryBackend(
        db_path=db_path,
        dimension=dimension,
        hybrid_weight_vector=hybrid_weight_vector,
        hybrid_weight_text=hybrid_weight_text,
    )
