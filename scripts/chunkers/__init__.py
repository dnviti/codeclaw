"""AST-aware chunking strategies for the vector memory layer.

Provides language-specific code chunking that preserves semantic boundaries
(functions, classes, methods) instead of naive line-based splitting.

Uses Python's built-in `ast` module for Python files and regex-based
boundary detection for other languages, leveraging the existing
`classify_file_role()` and `EXTENSION_MAP` infrastructure.

Zero external dependencies — stdlib only.
"""

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Add parent to path for analyzer imports
import sys
_PKG_DIR = Path(__file__).resolve().parent.parent
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

from analyzers import EXTENSION_MAP, classify_file_role


@dataclass
class Chunk:
    """A semantic chunk of source code or text."""
    content: str
    file_path: str
    chunk_type: str          # "function", "class", "method", "block", "doc"
    name: str                # e.g. function name, class name
    start_line: int
    end_line: int
    language: str
    file_role: str           # from classify_file_role()
    content_hash: str = ""   # SHA-256 of content for dedup/staleness
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.content_hash:
            self.content_hash = hashlib.sha256(
                self.content.encode("utf-8")
            ).hexdigest()


def detect_language(file_path: str) -> str:
    """Detect language from file extension using EXTENSION_MAP."""
    ext = Path(file_path).suffix.lower()
    if ext in EXTENSION_MAP:
        return EXTENSION_MAP[ext][0]
    return "unknown"


def chunk_file(file_path: str, content: str,
               max_chunk_size: int = 2000) -> list[Chunk]:
    """Chunk a file using the appropriate language-specific chunker.

    Args:
        file_path: Relative or absolute path to the file.
        content: File content as a string.
        max_chunk_size: Maximum characters per chunk (large chunks are split).

    Returns:
        List of Chunk objects.
    """
    language = detect_language(file_path)
    file_role = classify_file_role(file_path)

    if language == "Python":
        from chunkers.python_chunker import chunk_python
        return chunk_python(file_path, content, language, file_role,
                            max_chunk_size)
    else:
        from chunkers.generic_chunker import chunk_generic
        return chunk_generic(file_path, content, language, file_role,
                             max_chunk_size)


def chunk_text_document(file_path: str, content: str,
                        doc_type: str = "doc",
                        max_chunk_size: int = 2000) -> list[Chunk]:
    """Chunk a Markdown/text document by sections.

    Used for memory_builder output, analyzer reports, etc.
    """
    chunks = []
    lines = content.splitlines()
    current_section = ""
    current_lines: list[str] = []
    current_start = 1

    for i, line in enumerate(lines, 1):
        # Split on Markdown headers
        if line.startswith("## ") or line.startswith("# "):
            if current_lines:
                text = "\n".join(current_lines).strip()
                if text:
                    chunks.append(Chunk(
                        content=text,
                        file_path=file_path,
                        chunk_type=doc_type,
                        name=current_section or "header",
                        start_line=current_start,
                        end_line=i - 1,
                        language="Markdown",
                        file_role="documentation",
                    ))
            current_section = line.lstrip("#").strip()
            current_lines = [line]
            current_start = i
        else:
            current_lines.append(line)

    # Flush remaining
    if current_lines:
        text = "\n".join(current_lines).strip()
        if text:
            chunks.append(Chunk(
                content=text,
                file_path=file_path,
                chunk_type=doc_type,
                name=current_section or "content",
                start_line=current_start,
                end_line=len(lines),
                language="Markdown",
                file_role="documentation",
            ))

    # Split oversized chunks
    result = []
    for chunk in chunks:
        if len(chunk.content) > max_chunk_size:
            result.extend(_split_large_chunk(chunk, max_chunk_size))
        else:
            result.append(chunk)
    return result


def _split_large_chunk(chunk: Chunk, max_size: int) -> list[Chunk]:
    """Split an oversized chunk into smaller pieces at line boundaries."""
    lines = chunk.content.splitlines()
    parts: list[Chunk] = []
    current: list[str] = []
    current_len = 0
    part_start = chunk.start_line

    for i, line in enumerate(lines):
        line_len = len(line) + 1  # +1 for newline
        if current_len + line_len > max_size and current:
            parts.append(Chunk(
                content="\n".join(current),
                file_path=chunk.file_path,
                chunk_type=chunk.chunk_type,
                name=f"{chunk.name} (part {len(parts) + 1})",
                start_line=part_start,
                end_line=chunk.start_line + i - 1,
                language=chunk.language,
                file_role=chunk.file_role,
                metadata={**chunk.metadata, "part": len(parts) + 1},
            ))
            current = []
            current_len = 0
            part_start = chunk.start_line + i
        current.append(line)
        current_len += line_len

    if current:
        parts.append(Chunk(
            content="\n".join(current),
            file_path=chunk.file_path,
            chunk_type=chunk.chunk_type,
            name=f"{chunk.name} (part {len(parts) + 1})",
            start_line=part_start,
            end_line=chunk.end_line,
            language=chunk.language,
            file_role=chunk.file_role,
            metadata={**chunk.metadata, "part": len(parts) + 1},
        ))

    return parts
