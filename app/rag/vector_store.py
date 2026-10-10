from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from app.config import QDRANT_URL, QDRANT_COLLECTION

COLLECTION_NAME = QDRANT_COLLECTION


def get_qdrant_client(url: str | None = None) -> QdrantClient:
    return QdrantClient(url=url or QDRANT_URL)


def ensure_collection(
    client: QdrantClient | None = None,
    collection_name: str = COLLECTION_NAME,
    vector_size: int = 3072,
) -> bool:
    """Ensure the specified Qdrant collection exists without failing on re-initialization."""
    qdrant = client or get_qdrant_client()
    try:
        collections = [c.name for c in qdrant.get_collections().collections]
        if collection_name not in collections:
            qdrant.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=vector_size,
                    distance=Distance.COSINE,
                ),
            )
        return True
    except Exception as e:
        print(f"Warning: Could not connect to or initialize Qdrant at {QDRANT_URL}: {e}")
        return False