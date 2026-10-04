from qdrant_client import QdrantClient

from app.ai.embeddings import create_embedding


COLLECTION_NAME = "code_chunks"

qdrant = QdrantClient(
    url="http://localhost:6333"
)


def search_code_semantic(
    query: str,
    limit: int = 5,
):

    query_vector = create_embedding(
        query
    )

    results = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=limit,
    )

    return results.points