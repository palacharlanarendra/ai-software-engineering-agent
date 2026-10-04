from app.rag.indexer import index_repository


total = index_repository()

print(
    f"\nFinished indexing "
    f"{total} chunks."
)