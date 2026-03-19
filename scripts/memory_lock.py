#!/usr/bin/env python3
"""Cross-platform advisory locking for vector memory store writes.

Provides a pluggable ``LockBackend`` abstraction layer with three backends.
Supports per-backend lock files (``vector_store.lock``, ``sqlite_store.lock``,
``rlm_store.lock``) so backends can be written to independently without
blocking each other.

    - ``FileLockBackend`` (default) — file-based advisory locks using
      ``fcntl.flock`` on Unix and ``msvcrt.locking`` on Windows.
    - ``SQLiteLockBackend`` — SQLite WAL-mode advisory locks via
      ``BEGIN EXCLUSIVE`` transactions, portable across networked filesystems.
    - ``RedisLockBackend`` — optional Redis-based distributed locks using
      ``SET NX EX`` pattern with auto-renewal via background thread.

The ``MemoryLock`` context manager wraps the active backend, providing
single-writer / multi-reader semantics when multiple agents share the
same vector store.

Factory function ``create_lock(backend_name, **config)`` returns the
appropriate ``LockBackend`` instance.

Zero external dependencies for file and SQLite backends — stdlib only.
Redis backend requires the optional ``redis`` package.
"""

import os
import re
import sys
import time
import json
import uuid
import sqlite3
import threading
import warnings
from abc import ABC, abstractmethod
from pathlib import Path
from contextlib import contextmanager
from typing import Optional
from urllib.parse import urlparse

# ── Platform-specific imports ────────────────────────────────────────────────

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import msvcrt
else:
    import fcntl


# ── Constants ────────────────────────────────────────────────────────────────

# Relative path — callers must resolve against the *main* repository root
# (not a worktree root) via get_main_repo_root() or _find_project_root().
DEFAULT_LOCK_DIR = ".claude/memory/locks"
DEFAULT_TIMEOUT = 30.0      # seconds
DEFAULT_POLL_INTERVAL = 0.1  # seconds
DEADLOCK_THRESHOLD = 120.0   # seconds — flag potential deadlock
DEFAULT_AUTO_RENEW_INTERVAL = 10.0  # seconds — for Redis auto-renewal


# ── Exceptions ───────────────────────────────────────────────────────────────

class LockTimeoutError(Exception):
    """Raised when a lock cannot be acquired within the timeout period."""


class DeadlockWarning(Exception):
    """Raised when a lock wait exceeds the deadlock threshold."""


# ── Lock State Tracker ───────────────────────────────────────────────────────

class _LockRegistry:
    """Thread-safe registry of currently held locks for deadlock detection."""

    def __init__(self):
        self._held: dict[str, dict] = {}
        self._lock = threading.Lock()

    def register(self, lock_path: str, agent_id: str, acquired_at: float):
        with self._lock:
            self._held[lock_path] = {
                "agent_id": agent_id,
                "acquired_at": acquired_at,
                "pid": os.getpid(),
            }

    def unregister(self, lock_path: str):
        with self._lock:
            self._held.pop(lock_path, None)

    def is_held(self, lock_path: str) -> bool:
        with self._lock:
            return lock_path in self._held

    def held_by(self, lock_path: str) -> Optional[dict]:
        with self._lock:
            return self._held.get(lock_path)

    def all_held(self) -> dict[str, dict]:
        with self._lock:
            return dict(self._held)


_registry = _LockRegistry()


# ── Lock Info File ───────────────────────────────────────────────────────────

def _write_lock_info(lock_path: Path, agent_id: str, session_id: str):
    """Write metadata about who holds the lock."""
    # Temp files: OS tmpdir cleanup handles crash scenarios; explicit cleanup on normal exit
    info_path = lock_path.with_suffix(".info")
    try:
        info = {
            "agent_id": agent_id,
            "session_id": session_id,
            "pid": os.getpid(),
            "acquired_at": time.time(),
            "acquired_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        info_path.write_text(json.dumps(info, indent=2), encoding="utf-8")
    except OSError:
        pass  # Best-effort — lock still functions without info file


def _read_lock_info(lock_path: Path) -> Optional[dict]:
    """Read metadata about who holds the lock."""
    info_path = lock_path.with_suffix(".info")
    if info_path.exists():
        try:
            return json.loads(info_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _clear_lock_info(lock_path: Path):
    """Remove the lock info file."""
    info_path = lock_path.with_suffix(".info")
    try:
        info_path.unlink(missing_ok=True)
    except OSError:
        pass


# ── Abstract Lock Backend ────────────────────────────────────────────────────

class LockBackend(ABC):
    """Abstract base class for lock backends.

    All backends must implement acquire, release, status, and force_release.
    """

    @abstractmethod
    def acquire(self, exclusive: bool = True, timeout: float = DEFAULT_TIMEOUT) -> bool:
        """Acquire the lock.

        Args:
            exclusive: If True, acquire an exclusive (write) lock.
                       If False, acquire a shared (read) lock.
            timeout: Maximum seconds to wait for the lock.

        Returns:
            True if the lock was acquired, False otherwise.

        Raises:
            LockTimeoutError: If the lock could not be acquired within timeout.
        """

    @abstractmethod
    def release(self) -> None:
        """Release the currently held lock."""

    @abstractmethod
    def status(self) -> dict:
        """Return current lock status information.

        Returns a dict with at least:
            - lock_type: backend type name
            - is_held_locally: whether this instance holds the lock
            - holder_info: metadata about the current holder (or None)
            - agent_id: this instance's agent ID
        """

    @abstractmethod
    def force_release(self) -> None:
        """Force-release a stale lock (e.g., from a crashed agent).

        Use with caution -- only when certain the holding agent is dead.
        """


# ── File Lock Backend (default) ──────────────────────────────────────────────

def _acquire_unix(fd: int, exclusive: bool, blocking: bool) -> bool:
    """Acquire a lock on Unix using fcntl.flock."""
    flags = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    if not blocking:
        flags |= fcntl.LOCK_NB
    try:
        fcntl.flock(fd, flags)
        return True
    except (OSError, BlockingIOError):
        return False


def _release_unix(fd: int):
    """Release a lock on Unix."""
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


def _acquire_windows(fd: int, exclusive: bool, blocking: bool) -> bool:
    """Acquire a lock on Windows using msvcrt.locking."""
    mode = msvcrt.LK_NBLCK if not blocking else msvcrt.LK_LOCK
    try:
        msvcrt.locking(fd, mode, 1)
        return True
    except (OSError, IOError):
        return False


def _release_windows(fd: int):
    """Release a lock on Windows."""
    try:
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except (OSError, IOError):
        pass


def _acquire_file_lock(fd: int, exclusive: bool, blocking: bool) -> bool:
    if _IS_WINDOWS:
        return _acquire_windows(fd, exclusive, blocking)
    return _acquire_unix(fd, exclusive, blocking)


def _release_file_lock(fd: int):
    if _IS_WINDOWS:
        _release_windows(fd)
    else:
        _release_unix(fd)


class FileLockBackend(LockBackend):
    """File-based advisory lock backend using fcntl.flock / msvcrt.locking.

    This is the default backend, suitable for single-machine coordination.
    """

    def __init__(
        self,
        store_path: str | Path,
        agent_id: str = "",
        session_id: str = "",
        lock_dir: Optional[str | Path] = None,
        lock_name: str = "vector_store",
        timeout: float = 30.0,
    ):
        self.store_path = Path(store_path).resolve()
        self.agent_id = agent_id or f"agent-{os.getpid()}"
        self.session_id = session_id or ""
        self.timeout = timeout
        self.lock_name = lock_name

        if lock_dir:
            self._lock_dir = Path(lock_dir).resolve()
        else:
            self._lock_dir = self.store_path / ".locks"

        self._lock_dir.mkdir(parents=True, exist_ok=True)
        self._lock_file = self._lock_dir / f"{lock_name}.lock"
        self._fd: Optional[int] = None

    def acquire(self, exclusive: bool = True, timeout: float = DEFAULT_TIMEOUT) -> bool:
        """Acquire the file lock with timeout and deadlock detection."""
        if _IS_WINDOWS:
            self._fd = os.open(str(self._lock_file), os.O_RDWR | os.O_CREAT)
        else:
            flags = os.O_RDWR | os.O_CREAT
            self._fd = os.open(str(self._lock_file), flags, 0o644)

        start = time.monotonic()
        deadlock_warned = False

        while True:
            if _acquire_file_lock(self._fd, exclusive, blocking=False):
                _registry.register(str(self._lock_file), self.agent_id, time.time())
                _write_lock_info(self._lock_file, self.agent_id, self.session_id)
                return True

            elapsed = time.monotonic() - start

            if elapsed > DEADLOCK_THRESHOLD and not deadlock_warned:
                holder = _read_lock_info(self._lock_file)
                holder_desc = ""
                if holder:
                    holder_desc = (
                        f" (held by agent={holder.get('agent_id', '?')}, "
                        f"pid={holder.get('pid', '?')}, "
                        f"since={holder.get('acquired_iso', '?')})"
                    )
                warnings.warn(
                    f"Potential deadlock on {self._lock_file}{holder_desc}. "
                    f"Waiting {elapsed:.0f}s for lock.",
                    stacklevel=3,
                )
                deadlock_warned = True

            if elapsed >= timeout:
                if self._fd is not None:
                    os.close(self._fd)
                    self._fd = None
                holder = _read_lock_info(self._lock_file)
                raise LockTimeoutError(
                    f"Could not acquire {'exclusive' if exclusive else 'shared'} "
                    f"lock on {self._lock_file} within {timeout}s. "
                    f"Holder: {json.dumps(holder) if holder else 'unknown'}"
                )

            time.sleep(DEFAULT_POLL_INTERVAL)

    def release(self) -> None:
        """Release the file lock."""
        if self._fd is not None:
            _release_file_lock(self._fd)
            _registry.unregister(str(self._lock_file))
            _clear_lock_info(self._lock_file)
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None

    def status(self) -> dict:
        """Return current lock status information."""
        holder = _read_lock_info(self._lock_file)
        held = _registry.is_held(str(self._lock_file))
        return {
            "lock_type": "file",
            "lock_file": str(self._lock_file),
            "is_held_locally": held,
            "holder_info": holder,
            "agent_id": self.agent_id,
        }

    def force_release(self) -> None:
        """Force-release a stale file lock."""
        _clear_lock_info(self._lock_file)
        _registry.unregister(str(self._lock_file))
        try:
            self._lock_file.unlink(missing_ok=True)
        except OSError:
            pass


# ── SQLite Lock Backend ──────────────────────────────────────────────────────

class SQLiteLockBackend(LockBackend):
    """SQLite WAL-mode advisory lock backend.

    Uses ``BEGIN EXCLUSIVE`` transactions to provide advisory locking that
    is portable across networked filesystems (NFS, CIFS/SMB) where
    fcntl.flock may not work reliably.

    The lock database is a lightweight SQLite file that stores holder
    metadata alongside the transaction-level lock.
    """

    def __init__(
        self,
        store_path: str | Path,
        agent_id: str = "",
        session_id: str = "",
        sqlite_path: Optional[str | Path] = None,
    ):
        self.store_path = Path(store_path).resolve()
        self.agent_id = agent_id or f"agent-{os.getpid()}"
        self.session_id = session_id or ""

        if sqlite_path:
            self._db_path = Path(sqlite_path).resolve()
        else:
            lock_dir = self.store_path / ".locks"
            lock_dir.mkdir(parents=True, exist_ok=True)
            self._db_path = lock_dir / "lock.db"

        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._held = False
        self._initialize_db()

    def _initialize_db(self):
        """Create the lock table if it doesn't exist."""
        # Permissions: standard umask applies; for shared environments, configure umask externally
        conn = sqlite3.connect(str(self._db_path), timeout=5)
        # WAL permissions: acceptable for single-user CLI; document umask configuration for shared deployments
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lock_holders (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                agent_id TEXT NOT NULL,
                session_id TEXT NOT NULL DEFAULT '',
                pid INTEGER NOT NULL,
                acquired_at REAL NOT NULL,
                acquired_iso TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    def acquire(self, exclusive: bool = True, timeout: float = DEFAULT_TIMEOUT) -> bool:
        """Acquire the SQLite lock via BEGIN EXCLUSIVE transaction."""
        # Prevent connection leak if acquire() is called without release()
        if self._conn is not None and self._held:
            self.release()

        start = time.monotonic()
        deadlock_warned = False

        while True:
            try:
                conn = sqlite3.connect(
                    str(self._db_path),
                    timeout=min(timeout, 5.0),
                    isolation_level=None,
                )
                # WAL mode is persistent (set in _initialize_db), no need
                # to re-set on every acquire.

                if exclusive:
                    conn.execute("BEGIN EXCLUSIVE")
                else:
                    # Shared reads use a normal transaction in WAL mode
                    conn.execute("BEGIN IMMEDIATE")

                # Record holder info
                now = time.time()
                now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
                conn.execute(
                    "INSERT OR REPLACE INTO lock_holders "
                    "(id, agent_id, session_id, pid, acquired_at, acquired_iso) "
                    "VALUES (1, ?, ?, ?, ?, ?)",
                    (self.agent_id, self.session_id, os.getpid(), now, now_iso),
                )

                self._conn = conn
                self._held = True
                _registry.register(str(self._db_path), self.agent_id, now)
                return True

            except sqlite3.OperationalError:
                elapsed = time.monotonic() - start

                if elapsed > DEADLOCK_THRESHOLD and not deadlock_warned:
                    import warnings
                    warnings.warn(
                        f"Potential deadlock on SQLite lock {self._db_path}. "
                        f"Waiting {elapsed:.0f}s for lock.",
                        stacklevel=3,
                    )
                    deadlock_warned = True

                if elapsed >= timeout:
                    raise LockTimeoutError(
                        f"Could not acquire {'exclusive' if exclusive else 'shared'} "
                        f"SQLite lock on {self._db_path} within {timeout}s."
                    )

                time.sleep(DEFAULT_POLL_INTERVAL)

    def release(self) -> None:
        """Release the SQLite lock by committing the transaction."""
        if self._conn is not None and self._held:
            try:
                self._conn.execute(
                    "DELETE FROM lock_holders WHERE id = 1"
                )
                self._conn.execute("COMMIT")
            except sqlite3.OperationalError:
                try:
                    self._conn.execute("ROLLBACK")
                except sqlite3.OperationalError:
                    pass
            finally:
                _registry.unregister(str(self._db_path))
                self._held = False
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def status(self) -> dict:
        """Return current lock status information."""
        holder_info = None
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=2)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM lock_holders WHERE id = 1")
            row = cursor.fetchone()
            if row:
                holder_info = dict(row)
            conn.close()
        except (sqlite3.OperationalError, OSError):
            pass

        return {
            "lock_type": "sqlite",
            "db_path": str(self._db_path),
            "is_held_locally": self._held,
            "holder_info": holder_info,
            "agent_id": self.agent_id,
        }

    def force_release(self) -> None:
        """Force-release the SQLite lock by clearing holder data."""
        try:
            conn = sqlite3.connect(str(self._db_path), timeout=2)
            conn.execute("DELETE FROM lock_holders WHERE id = 1")
            conn.commit()
            conn.close()
        except (sqlite3.OperationalError, OSError):
            pass
        _registry.unregister(str(self._db_path))
        self._held = False
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None


# ── Redis Lock Backend ───────────────────────────────────────────────────────

class RedisLockBackend(LockBackend):
    """Redis-based distributed lock backend.

    Uses the ``SET NX EX`` pattern for distributed mutual exclusion,
    with automatic lock renewal via a background daemon thread to
    prevent premature expiry during long operations.

    Requires the optional ``redis`` package: ``pip install redis``.
    """

    def __init__(
        self,
        store_path: str | Path,
        agent_id: str = "",
        session_id: str = "",
        redis_url: str = "redis://localhost:6379",
        redis_key_prefix: str = "claw:",
        auto_renew_interval: float = DEFAULT_AUTO_RENEW_INTERVAL,
    ):
        self.store_path = Path(store_path).resolve()
        self.agent_id = agent_id or f"agent-{os.getpid()}"
        self.session_id = session_id or ""
        self.redis_url = redis_url
        self.key_prefix = redis_key_prefix
        self.auto_renew_interval = auto_renew_interval

        # Unique token for this lock holder (prevents releasing others' locks)
        self._token = f"{self.agent_id}:{os.getpid()}:{uuid.uuid4().hex[:12]}"
        self._lock_key = f"{self.key_prefix}lock:vector_store"
        self._info_key = f"{self.key_prefix}lock:vector_store:info"
        self._held = False
        self._renew_thread: Optional[threading.Thread] = None
        self._renew_stop = threading.Event()
        self._client = None

    @staticmethod
    def _validate_redis_url(url: str) -> str:
        """Validate and sanitize a Redis connection URL.

        Ensures the URL uses an allowed scheme (redis:// or rediss://) and
        strips embedded credentials from the URL to avoid leaking them in
        status output or logs.

        Raises ValueError for malformed or disallowed URLs.
        """
        parsed = urlparse(url)
        if parsed.scheme not in ("redis", "rediss"):
            raise ValueError(
                f"Invalid Redis URL scheme: {parsed.scheme!r}. "
                f"Only 'redis://' and 'rediss://' are allowed."
            )
        if not parsed.hostname:
            raise ValueError(f"Redis URL must include a hostname: {url!r}")
        return url

    @staticmethod
    def _redact_redis_url(url: str) -> str:
        """Return a redacted version of the Redis URL for safe logging.

        Replaces any password component with '***'.
        """
        parsed = urlparse(url)
        if parsed.password:
            redacted = url.replace(f":{parsed.password}@", ":***@")
            return redacted
        return url

    def _get_client(self):
        """Lazily create the Redis client."""
        if self._client is None:
            try:
                import redis as redis_lib
            except ImportError:
                raise ImportError(
                    "Redis backend requires the 'redis' package. "
                    "Install with: pip install redis"
                )
            self._validate_redis_url(self.redis_url)
            self._client = redis_lib.from_url(self.redis_url, decode_responses=True)
        return self._client

    def _start_renewal(self, ttl: float):
        """Start background thread to auto-renew the lock."""
        self._renew_stop.clear()

        def _renew_loop():
            client = self._get_client()
            # Atomic Lua script: check token ownership and renew both keys
            renew_script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                redis.call("expire", KEYS[1], ARGV[2])
                redis.call("expire", KEYS[2], ARGV[2])
                return 1
            else
                return 0
            end
            """
            while not self._renew_stop.is_set():
                self._renew_stop.wait(timeout=self.auto_renew_interval)
                if self._renew_stop.is_set():
                    break
                try:
                    # Atomically check ownership and renew TTL
                    result = client.eval(
                        renew_script, 2,
                        self._lock_key, self._info_key,
                        self._token, int(ttl),
                    )
                    if result == 0:
                        break  # We no longer hold the lock
                except Exception:
                    break

        self._renew_thread = threading.Thread(
            target=_renew_loop, daemon=True, name="redis-lock-renewal"
        )
        self._renew_thread.start()

    def _stop_renewal(self):
        """Stop the background renewal thread."""
        self._renew_stop.set()
        if self._renew_thread is not None:
            self._renew_thread.join(timeout=2)
            self._renew_thread = None

    def acquire(self, exclusive: bool = True, timeout: float = DEFAULT_TIMEOUT) -> bool:
        """Acquire the Redis lock using SET NX EX pattern.

        Note: Redis locks are always exclusive. The ``exclusive`` parameter
        is accepted for interface compatibility but shared locks are treated
        as exclusive in this backend.
        """
        client = self._get_client()
        ttl = int(max(timeout * 2, 60))  # TTL is 2x timeout, minimum 60s
        start = time.monotonic()
        deadlock_warned = False

        while True:
            acquired = client.set(
                self._lock_key, self._token, nx=True, ex=ttl
            )
            if acquired:
                # Store holder info
                now = time.time()
                info = json.dumps({
                    "agent_id": self.agent_id,
                    "session_id": self.session_id,
                    "pid": os.getpid(),
                    "acquired_at": now,
                    "acquired_iso": time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)
                    ),
                })
                client.set(self._info_key, info, ex=ttl)
                self._held = True
                _registry.register(self._lock_key, self.agent_id, now)
                self._start_renewal(ttl)
                return True

            elapsed = time.monotonic() - start

            if elapsed > DEADLOCK_THRESHOLD and not deadlock_warned:
                warnings.warn(
                    f"Potential deadlock on Redis lock {self._lock_key}. "
                    f"Waiting {elapsed:.0f}s for lock.",
                    stacklevel=3,
                )
                deadlock_warned = True

            if elapsed >= timeout:
                raise LockTimeoutError(
                    f"Could not acquire Redis lock {self._lock_key} "
                    f"within {timeout}s."
                )

            time.sleep(DEFAULT_POLL_INTERVAL)

    def release(self) -> None:
        """Release the Redis lock (only if we hold it)."""
        if not self._held:
            return

        self._stop_renewal()

        try:
            client = self._get_client()
            # Atomically check-and-delete using Lua script
            lua_script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                redis.call("del", KEYS[1])
                redis.call("del", KEYS[2])
                return 1
            else
                return 0
            end
            """
            client.eval(lua_script, 2, self._lock_key, self._info_key, self._token)
        except Exception:
            pass
        finally:
            _registry.unregister(self._lock_key)
            self._held = False

    def status(self) -> dict:
        """Return current lock status information."""
        holder_info = None
        try:
            client = self._get_client()
            info_raw = client.get(self._info_key)
            if info_raw:
                holder_info = json.loads(info_raw)
        except Exception:
            pass

        return {
            "lock_type": "redis",
            "lock_key": self._lock_key,
            "redis_url": self._redact_redis_url(self.redis_url),
            "is_held_locally": self._held,
            "holder_info": holder_info,
            "agent_id": self.agent_id,
        }

    def force_release(self) -> None:
        """Force-release the Redis lock regardless of holder."""
        self._stop_renewal()
        try:
            client = self._get_client()
            client.delete(self._lock_key)
            client.delete(self._info_key)
        except Exception:
            pass
        _registry.unregister(self._lock_key)
        self._held = False


# ── MemoryLock Context Manager ───────────────────────────────────────────────

class MemoryLock:
    """Cross-platform advisory lock for vector memory store operations.

    Wraps a ``LockBackend`` instance and provides context-manager interfaces
    for read (shared) and write (exclusive) locking.

    Usage::

        lock = MemoryLock(store_path, agent_id="agent-001")
        with lock.write():
            # ... exclusive write operations ...

        with lock.read():
            # ... shared read operations ...

    The backend can be specified via the ``backend`` parameter, which
    accepts a pre-configured ``LockBackend`` instance. If not provided,
    a ``FileLockBackend`` is used by default.
    """

    def __init__(
        self,
        store_path: str | Path,
        agent_id: str = "",
        session_id: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        lock_dir: Optional[str | Path] = None,
        backend: Optional[LockBackend] = None,
    ):
        self.store_path = Path(store_path).resolve()
        self.agent_id = agent_id or f"agent-{os.getpid()}"
        self.session_id = session_id or ""
        self.timeout = timeout

        if backend is not None:
            self._backend = backend
        else:
            # Default to file-based locking (backward compatible)
            if lock_dir:
                self._lock_dir = Path(lock_dir).resolve()
            else:
                self._lock_dir = self.store_path / ".locks"

            self._backend = FileLockBackend(
                store_path=store_path,
                agent_id=self.agent_id,
                session_id=self.session_id,
                lock_dir=str(self._lock_dir),
            )

    @contextmanager
    def write(self):
        """Acquire an exclusive (write) lock."""
        self._backend.acquire(exclusive=True, timeout=self.timeout)
        try:
            yield
        finally:
            self._backend.release()

    @contextmanager
    def read(self):
        """Acquire a shared (read) lock."""
        self._backend.acquire(exclusive=False, timeout=self.timeout)
        try:
            yield
        finally:
            self._backend.release()

    def status(self) -> dict:
        """Return current lock status information."""
        return self._backend.status()

    def force_release(self):
        """Force-release a stale lock (e.g., from a crashed agent).

        Use with caution -- only when certain the holding agent is dead.
        """
        self._backend.force_release()


# ── EventLock ────────────────────────────────────────────────────────────────

class EventLock:
    """Lock strategy for event-sourced memory writes.

    Agents use ``EventLock.append()`` (no lock) for writing events to the
    append-only log, and ``EventLock.compact()`` (exclusive lock) for merging
    events into the vector store.  This replaces the per-write exclusive
    locking of ``MemoryLock`` with optimistic concurrency -- multiple agents
    can write simultaneously without blocking.

    Usage::

        elock = EventLock(store_path, agent_id="agent-001")

        with elock.append():
            # ... append events to the log -- no lock held ...

        with elock.compact():
            # ... exclusive lock for merging events into the index ...
    """

    def __init__(
        self,
        store_path: str | Path,
        agent_id: str = "",
        session_id: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        lock_dir: Optional[str | Path] = None,
    ):
        self.agent_id = agent_id or f"agent-{os.getpid()}"
        self.session_id = session_id or ""
        # Delegate to MemoryLock for actual compaction locking
        self._memory_lock = MemoryLock(
            store_path=store_path,
            agent_id=self.agent_id,
            session_id=self.session_id,
            timeout=timeout,
            lock_dir=lock_dir,
        )

    @contextmanager
    def append(self):
        """Context manager for event appends -- no lock is acquired.

        Event appends are lock-free because each agent writes to its own
        segment file using O_APPEND, which is atomic on POSIX.
        """
        yield

    @contextmanager
    def compact(self):
        """Context manager for event compaction -- acquires exclusive lock.

        Only one agent may compact at a time to prevent duplicate
        application of events to the vector store.
        """
        with self._memory_lock.write():
            yield

    def status(self) -> dict:
        """Return lock status for diagnostics."""
        base = self._memory_lock.status()
        base["lock_type"] = "event_lock"
        return base


# ── Backend Factory ──────────────────────────────────────────────────────────

def create_lock(
    backend_name: str = "file",
    store_path: str | Path = "",
    agent_id: str = "",
    session_id: str = "",
    timeout: float = DEFAULT_TIMEOUT,
    **config,
) -> MemoryLock:
    """Create a MemoryLock instance with the specified backend.

    Args:
        backend_name: Backend type — "file" (default), "sqlite", or "redis".
        store_path: Path to the vector store directory.
        agent_id: Identifier for the agent acquiring the lock.
        session_id: Session identifier for the current session.
        timeout: Maximum seconds to wait for lock acquisition.
        **config: Backend-specific configuration:
            - sqlite_path: Path to SQLite lock database (SQLite backend).
            - redis_url: Redis connection URL (Redis backend).
            - redis_key_prefix: Key prefix for Redis keys (Redis backend).
            - auto_renew_interval: Renewal interval in seconds (Redis backend).

    Returns:
        A MemoryLock instance wrapping the chosen backend.

    Raises:
        ValueError: If backend_name is not recognized.
        ImportError: If Redis backend is selected but ``redis`` is not installed.
    """
    backend_name = backend_name.lower().strip()

    if backend_name == "file":
        backend = FileLockBackend(
            store_path=store_path,
            agent_id=agent_id,
            session_id=session_id,
            lock_dir=config.get("lock_dir"),
        )
    elif backend_name == "sqlite":
        backend = SQLiteLockBackend(
            store_path=store_path,
            agent_id=agent_id,
            session_id=session_id,
            sqlite_path=config.get("sqlite_path"),
        )
    elif backend_name == "redis":
        backend = RedisLockBackend(
            store_path=store_path,
            agent_id=agent_id,
            session_id=session_id,
            redis_url=config.get("redis_url", "redis://localhost:6379"),
            redis_key_prefix=config.get("redis_key_prefix", "claw:"),
            auto_renew_interval=config.get(
                "auto_renew_interval", DEFAULT_AUTO_RENEW_INTERVAL
            ),
        )
    else:
        raise ValueError(
            f"Unknown lock backend: {backend_name!r}. "
            f"Supported backends: file, sqlite, redis."
        )

    return MemoryLock(
        store_path=store_path,
        agent_id=agent_id,
        session_id=session_id,
        timeout=timeout,
        backend=backend,
    )


# ── Convenience Functions ────────────────────────────────────────────────────

def list_active_locks(store_path: str | Path) -> list[dict]:
    """List all active locks in the store's lock directory."""
    lock_dir = Path(store_path).resolve() / ".locks"
    active = []
    if lock_dir.exists():
        for info_file in lock_dir.glob("*.info"):
            try:
                info = json.loads(info_file.read_text(encoding="utf-8"))
                info["lock_file"] = str(info_file.with_suffix(".lock"))
                active.append(info)
            except (json.JSONDecodeError, OSError):
                pass
    return active


def cleanup_stale_locks(store_path: str | Path, max_age_seconds: float = 3600.0) -> int:
    """Remove lock info files older than max_age_seconds.

    Returns the number of stale locks cleaned up.
    """
    lock_dir = Path(store_path).resolve() / ".locks"
    cleaned = 0
    if lock_dir.exists():
        now = time.time()
        for info_file in lock_dir.glob("*.info"):
            try:
                info = json.loads(info_file.read_text(encoding="utf-8"))
                acquired = info.get("acquired_at", 0)
                if now - acquired > max_age_seconds:
                    info_file.unlink(missing_ok=True)
                    lock_file = info_file.with_suffix(".lock")
                    lock_file.unlink(missing_ok=True)
                    cleaned += 1
            except (json.JSONDecodeError, OSError):
                # Corrupt info file — remove it
                try:
                    info_file.unlink(missing_ok=True)
                    cleaned += 1
                except OSError:
                    pass
    return cleaned


# ── Per-Backend Lock Factories ──────────────────────────────────────────────

# Standard lock names for each memory backend
BACKEND_LOCK_NAMES = {
    "lancedb": "vector_store",
    "sqlite": "sqlite_store",
    "rlm": "rlm_store",
}


def create_backend_lock(
    store_path: str | Path,
    backend: str,
    agent_id: str = "",
    session_id: str = "",
    timeout: float = DEFAULT_TIMEOUT,
) -> MemoryLock:
    """Create a MemoryLock scoped to a specific memory backend.

    Each backend gets its own lock file so backends can be written to
    independently without blocking each other.

    Args:
        store_path: Path to the memory store directory.
        backend: Backend name ('lancedb', 'sqlite', 'rlm').
        agent_id: Agent identifier for lock info.
        session_id: Session identifier for lock info.
        timeout: Lock acquisition timeout in seconds.

    Returns:
        MemoryLock instance with the appropriate per-backend lock file.

    Raises:
        ValueError: If backend name is not recognized.
    """
    lock_name = BACKEND_LOCK_NAMES.get(backend)
    if lock_name is None:
        raise ValueError(
            f"Unknown backend {backend!r}. "
            f"Supported: {', '.join(BACKEND_LOCK_NAMES.keys())}"
        )
    return MemoryLock(
        store_path=store_path,
        agent_id=agent_id,
        session_id=session_id,
        timeout=timeout,
        lock_name=lock_name,
    )
