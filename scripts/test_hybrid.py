from app.rag.hybrid_retriever import hybrid_search


query = "chunking function"

results = hybrid_search(query)

print("\n=== KEYWORD RESULTS ===")

for result in results["keyword"]:
    print(
        result["file"],
        result["line"],
        result["content"],
    )


print("\n=== SEMANTIC RESULTS ===")

for result in results["semantic"]:
    print(
        result.score,
        result.payload["file_path"],
    )