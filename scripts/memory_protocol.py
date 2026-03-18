#!/usr/bin/env python3
"""Multi-agent memory consistency protocol for shared vector stores.

Provides agent registration, entry tagging with agent metadata, conflict
detection and resolution, and versioned reads for the CTDF vector memory
layer. Designed to coordinate multiple concurrent agents spawned by
``/task pick all``, ``/release`` stage 4, or agentic fleet CI pipelines.

Consistency guarantees:
    - Single-writer / multi-reader via MemoryLock (advisory file locks)
    - Every memory entry tagged with agent_id, agent_type, task_code,
      session_id, and timestamp
    - Conflict resolution: last-writer-wins for factual entries,
      merge for additive entries, flag-for-review for contradictions
    - LanceDB dataset versioning for point-in-time queries

Zero required dependencies — stdlib only (optional: lancedb for
versioned reads).
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

DEFAULT_SESSIONS_DIR = ".claude/memory/sessions"
DEFAULT_CONFLICTS_DIR = ".claude/memory/conflicts"

AGENT_TYPES = ("task", "scout", "release", "docs", "pr-analysis", "monitor")
ENTRY_CATEGORIES = ("factual", "additive", "opinion")

CONFLICT_STRATEGIES = {
    "factual": "last-writer-wins",
    "additive": "merge",
    "opinion": "flag-for-review",
}


# ── Agent Session ────────────────────────────────────────────────────────────

class AgentSession:
    """Represents a registered agent session.

    Each spawned agent gets a unique session that tracks its identity
    and lifespan.
    """

    def __init__(
        self,
        agent_id: str,
        agent_type: str = "task",
        task_code: str = "",
        session_id: Optional[str] = None,
        parent_session: Optional[str] = None,
    ):
        self.agent_id = agent_id
        self.agent_type = agent_type if agent_type in AGENT_TYPES else "task"
        self.task_code = task_code
        self.session_id = session_id or str(uuid.uuid4())[:12]
        self.parent_session = parent_session
        self.started_at = time.time()
        self.started_iso = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.started_at)
        )
        self.ended_at: Optional[float] = None
        self.status = "active"
        self.entries_written = 0
        self.events_appended = 0
        self.conflicts_detected = 0

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "task_code": self.task_code,
            "session_id": self.session_id,
            "parent_session": self.parent_session,
            "started_at": self.started_at,
            "started_iso": self.started_iso,
            "ended_at": self.ended_at,
            "status": self.status,
            "pid": os.getpid(),
            "entries_written": self.entries_written,
            "events_appended": self.events_appended,
            "conflicts_detected": self.conflicts_detected,
        }

    def end(self):
        self.ended_at = time.time()
        self.status = "completed"

    def mark_orphaned(self):
        self.status = "orphaned"

    @staticmethod
    def from_dict(data: dict) -> "AgentSession":
        session = AgentSession(
            agent_id=data["agent_id"],
            agent_type=data.get("agent_type", "task"),
            task_code=data.get("task_code", ""),
            session_id=data.get("session_id", ""),
            parent_session=data.get("parent_session"),
        )
        session.started_at = data.get("started_at", time.time())
        session.started_iso = data.get(
            "started_iso",
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(session.started_at)),
        )
        session.ended_at = data.get("ended_at")
        session.status = data.get("status", "active")
        session.entries_written = data.get("entries_written", 0)
        session.events_appended = data.get("events_appended", 0)
        session.conflicts_detected = data.get("conflicts_detected", 0)
        return session


# ── Session Registry ─────────────────────────────────────────────────────────

class SessionRegistry:
    """Manages agent sessions persisted to disk.

    Sessions are stored as individual JSON files in the sessions directory,
    enabling concurrent writes from multiple agents without coordination.
    """

    def __init__(self, root: Path):
        self.sessions_dir = root / DEFAULT_SESSIONS_DIR
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def register(self, session: AgentSession) -> Path:
        """Register a new agent session. Returns the session file path."""
        path = self.sessions_dir / f"{session.session_id}.json"
        path.write_text(
            json.dumps(session.to_dict(), indent=2), encoding="utf-8"
        )
        return path

    def deregister(self, session_id: str):
        """Mark a session as completed and update its file."""
        path = self.sessions_dir / f"{session_id}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data["status"] = "completed"
                data["ended_at"] = time.time()
                path.write_text(
                    json.dumps(data, indent=2), encoding="utf-8"
                )
            except (json.JSONDecodeError, OSError):
                pass

    def get_session(self, session_id: str) -> Optional[AgentSession]:
        """Load a session by ID."""
        path = self.sessions_dir / f"{session_id}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return AgentSession.from_dict(data)
            except (json.JSONDecodeError, OSError):
                pass
        return None

    def list_sessions(
        self,
        status: Optional[str] = None,
        agent_type: Optional[str] = None,
    ) -> list[dict]:
        """List all sessions, optionally filtered by status or type."""
        sessions = []
        for f in sorted(self.sessions_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if status and data.get("status") != status:
                    continue
                if agent_type and data.get("agent_type") != agent_type:
                    continue
                sessions.append(data)
            except (json.JSONDecodeError, OSError):
                pass
        return sessions

    def active_count(self) -> int:
        """Return the number of currently active sessions."""
        return len(self.list_sessions(status="active"))

    def cleanup_orphaned(self, max_age_seconds: float = 7200.0) -> int:
        """Mark sessions as orphaned if they are old and still active.

        Returns the count of sessions marked orphaned.
        """
        count = 0
        now = time.time()
        for f in self.sessions_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("status") != "active":
                    continue
                started = data.get("started_at", 0)
                if now - started > max_age_seconds:
                    data["status"] = "orphaned"
                    f.write_text(
                        json.dumps(data, indent=2), encoding="utf-8"
                    )
                    count += 1
            except (json.JSONDecodeError, OSError):
                pass
        return count

    def purge_completed(self, older_than_seconds: float = 86400.0) -> int:
        """Remove completed/orphaned session files older than threshold.

        Returns the count of files removed.
        """
        count = 0
        now = time.time()
        for f in self.sessions_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("status") not in ("completed", "orphaned"):
                    continue
                ended = data.get("ended_at") or data.get("started_at", 0)
                if now - ended > older_than_seconds:
                    f.unlink(missing_ok=True)
                    count += 1
            except (json.JSONDecodeError, OSError):
                try:
                    f.unlink(missing_ok=True)
                    count += 1
                except OSError:
                    pass
        return count


# ── Entry Tagging ────────────────────────────────────────────────────────────

def tag_entry(
    entry: dict,
    agent_id: str,
    agent_type: str = "task",
    task_code: str = "",
    session_id: str = "",
    category: str = "factual",
) -> dict:
    """Add agent metadata tags to a memory entry.

    Adds the following fields:
        - agent_id: unique identifier for the agent
        - agent_type: task | scout | release | docs | pr-analysis | monitor
        - task_code: associated task code if applicable
        - session_id: unique session identifier
        - written_at: Unix timestamp of write
        - written_iso: ISO-formatted timestamp
        - entry_version: monotonically increasing version number
        - entry_category: factual | additive | opinion

    The entry dict is modified in-place and returned.
    """
    now = time.time()
    entry["agent_id"] = agent_id
    entry["agent_type"] = agent_type if agent_type in AGENT_TYPES else "task"
    entry["task_code"] = task_code
    entry["session_id"] = session_id
    entry["written_at"] = now
    entry["written_iso"] = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)
    )
    entry["entry_version"] = int(now * 1000)  # millisecond-precision version
    entry["entry_category"] = (
        category if category in ENTRY_CATEGORIES else "factual"
    )
    return entry


# ── Conflict Detection and Resolution ────────────────────────────────────────

class ConflictRecord:
    """A detected conflict between two memory entries."""

    def __init__(
        self,
        entry_a: dict,
        entry_b: dict,
        field: str,
        resolution: str,
        resolved: bool = False,
        resolve_strategy: str = "manual",
    ):
        self.conflict_id = str(uuid.uuid4())[:12]
        self.entry_a = entry_a
        self.entry_b = entry_b
        self.field = field
        self.resolution = resolution
        self.resolved = resolved
        self.resolve_strategy = resolve_strategy
        self.detected_at = time.time()
        self.detected_iso = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.detected_at)
        )

    def to_dict(self) -> dict:
        return {
            "conflict_id": self.conflict_id,
            "field": self.field,
            "resolution": self.resolution,
            "resolved": self.resolved,
            "resolve_strategy": self.resolve_strategy,
            "detected_at": self.detected_at,
            "detected_iso": self.detected_iso,
            "entry_a_agent": self.entry_a.get("agent_id", "?"),
            "entry_a_session": self.entry_a.get("session_id", "?"),
            "entry_a_value": str(self.entry_a.get(self.field, ""))[:200],
            "entry_b_agent": self.entry_b.get("agent_id", "?"),
            "entry_b_session": self.entry_b.get("session_id", "?"),
            "entry_b_value": str(self.entry_b.get(self.field, ""))[:200],
        }


class ConflictResolver:
    """Detects and resolves conflicts between memory entries.

    Strategies:
        - factual: last-writer-wins (code analysis, file metadata)
        - additive: merge (discovered patterns, imports)
        - opinion: flag-for-review (contradictory architectural opinions)
    """

    def __init__(self, root: Path):
        self.conflicts_dir = root / DEFAULT_CONFLICTS_DIR
        self.conflicts_dir.mkdir(parents=True, exist_ok=True)

    def detect_conflict(
        self,
        new_entry: dict,
        existing_entry: dict,
        fields: Optional[list[str]] = None,
    ) -> list[ConflictRecord]:
        """Compare two entries and detect conflicts on specified fields.

        If fields is None, compares 'content' and 'file_path'.
        """
        if fields is None:
            fields = ["content", "file_path"]

        conflicts = []
        for field in fields:
            new_val = new_entry.get(field)
            old_val = existing_entry.get(field)

            if new_val is None or old_val is None:
                continue
            if new_val == old_val:
                continue

            # Same file_path but different content = potential conflict
            if field == "content" and new_entry.get("file_path") != existing_entry.get("file_path"):
                continue  # Different files — not a conflict

            category = new_entry.get("entry_category", "factual")
            resolution = CONFLICT_STRATEGIES.get(category, "last-writer-wins")

            conflicts.append(ConflictRecord(
                entry_a=existing_entry,
                entry_b=new_entry,
                field=field,
                resolution=resolution,
            ))

        return conflicts

    def resolve(self, conflict: ConflictRecord) -> dict:
        """Apply the resolution strategy and return the winning entry.

        For opinion conflicts (flag-for-review), checks ``auto_resolve``
        config.  If enabled, delegates to ``ConflictJudge`` instead of
        always flagging for manual review.

        Returns the entry that should be kept.
        """
        if conflict.resolution == "last-writer-wins":
            # Newer entry wins
            a_time = conflict.entry_a.get("written_at", 0)
            b_time = conflict.entry_b.get("written_at", 0)
            winner = conflict.entry_b if b_time >= a_time else conflict.entry_a
            conflict.resolved = True
            conflict.resolve_strategy = "last-writer-wins"
            return winner

        elif conflict.resolution == "merge":
            # Merge: combine content from both entries
            merged = dict(conflict.entry_b)  # Start with newer
            a_content = conflict.entry_a.get("content", "")
            b_content = conflict.entry_b.get("content", "")
            if a_content and b_content and a_content != b_content:
                merged["content"] = b_content + "\n\n---\n\n" + a_content
                merged["merged_from"] = [
                    conflict.entry_a.get("agent_id", ""),
                    conflict.entry_b.get("agent_id", ""),
                ]
            conflict.resolved = True
            conflict.resolve_strategy = "merge"
            return merged

        else:
            # flag-for-review: attempt auto-resolution if enabled
            auto_result = self._try_auto_resolve(conflict)
            if auto_result is not None:
                return auto_result
            # Fallback: save the conflict for manual review
            self._save_conflict(conflict)
            return conflict.entry_b

    def _try_auto_resolve(self, conflict: ConflictRecord) -> Optional[dict]:
        """Attempt automated resolution of an opinion conflict via LLM judge.

        Returns the winning entry if auto-resolution succeeds, or None
        if auto-resolve is disabled or the judge cannot resolve the conflict.
        """
        try:
            from conflict_judge import ConflictJudge, load_auto_resolve_config
        except ImportError:
            return None

        config = load_auto_resolve_config(self.conflicts_dir.parent.parent)
        if not config.get("enabled", False):
            return None

        judge = ConflictJudge(
            root=self.conflicts_dir.parent.parent,
            provider=config.get("provider", "ollama"),
            model=config.get("model", ""),
            confidence_threshold=config.get("confidence_threshold", 0.8),
            num_votes=config.get("num_votes", 3),
        )

        strategy = config.get("strategy", "single-judge")
        result = judge.judge(conflict.to_dict(), strategy=strategy)

        if not result.get("resolved"):
            return None

        verdict = result.get("verdict", {})
        winner_key = verdict.get("winner", "B")

        if winner_key == "A":
            winner = conflict.entry_a
        elif winner_key == "merged":
            winner = dict(conflict.entry_b)
            winner["content"] = verdict.get("merged_content", "")
            winner["merged_from"] = [
                conflict.entry_a.get("agent_id", ""),
                conflict.entry_b.get("agent_id", ""),
            ]
        else:
            winner = conflict.entry_b

        winner["auto_resolved"] = True
        winner["judge_reasoning"] = verdict.get("reasoning", "")
        winner["judge_confidence"] = verdict.get("confidence", 0)

        conflict.resolved = True
        conflict.resolve_strategy = f"auto-judge:{strategy}"

        # Still save the conflict record (now marked resolved)
        self._save_conflict(conflict)

        return winner

    def _save_conflict(self, conflict: ConflictRecord):
        """Persist an unresolved conflict for later review."""
        path = self.conflicts_dir / f"{conflict.conflict_id}.json"
        try:
            path.write_text(
                json.dumps(conflict.to_dict(), indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def list_conflicts(
        self, resolved: Optional[bool] = None
    ) -> list[dict]:
        """List all saved conflicts, optionally filtered by status.

        Each conflict dict includes a ``resolve_strategy`` field indicating
        how it was resolved: ``manual`` (default for legacy records),
        ``auto-judge:<strategy>``, ``last-writer-wins``, or ``merge``.
        """
        conflicts = []
        for f in sorted(self.conflicts_dir.glob("*.json")):
            if f.name.endswith(".resolution.json"):
                continue  # Skip judge resolution metadata files
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                # Ensure resolve_strategy is present for legacy records
                if "resolve_strategy" not in data:
                    data["resolve_strategy"] = "manual"
                if resolved is not None and data.get("resolved") != resolved:
                    continue
                conflicts.append(data)
            except (json.JSONDecodeError, OSError):
                pass
        return conflicts

    def resolve_conflict_by_id(self, conflict_id: str) -> bool:
        """Mark a conflict as resolved by ID. Returns True if found."""
        path = self.conflicts_dir / f"{conflict_id}.json"
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data["resolved"] = True
                path.write_text(
                    json.dumps(data, indent=2), encoding="utf-8"
                )
                return True
            except (json.JSONDecodeError, OSError):
                pass
        return False

    def purge_resolved(self) -> int:
        """Remove all resolved conflict files. Returns count removed."""
        count = 0
        for f in self.conflicts_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("resolved"):
                    f.unlink(missing_ok=True)
                    count += 1
            except (json.JSONDecodeError, OSError):
                try:
                    f.unlink(missing_ok=True)
                    count += 1
                except OSError:
                    pass
        return count


# ── Versioned Reads ──────────────────────────────────────────────────────────

def versioned_query(
    db,
    table_name: str,
    version: Optional[int] = None,
):
    """Open a LanceDB table at a specific version for point-in-time reads.

    If version is None, opens the latest version.

    Args:
        db: LanceDB connection object.
        table_name: Name of the table to open.
        version: Dataset version number (from LanceDB versioning).

    Returns:
        The table object at the specified version.
    """
    try:
        if version is not None:
            return db.open_table(table_name, version=version)
        return db.open_table(table_name)
    except Exception:
        return db.open_table(table_name)


def get_table_version(db, table_name: str) -> Optional[int]:
    """Get the current version of a LanceDB table.

    Returns None if the table doesn't exist or versioning info
    is unavailable.
    """
    try:
        table = db.open_table(table_name)
        if hasattr(table, "version"):
            v = table.version
            return v() if callable(v) else v
    except Exception:
        pass
    return None


# ── Memory Protocol Coordinator ──────────────────────────────────────────────

class MemoryProtocol:
    """High-level coordinator for multi-agent memory consistency.

    Integrates session management, entry tagging, locking, conflict
    detection, and versioned reads into a single interface.
    """

    def __init__(self, root: Path):
        self.root = root
        self.registry = SessionRegistry(root)
        self.resolver = ConflictResolver(root)

    def register_agent(
        self,
        agent_id: str,
        agent_type: str = "task",
        task_code: str = "",
        parent_session: Optional[str] = None,
    ) -> AgentSession:
        """Register a new agent session."""
        # Sanitize values before setting as env vars to prevent injection
        safe_agent_id = _sanitize_identifier(agent_id)
        safe_agent_type = _sanitize_identifier(agent_type)
        safe_task_code = _sanitize_identifier(task_code)

        session = AgentSession(
            agent_id=safe_agent_id,
            agent_type=safe_agent_type,
            task_code=safe_task_code,
            parent_session=parent_session,
        )
        self.registry.register(session)

        # Set environment variables for child processes
        os.environ["CTDF_AGENT_ID"] = safe_agent_id
        os.environ["CTDF_SESSION_ID"] = session.session_id
        os.environ["CTDF_AGENT_TYPE"] = safe_agent_type
        if safe_task_code:
            os.environ["CTDF_TASK_CODE"] = safe_task_code

        return session

    def deregister_agent(self, session_id: str):
        """Deregister an agent session."""
        self.registry.deregister(session_id)
        # Clean up environment variables
        for var in ("CTDF_AGENT_ID", "CTDF_SESSION_ID",
                    "CTDF_AGENT_TYPE", "CTDF_TASK_CODE"):
            os.environ.pop(var, None)

    def tag_and_check(
        self,
        entry: dict,
        existing_entries: Optional[list[dict]] = None,
        agent_id: str = "",
        agent_type: str = "task",
        task_code: str = "",
        session_id: str = "",
        category: str = "factual",
    ) -> tuple[dict, list[ConflictRecord]]:
        """Tag an entry with agent metadata and check for conflicts.

        Returns (tagged_entry, conflicts).
        """
        # Auto-detect from environment if not provided
        if not agent_id:
            agent_id = os.environ.get("CTDF_AGENT_ID", f"agent-{os.getpid()}")
        if not session_id:
            session_id = os.environ.get("CTDF_SESSION_ID", "")
        if not agent_type:
            agent_type = os.environ.get("CTDF_AGENT_TYPE", "task")
        if not task_code:
            task_code = os.environ.get("CTDF_TASK_CODE", "")

        tagged = tag_entry(
            entry, agent_id, agent_type, task_code, session_id, category
        )

        conflicts = []
        if existing_entries:
            for existing in existing_entries:
                found = self.resolver.detect_conflict(tagged, existing)
                conflicts.extend(found)

        return tagged, conflicts

    def get_status(self) -> dict:
        """Return protocol status: active agents, pending conflicts."""
        active = self.registry.list_sessions(status="active")
        pending = self.resolver.list_conflicts(resolved=False)

        return {
            "active_agents": len(active),
            "active_sessions": [
                {
                    "agent_id": s.get("agent_id", ""),
                    "agent_type": s.get("agent_type", ""),
                    "task_code": s.get("task_code", ""),
                    "session_id": s.get("session_id", ""),
                }
                for s in active
            ],
            "pending_conflicts": len(pending),
            "conflicts": pending[:10],  # Cap at 10 for summary
        }

    def gc_sessions(
        self,
        orphan_threshold: float = 7200.0,
        purge_threshold: float = 86400.0,
    ) -> dict:
        """Garbage-collect agent sessions.

        1. Mark old active sessions as orphaned
        2. Purge completed/orphaned sessions older than threshold

        Returns summary of actions taken.
        """
        orphaned = self.registry.cleanup_orphaned(orphan_threshold)
        purged = self.registry.purge_completed(purge_threshold)
        resolved_purged = self.resolver.purge_resolved()

        return {
            "sessions_orphaned": orphaned,
            "sessions_purged": purged,
            "conflicts_purged": resolved_purged,
        }


# ── Generate Agent ID ────────────────────────────────────────────────────────

def _sanitize_identifier(value: str) -> str:
    """Sanitize a string for use as an identifier or env var value.

    Strips any characters outside alphanumerics, hyphens, underscores,
    and dots to prevent injection via environment variables or file paths.
    """
    import re
    return re.sub(r"[^a-zA-Z0-9._-]", "", value)


def generate_agent_id(prefix: str = "agent") -> str:
    """Generate a unique agent ID.

    Format: {prefix}-{short_uuid}-{pid}
    The prefix is sanitized to prevent injection of special characters.
    """
    safe_prefix = _sanitize_identifier(prefix) or "agent"
    short_id = str(uuid.uuid4())[:8]
    return f"{safe_prefix}-{short_id}-{os.getpid()}"
