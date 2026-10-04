from app.rag.retriever import search_code_semantic

results = search_code_semantic(
    "Where is the chunking is happening?"
)

for result in results:
    print("-----")
    print(result.score)
    print(result.payload["file_path"])
    print(result.payload["content"])