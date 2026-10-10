from qdrant_client import QdrantClient

from app.ai.embeddings import create_embedding
from app.rag.vector_store import get_qdrant_client, COLLECTION_NAME


class SemanticSearchResult(dict):
    """
    Structured search result supporting dictionary keys, object attributes,
    and a `.payload` dictionary property for backward compatibility.
    """

    def __init__(
        self,
        file_path: str,
        chunk_index: int,
        content: str,
        start_line: int,
        end_line: int,
        score: float,
    ):
        data = {
            "file_path": file_path,
            "chunk_index": chunk_index,
            "content": content,
            "start_line": start_line,
            "end_line": end_line,
            "score": score,
        }
        super().__init__(data)
        self.file_path = file_path
        self.chunk_index = chunk_index
        self.content = content
        self.start_line = start_line
        self.end_line = end_line
        self.score = score
        self.payload = data


def search_code_semantic(
    query: str,
    limit: int = 5,
    client: QdrantClient | None = None,
) -> list[SemanticSearchResult]:
    """
    Perform semantic vector search across the indexed repository code.

    Args:
        query: Natural language question or code search prompt.
        limit: Number of top results to retrieve.
        client: Optional QdrantClient instance.

    Returns:
        List of SemanticSearchResult instances ordered by relevance score.
    """
    if not query or not query.strip():
        return []

    qdrant = client or get_qdrant_client()
    query_vector = create_embedding(query)

    try:
        response = qdrant.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            limit=limit,
        )
        points = response.points
    except Exception as exc:
        print(f"Warning: Semantic retrieval failed: {exc}")
        return []

    results: list[SemanticSearchResult] = []
    for point in points:
        payload = point.payload or {}
        results.append(
            SemanticSearchResult(
                file_path=payload.get("file_path", ""),
                chunk_index=payload.get("chunk_index", 0),
                content=payload.get("content", ""),
                start_line=payload.get("start_line", 1),
                end_line=payload.get("end_line", 1),
                score=point.score,
            )
        )

    return results