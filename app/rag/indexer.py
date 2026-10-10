from pathlib import Path
from uuid import uuid4

from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
)

from app.config import (
    PROJECT_ROOT,
    IGNORED_DIRS,
    SENSITIVE_FILES,
    QDRANT_COLLECTION,
)
from app.ai.embeddings import create_embedding
from app.rag.chunker import chunk_code
from app.rag.vector_store import get_qdrant_client, ensure_collection, COLLECTION_NAME

SUPPORTED_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".json",
    ".md",
    ".yaml",
    ".yml",
    ".toml",
    ".html",
    ".css",
    ".sh",
}


def index_file(file_path: Path, client: QdrantClient | None = None) -> int:
    """
    Index a single file into Qdrant after removing any previous chunks for this file.

    Args:
        file_path: Path to the target file.
        client: Optional QdrantClient instance.

    Returns:
        Number of chunks indexed.
    """
    qdrant = client or get_qdrant_client()
    ensure_collection(qdrant, collection_name=COLLECTION_NAME)

    relative_path = file_path.relative_to(PROJECT_ROOT).as_posix()

    # Delete previously indexed chunks for this file to prevent duplicates
    try:
        qdrant.delete(
            collection_name=COLLECTION_NAME,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="file_path",
                        match=MatchValue(value=relative_path),
                    )
                ]
            ),
            wait=True,
        )
    except Exception:
        # If collection is empty or filter fails on new collection, proceed
        pass

    try:
        if file_path.stat().st_size > 1_000_000:
            return 0
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0

    chunks = chunk_code(content, relative_path)
    if not chunks:
        return 0

    points = []
    for chunk in chunks:
        vector = create_embedding(chunk.content)
        points.append(
            PointStruct(
                id=str(uuid4()),
                vector=vector,
                payload={
                    "file_path": chunk.file_path,
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                },
            )
        )

    if points:
        qdrant.upsert(
            collection_name=COLLECTION_NAME,
            points=points,
        )

    return len(points)


def index_repository(client: QdrantClient | None = None) -> int:
    """
    Inventory and index all eligible repository files according to exclusion rules.

    Args:
        client: Optional QdrantClient instance.

    Returns:
        Total number of chunks indexed across all eligible files.
    """
    qdrant = client or get_qdrant_client()
    ensure_collection(qdrant, collection_name=COLLECTION_NAME)

    total_chunks = 0

    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue

        relative_path = path.relative_to(PROJECT_ROOT)

        if any(part in IGNORED_DIRS for part in relative_path.parts):
            continue

        if path.name in SENSITIVE_FILES:
            continue

        if path.suffix not in SUPPORTED_EXTENSIONS:
            continue

        try:
            count = index_file(path, client=qdrant)
            total_chunks += count
            if count > 0:
                print(f"Indexed {relative_path.as_posix()}: {count} chunks")
        except Exception as e:
            print(f"Failed to index {relative_path.as_posix()}: {e}")

    return total_chunks