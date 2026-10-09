from langchain_core.tools import tool

from app.tools.repository import (
    list_files,
    read_file,
    search_code,
)

from app.rag.retriever import search_code_semantic


@tool
def semantic_repository_search(query: str) -> list[dict]:
    """
    Search the repository semantically.
    Useful for natural-language questions about how
    the code works.
    """

    results = search_code_semantic(
        query,
        limit=5,
    )

    return [
        {
            "file": result.payload["file_path"],
            "chunk": result.payload["chunk_index"],
            "content": result.payload["content"],
            "score": result.score,
        }
        for result in results
    ]
    
@tool
def list_repository_files() -> list[str]:
    """List all relevant files in the repository."""
    return list_files()


@tool
def read_repository_file(file_path: str) -> str:
    """Read the contents of a specific repository file."""
    return read_file(file_path)


@tool
def search_repository(query: str) -> list[dict]:
    """
    Search the repository for exact keyword matches.
    Useful when looking for function names, class names,
    variables, errors, or API paths.
    """
    return search_code(query)