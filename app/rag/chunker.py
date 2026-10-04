from dataclasses import dataclass


@dataclass
class CodeChunk:
    file_path: str
    chunk_index: int
    content: str


def chunk_code(
    content: str,
    file_path: str,
    chunk_size: int = 80,
    overlap: int = 15,
) -> list[CodeChunk]:

    lines = content.splitlines()

    chunks = []

    start = 0
    chunk_index = 0

    while start < len(lines):

        end = min(
            start + chunk_size,
            len(lines)
        )

        chunk = "\n".join(
            lines[start:end]
        )

        chunks.append(
            CodeChunk(
                file_path=file_path,
                chunk_index=chunk_index,
                content=chunk,
            )
        )

        if end == len(lines):
            break

        start = end - overlap
        chunk_index += 1

    return chunks