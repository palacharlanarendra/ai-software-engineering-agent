def rerank(
    query: str,
    documents: list[dict],
    top_k: int = 5,
):
    query_words = set(
        query.lower().split()
    )

    scored = []

    for document in documents:

        content = document["content"].lower()

        score = sum(
            1
            for word in query_words
            if word in content
        )

        scored.append(
            {
                "document": document,
                "score": score,
            }
        )

    scored.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    return scored[:top_k]