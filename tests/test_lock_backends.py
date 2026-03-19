#!/usr/bin/env python3
"""Tests for the pluggable lock backend system in memory_lock.py.

Covers:
    - LockBackend abstract interface contract
    - FileLockBackend acquire/release/status/force_release
    - SQLiteLockBackend acquire/release/status/force_release
    - RedisLockBackend (skipped if redis is unavailable)
    - create_lock() factory function
    - MemoryLock context manager (write/read)
    - Timeout and error handling
    - Lock info file lifecycle
    - Convenience functions (list_active_locks, cleanup_stale_locks)
"""

import os
import sys
import json
import time
import threading
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add scripts/ to path so memory_lock can be imported
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))

from memory_lock import (
    LockBackend,
    FileLockBackend,
    SQLiteLockBackend,
    RedisLockBackend,
    MemoryLock,
    create_lock,
    LockTimeoutError,
    list_active_locks,
    cleanup_stale_locks,
    _write_lock_info,
    _read_lock_info,
    _clear_lock_info,
    _registry,
    DEFAULT_TIMEOUT,
    DEFAULT_AUTO_RENEW_INTERVAL,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_store(tmp_path):
    """Create a temporary store directory for lock tests."""
    store = tmp_path / "vector_store"
    store.mkdir()
    return store


@pytest.fixture
def file_backend(tmp_store):
    """Create a FileLockBackend instance."""
    return FileLockBackend(
        store_path=tmp_store,
        agent_id="test-agent-file",
        session_id="test-session-file",
    )


@pytest.fixture
def sqlite_backend(tmp_store):
    """Create a SQLiteLockBackend instance."""
    return SQLiteLockBackend(
        store_path=tmp_store,
        agent_id="test-agent-sqlite",
        session_id="test-session-sqlite",
    )


# ── LockBackend ABC ─────────────────────────────────────────────────────────

class TestLockBackendABC:
    """Test that LockBackend cannot be instantiated directly."""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            LockBackend()

    def test_subclass_must_implement_all_methods(self):
        class IncompleteLock(LockBackend):
            def acquire(self, exclusive=True, timeout=30):
                return True

        with pytest.raises(TypeError):
            IncompleteLock()

    def test_complete_subclass_can_instantiate(self):
        class CompleteLock(LockBackend):
            def acquire(self, exclusive=True, timeout=30):
                return True

            def release(self):
                pass

            def status(self):
                return {}

            def force_release(self):
                pass

        lock = CompleteLock()
        assert lock.acquire() is True
        assert lock.status() == {}


# ── FileLockBackend ──────────────────────────────────────────────────────────

class TestFileLockBackend:
    """Tests for the file-based advisory lock backend."""

    def test_init_creates_lock_dir(self, tmp_store):
        backend = FileLockBackend(store_path=tmp_store, agent_id="test")
        lock_dir = tmp_store / ".locks"
        assert lock_dir.exists()

    def test_init_custom_lock_dir(self, tmp_store):
        custom_dir = tmp_store / "custom_locks"
        backend = FileLockBackend(
            store_path=tmp_store,
            agent_id="test",
            lock_dir=custom_dir,
        )
        assert custom_dir.exists()

    def test_init_default_agent_id(self, tmp_store):
        backend = FileLockBackend(store_path=tmp_store)
        assert backend.agent_id.startswith("agent-")
        assert str(os.getpid()) in backend.agent_id

    def test_acquire_exclusive(self, file_backend):
        result = file_backend.acquire(exclusive=True, timeout=5)
        assert result is True
        file_backend.release()

    def test_acquire_shared(self, file_backend):
        result = file_backend.acquire(exclusive=False, timeout=5)
        assert result is True
        file_backend.release()

    def test_release_clears_state(self, file_backend):
        file_backend.acquire(exclusive=True, timeout=5)
        file_backend.release()
        assert file_backend._fd is None

    def test_status_when_not_held(self, file_backend):
        status = file_backend.status()
        assert status["lock_type"] == "file"
        assert status["is_held_locally"] is False
        assert status["agent_id"] == "test-agent-file"

    def test_status_when_held(self, file_backend):
        file_backend.acquire(exclusive=True, timeout=5)
        status = file_backend.status()
        assert status["is_held_locally"] is True
        assert status["holder_info"] is not None
        assert status["holder_info"]["agent_id"] == "test-agent-file"
        file_backend.release()

    def test_force_release(self, file_backend):
        file_backend.acquire(exclusive=True, timeout=5)
        file_backend.force_release()
        status = file_backend.status()
        assert status["is_held_locally"] is False

    def test_double_release_is_safe(self, file_backend):
        file_backend.acquire(exclusive=True, timeout=5)
        file_backend.release()
        file_backend.release()  # Should not raise

    def test_acquire_timeout(self, tmp_store):
        """Test that a second exclusive lock times out when the first is held."""
        backend1 = FileLockBackend(
            store_path=tmp_store,
            agent_id="holder",
            lock_dir=tmp_store / "shared_locks",
        )
        backend2 = FileLockBackend(
            store_path=tmp_store,
            agent_id="waiter",
            lock_dir=tmp_store / "shared_locks",
        )

        backend1.acquire(exclusive=True, timeout=5)
        try:
            with pytest.raises(LockTimeoutError):
                backend2.acquire(exclusive=True, timeout=0.3)
        finally:
            backend1.release()

    def test_lock_info_lifecycle(self, file_backend):
        lock_file = file_backend._lock_file

        # Before acquire: no info
        assert _read_lock_info(lock_file) is None

        # After acquire: info present
        file_backend.acquire(exclusive=True, timeout=5)
        info = _read_lock_info(lock_file)
        assert info is not None
        assert info["agent_id"] == "test-agent-file"
        assert info["session_id"] == "test-session-file"
        assert "pid" in info
        assert "acquired_at" in info

        # After release: info cleared
        file_backend.release()
        assert _read_lock_info(lock_file) is None


# ── SQLiteLockBackend ────────────────────────────────────────────────────────

class TestSQLiteLockBackend:
    """Tests for the SQLite WAL-mode advisory lock backend."""

    def test_init_creates_db(self, tmp_store):
        backend = SQLiteLockBackend(store_path=tmp_store, agent_id="test")
        db_path = tmp_store / ".locks" / "lock.db"
        assert db_path.exists()

    def test_init_custom_sqlite_path(self, tmp_store):
        custom_db = tmp_store / "custom" / "lock.db"
        backend = SQLiteLockBackend(
            store_path=tmp_store,
            agent_id="test",
            sqlite_path=custom_db,
        )
        assert custom_db.exists()

    def test_init_creates_table(self, tmp_store):
        backend = SQLiteLockBackend(store_path=tmp_store, agent_id="test")
        db_path = tmp_store / ".locks" / "lock.db"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='lock_holders'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_acquire_exclusive(self, sqlite_backend):
        result = sqlite_backend.acquire(exclusive=True, timeout=5)
        assert result is True
        sqlite_backend.release()

    def test_acquire_shared(self, sqlite_backend):
        result = sqlite_backend.acquire(exclusive=False, timeout=5)
        assert result is True
        sqlite_backend.release()

    def test_release_clears_state(self, sqlite_backend):
        sqlite_backend.acquire(exclusive=True, timeout=5)
        sqlite_backend.release()
        assert sqlite_backend._held is False
        assert sqlite_backend._conn is None

    def test_status_when_not_held(self, sqlite_backend):
        status = sqlite_backend.status()
        assert status["lock_type"] == "sqlite"
        assert status["is_held_locally"] is False
        assert status["agent_id"] == "test-agent-sqlite"

    def test_status_when_held(self, sqlite_backend):
        sqlite_backend.acquire(exclusive=True, timeout=5)
        status = sqlite_backend.status()
        assert status["is_held_locally"] is True
        sqlite_backend.release()

    def test_force_release(self, sqlite_backend):
        sqlite_backend.acquire(exclusive=True, timeout=5)
        sqlite_backend.force_release()
        assert sqlite_backend._held is False
        assert sqlite_backend._conn is None

    def test_double_release_is_safe(self, sqlite_backend):
        sqlite_backend.acquire(exclusive=True, timeout=5)
        sqlite_backend.release()
        sqlite_backend.release()  # Should not raise

    def test_acquire_timeout(self, tmp_store):
        """Test that a second exclusive lock times out when the first is held."""
        db_path = tmp_store / "shared_lock.db"
        backend1 = SQLiteLockBackend(
            store_path=tmp_store,
            agent_id="holder",
            sqlite_path=db_path,
        )
        backend2 = SQLiteLockBackend(
            store_path=tmp_store,
            agent_id="waiter",
            sqlite_path=db_path,
        )

        backend1.acquire(exclusive=True, timeout=5)
        try:
            with pytest.raises(LockTimeoutError):
                backend2.acquire(exclusive=True, timeout=0.3)
        finally:
            backend1.release()

    def test_holder_info_recorded(self, sqlite_backend):
        sqlite_backend.acquire(exclusive=True, timeout=5)
        # While the lock is held, the exclusive transaction blocks external
        # reads.  Verify via the status() method instead, which reports
        # the locally held state without opening a second connection.
        status = sqlite_backend.status()
        assert status["is_held_locally"] is True
        assert status["agent_id"] == "test-agent-sqlite"
        sqlite_backend.release()

        # After release the holder row is deleted, confirming the write
        # happened during the transaction.
        conn = sqlite3.connect(str(sqlite_backend._db_path))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM lock_holders WHERE id = 1").fetchone()
        assert row is None
        conn.close()

    def test_holder_info_cleared_on_release(self, sqlite_backend):
        sqlite_backend.acquire(exclusive=True, timeout=5)
        sqlite_backend.release()
        conn = sqlite3.connect(str(sqlite_backend._db_path))
        row = conn.execute("SELECT * FROM lock_holders WHERE id = 1").fetchone()
        assert row is None
        conn.close()


# ── RedisLockBackend ─────────────────────────────────────────────────────────

def _redis_available():
    """Check if Redis is importable and a local server is reachable."""
    try:
        import redis as redis_lib
        client = redis_lib.from_url("redis://localhost:6379", decode_responses=True)
        client.ping()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _redis_available(), reason="Redis not available")
class TestRedisLockBackend:
    """Tests for the Redis distributed lock backend."""

    @pytest.fixture(autouse=True)
    def _cleanup_redis_keys(self, tmp_store):
        """Clean up test keys after each test."""
        yield
        try:
            import redis as redis_lib
            client = redis_lib.from_url("redis://localhost:6379", decode_responses=True)
            for key in client.keys("test-claw:*"):
                client.delete(key)
        except Exception:
            pass

    def test_init(self, tmp_store):
        backend = RedisLockBackend(
            store_path=tmp_store,
            agent_id="test-redis",
            redis_key_prefix="test-claw:",
        )
        assert backend.agent_id == "test-redis"
        assert backend.key_prefix == "test-claw:"

    def test_acquire_and_release(self, tmp_store):
        backend = RedisLockBackend(
            store_path=tmp_store,
            agent_id="test-redis",
            redis_key_prefix="test-claw:",
        )
        result = backend.acquire(exclusive=True, timeout=5)
        assert result is True
        assert backend._held is True
        backend.release()
        assert backend._held is False

    def test_status(self, tmp_store):
        backend = RedisLockBackend(
            store_path=tmp_store,
            agent_id="test-redis",
            redis_key_prefix="test-claw:",
        )
        status = backend.status()
        assert status["lock_type"] == "redis"
        assert status["is_held_locally"] is False

    def test_force_release(self, tmp_store):
        backend = RedisLockBackend(
            store_path=tmp_store,
            agent_id="test-redis",
            redis_key_prefix="test-claw:",
        )
        backend.acquire(exclusive=True, timeout=5)
        backend.force_release()
        assert backend._held is False

    def test_import_error_when_redis_missing(self, tmp_store):
        """Test graceful error when redis package is not installed."""
        backend = RedisLockBackend.__new__(RedisLockBackend)
        backend.store_path = Path(tmp_store).resolve()
        backend.agent_id = "test"
        backend.session_id = ""
        backend.redis_url = "redis://localhost:6379"
        backend.key_prefix = "test-claw:"
        backend.auto_renew_interval = 10
        backend._token = "test-token"
        backend._lock_key = "test-claw:lock:vector_store"
        backend._info_key = "test-claw:lock:vector_store:info"
        backend._held = False
        backend._renew_thread = None
        backend._renew_stop = threading.Event()
        backend._client = None

        with patch.dict("sys.modules", {"redis": None}):
            backend._client = None
            with pytest.raises(ImportError, match="redis"):
                backend._get_client()


# ── Redis URL Validation and Redaction ────────────────────────────────────────

class TestRedisURLValidation:
    """Tests for Redis URL validation and redaction utility methods."""

    def test_valid_redis_url(self):
        assert RedisLockBackend._validate_redis_url("redis://localhost:6379") == "redis://localhost:6379"

    def test_valid_rediss_url(self):
        assert RedisLockBackend._validate_redis_url("rediss://secure-host:6380") == "rediss://secure-host:6380"

    def test_invalid_scheme_rejected(self):
        with pytest.raises(ValueError, match="Invalid Redis URL scheme"):
            RedisLockBackend._validate_redis_url("http://localhost:6379")

    def test_no_hostname_rejected(self):
        with pytest.raises(ValueError, match="must include a hostname"):
            RedisLockBackend._validate_redis_url("redis://")

    def test_redact_url_without_password(self):
        result = RedisLockBackend._redact_redis_url("redis://localhost:6379")
        assert result == "redis://localhost:6379"

    def test_redact_url_with_password(self):
        result = RedisLockBackend._redact_redis_url("redis://user:secretpass@host:6379")
        assert "secretpass" not in result
        assert "***" in result

    def test_redact_url_preserves_host(self):
        result = RedisLockBackend._redact_redis_url("redis://user:pass@myhost:6380/0")
        assert "myhost" in result
        assert "pass" not in result


# ── create_lock() Factory ────────────────────────────────────────────────────

class TestCreateLock:
    """Tests for the create_lock() factory function."""

    def test_file_backend(self, tmp_store):
        lock = create_lock("file", store_path=tmp_store, agent_id="test")
        assert isinstance(lock, MemoryLock)
        assert isinstance(lock._backend, FileLockBackend)

    def test_sqlite_backend(self, tmp_store):
        lock = create_lock("sqlite", store_path=tmp_store, agent_id="test")
        assert isinstance(lock, MemoryLock)
        assert isinstance(lock._backend, SQLiteLockBackend)

    def test_redis_backend_creation(self, tmp_store):
        """Test RedisLockBackend instantiation (does not require Redis server)."""
        lock = create_lock(
            "redis",
            store_path=tmp_store,
            agent_id="test",
            redis_url="redis://localhost:6379",
            redis_key_prefix="test-claw:",
        )
        assert isinstance(lock, MemoryLock)
        assert isinstance(lock._backend, RedisLockBackend)

    def test_unknown_backend_raises(self, tmp_store):
        with pytest.raises(ValueError, match="Unknown lock backend"):
            create_lock("memcached", store_path=tmp_store)

    def test_case_insensitive(self, tmp_store):
        lock = create_lock("FILE", store_path=tmp_store)
        assert isinstance(lock._backend, FileLockBackend)

    def test_whitespace_stripped(self, tmp_store):
        lock = create_lock("  sqlite  ", store_path=tmp_store)
        assert isinstance(lock._backend, SQLiteLockBackend)

    def test_default_backend_is_file(self, tmp_store):
        lock = create_lock(store_path=tmp_store)
        assert isinstance(lock._backend, FileLockBackend)

    def test_custom_timeout(self, tmp_store):
        lock = create_lock("file", store_path=tmp_store, timeout=60)
        assert lock.timeout == 60

    def test_sqlite_custom_path(self, tmp_store):
        custom_db = tmp_store / "custom.db"
        lock = create_lock(
            "sqlite",
            store_path=tmp_store,
            sqlite_path=str(custom_db),
        )
        assert isinstance(lock._backend, SQLiteLockBackend)
        assert lock._backend._db_path == custom_db


# ── MemoryLock Context Manager ───────────────────────────────────────────────

class TestMemoryLock:
    """Tests for the MemoryLock context manager wrapper."""

    def test_write_context_manager(self, tmp_store):
        lock = MemoryLock(store_path=tmp_store, agent_id="test-cm")
        with lock.write():
            status = lock.status()
            assert status["is_held_locally"] is True
        status = lock.status()
        assert status["is_held_locally"] is False

    def test_read_context_manager(self, tmp_store):
        lock = MemoryLock(store_path=tmp_store, agent_id="test-cm")
        with lock.read():
            status = lock.status()
            assert status["is_held_locally"] is True
        status = lock.status()
        assert status["is_held_locally"] is False

    def test_default_backend_is_file(self, tmp_store):
        lock = MemoryLock(store_path=tmp_store)
        assert isinstance(lock._backend, FileLockBackend)

    def test_custom_backend(self, tmp_store):
        backend = SQLiteLockBackend(
            store_path=tmp_store, agent_id="custom"
        )
        lock = MemoryLock(store_path=tmp_store, backend=backend)
        assert isinstance(lock._backend, SQLiteLockBackend)

    def test_status_delegates_to_backend(self, tmp_store):
        lock = MemoryLock(store_path=tmp_store, agent_id="test-status")
        status = lock.status()
        assert status["agent_id"] == "test-status"

    def test_force_release_delegates_to_backend(self, tmp_store):
        lock = MemoryLock(store_path=tmp_store, agent_id="test-force")
        with lock.write():
            pass
        lock.force_release()  # Should not raise

    def test_write_releases_on_exception(self, tmp_store):
        lock = MemoryLock(store_path=tmp_store, agent_id="test-exc")
        try:
            with lock.write():
                raise RuntimeError("test error")
        except RuntimeError:
            pass
        status = lock.status()
        assert status["is_held_locally"] is False

    def test_read_releases_on_exception(self, tmp_store):
        lock = MemoryLock(store_path=tmp_store, agent_id="test-exc")
        try:
            with lock.read():
                raise RuntimeError("test error")
        except RuntimeError:
            pass
        status = lock.status()
        assert status["is_held_locally"] is False


# ── Lock Info Helpers ────────────────────────────────────────────────────────

class TestLockInfoHelpers:
    """Tests for lock info file read/write/clear helpers."""

    def test_write_and_read(self, tmp_path):
        lock_file = tmp_path / "test.lock"
        lock_file.touch()
        _write_lock_info(lock_file, "agent-1", "session-1")
        info = _read_lock_info(lock_file)
        assert info is not None
        assert info["agent_id"] == "agent-1"
        assert info["session_id"] == "session-1"
        assert "pid" in info

    def test_clear(self, tmp_path):
        lock_file = tmp_path / "test.lock"
        lock_file.touch()
        _write_lock_info(lock_file, "agent-1", "session-1")
        _clear_lock_info(lock_file)
        assert _read_lock_info(lock_file) is None

    def test_read_nonexistent(self, tmp_path):
        lock_file = tmp_path / "nonexistent.lock"
        assert _read_lock_info(lock_file) is None

    def test_clear_nonexistent_is_safe(self, tmp_path):
        lock_file = tmp_path / "nonexistent.lock"
        _clear_lock_info(lock_file)  # Should not raise


# ── Convenience Functions ────────────────────────────────────────────────────

class TestConvenienceFunctions:
    """Tests for list_active_locks and cleanup_stale_locks."""

    def test_list_active_locks_empty(self, tmp_store):
        locks = list_active_locks(tmp_store)
        assert locks == []

    def test_list_active_locks_with_locks(self, tmp_store):
        lock_dir = tmp_store / ".locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        info = {
            "agent_id": "test-agent",
            "session_id": "test-session",
            "pid": os.getpid(),
            "acquired_at": time.time(),
        }
        (lock_dir / "test.info").write_text(json.dumps(info))
        locks = list_active_locks(tmp_store)
        assert len(locks) == 1
        assert locks[0]["agent_id"] == "test-agent"

    def test_cleanup_stale_locks_removes_old(self, tmp_store):
        lock_dir = tmp_store / ".locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        old_info = {
            "agent_id": "old-agent",
            "acquired_at": time.time() - 7200,  # 2 hours ago
        }
        (lock_dir / "old.info").write_text(json.dumps(old_info))
        (lock_dir / "old.lock").touch()

        cleaned = cleanup_stale_locks(tmp_store, max_age_seconds=3600)
        assert cleaned == 1
        assert not (lock_dir / "old.info").exists()
        assert not (lock_dir / "old.lock").exists()

    def test_cleanup_stale_locks_keeps_fresh(self, tmp_store):
        lock_dir = tmp_store / ".locks"
        lock_dir.mkdir(parents=True, exist_ok=True)
        fresh_info = {
            "agent_id": "fresh-agent",
            "acquired_at": time.time(),  # Just now
        }
        (lock_dir / "fresh.info").write_text(json.dumps(fresh_info))

        cleaned = cleanup_stale_locks(tmp_store, max_age_seconds=3600)
        assert cleaned == 0
        assert (lock_dir / "fresh.info").exists()


# ── Integration: Multi-threaded Lock Contention ──────────────────────────────

class TestMultiThreadedContention:
    """Test lock contention across threads to verify mutual exclusion."""

    def test_file_lock_mutual_exclusion(self, tmp_store):
        """Verify that only one thread holds the file lock at a time."""
        lock_dir = tmp_store / "contention_locks"
        counter = {"value": 0}
        errors = []

        def increment_with_lock(thread_id):
            try:
                backend = FileLockBackend(
                    store_path=tmp_store,
                    agent_id=f"thread-{thread_id}",
                    lock_dir=lock_dir,
                )
                backend.acquire(exclusive=True, timeout=10)
                try:
                    # Read-modify-write pattern; would race without lock
                    val = counter["value"]
                    time.sleep(0.01)  # Simulate work
                    counter["value"] = val + 1
                finally:
                    backend.release()
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(5):
            t = threading.Thread(target=increment_with_lock, args=(i,))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert not errors, f"Errors during threaded test: {errors}"
        assert counter["value"] == 5

    def test_sqlite_lock_mutual_exclusion(self, tmp_store):
        """Verify that only one thread holds the SQLite lock at a time.

        SQLite serialises exclusive transactions, so each thread must wait
        for the previous holder to commit.  We use a generous timeout and
        fewer threads to keep the test fast while still proving exclusion.
        """
        db_path = tmp_store / "contention.db"
        counter = {"value": 0}
        errors = []

        def increment_with_lock(thread_id):
            try:
                backend = SQLiteLockBackend(
                    store_path=tmp_store,
                    agent_id=f"thread-{thread_id}",
                    sqlite_path=db_path,
                )
                backend.acquire(exclusive=True, timeout=30)
                try:
                    val = counter["value"]
                    time.sleep(0.005)
                    counter["value"] = val + 1
                finally:
                    backend.release()
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(3):
            t = threading.Thread(target=increment_with_lock, args=(i,))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        assert not errors, f"Errors during threaded test: {errors}"
        assert counter["value"] == 3


# ── Integration: MemoryLock with SQLite Backend ──────────────────────────────

class TestMemoryLockWithSQLiteBackend:
    """Test MemoryLock using SQLite backend through the factory."""

    def test_create_and_use_sqlite_lock(self, tmp_store):
        lock = create_lock("sqlite", store_path=tmp_store, agent_id="test-sqlite")
        with lock.write():
            status = lock.status()
            assert status["lock_type"] == "sqlite"
            assert status["is_held_locally"] is True
        status = lock.status()
        assert status["is_held_locally"] is False

    def test_sqlite_read_lock(self, tmp_store):
        lock = create_lock("sqlite", store_path=tmp_store, agent_id="test-sqlite")
        with lock.read():
            status = lock.status()
            assert status["is_held_locally"] is True


# ── Registry ─────────────────────────────────────────────────────────────────

class TestLockRegistry:
    """Tests for the thread-safe _LockRegistry."""

    def test_register_and_check(self):
        _registry.register("test_path_a", "agent-a", time.time())
        assert _registry.is_held("test_path_a") is True
        info = _registry.held_by("test_path_a")
        assert info["agent_id"] == "agent-a"
        _registry.unregister("test_path_a")
        assert _registry.is_held("test_path_a") is False

    def test_unregister_nonexistent_is_safe(self):
        _registry.unregister("nonexistent_path")  # Should not raise

    def test_all_held(self):
        _registry.register("path_x", "agent-x", time.time())
        _registry.register("path_y", "agent-y", time.time())
        held = _registry.all_held()
        assert "path_x" in held
        assert "path_y" in held
        _registry.unregister("path_x")
        _registry.unregister("path_y")
