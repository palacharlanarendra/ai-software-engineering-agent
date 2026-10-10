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
    QDRANT_URL,
    QDRANT_COLLECTION,
)
from app.ai.embeddings import create_embedding
from app.rag.chunker import chunk_code

COLLECTION_NAME = QDRANT_COLLECTION

def get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=QDRANT_URL)


def index_file(file_path: Path, client: QdrantClient | None = None) -> int:
    qdrant = client or get_qdrant_client()
    
    relative_path = file_path.relative_to(PROJECT_ROOT).as_posix()

    # Delete previously indexed chunks for this file only.
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

    content = file_path.read_text(encoding="utf-8", errors="ignore")
    chunks = chunk_code(content, relative_path)

    points = []

    for chunk in chunks:
        vector = create_embedding(
            chunk.content
        )

        points.append(
            PointStruct(
                id=str(uuid4()),
                vector=vector,
                payload={
                    "file_path": chunk.file_path,
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
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
    qdrant = client or get_qdrant_client()
    total_chunks = 0

    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue

        relative_path = path.relative_to(PROJECT_ROOT)

        if any(part in IGNORED_DIRS for part in relative_path.parts):
            continue

        if path.name in SENSITIVE_FILES:
            continue

        # Skip non-code files
        if path.suffix not in {
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".json",
            ".md",
            ".yaml",
            ".yml",
        }:
            continue

        try:
            count = index_file(path, client=qdrant)
            total_chunks += count
            print(f"Indexed {relative_path.as_posix()}: {count} chunks")
        except Exception as e:
            print(f"Failed to index {relative_path.as_posix()}: {e}")

    return total_chunks