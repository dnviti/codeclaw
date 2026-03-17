"""AST-aware chunker for Python source files.

Uses Python's built-in `ast` module to extract semantic boundaries:
functions, classes, methods, and module-level code blocks.

Zero external dependencies — stdlib only.
"""

import ast
from chunkers import Chunk


def chunk_python(file_path: str, content: str, language: str,
                 file_role: str, max_chunk_size: int = 2000) -> list[Chunk]:
    """Parse Python source and extract semantic chunks.

    Falls back to line-based splitting if AST parsing fails
    (e.g., syntax errors in the file).
    """
    try:
        tree = ast.parse(content, filename=file_path)
    except SyntaxError:
        # Fall back to generic chunking for files with syntax errors
        from chunkers.generic_chunker import chunk_generic
        return chunk_generic(file_path, content, language, file_role,
                             max_chunk_size)

    lines = content.splitlines()
    chunks: list[Chunk] = []
    consumed_lines: set[int] = set()

    # ── Extract top-level definitions ──────────────────────────────────────
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            chunk = _extract_function(node, lines, file_path, language,
                                      file_role)
            if chunk:
                chunks.append(chunk)
                consumed_lines.update(
                    range(chunk.start_line, chunk.end_line + 1)
                )

        elif isinstance(node, ast.ClassDef):
            # Extract the class as a whole, plus individual methods
            class_chunks = _extract_class(node, lines, file_path, language,
                                          file_role, max_chunk_size)
            for c in class_chunks:
                chunks.append(c)
                consumed_lines.update(range(c.start_line, c.end_line + 1))

    # ── Collect remaining module-level code ─────────────────────────────────
    module_lines: list[tuple[int, str]] = []
    for i, line in enumerate(lines, 1):
        if i not in consumed_lines:
            module_lines.append((i, line))

    if module_lines:
        # Group contiguous runs of module-level code
        groups = _group_contiguous(module_lines)
        for group in groups:
            text = "\n".join(line for _, line in group)
            if text.strip():
                chunks.append(Chunk(
                    content=text,
                    file_path=file_path,
                    chunk_type="block",
                    name="module-level",
                    start_line=group[0][0],
                    end_line=group[-1][0],
                    language=language,
                    file_role=file_role,
                ))

    # ── Split oversized chunks ─────────────────────────────────────────────
    result = []
    for chunk in chunks:
        if len(chunk.content) > max_chunk_size:
            result.extend(_split_chunk(chunk, max_chunk_size))
        else:
            result.append(chunk)

    return result


def _extract_function(node: ast.FunctionDef | ast.AsyncFunctionDef,
                      lines: list[str], file_path: str, language: str,
                      file_role: str) -> Chunk | None:
    """Extract a function/async function as a chunk."""
    start = node.lineno
    end = node.end_lineno or node.lineno
    if start > len(lines) or end > len(lines):
        return None

    text = "\n".join(lines[start - 1:end])
    if not text.strip():
        return None

    # Include decorators if present
    decorator_start = start
    for dec in node.decorator_list:
        if dec.lineno < decorator_start:
            decorator_start = dec.lineno
    if decorator_start < start:
        text = "\n".join(lines[decorator_start - 1:end])
        start = decorator_start

    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    return Chunk(
        content=text,
        file_path=file_path,
        chunk_type="function",
        name=f"{prefix}def {node.name}",
        start_line=start,
        end_line=end,
        language=language,
        file_role=file_role,
        metadata={"args": [a.arg for a in node.args.args]},
    )


def _extract_class(node: ast.ClassDef, lines: list[str], file_path: str,
                   language: str, file_role: str,
                   max_chunk_size: int) -> list[Chunk]:
    """Extract a class, producing one chunk per method + class header."""
    chunks: list[Chunk] = []
    start = node.lineno
    end = node.end_lineno or node.lineno

    # Include decorators
    decorator_start = start
    for dec in node.decorator_list:
        if dec.lineno < decorator_start:
            decorator_start = dec.lineno
    if decorator_start < start:
        start = decorator_start

    # Find where the body starts to extract class header/docstring
    first_body = node.body[0] if node.body else None
    body_start = first_body.lineno if first_body else end

    # Class header (class line + docstring if present)
    header_end = start
    if first_body and isinstance(first_body, ast.Expr) and isinstance(
            first_body.value, ast.Constant) and isinstance(
            first_body.value.value, str):
        # Docstring found
        header_end = first_body.end_lineno or first_body.lineno
    else:
        header_end = body_start - 1 if body_start > start else start

    if header_end >= start:
        header_text = "\n".join(lines[start - 1:header_end])
        if header_text.strip():
            bases = [_name_from_node(b) for b in node.bases]
            chunks.append(Chunk(
                content=header_text,
                file_path=file_path,
                chunk_type="class",
                name=f"class {node.name}",
                start_line=start,
                end_line=header_end,
                language=language,
                file_role=file_role,
                metadata={"bases": bases},
            ))

    # Extract methods
    for child in node.body:
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            method = _extract_function(child, lines, file_path, language,
                                       file_role)
            if method:
                method.chunk_type = "method"
                method.name = f"{node.name}.{child.name}"
                chunks.append(method)

    return chunks


def _name_from_node(node) -> str:
    """Get a string name from an AST node (for base classes, etc.)."""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        return f"{_name_from_node(node.value)}.{node.attr}"
    return "?"


def _group_contiguous(items: list[tuple[int, str]]) -> list[list[tuple[int, str]]]:
    """Group (line_number, content) tuples into contiguous runs."""
    if not items:
        return []
    groups: list[list[tuple[int, str]]] = [[items[0]]]
    for item in items[1:]:
        if item[0] == groups[-1][-1][0] + 1:
            groups[-1].append(item)
        else:
            groups.append([item])
    return groups


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
