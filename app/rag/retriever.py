from qdrant_client import QdrantClient

from app.ai.embeddings import create_embedding
from app.rag.vector_store import get_qdrant_client, COLLECTION_NAME

def search_code_semantic(query: str, limit: int = 5):
    qdrant = get_qdrant_client()

    query_vector = create_embedding(query)

    results = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=limit,
    )

    return results.points
