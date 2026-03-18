#!/usr/bin/env python3
"""Unified memory orchestrator for tandem multi-backend coordination.

Manages all three memory backends (LanceDB vector search, SQLite hybrid
FTS5+vec, and RLM recursive processing) in tandem. Routes queries to the
appropriate backend(s) based on per-repository configuration, query
characteristics, and context size. Results from multiple backends are
merged via Reciprocal Rank Fusion (RRF) with configurable weights.

Integrates with the existing MCP server and uses the current MemoryLock
infrastructure for concurrent safety. Per-repository configuration in
``.claude/project-config.json`` controls which backends are active, their
routing weights, fallback chains, and query-type routing rules.

Supports graceful degradation -- if a backend's dependencies are missing
(e.g., sqlite-vec not installed), it falls back to the remaining available
backends transparently.

Zero external dependencies -- stdlib only for core logic. Backend-specific
dependencies are loaded lazily and checked for availability at runtime.
"""

import json
import os
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Optional

# Add scripts/ to path for sibling package imports
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_RRF_K = 60
DEFAULT_STRATEGY = "auto"
VALID_STRATEGIES = ("auto", "all", "specific")
BACKEND_NAMES = ("lancedb", "sqlite", "rlm")

# Query-type heuristics for auto routing
_EXACT_KEYWORDS = frozenset({
    "find", "grep", "search for", "exact", "literal", "match",
    "where is", "locate", "definition of", "function named",
})
_DEEP_KEYWORDS = frozenset({
    "how does", "explain", "why", "trace", "architecture",
    "design", "deep", "multi-hop", "relationship between",
    "impact of", "dependencies", "flow",
})


# ── Configuration ────────────────────────────────────────────────────────────

def load_orchestrator_config(root: Path) -> dict:
    """Load orchestrator config from project-config.json.

    Reads ``vector_memory.orchestrator`` section. Returns empty dict
    if not configured.
    """
    config_paths = [
        root / ".claude" / "project-config.json",
        root / "config" / "project-config.json",
    ]
    for cp in config_paths:
        if cp.exists():
            try:
                data = json.loads(cp.read_text(encoding="utf-8"))
                vm = data.get("vector_memory", {})
                return vm.get("orchestrator", {})
            except (json.JSONDecodeError, OSError):
                pass
    return {}


def get_effective_orchestrator_config(root: Path) -> dict:
    """Return effective orchestrator config with defaults applied.

    Args:
        root: Project root directory.

    Returns:
        Dict with all orchestrator configuration keys populated.
    """
    user_cfg = load_orchestrator_config(root)
    return {
        "backends": user_cfg.get("backends", ["lancedb"]),
        "routing_weights": user_cfg.get("routing_weights", {
            "lancedb": 1.0,
            "sqlite": 0.8,
            "rlm": 0.6,
        }),
        "fallback_chain": user_cfg.get("fallback_chain",
                                        ["lancedb", "sqlite", "rlm"]),
        "query_routing": user_cfg.get("query_routing", {
            "exact": "sqlite",
            "semantic": "lancedb",
            "deep": "rlm",
        }),
        "rrf_k": user_cfg.get("rrf_k", DEFAULT_RRF_K),
    }


# ── Query Classification ────────────────────────────────────────────────────

def classify_query(query: str) -> str:
    """Classify a query into a type for routing purposes.

    Types:
        exact     -- keyword/literal searches, best for FTS5
        semantic  -- concept/similarity searches, best for vector search
        deep      -- multi-hop reasoning, best for RLM recursive processing

    Args:
        query: Natural-language search query.

    Returns:
        One of 'exact', 'semantic', or 'deep'.
    """
    lower = query.lower().strip()

    # Check for deep/multi-hop patterns
    for keyword in _DEEP_KEYWORDS:
        if keyword in lower:
            return "deep"

    # Check for exact/keyword patterns
    for keyword in _EXACT_KEYWORDS:
        if keyword in lower:
            return "exact"

    # Default to semantic search
    return "semantic"


# ── Backend Registry ─────────────────────────────────────────────────────────

class BackendRegistry:
    """Registry of available memory backends with health checking.

    Lazily discovers and instantiates backends based on configuration
    and dependency availability. Supports graceful degradation.
    """

    def __init__(self, root: Path, config: dict):
        """Initialize the backend registry.

        Args:
            root: Project root directory.
            config: Effective orchestrator configuration.
        """
        self.root = root
        self.config = config
        self._backends: dict[str, object] = {}
        self._health_cache: dict[str, dict] = {}
        self._health_ts: dict[str, float] = {}

    def discover(self) -> dict[str, bool]:
        """Discover which backends are available and their deps are met.

        Returns:
            Dict mapping backend name to availability bool.
        """
        available = {}
        requested = self.config.get("backends", ["lancedb"])

        for name in requested:
            if name == "lancedb":
                available[name] = self._check_lancedb()
            elif name == "sqlite":
                available[name] = self._check_sqlite()
            elif name == "rlm":
                available[name] = self._check_rlm()
            else:
                available[name] = False

        return available

    def _check_lancedb(self) -> bool:
        """Check if LanceDB dependencies are available."""
        try:
            import lancedb  # noqa: F401
            return True
        except ImportError:
            return False

    def _check_sqlite(self) -> bool:
        """Check if SQLite backend is available (FTS5 is always in stdlib)."""
        try:
            import sqlite3  # noqa: F401
            # sqlite_backend.py provides the SQLiteMemoryBackend
            from sqlite_backend import SQLiteMemoryBackend  # noqa: F401
            return True
        except ImportError:
            return False

    def _check_rlm(self) -> bool:
        """Check if RLM backend is available."""
        try:
            from rlm_backend import search as rlm_search  # noqa: F401
            return True
        except ImportError:
            return False

    def get_backend(self, name: str):
        """Get or create a backend instance by name.

        Args:
            name: Backend name ('lancedb', 'sqlite', 'rlm').

        Returns:
            Backend instance, or None if unavailable.
        """
        if name in self._backends:
            return self._backends[name]

        instance = self._create_backend(name)
        if instance is not None:
            self._backends[name] = instance
        return instance

    def _create_backend(self, name: str):
        """Create a new backend instance."""
        if name == "lancedb":
            return self._create_lancedb_backend()
        elif name == "sqlite":
            return self._create_sqlite_backend()
        elif name == "rlm":
            return self._create_rlm_backend()
        return None

    def _create_lancedb_backend(self):
        """Create a LanceDB backend wrapper."""
        try:
            return LanceDBBackendWrapper(self.root)
        except Exception:
            return None

    def _create_sqlite_backend(self):
        """Create a SQLite backend instance."""
        try:
            from sqlite_backend import create_sqlite_backend
            from vector_memory import load_config
            vm_config = load_config(self.root)
            return create_sqlite_backend(self.root, vm_config)
        except Exception:
            return None

    def _create_rlm_backend(self):
        """Create an RLM backend wrapper."""
        try:
            return RLMBackendWrapper(self.root)
        except Exception:
            return None

    def health(self, name: str) -> dict:
        """Get health status for a specific backend.

        Caches results for 60 seconds to avoid expensive checks.

        Args:
            name: Backend name.

        Returns:
            Dict with health information.
        """
        now = time.time()
        cached_ts = self._health_ts.get(name, 0)

        if now - cached_ts < 60 and name in self._health_cache:
            return self._health_cache[name]

        health = self._check_health(name)
        self._health_cache[name] = health
        self._health_ts[name] = now
        return health

    def _check_health(self, name: str) -> dict:
        """Perform actual health check for a backend."""
        available = False
        if name == "lancedb":
            available = self._check_lancedb()
        elif name == "sqlite":
            available = self._check_sqlite()
        elif name == "rlm":
            available = self._check_rlm()

        result = {
            "backend": name,
            "available": available,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        if available:
            backend = self.get_backend(name)
            if backend is not None:
                try:
                    status = backend.status()
                    result["status"] = status
                except Exception as e:
                    result["status_error"] = str(e)

        return result

    def all_health(self) -> dict[str, dict]:
        """Get health status for all configured backends."""
        requested = self.config.get("backends", ["lancedb"])
        return {name: self.health(name) for name in requested}


# ── Backend Wrappers ─────────────────────────────────────────────────────────

class LanceDBBackendWrapper:
    """Wrapper around LanceDB vector_memory.py operations.

    Implements the same interface as MemoryBackend (search, index, status)
    by delegating to vector_memory.py functions.
    """

    def __init__(self, root: Path):
        self.root = root

    def search(self, query: str, top_k: int = 10,
               file_filter: str = "", type_filter: str = "") -> list[dict]:
        """Search the LanceDB vector index."""
        try:
            from vector_memory import (
                get_effective_config, _open_db, _sanitize_filter_value,
                TABLE_NAME,
            )
            from embeddings import create_provider

            config = get_effective_config(self.root)
            index_dir = self.root / config["index_path"]

            if not (index_dir / "lancedb").exists():
                return []

            emb_config = {
                "provider": config["embedding_provider"],
                "model": config["embedding_model"],
                "api_key_env": config["embedding_api_key_env"],
            }
            provider = create_provider(emb_config)
            query_embedding = provider.embed([query])[0]

            db = _open_db(index_dir)
            try:
                table = db.open_table(TABLE_NAME)
            except Exception:
                return []

            results = table.search(query_embedding).limit(top_k * 3)

            if file_filter:
                safe_filter = _sanitize_filter_value(file_filter)
                results = results.where(f"file_path LIKE '%{safe_filter}%'")
            if type_filter:
                safe_type = _sanitize_filter_value(type_filter)
                results = results.where(f"chunk_type = '{safe_type}'")

            df = results.limit(top_k).to_pandas()

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
                    "content": row.get("content", ""),
                    "backend": "lancedb",
                })
            return records

        except Exception:
            return []

    def index(self, file_paths: list[str], root: Path, config: dict,
              full: bool = False) -> dict:
        """Index files into LanceDB (delegates to vector_memory.py)."""
        import subprocess
        cmd = [
            sys.executable,
            str(_SCRIPT_DIR / "vector_memory.py"),
            "index",
            "--root", str(root),
        ]
        if full:
            cmd.append("--full")
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600,
            )
            return {
                "success": result.returncode == 0,
                "output": result.stderr.strip(),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def status(self) -> dict:
        """Get LanceDB index status."""
        try:
            from vector_memory import (
                get_effective_config, _open_db, _dir_size_mb, TABLE_NAME,
                INDEX_META,
            )

            config = get_effective_config(self.root)
            index_dir = self.root / config["index_path"]

            result = {
                "backend": "lancedb",
                "index_exists": (index_dir / "lancedb").exists(),
            }

            if not result["index_exists"]:
                result["total_chunks"] = 0
                return result

            meta_path = index_dir / INDEX_META
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    result["last_indexed"] = meta.get("last_indexed")
                    result["indexed_files"] = meta.get("file_count", 0)
                    result["embedding_model"] = meta.get("embedding_model")
                except (json.JSONDecodeError, OSError):
                    pass

            result["index_size_mb"] = round(_dir_size_mb(index_dir), 2)
            return result
        except Exception as e:
            return {"backend": "lancedb", "error": str(e)}

    def gc(self, ttl_days: int = 30, deep: bool = False) -> dict:
        """Garbage collection (delegates to vector_memory.py gc)."""
        import subprocess
        cmd = [
            sys.executable,
            str(_SCRIPT_DIR / "vector_memory.py"),
            "gc",
            "--root", str(self.root),
            "--ttl-days", str(ttl_days),
        ]
        if deep:
            cmd.append("--deep")
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300,
            )
            return {"success": result.returncode == 0}
        except Exception as e:
            return {"success": False, "error": str(e)}


class RLMBackendWrapper:
    """Wrapper around RLM recursive context processing.

    Adapts the RLM search interface to the standard backend interface
    used by the orchestrator.
    """

    def __init__(self, root: Path):
        self.root = root

    def search(self, query: str, top_k: int = 10,
               file_filter: str = "", type_filter: str = "",
               context_paths: Optional[list[str]] = None) -> list[dict]:
        """Perform RLM recursive search.

        Since RLM operates on context rather than an index, it needs
        file paths to load as context. If not provided, uses recent
        files from the project.
        """
        try:
            from rlm_backend import search as rlm_search, get_effective_rlm_config

            config = get_effective_rlm_config(self.root)
            if not config.get("enabled", False):
                return []

            # Build context from file paths
            context_data = {}
            if context_paths:
                for fpath in context_paths:
                    try:
                        full_path = self.root / fpath if not Path(fpath).is_absolute() else Path(fpath)
                        content = full_path.read_text(
                            encoding="utf-8", errors="replace")
                        context_data[str(fpath)] = content
                    except OSError:
                        continue

            if not context_data:
                return []

            result = rlm_search(
                query=query,
                context_data=context_data,
                config=config,
            )

            if not result.get("success"):
                return []

            # Convert RLM findings to standard result format
            records = []
            for i, finding in enumerate(result.get("findings", [])):
                records.append({
                    "file_path": "",
                    "name": f"rlm-finding-{i + 1}",
                    "chunk_type": "rlm-analysis",
                    "language": "",
                    "start_line": 0,
                    "end_line": 0,
                    "score": 1.0 / (i + 1),  # Rank-based score
                    "content": finding if isinstance(finding, str) else str(finding),
                    "backend": "rlm",
                })
                if len(records) >= top_k:
                    break

            return records

        except Exception:
            return []

    def index(self, file_paths: list[str], root: Path, config: dict,
              full: bool = False) -> dict:
        """RLM does not maintain a persistent index."""
        return {
            "success": True,
            "message": "RLM backend does not require indexing.",
        }

    def status(self) -> dict:
        """Return RLM backend status."""
        try:
            from rlm_backend import get_effective_rlm_config
            config = get_effective_rlm_config(self.root)
            return {
                "backend": "rlm",
                "enabled": config.get("enabled", False),
                "provider": config.get("provider", "ollama"),
                "max_depth": config.get("max_depth", 3),
                "aggregation": config.get("aggregation", "map-reduce"),
            }
        except ImportError:
            return {"backend": "rlm", "available": False}

    def gc(self, ttl_days: int = 30, deep: bool = False) -> dict:
        """RLM has no persistent state to garbage collect."""
        return {"success": True, "message": "No persistent state to GC."}


# ── Reciprocal Rank Fusion ───────────────────────────────────────────────────

def reciprocal_rank_fusion(
    result_lists: list[tuple[str, list[dict]]],
    weights: dict[str, float],
    k: int = DEFAULT_RRF_K,
    top_k: int = 10,
) -> list[dict]:
    """Merge ranked result lists using Reciprocal Rank Fusion (RRF).

    RRF formula: score(d) = sum over lists L of (weight_L / (k + rank_L(d)))
    where rank_L(d) is the 1-based rank of document d in list L.

    Uses content_hash + file_path + start_line as the document identity key
    to allow deduplication across backends.

    Args:
        result_lists: List of (backend_name, results) tuples.
        weights: Per-backend weights for the RRF formula.
        k: RRF constant (default 60). Higher values reduce the impact
           of rank position differences.
        top_k: Maximum number of merged results to return.

    Returns:
        Merged and re-ranked list of result dicts.
    """
    # Score accumulator: doc_key -> {score, best_result}
    scores: dict[str, dict] = {}

    for backend_name, results in result_lists:
        weight = weights.get(backend_name, 1.0)

        for rank, result in enumerate(results, 1):
            # Build a document identity key
            doc_key = _result_key(result)

            rrf_score = weight / (k + rank)

            if doc_key in scores:
                scores[doc_key]["rrf_score"] += rrf_score
                scores[doc_key]["sources"].append(backend_name)
                # Keep the result with the highest original score
                if result.get("score", 0) > scores[doc_key]["result"].get("score", 0):
                    scores[doc_key]["result"] = result
            else:
                scores[doc_key] = {
                    "rrf_score": rrf_score,
                    "result": result,
                    "sources": [backend_name],
                }

    # Sort by RRF score descending
    ranked = sorted(scores.values(), key=lambda x: x["rrf_score"], reverse=True)

    # Build final results
    merged = []
    for entry in ranked[:top_k]:
        result = dict(entry["result"])
        result["rrf_score"] = round(entry["rrf_score"], 6)
        result["sources"] = entry["sources"]
        merged.append(result)

    return merged


def _result_key(result: dict) -> str:
    """Build a unique key for a search result for deduplication."""
    file_path = result.get("file_path", "")
    start_line = result.get("start_line", 0)
    content_hash = result.get("content_hash", "")
    name = result.get("name", "")

    if content_hash:
        return f"{file_path}:{content_hash}"
    if file_path and start_line:
        return f"{file_path}:{start_line}:{name}"
    # Fallback: use content prefix
    content = result.get("content", "")[:100]
    return f"{file_path}:{name}:{content}"


# ── Memory Orchestrator ──────────────────────────────────────────────────────

class MemoryOrchestrator:
    """Unified coordinator for multi-backend memory operations.

    Routes queries to appropriate backend(s), merges results via RRF,
    and handles graceful degradation when backends are unavailable.

    Usage::

        orchestrator = MemoryOrchestrator(root=Path("/project"))
        results = orchestrator.search("How does auth work?")

        # Explicit strategy
        results = orchestrator.search("find login function", strategy="specific",
                                       backends=["sqlite"])

        # Fan-out to all backends
        results = orchestrator.search("security audit", strategy="all")
    """

    def __init__(self, root: Optional[Path] = None,
                 config: Optional[dict] = None):
        """Initialize the orchestrator.

        Args:
            root: Project root directory. Auto-detected if None.
            config: Orchestrator configuration. Loaded from
                    project-config.json if None.
        """
        if root is None:
            root = self._find_root()
        self.root = root

        if config is None:
            config = get_effective_orchestrator_config(root)
        self.config = config

        self.registry = BackendRegistry(root, config)
        self._available = self.registry.discover()

    def _find_root(self) -> Path:
        """Auto-detect project root."""
        d = Path.cwd()
        while d != d.parent:
            if (d / ".claude").is_dir() or (d / ".git").exists():
                return d
            d = d.parent
        return Path.cwd()

    def search(
        self,
        query: str,
        strategy: str = "auto",
        top_k: int = 10,
        file_filter: str = "",
        type_filter: str = "",
        backends: Optional[list[str]] = None,
        context_paths: Optional[list[str]] = None,
    ) -> list[dict]:
        """Search across memory backends with configurable strategy.

        Args:
            query: Natural-language search query.
            strategy: Routing strategy:
                - 'auto': classify query and route to best backend(s)
                - 'all': fan-out to all available backends, merge via RRF
                - 'specific': use only the named backend(s)
            top_k: Maximum number of results to return.
            file_filter: Optional substring filter on file paths.
            type_filter: Optional chunk type filter.
            backends: Specific backend names (used with strategy='specific').
            context_paths: File paths for RLM context (optional).

        Returns:
            List of result dicts, ranked by relevance. Each result
            includes an 'rrf_score' and 'sources' field when results
            from multiple backends are merged.
        """
        if strategy not in VALID_STRATEGIES:
            strategy = DEFAULT_STRATEGY

        # Determine which backends to query
        target_backends = self._resolve_backends(
            query, strategy, backends)

        if not target_backends:
            return []

        # Acquire read lock if available
        lock_ctx = self._get_lock_ctx(exclusive=False)
        with lock_ctx:
            return self._execute_search(
                query, target_backends, top_k, file_filter,
                type_filter, context_paths)

    def _resolve_backends(
        self,
        query: str,
        strategy: str,
        backends: Optional[list[str]],
    ) -> list[str]:
        """Resolve which backends to query based on strategy.

        Applies fallback chain when primary backends are unavailable.
        """
        if strategy == "specific" and backends:
            # Use only available backends from the specified list
            available = [b for b in backends if self._available.get(b, False)]
            if available:
                return available
            # Fall through to fallback chain

        if strategy == "auto":
            query_type = classify_query(query)
            routing = self.config.get("query_routing", {})
            primary = routing.get(query_type, "lancedb")

            if self._available.get(primary, False):
                return [primary]
            # Primary unavailable, use fallback chain

        if strategy == "all":
            available = [
                b for b in self.config.get("backends", ["lancedb"])
                if self._available.get(b, False)
            ]
            if available:
                return available

        # Fallback chain
        fallback = self.config.get("fallback_chain",
                                    ["lancedb", "sqlite", "rlm"])
        for backend_name in fallback:
            if self._available.get(backend_name, False):
                return [backend_name]

        return []

    def _execute_search(
        self,
        query: str,
        target_backends: list[str],
        top_k: int,
        file_filter: str,
        type_filter: str,
        context_paths: Optional[list[str]],
    ) -> list[dict]:
        """Execute search across the target backends and merge results."""
        result_lists: list[tuple[str, list[dict]]] = []

        for backend_name in target_backends:
            backend = self.registry.get_backend(backend_name)
            if backend is None:
                continue

            try:
                if backend_name == "rlm":
                    results = backend.search(
                        query, top_k=top_k,
                        file_filter=file_filter,
                        type_filter=type_filter,
                        context_paths=context_paths,
                    )
                else:
                    results = backend.search(
                        query, top_k=top_k,
                        file_filter=file_filter,
                        type_filter=type_filter,
                    )
                if results:
                    result_lists.append((backend_name, results))
            except Exception:
                continue

        if not result_lists:
            return []

        # Single backend: return directly without RRF overhead
        if len(result_lists) == 1:
            backend_name, results = result_lists[0]
            for r in results:
                r.setdefault("sources", [backend_name])
                r.setdefault("rrf_score", r.get("score", 0.0))
            return results[:top_k]

        # Multiple backends: merge via RRF
        weights = self.config.get("routing_weights", {})
        rrf_k = self.config.get("rrf_k", DEFAULT_RRF_K)

        return reciprocal_rank_fusion(
            result_lists, weights, k=rrf_k, top_k=top_k)

    def index(
        self,
        paths: Optional[list[str]] = None,
        backends: Optional[list[str]] = None,
        full: bool = False,
    ) -> dict:
        """Index files into one or more backends.

        Args:
            paths: File paths to index. If None, indexes all files.
            backends: Specific backends to index into. If None, uses
                     all configured backends.
            full: Whether to perform a full rebuild.

        Returns:
            Dict with per-backend indexing results.
        """
        if backends is None:
            backends = [
                b for b in self.config.get("backends", ["lancedb"])
                if self._available.get(b, False)
            ]

        from vector_memory import get_effective_config
        vm_config = get_effective_config(self.root)

        lock_ctx = self._get_lock_ctx(exclusive=True)
        with lock_ctx:
            results = {}
            for backend_name in backends:
                backend = self.registry.get_backend(backend_name)
                if backend is None:
                    results[backend_name] = {"error": "Backend unavailable"}
                    continue

                try:
                    result = backend.index(
                        paths or [], self.root, vm_config, full=full)
                    results[backend_name] = result
                except Exception as e:
                    results[backend_name] = {"error": str(e)}

            return results

    def status(self) -> dict:
        """Get comprehensive status across all backends.

        Returns:
            Dict with orchestrator status and per-backend health.
        """
        return {
            "orchestrator": {
                "configured_backends": self.config.get("backends", []),
                "available_backends": [
                    b for b, avail in self._available.items() if avail
                ],
                "unavailable_backends": [
                    b for b, avail in self._available.items() if not avail
                ],
                "strategy": self.config.get("query_routing", {}),
                "rrf_k": self.config.get("rrf_k", DEFAULT_RRF_K),
            },
            "backends": self.registry.all_health(),
        }

    def list_backends(self) -> list[dict]:
        """List all configured backends with their availability.

        Returns:
            List of backend info dicts.
        """
        backends = []
        for name in BACKEND_NAMES:
            configured = name in self.config.get("backends", [])
            available = self._available.get(name, False)
            weight = self.config.get("routing_weights", {}).get(name, 0.0)

            backends.append({
                "name": name,
                "configured": configured,
                "available": available,
                "weight": weight,
            })
        return backends

    def _get_lock_ctx(self, exclusive: bool = False):
        """Get a lock context manager for thread safety.

        Uses per-backend lock files when available.
        """
        try:
            from memory_lock import MemoryLock
            from vector_memory import get_effective_config

            config = get_effective_config(self.root)
            index_dir = self.root / config["index_path"]
            agent_id = os.environ.get("CTDF_AGENT_ID",
                                       f"agent-{os.getpid()}")
            lock = MemoryLock(index_dir, agent_id=agent_id)
            return lock.write() if exclusive else lock.read()
        except (ImportError, Exception):
            return nullcontext()

    def refresh_availability(self):
        """Re-check backend availability (e.g., after installing deps)."""
        self._available = self.registry.discover()


# ── Module-level convenience ─────────────────────────────────────────────────

_orchestrator: Optional[MemoryOrchestrator] = None


def get_orchestrator(root: Optional[Path] = None) -> MemoryOrchestrator:
    """Get or create a module-level MemoryOrchestrator singleton.

    The orchestrator is cached for the lifetime of the process.

    Args:
        root: Project root directory. Auto-detected if None.

    Returns:
        Configured MemoryOrchestrator instance.
    """
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = MemoryOrchestrator(root=root)
    return _orchestrator


def search(query: str, strategy: str = "auto", top_k: int = 10,
           root: Optional[Path] = None, **kwargs) -> list[dict]:
    """Convenience function for orchestrated search.

    Args:
        query: Natural-language search query.
        strategy: Routing strategy ('auto', 'all', 'specific').
        top_k: Maximum number of results.
        root: Project root (auto-detected if None).
        **kwargs: Additional arguments passed to MemoryOrchestrator.search().

    Returns:
        List of ranked result dicts.
    """
    orch = get_orchestrator(root)
    return orch.search(query, strategy=strategy, top_k=top_k, **kwargs)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    """CLI entry point for the memory orchestrator."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Unified memory orchestrator for multi-backend coordination",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s search "How does authentication work?"
  %(prog)s search "find login function" --strategy specific --backends sqlite
  %(prog)s search "security architecture" --strategy all
  %(prog)s status
  %(prog)s backends
""",
    )
    sub = parser.add_subparsers(dest="command")

    # search
    s = sub.add_parser("search", help="Orchestrated multi-backend search")
    s.add_argument("query", help="Search query")
    s.add_argument("--strategy", choices=VALID_STRATEGIES,
                   default="auto", help="Routing strategy")
    s.add_argument("--backends", nargs="+", default=None,
                   help="Specific backends (for strategy=specific)")
    s.add_argument("--top-k", type=int, default=10,
                   help="Maximum results")
    s.add_argument("--file-filter", default="",
                   help="File path substring filter")
    s.add_argument("--type-filter", default="",
                   help="Chunk type filter")
    s.add_argument("--root", default=".",
                   help="Project root directory")
    s.add_argument("--json", dest="json_output", action="store_true",
                   help="Output as JSON")

    # status
    st = sub.add_parser("status", help="Orchestrator and backend status")
    st.add_argument("--root", default=".", help="Project root directory")

    # backends
    b = sub.add_parser("backends", help="List available backends")
    b.add_argument("--root", default=".", help="Project root directory")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    root = Path(args.root).resolve()

    if args.command == "search":
        orch = MemoryOrchestrator(root=root)
        results = orch.search(
            query=args.query,
            strategy=args.strategy,
            top_k=args.top_k,
            file_filter=args.file_filter,
            type_filter=args.type_filter,
            backends=args.backends,
        )
        if getattr(args, "json_output", False):
            print(json.dumps(results, indent=2))
        else:
            if not results:
                print("No results found.")
                return
            print(f"\nOrchestrated search results for: {args.query!r}")
            print(f"{'=' * 60}")
            for i, r in enumerate(results, 1):
                sources = ", ".join(r.get("sources", []))
                print(f"\n[{i}] {r.get('file_path', '?')}:"
                      f"{r.get('start_line', '?')}-{r.get('end_line', '?')}"
                      f"  rrf={r.get('rrf_score', 0):.4f}"
                      f"  sources=[{sources}]")
                content = r.get("content", "")[:200]
                print(f"    {content.replace(chr(10), chr(10) + '    ')}")
            print()

    elif args.command == "status":
        orch = MemoryOrchestrator(root=root)
        status = orch.status()
        print(json.dumps(status, indent=2))

    elif args.command == "backends":
        orch = MemoryOrchestrator(root=root)
        backends = orch.list_backends()
        print(json.dumps(backends, indent=2))


if __name__ == "__main__":
    main()
