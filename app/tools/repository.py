from pathlib import Path
from app.config import PROJECT_ROOT, IGNORED_DIRS, SENSITIVE_FILES


def list_files() -> list[str]:
    """List repository files while skipping ignored directories."""

    files = []

    for path in PROJECT_ROOT.rglob("*"):
        relative_path = path.relative_to(PROJECT_ROOT)

        if any(part in IGNORED_DIRS for part in relative_path.parts):
            continue

        if not path.is_file():
            continue

        if path.name in SENSITIVE_FILES:
            continue

        files.append(relative_path.as_posix())

    return sorted(files)

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
    """Search repository files for a case-insensitive text match."""

    if not query or not query.strip():
        return []

    results = []
    root = PROJECT_ROOT.resolve()
    max_file_size = 1_000_000
    max_results = 50

    for path in root.rglob("*"):
        relative_path = path.relative_to(root)

        if any(part in IGNORED_DIRS for part in relative_path.parts):
            continue

        if path.name in SENSITIVE_FILES:
            continue

        if not path.is_file():
            continue

        try:
            if path.stat().st_size > max_file_size:
                continue

            content = path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue

        for line_number, line in enumerate(content.splitlines(), start=1):
            if query.casefold() in line.casefold():
                results.append({
                    "file": relative_path.as_posix(),
                    "line": line_number,
                    "content": line.strip(),
                })

                if len(results) >= max_results:
                    return results

    return results
