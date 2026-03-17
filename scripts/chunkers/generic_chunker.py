"""Regex-based chunker for non-Python source files.

Detects function/class boundaries using language-family regex patterns.
Falls back to fixed-size line-based splitting for unrecognized languages.

Zero external dependencies — stdlib only.
"""

import re
from chunkers import Chunk


# ── Language-family boundary patterns ────────────────────────────────────────
# Each entry: (family_extensions, function_pattern, class_pattern)
# Patterns match the opening line of a function/class definition.

_BOUNDARY_PATTERNS: list[tuple[set[str], str, str | None]] = [
    # C-family: JS/TS, Java, C#, C/C++, Go, Rust, etc.
    (
        {"JavaScript", "TypeScript", "TypeScript/React", "JavaScript/React",
         "Java", "Kotlin", "C#", "C", "C++", "Dart", "Scala", "Swift",
         "Objective-C"},
        # function/method patterns
        r"^[\s]*((?:export\s+)?(?:default\s+)?(?:async\s+)?(?:public|private|protected|static|abstract|override|virtual|inline|const|extern)?\s*(?:function|def|fn|func|fun|void|int|string|bool|double|float|char|var|let|const|auto)\s+\w+|(?:public|private|protected|static|abstract|override|virtual)?\s*\w+\s*\([^)]*\)\s*(?:\{|=>|:))",
        # class/interface/struct patterns
        r"^[\s]*((?:export\s+)?(?:abstract\s+)?(?:public\s+)?(?:class|interface|struct|enum|trait|protocol)\s+\w+)",
    ),
    # Go
    (
        {"Go"},
        r"^func\s+(?:\(\w+\s+\*?\w+\)\s+)?\w+\s*\(",
        r"^type\s+\w+\s+struct\s*\{",
    ),
    # Rust
    (
        {"Rust"},
        r"^[\s]*(pub\s+)?(async\s+)?fn\s+\w+",
        r"^[\s]*(pub\s+)?(struct|enum|trait|impl)\s+\w+",
    ),
    # Ruby
    (
        {"Ruby", "Ruby/ERB"},
        r"^[\s]*(def\s+\w+)",
        r"^[\s]*(class|module)\s+\w+",
    ),
    # PHP
    (
        {"PHP"},
        r"^[\s]*((?:public|private|protected|static)?\s*function\s+\w+)",
        r"^[\s]*((?:abstract\s+)?class|interface|trait|enum)\s+\w+",
    ),
    # Elixir / Erlang
    (
        {"Elixir", "Erlang"},
        r"^[\s]*(def[p]?\s+\w+)",
        r"^[\s]*(defmodule|defprotocol|defimpl)\s+\w+",
    ),
    # Shell
    (
        {"Shell", "PowerShell"},
        r"^[\s]*(function\s+\w+|\w+\s*\(\)\s*\{)",
        None,
    ),
    # Lua
    (
        {"Lua"},
        r"^[\s]*((?:local\s+)?function\s+[\w.:]+)",
        None,
    ),
]


def _get_patterns(language: str) -> tuple[str | None, str | None]:
    """Find the best matching boundary patterns for a language."""
    for families, func_pat, class_pat in _BOUNDARY_PATTERNS:
        if language in families:
            return func_pat, class_pat
    return None, None


def chunk_generic(file_path: str, content: str, language: str,
                  file_role: str, max_chunk_size: int = 2000) -> list[Chunk]:
    """Chunk a non-Python source file using regex boundary detection.

    Strategy:
    1. Identify function/class boundary lines using language-family regexes.
    2. Split content at those boundaries into semantic chunks.
    3. Fall back to fixed-size line splitting if no patterns match.
    """
    func_pat, class_pat = _get_patterns(language)

    # If we have no patterns, use simple line-based splitting
    if not func_pat and not class_pat:
        return _chunk_by_lines(file_path, content, language, file_role,
                               max_chunk_size)

    lines = content.splitlines()
    boundaries: list[tuple[int, str, str]] = []  # (line_idx, type, name)

    func_re = re.compile(func_pat) if func_pat else None
    class_re = re.compile(class_pat) if class_pat else None

    for i, line in enumerate(lines):
        if class_re:
            m = class_re.match(line)
            if m:
                name = _extract_name(m.group(0))
                boundaries.append((i, "class", name))
                continue
        if func_re:
            m = func_re.match(line)
            if m:
                name = _extract_name(m.group(0))
                boundaries.append((i, "function", name))

    # If no boundaries found, fall back to line-based splitting
    if not boundaries:
        return _chunk_by_lines(file_path, content, language, file_role,
                               max_chunk_size)

    # Build chunks between boundaries
    chunks: list[Chunk] = []

    # Module-level code before first boundary
    if boundaries[0][0] > 0:
        header = "\n".join(lines[:boundaries[0][0]])
        if header.strip():
            chunks.append(Chunk(
                content=header,
                file_path=file_path,
                chunk_type="block",
                name="module-header",
                start_line=1,
                end_line=boundaries[0][0],
                language=language,
                file_role=file_role,
            ))

    # Each boundary to the next
    for idx, (line_idx, btype, name) in enumerate(boundaries):
        if idx + 1 < len(boundaries):
            end_idx = boundaries[idx + 1][0]
        else:
            end_idx = len(lines)

        text = "\n".join(lines[line_idx:end_idx])
        if text.strip():
            chunk = Chunk(
                content=text,
                file_path=file_path,
                chunk_type=btype,
                name=name,
                start_line=line_idx + 1,
                end_line=end_idx,
                language=language,
                file_role=file_role,
            )
            # Split if oversized
            if len(text) > max_chunk_size:
                chunks.extend(_split_chunk(chunk, max_chunk_size))
            else:
                chunks.append(chunk)

    return chunks


def _extract_name(definition_line: str) -> str:
    """Extract the identifier name from a definition line."""
    # Try to find the first word-like identifier after keywords
    cleaned = definition_line.strip()
    # Remove common keywords
    for kw in ["export", "default", "async", "public", "private",
               "protected", "static", "abstract", "override", "virtual",
               "inline", "const", "extern", "pub", "local", "def", "defp",
               "defmodule", "fn", "func", "fun", "function", "class",
               "interface", "struct", "enum", "trait", "impl", "protocol",
               "module", "type", "void", "int", "string", "bool"]:
        cleaned = re.sub(rf"\b{kw}\b", "", cleaned)

    # Find the first remaining identifier
    m = re.search(r"[a-zA-Z_]\w*", cleaned)
    return m.group(0) if m else "unknown"


def _chunk_by_lines(file_path: str, content: str, language: str,
                    file_role: str, max_chunk_size: int) -> list[Chunk]:
    """Simple fixed-size line-based chunking for unknown languages."""
    lines = content.splitlines()
    if not lines:
        return []

    chunks: list[Chunk] = []
    current: list[str] = []
    current_len = 0
    start_line = 1

    for i, line in enumerate(lines, 1):
        line_len = len(line) + 1
        if current_len + line_len > max_chunk_size and current:
            chunks.append(Chunk(
                content="\n".join(current),
                file_path=file_path,
                chunk_type="block",
                name=f"block-{len(chunks) + 1}",
                start_line=start_line,
                end_line=i - 1,
                language=language,
                file_role=file_role,
            ))
            current = []
            current_len = 0
            start_line = i
        current.append(line)
        current_len += line_len

    if current:
        text = "\n".join(current)
        if text.strip():
            chunks.append(Chunk(
                content=text,
                file_path=file_path,
                chunk_type="block",
                name=f"block-{len(chunks) + 1}",
                start_line=start_line,
                end_line=len(lines),
                language=language,
                file_role=file_role,
            ))

    return chunks


def _split_chunk(chunk: Chunk, max_size: int) -> list[Chunk]:
    """Split an oversized chunk at line boundaries."""
    lines = chunk.content.splitlines()
    parts: list[Chunk] = []
    current: list[str] = []
    current_len = 0
    part_start = chunk.start_line

    for i, line in enumerate(lines):
        line_len = len(line) + 1
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
