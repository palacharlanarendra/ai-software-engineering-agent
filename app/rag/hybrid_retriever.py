from app.tools.repository import search_code
from app.rag.retriever import search_code_semantic


def hybrid_search(
    query: str,
    limit: int = 5,
):
    keyword_results = search_code(query)

    semantic_results = search_code_semantic(
        query,
        limit=limit,
    )

    return {
        "keyword": keyword_results,
        "semantic": semantic_results,
    }