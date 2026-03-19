#!/usr/bin/env python3
"""Cross-platform file locking for project-config.json writes.

Provides atomic, locked writes to JSON configuration files to prevent
race conditions when multiple processes (e.g. parallel agents) write
config simultaneously.

Uses ``fcntl.flock`` on Unix and ``msvcrt.locking`` on Windows.
Includes retry logic for lock contention and atomic write-via-rename
to prevent partial/corrupt writes.

Zero external dependencies — stdlib only.
"""

import json
import logging
import os
import stat
import sys
import tempfile
import time
from pathlib import Path
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

# ── Platform-specific imports ────────────────────────────────────────────────

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import msvcrt
else:
    import fcntl


# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_LOCK_TIMEOUT = 10.0   # seconds
DEFAULT_RETRY_DELAY = 0.05    # seconds between retries
MAX_RETRIES = 3               # max retry attempts for lock acquisition


# ── Exceptions ───────────────────────────────────────────────────────────────

class ConfigLockError(Exception):
    """Raised when a config file lock cannot be acquired."""


# ── Low-level lock primitives ────────────────────────────────────────────────

def _acquire_lock(fd: int) -> bool:
    """Try to acquire an exclusive lock on a file descriptor (non-blocking).

    On Windows, ``msvcrt.locking`` locks exactly 1 byte.  This is
    sufficient because we only lock dedicated ``.lock`` sidecar files
    (never the config files themselves).
    """
    if _IS_WINDOWS:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except (OSError, IOError):
            return False
    else:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (OSError, BlockingIOError):
            return False


def _release_lock(fd: int) -> None:
    """Release a held lock on a file descriptor."""
    if _IS_WINDOWS:
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except (OSError, IOError):
            pass
    else:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass


# ── Lock context manager ────────────────────────────────────────────────────

@contextmanager
def _config_file_lock(
    lock_path: Path,
    timeout: float = DEFAULT_LOCK_TIMEOUT,
    retry_delay: float = DEFAULT_RETRY_DELAY,
):
    """Context manager that acquires an exclusive file lock.

    Creates a ``.lock`` sidecar file next to the target config and holds
    an OS-level exclusive lock on it for the duration of the context.

    Args:
        lock_path: Path to the ``.lock`` file to acquire.
        timeout: Maximum seconds to wait for the lock.
        retry_delay: Seconds between retry attempts.

    Yields:
        None — the lock is held while inside the ``with`` block.

    Raises:
        ConfigLockError: If the lock cannot be acquired within *timeout*.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if _IS_WINDOWS:
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT)
    else:
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)

    fd_closed = False
    try:
        start = time.monotonic()
        while True:
            if _acquire_lock(fd):
                break
            elapsed = time.monotonic() - start
            if elapsed >= timeout:
                os.close(fd)
                fd_closed = True
                raise ConfigLockError(
                    f"Could not acquire config lock on {lock_path} "
                    f"within {timeout}s. Another process may be writing "
                    f"to the config file."
                )
            time.sleep(retry_delay)
        yield
    finally:
        if not fd_closed:
            _release_lock(fd)
            os.close(fd)


# ── Internal helpers ─────────────────────────────────────────────────────────

def _atomic_json_write(config_path: Path, data: dict) -> None:
    """Write *data* as JSON to *config_path* atomically via temp + rename.

    Preserves the original file permissions when the target already exists.
    Must be called while the caller holds the config lock.
    """
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Capture original file permissions so we can restore them after replace.
    original_mode: Optional[int] = None
    try:
        if config_path.exists():
            original_mode = stat.S_IMODE(os.stat(str(config_path)).st_mode)
    except OSError:
        pass

    fd, tmp_path = tempfile.mkstemp(
        dir=str(config_path.parent),
        prefix=".config_tmp_",
        suffix=".json",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, str(config_path))

        # Restore original permissions (os.replace inherits temp-file perms).
        if original_mode is not None:
            try:
                os.chmod(str(config_path), original_mode)
            except OSError:
                pass
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _with_retries(
    config_path: Path,
    operation: str,
    action,
    *,
    timeout: float = DEFAULT_LOCK_TIMEOUT,
    max_retries: int = MAX_RETRIES,
) -> bool:
    """Run *action* under a config lock with retry logic.

    *action* is a callable that receives no arguments and is invoked
    inside the lock context.  It should perform the actual read/write
    and is expected to return ``True`` on success.
    """
    lock_path = config_path.with_suffix(".lock")
    last_error: Optional[Exception] = None

    for attempt in range(max_retries):
        try:
            with _config_file_lock(lock_path, timeout=timeout):
                action()
                return True
        except ConfigLockError as exc:
            last_error = exc
            if attempt < max_retries - 1:
                time.sleep(DEFAULT_RETRY_DELAY * (attempt + 1))
        except (OSError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < max_retries - 1:
                time.sleep(DEFAULT_RETRY_DELAY * (attempt + 1))

    if last_error:
        raise ConfigLockError(
            f"Failed to {operation} {config_path} after {max_retries} "
            f"attempts: {last_error}"
        )
    return False


# ── Public API ───────────────────────────────────────────────────────────────

def locked_config_read(config_path: str | Path) -> dict:
    """Read a JSON config file under an exclusive lock.

    Returns an empty dict if the file does not exist or is unreadable.
    """
    config_path = Path(config_path)
    if not config_path.exists():
        return {}

    lock_path = config_path.with_suffix(".lock")

    with _config_file_lock(lock_path):
        try:
            return json.loads(config_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}


def locked_config_write(
    config_path: str | Path,
    data: dict,
    *,
    timeout: float = DEFAULT_LOCK_TIMEOUT,
    max_retries: int = MAX_RETRIES,
) -> bool:
    """Atomically write a JSON config file under an exclusive lock.

    The write is performed via a temporary file + rename to prevent
    partial writes from corrupting the config on crash.

    Args:
        config_path: Path to the JSON config file.
        data: The dict to serialize as JSON.
        timeout: Maximum seconds to wait for the lock per attempt.
        max_retries: Number of retry attempts if the lock is contended.

    Returns:
        True if the write succeeded, False otherwise.

    Raises:
        ConfigLockError: After exhausting all retries.
    """
    config_path = Path(config_path)

    def _do_write():
        _atomic_json_write(config_path, data)

    return _with_retries(
        config_path, "write", _do_write,
        timeout=timeout, max_retries=max_retries,
    )


def locked_config_update(
    config_path: str | Path,
    update_fn,
    *,
    timeout: float = DEFAULT_LOCK_TIMEOUT,
    max_retries: int = MAX_RETRIES,
) -> bool:
    """Read-modify-write a JSON config file atomically under a lock.

    This is the safest way to update a config file when you need to
    preserve existing keys while changing specific values.

    Args:
        config_path: Path to the JSON config file.
        update_fn: A callable that receives the current config dict
                   and returns the modified dict to write back.
                   Must return a dict; TypeError is raised otherwise.
        timeout: Maximum seconds to wait for the lock per attempt.
        max_retries: Number of retry attempts if the lock is contended.

    Returns:
        True if the update succeeded, False otherwise.
    """
    config_path = Path(config_path)

    def _do_update():
        # Read current config
        current = {}
        if config_path.exists():
            try:
                current = json.loads(
                    config_path.read_text(encoding="utf-8")
                )
            except (json.JSONDecodeError, OSError):
                current = {}

        # Apply the update function and validate the result
        updated = update_fn(current)
        if not isinstance(updated, dict):
            raise TypeError(
                f"update_fn must return a dict, got {type(updated).__name__}"
            )

        _atomic_json_write(config_path, updated)

    return _with_retries(
        config_path, "update", _do_update,
        timeout=timeout, max_retries=max_retries,
    )
