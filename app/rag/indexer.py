from pathlib import Path
from uuid import uuid4

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from app.ai.embeddings import create_embedding
from app.rag.chunker import chunk_code


PROJECT_ROOT = Path.cwd()

COLLECTION_NAME = "code_chunks"

qdrant = QdrantClient(
    url="http://localhost:6333"
)


IGNORED_DIRS = {
    ".git",
    "venv",
    "__pycache__",
    "node_modules",
    "my-ai-env"
}

def index_file(file_path: Path):

    relative_path = str(
        file_path.relative_to(PROJECT_ROOT)
    )

    content = file_path.read_text(
        encoding="utf-8",
        errors="ignore",
    )

    chunks = chunk_code(
        content,
        relative_path,
    )

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

def index_repository():

    total_chunks = 0

    for path in PROJECT_ROOT.rglob("*"):

        if not path.is_file():
            continue

        if any(
            part in IGNORED_DIRS
            for part in path.parts
        ):
            continue

        # Skip obvious non-code files for now
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
            count = index_file(path)
            total_chunks += count

            print(
                f"Indexed {path}: "
                f"{count} chunks"
            )

        except Exception as e:
            print(
                f"Failed to index {path}: {e}"
            )

    return total_chunks