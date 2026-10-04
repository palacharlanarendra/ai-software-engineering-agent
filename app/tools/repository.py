from pathlib import Path

PROJECT_ROOT = Path.cwd()

def list_files() -> list[str]:
    """
    List all files in the current repository.
    """
    files = []
    for path in PROJECT_ROOT.rglob('*'):
        if path.is_file():
            files.append(str(path.relative_to(PROJECT_ROOT)))
        
    return files

def read_file(file_path: str) -> str:
    """
    Read the contents of a file inside the repository.

    Args:
        file_path: Relative path of the file.
    """
    root = PROJECT_ROOT.resolve()
    path = (root/file_path).resolve()

    if root not in path.parents and path != root:
        return "Access denied."

    if not path.exists():
        return f"file not found: {file_path}"

    if not path.is_file():
        return f"Not a file: {file_path}"

    return path.read_text()

def search_code(query: str) -> list[dict]:
    """
    Search repository files for a text string.

    Args:
        query: Text to search for.
    """
    results = []

    root = PROJECT_ROOT.resolve()

    ignored_dirs = {
        ".git", "my-ai-env", "__pycache__", "node_modules"
    }

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in ignored_dirs for part in path.parts):
            continue

        try: 
            content = path.read_text(
                encoding="utf-8",
                errors="ignore"
            )
        except Execption:
            continue

        for line_number, line in enumerate(
            content.splitlines(),
            start=1
        ):
            if query.lower() in line.lower():
                results.append({
                    "file": str(path.relative_to(root)),
                    "line": line_number,
                    "content": line.strip()
                })
    return results[:50]