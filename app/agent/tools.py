from typing import Optional
from langchain_core.tools import tool

from app.tools.repository import (
    list_files,
    read_file,
    search_code,
    inspect_symbols,
    find_references,
)
from app.rag.retriever import search_code_semantic


@tool
def semantic_repository_search(query: str, limit: int = 5) -> list[dict]:
    """
    Search the repository semantically.
    Useful for natural-language questions about how the code works or finding
    relevant modules and concepts.
    """
    results = search_code_semantic(query, limit=limit)
    return [
        {
            "file": result.file_path,
            "chunk": result.chunk_index,
            "start_line": result.start_line,
            "end_line": result.end_line,
            "content": result.content,
            "score": result.score,
        }
        for result in results
    ]


@tool
def list_repository_files(directory: str = "") -> list[str]:
    """List repository files, optionally within a specific sub-directory."""
    return list_files(directory=directory)


@tool
def read_repository_file(file_path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
    """
    Read the contents of a specific repository file.
    Optionally reads a specific line range [start_line, end_line].
    """
    return read_file(file_path, start_line=start_line, end_line=end_line)


@tool
def search_repository(query: str, path_filter: Optional[str] = None) -> list[dict]:
    """
    Search the repository for exact keyword or text matches.
    Useful when looking for function names, class names, variables, errors, or API paths.
    """
    return search_code(query, path_filter=path_filter)


@tool
def inspect_repository_symbols(file_path: str) -> dict:
    """
    Extract classes, methods, functions, and imports from a Python file using AST inspection.
    Enables instant structural discovery of a module before proposing edits.
    """
    return inspect_symbols(file_path)


@tool
def find_symbol_references(symbol: str) -> list[dict]:
    """
    Find all occurrences, usages, and call sites of a symbol across the entire repository.
    Crucial for multi-edit tasks to know all files that need updating when a signature changes.
    """
    return find_references(symbol)


ALL_AGENT_TOOLS = [
    semantic_repository_search,
    list_repository_files,
    read_repository_file,
    search_repository,
    inspect_repository_symbols,
    find_symbol_references,
]

AGENT_TOOLS_MAP = {t.name: t for t in ALL_AGENT_TOOLS}


def execute_agent_tool(tool_name: str, **kwargs):
    """Safely execute an agent tool by name."""
    tool_fn = AGENT_TOOLS_MAP.get(tool_name)
    if not tool_fn:
        return f"Tool '{tool_name}' not found. Available tools: {list(AGENT_TOOLS_MAP.keys())}"
    try:
        return tool_fn.invoke(kwargs)
    except Exception as exc:
        return f"Error executing tool '{tool_name}': {exc}"