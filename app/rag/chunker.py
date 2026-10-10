from dataclasses import dataclass


@dataclass
class CodeChunk:
    file_path: str
    chunk_index: int
    content: str
    start_line: int
    end_line: int


def chunk_code(
    content: str,
    file_path: str,
    chunk_size: int = 80,
    overlap: int = 15,
) -> list[CodeChunk]:
    """
    Split source file contents into overlapping chunks with line numbers.

    Args:
        content: Source code text.
        file_path: Relative path of the file.
        chunk_size: Number of lines per chunk.
        overlap: Number of overlapping lines between consecutive chunks.

    Returns:
        List of CodeChunk instances with file_path, chunk_index, content, start_line, and end_line.
    """
    if not content or not content.strip():
        return []

    lines = content.splitlines()
    if not lines:
        return []

    # Ensure valid chunking parameters
    if chunk_size <= 0:
        chunk_size = 80
    if overlap < 0 or overlap >= chunk_size:
        overlap = max(0, min(15, chunk_size - 1))

    chunks: list[CodeChunk] = []
    start = 0
    chunk_index = 0

    while start < len(lines):
        end = min(start + chunk_size, len(lines))
        chunk_text = "\n".join(lines[start:end])

        chunks.append(
            CodeChunk(
                file_path=file_path,
                chunk_index=chunk_index,
                content=chunk_text,
                start_line=start + 1,
                end_line=end,
            )
        )

        if end == len(lines):
            break

        start = end - overlap
        chunk_index += 1

    return chunks