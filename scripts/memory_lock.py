#!/usr/bin/env python3
"""Cross-platform advisory locking for vector memory store writes.

Provides a ``MemoryLock`` context manager that wraps file-based advisory
locks around memory backend write operations, ensuring single-writer /
multi-reader semantics when multiple agents share the same store.

Supports per-backend lock files (``vector_store.lock``, ``sqlite_store.lock``,
``rlm_store.lock``) so backends can be written to independently without
blocking each other.

Uses ``fcntl.flock`` on Unix and ``msvcrt.locking`` on Windows.

Zero external dependencies — stdlib only.
"""

import os
import sys
import time
import json
import threading
from pathlib import Path
from contextlib import contextmanager
from typing import Optional

# ── Platform-specific imports ────────────────────────────────────────────────

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import msvcrt
else:
    import fcntl


# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_LOCK_DIR = ".claude/memory/locks"
DEFAULT_TIMEOUT = 30.0      # seconds
DEFAULT_POLL_INTERVAL = 0.1  # seconds
DEADLOCK_THRESHOLD = 120.0   # seconds — flag potential deadlock


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


# ── Core Lock Implementation ────────────────────────────────────────────────

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


def _acquire_lock(fd: int, exclusive: bool, blocking: bool) -> bool:
    if _IS_WINDOWS:
        return _acquire_windows(fd, exclusive, blocking)
    return _acquire_unix(fd, exclusive, blocking)


def _release_lock(fd: int):
    if _IS_WINDOWS:
        _release_windows(fd)
    else:
        _release_unix(fd)


# ── MemoryLock Context Manager ───────────────────────────────────────────────

class MemoryLock:
    """Cross-platform advisory lock for vector memory store operations.

    Usage::

        lock = MemoryLock(store_path, agent_id="agent-001")
        with lock.write():
            # ... exclusive write operations ...

        with lock.read():
            # ... shared read operations ...
    """

    def __init__(
        self,
        store_path: str | Path,
        agent_id: str = "",
        session_id: str = "",
        timeout: float = DEFAULT_TIMEOUT,
        lock_dir: Optional[str | Path] = None,
        lock_name: str = "vector_store",
    ):
        self.store_path = Path(store_path).resolve()
        self.agent_id = agent_id or f"agent-{os.getpid()}"
        self.session_id = session_id or ""
        self.timeout = timeout
        self.lock_name = lock_name

        # Determine lock directory
        if lock_dir:
            self._lock_dir = Path(lock_dir).resolve()
        else:
            # Place locks next to the store
            self._lock_dir = self.store_path / ".locks"

        self._lock_dir.mkdir(parents=True, exist_ok=True)
        self._lock_file = self._lock_dir / f"{lock_name}.lock"
        self._fd: Optional[int] = None

    @contextmanager
    def write(self):
        """Acquire an exclusive (write) lock."""
        self._acquire(exclusive=True)
        try:
            yield
        finally:
            self._release()

    @contextmanager
    def read(self):
        """Acquire a shared (read) lock."""
        self._acquire(exclusive=False)
        try:
            yield
        finally:
            self._release()

    def _acquire(self, exclusive: bool):
        """Acquire the lock with timeout and deadlock detection."""
        # Open (and atomically create) the lock file — O_CREAT handles
        # creation so no separate exists()/touch() is needed, avoiding
        # a TOCTOU race between the check and the open.
        if _IS_WINDOWS:
            self._fd = os.open(str(self._lock_file), os.O_RDWR | os.O_CREAT)
        else:
            flags = os.O_RDWR | os.O_CREAT
            self._fd = os.open(str(self._lock_file), flags, 0o644)

        start = time.monotonic()
        deadlock_warned = False

        while True:
            if _acquire_lock(self._fd, exclusive, blocking=False):
                # Lock acquired
                _registry.register(str(self._lock_file), self.agent_id, time.time())
                _write_lock_info(self._lock_file, self.agent_id, self.session_id)
                return

            elapsed = time.monotonic() - start

            # Deadlock detection
            if elapsed > DEADLOCK_THRESHOLD and not deadlock_warned:
                holder = _read_lock_info(self._lock_file)
                holder_desc = ""
                if holder:
                    holder_desc = (
                        f" (held by agent={holder.get('agent_id', '?')}, "
                        f"pid={holder.get('pid', '?')}, "
                        f"since={holder.get('acquired_iso', '?')})"
                    )
                import warnings
                warnings.warn(
                    f"Potential deadlock on {self._lock_file}{holder_desc}. "
                    f"Waiting {elapsed:.0f}s for lock.",
                    stacklevel=3,
                )
                deadlock_warned = True

            # Timeout check
            if elapsed >= self.timeout:
                if self._fd is not None:
                    os.close(self._fd)
                    self._fd = None
                holder = _read_lock_info(self._lock_file)
                raise LockTimeoutError(
                    f"Could not acquire {'exclusive' if exclusive else 'shared'} "
                    f"lock on {self._lock_file} within {self.timeout}s. "
                    f"Holder: {json.dumps(holder) if holder else 'unknown'}"
                )

            time.sleep(DEFAULT_POLL_INTERVAL)

    def _release(self):
        """Release the lock."""
        if self._fd is not None:
            _release_lock(self._fd)
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
            "lock_file": str(self._lock_file),
            "is_held_locally": held,
            "holder_info": holder,
            "agent_id": self.agent_id,
        }

    def force_release(self):
        """Force-release a stale lock (e.g., from a crashed agent).

        Use with caution — only when certain the holding agent is dead.
        """
        _clear_lock_info(self._lock_file)
        _registry.unregister(str(self._lock_file))
        try:
            self._lock_file.unlink(missing_ok=True)
        except OSError:
            pass


# ── Convenience Functions ────────────────────────────────────────────────────

def create_lock(
    store_path: str | Path,
    agent_id: str = "",
    session_id: str = "",
    timeout: float = DEFAULT_TIMEOUT,
) -> MemoryLock:
    """Create a MemoryLock instance for the given store path."""
    return MemoryLock(
        store_path=store_path,
        agent_id=agent_id,
        session_id=session_id,
        timeout=timeout,
    )


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
