"""MCP tool handler: store_memory.

Persists agent learnings, discoveries, and arbitrary content into the
vector index under a given namespace.  This writes a text document into
a ``memory/<namespace>/`` directory and then incrementally indexes it
so that future searches can retrieve it.
"""

import json
import hashlib
import re
import subprocess
import sys
import time
from pathlib import Path

_SAFE_NAMESPACE_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

from mcp_tools import SCRIPTS_DIR as _SCRIPT_DIR, resolve_main_repo_root


def register(server):
    """Register the store_memory tool on *server*."""

    @server.tool()
    async def store_memory(
        content: str,
        metadata: dict | None = None,
        namespace: str = "general",
        root: str = ".",
    ) -> str:
        """Persist agent learnings and discoveries into vector memory.

        The content is written to a file under
        ``.claude/memory/notes/<namespace>/`` and then incrementally
        indexed so it can be retrieved by ``semantic_search``.

        Args:
            content: The text content to store (markdown recommended).
            metadata: Optional key-value metadata dict attached to the note.
            namespace: Logical grouping (e.g. "learnings", "bugs",
                       "architecture"). Defaults to "general".
            root: Project root directory.

        Returns:
            JSON object with ``status``, ``path`` of stored file, and
            ``message``.
        """
        # Validate namespace to prevent directory traversal
        if not _SAFE_NAMESPACE_RE.match(namespace):
            return json.dumps({
                "status": "error",
                "message": f"Invalid namespace: {namespace!r}. "
                           f"Must contain only alphanumeric characters, "
                           f"hyphens, and underscores.",
            })

        # Resolve to main repo root (worktree-aware)
        root_path = resolve_main_repo_root(root)
        notes_dir = root_path / ".claude" / "memory" / "notes" / namespace
        # Verify resolved path stays within expected directory
        expected_base = root_path / ".claude" / "memory" / "notes"
        if not str(notes_dir.resolve()).startswith(str(expected_base.resolve())):
            return json.dumps({
                "status": "error",
                "message": "Namespace resolves outside the allowed directory.",
            })
        notes_dir.mkdir(parents=True, exist_ok=True)

        # Generate a unique filename from timestamp + content hash
        ts = time.strftime("%Y%m%dT%H%M%S")
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:8]
        filename = f"{ts}_{content_hash}.md"
        filepath = notes_dir / filename

        # Build the document with optional frontmatter
        doc_lines = []
        if metadata:
            doc_lines.append("---")
            for k, v in metadata.items():
                # Sanitize: keys must be simple identifiers, values are
                # single-line strings with special chars escaped.
                safe_key = re.sub(r"[^a-zA-Z0-9_]", "_", str(k))
                safe_val = str(v).replace("\n", " ").replace("---", "- -")
                doc_lines.append(f"{safe_key}: {safe_val}")
            doc_lines.append("---")
            doc_lines.append("")
        doc_lines.append(content)

        try:
            filepath.write_text("\n".join(doc_lines), encoding="utf-8")
        except OSError as exc:
            return json.dumps({
                "status": "error",
                "message": f"Failed to write memory file: {exc}",
            })

        # Trigger incremental index so the new note is searchable
        vm_script = _SCRIPT_DIR / "vector_memory.py"
        index_msg = ""
        if vm_script.exists():
            try:
                result = subprocess.run(
                    [sys.executable, str(vm_script), "hook", str(filepath)],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode != 0:
                    index_msg = (
                        f"Note saved but incremental index failed: "
                        f"{result.stderr.strip()}"
                    )
            except Exception as exc:
                index_msg = f"Note saved but incremental index failed: {exc}"

        rel_path = str(filepath.relative_to(root_path))
        return json.dumps({
            "status": "ok",
            "path": rel_path,
            "namespace": namespace,
            "message": index_msg or f"Memory stored and indexed: {rel_path}",
        })
