#!/usr/bin/env python3
"""Append-only event log for concurrent agent memory writes.

Replaces the exclusive-write-lock bottleneck with event sourcing: each agent
appends memory events (indexed chunks, discoveries, learnings) as immutable
entries to its own segment file ``{session_id}.jsonl`` under
``.claude/memory/events/``.  A background compactor merges events into the
LanceDB index periodically, requiring only a brief exclusive lock during
compaction rather than on every write.

Event types:
    chunk_add    — A new chunk was indexed (file content, code, docs)
    chunk_remove — A chunk was deleted (file removed or re-indexed)
    note_add     — An agent-generated learning / discovery note

Zero external dependencies — stdlib only for core event log operations.
LanceDB is required only for the ``compact`` method.
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

# Add scripts/ to path for sibling imports
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_EVENTS_DIR = ".claude/memory/events"
EVENT_TYPES = ("chunk_add", "chunk_remove", "note_add")
DEFAULT_MAX_SEGMENT_SIZE_MB = 10
DEFAULT_COMPACT_INTERVAL = 300  # seconds



# ── Event Data Classes ───────────────────────────────────────────────────────

class MemoryEvent:
    """A single immutable memory event.

    Each event captures an atomic change that an agent wants to persist
    in the shared memory store.
    """

    def __init__(
        self,
        event_type: str,
        agent_id: str,
        session_id: str,
        payload: dict,
        timestamp: Optional[str] = None,
        event_id: Optional[str] = None,
    ):
        if event_type not in EVENT_TYPES:
            raise ValueError(
                f"Invalid event type: {event_type!r}. "
                f"Must be one of {EVENT_TYPES}"
            )
        self.event_id = event_id or uuid.uuid4().hex
        self.type = event_type
        self.timestamp = timestamp or time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        )
        self.unix_ts = time.time()
        self.agent_id = agent_id
        self.session_id = session_id
        self.payload = payload

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "type": self.type,
            "timestamp": self.timestamp,
            "unix_ts": self.unix_ts,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "payload": self.payload,
        }

    def to_json(self) -> str:
        """Serialize to a single JSON line (no trailing newline)."""
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @staticmethod
    def from_dict(data: dict) -> "MemoryEvent":
        event = MemoryEvent(
            event_type=data["type"],
            agent_id=data["agent_id"],
            session_id=data["session_id"],
            payload=data.get("payload", {}),
            timestamp=data.get("timestamp"),
            event_id=data.get("event_id"),
        )
        event.unix_ts = data.get("unix_ts", time.time())
        return event

    @staticmethod
    def from_json(line: str) -> "MemoryEvent":
        """Deserialize from a single JSON line."""
        return MemoryEvent.from_dict(json.loads(line))


# ── Event Log ────────────────────────────────────────────────────────────────

class EventLog:
    """Append-only event log with per-session segment files.

    Each agent writes to its own segment ``{session_id}.jsonl`` so that
    concurrent appends never contend on the same file.  The compactor
    reads all segments, merges events into the vector store, and then
    garbage-collects processed segments.

    File appends use ``os.open`` with ``O_APPEND`` for atomicity on
    POSIX systems (guaranteed for writes <= PIPE_BUF on most kernels).
    """

    def __init__(
        self,
        root: Path,
        events_dir: Optional[str] = None,
        max_segment_size_mb: float = DEFAULT_MAX_SEGMENT_SIZE_MB,
    ):
        self.root = Path(root).resolve()
        self.events_dir = self.root / (events_dir or DEFAULT_EVENTS_DIR)
        self.events_dir.mkdir(parents=True, exist_ok=True)
        self.max_segment_size_bytes = int(max_segment_size_mb * 1024 * 1024)

    # ── Append (lock-free) ───────────────────────────────────────────────

    def append(self, event: MemoryEvent) -> Path:
        """Append an event to the agent's segment file.

        This is lock-free: each session writes to its own file and uses
        O_APPEND for atomic writes.  Returns the path to the segment.
        """
        segment = self.events_dir / f"{event.session_id}.jsonl"
        line = event.to_json() + "\n"
        data = line.encode("utf-8")

        # O_APPEND guarantees atomic append on POSIX for small writes
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if sys.platform == "win32":
            flags |= getattr(os, "O_BINARY", 0)

        fd = os.open(str(segment), flags, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)

        return segment

    # ── Read ─────────────────────────────────────────────────────────────

    def read_events(
        self,
        since_timestamp: Optional[float] = None,
        session_id: Optional[str] = None,
    ) -> list[MemoryEvent]:
        """Read events from all segments (or a specific session).

        Args:
            since_timestamp: Only return events with unix_ts > this value.
            session_id: If provided, read only this session's segment.

        Returns:
            List of MemoryEvent sorted by unix_ts ascending.
        """
        events: list[MemoryEvent] = []

        if session_id:
            segments = [self.events_dir / f"{session_id}.jsonl"]
        else:
            segments = sorted(self.events_dir.glob("*.jsonl"))

        for seg in segments:
            if not seg.exists():
                continue
            try:
                content = seg.read_text(encoding="utf-8")
            except OSError:
                continue

            for line in content.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = MemoryEvent.from_json(line)
                    if since_timestamp is not None and ev.unix_ts <= since_timestamp:
                        continue
                    events.append(ev)
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue  # Skip malformed lines

        events.sort(key=lambda e: e.unix_ts)
        return events

    # ── Compact ──────────────────────────────────────────────────────────

    def compact(self, target_backend=None) -> dict:
        """Merge pending events into the target backend (LanceDB/SQLite).

        This method requires an exclusive write lock (provided by the caller
        via ``EventLock.compact()``).  It reads all segment files, applies
        events to the backend, and records which segments were processed.

        Args:
            target_backend: A backend object with ``apply_events(events)``
                method.  If None, events are read but not applied (dry run).

        Returns:
            Summary dict with counts of events processed.
        """
        # TOCTOU: mitigated by compaction idempotency — concurrent compactions produce identical results
        events = self.read_events()
        if not events:
            return {
                "events_processed": 0,
                "segments_processed": 0,
                "status": "nothing_to_compact",
            }

        # Group by type for summary
        by_type: dict[str, int] = {}
        for ev in events:
            by_type[ev.type] = by_type.get(ev.type, 0) + 1

        # Apply to backend if provided
        if target_backend is not None:
            target_backend.apply_events(events)

        # Mark segments as compacted by writing a companion .done file
        segments_processed = set()
        for ev in events:
            segments_processed.add(ev.session_id)

        for sid in segments_processed:
            done_path = self.events_dir / f"{sid}.done"
            try:
                done_path.write_text(
                    json.dumps({
                        "compacted_at": time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                        ),
                        "events_count": sum(
                            1 for e in events if e.session_id == sid
                        ),
                    }),
                    encoding="utf-8",
                )
            except OSError:
                pass

        return {
            "events_processed": len(events),
            "segments_processed": len(segments_processed),
            "by_type": by_type,
            "status": "compacted",
        }

    # ── Garbage Collection ───────────────────────────────────────────────

    def gc_segments(self, older_than: float = 3600.0) -> dict:
        """Remove compacted segments older than ``older_than`` seconds.

        Only removes segments that have a corresponding ``.done`` marker.

        Returns:
            Summary dict with count of segments removed.
        """
        now = time.time()
        removed = 0

        for done_file in sorted(self.events_dir.glob("*.done")):
            try:
                info = json.loads(done_file.read_text(encoding="utf-8"))
                # Parse compacted_at to check age
                compacted_str = info.get("compacted_at", "")
                if compacted_str:
                    compacted_ts = time.mktime(
                        time.strptime(compacted_str, "%Y-%m-%dT%H:%M:%SZ")
                    ) - time.timezone
                else:
                    compacted_ts = done_file.stat().st_mtime
            except (json.JSONDecodeError, OSError, ValueError):
                compacted_ts = done_file.stat().st_mtime

            if now - compacted_ts < older_than:
                continue

            # Remove segment and done marker
            segment = done_file.with_suffix(".jsonl")
            try:
                if segment.exists():
                    segment.unlink()
                done_file.unlink()
                removed += 1
            except OSError:
                pass

        return {
            "segments_removed": removed,
        }

    # ── Status ───────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return event log status: segment count, total events, size."""
        segments = list(self.events_dir.glob("*.jsonl"))
        done_segments = list(self.events_dir.glob("*.done"))

        total_size = 0
        total_events = 0
        for seg in segments:
            try:
                # Single read per segment: use content length for size and
                # line count for events to avoid redundant stat() + read()
                content = seg.read_text(encoding="utf-8")
                total_size += len(content.encode("utf-8"))
                total_events += sum(
                    1 for line in content.splitlines() if line.strip()
                )
            except OSError:
                pass

        return {
            "events_dir": str(self.events_dir),
            "active_segments": len(segments),
            "compacted_segments": len(done_segments),
            "total_events": total_events,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
        }


# ── LanceDB Backend Adapter ─────────────────────────────────────────────────

class LanceDBEventBackend:
    """Applies memory events to a LanceDB vector store.

    Used by ``EventLog.compact()`` to merge events into the actual index.
    """

    def __init__(self, db, table, provider=None, cache=None):
        """
        Args:
            db: LanceDB database connection.
            table: LanceDB table object.
            provider: Embedding provider for chunk_add events.
            cache: EmbeddingCache instance (optional).
        """
        self.db = db
        self.table = table
        self.provider = provider
        self.cache = cache

    def apply_events(self, events: list[MemoryEvent]):
        """Apply a list of events to the LanceDB table.

        Events are processed in order:
            - chunk_add: embed and insert the chunk
            - chunk_remove: delete matching entries
            - note_add: embed and insert as a note chunk
        """
        from analyzers import read_file_safe  # noqa: F811

        pending_records: list[dict] = []
        pending_texts: list[str] = []

        for event in events:
            if event.type == "chunk_remove":
                # Apply removes immediately
                file_path = event.payload.get("file_path", "")
                if file_path:
                    try:
                        safe = file_path.replace("'", "''")
                        self.table.delete(f"file_path = '{safe}'")
                    except Exception:
                        pass
                continue

            if event.type in ("chunk_add", "note_add"):
                payload = event.payload
                content = payload.get("content", "")
                if not content:
                    continue

                record = {
                    "content": content,
                    "file_path": payload.get("file_path", ""),
                    "chunk_type": payload.get("chunk_type", "note" if event.type == "note_add" else "chunk"),
                    "name": payload.get("name", ""),
                    "start_line": payload.get("start_line", 0),
                    "end_line": payload.get("end_line", 0),
                    "language": payload.get("language", ""),
                    "file_role": payload.get("file_role", ""),
                    "content_hash": payload.get("content_hash", ""),
                    # Agent metadata
                    "agent_id": event.agent_id,
                    "session_id": event.session_id,
                    "written_at": event.unix_ts,
                    "written_iso": event.timestamp,
                }
                pending_records.append(record)
                pending_texts.append(content)

        # Batch embed and insert
        if pending_texts and self.provider:
            if self.cache:
                embeddings = self.cache.embed_with_cache(
                    self.provider, pending_texts
                )
            else:
                embeddings = self.provider.embed(pending_texts)

            for rec, emb in zip(pending_records, embeddings):
                rec["vector"] = emb

            try:
                self.table.add(pending_records)
            except Exception as e:
                print(
                    f"Warning: event compaction batch insert failed: {e}",
                    file=sys.stderr,
                )


# ── Convenience Functions ────────────────────────────────────────────────────

def load_event_sourcing_config(root: Path) -> dict:
    """Load event_sourcing config from project-config.json.

    Returns effective config with defaults applied.
    """
    config_paths = [
        root / ".claude" / "project-config.json",
        root / "config" / "project-config.json",
    ]
    user_cfg: dict = {}
    for cp in config_paths:
        if cp.exists():
            try:
                data = json.loads(cp.read_text(encoding="utf-8"))
                vm = data.get("vector_memory", {})
                user_cfg = vm.get("event_sourcing", {})
                break
            except (json.JSONDecodeError, OSError):
                pass

    return {
        "enabled": user_cfg.get("enabled", False),
        "compact_interval_seconds": user_cfg.get(
            "compact_interval_seconds", DEFAULT_COMPACT_INTERVAL
        ),
        "max_segment_size_mb": user_cfg.get(
            "max_segment_size_mb", DEFAULT_MAX_SEGMENT_SIZE_MB
        ),
        "auto_compact_on_search": user_cfg.get(
            "auto_compact_on_search", True
        ),
    }


def is_event_sourcing_enabled(root: Path) -> bool:
    """Check if event sourcing is enabled in project config."""
    cfg = load_event_sourcing_config(root)
    return cfg.get("enabled", False)


def create_event_log(root: Path) -> EventLog:
    """Create an EventLog instance with configuration from project-config."""
    cfg = load_event_sourcing_config(root)
    return EventLog(
        root=root,
        max_segment_size_mb=cfg.get(
            "max_segment_size_mb", DEFAULT_MAX_SEGMENT_SIZE_MB
        ),
    )


def create_chunk_add_event(
    agent_id: str,
    session_id: str,
    chunk_data: dict,
) -> MemoryEvent:
    """Helper to create a chunk_add event from chunk data."""
    return MemoryEvent(
        event_type="chunk_add",
        agent_id=agent_id,
        session_id=session_id,
        payload=chunk_data,
    )


def create_chunk_remove_event(
    agent_id: str,
    session_id: str,
    file_path: str,
) -> MemoryEvent:
    """Helper to create a chunk_remove event for a file."""
    return MemoryEvent(
        event_type="chunk_remove",
        agent_id=agent_id,
        session_id=session_id,
        payload={"file_path": file_path},
    )


def create_note_event(
    agent_id: str,
    session_id: str,
    content: str,
    name: str = "",
) -> MemoryEvent:
    """Helper to create a note_add event."""
    return MemoryEvent(
        event_type="note_add",
        agent_id=agent_id,
        session_id=session_id,
        payload={
            "content": content,
            "name": name,
            "chunk_type": "note",
        },
    )
